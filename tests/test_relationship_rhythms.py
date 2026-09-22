from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time
import hashlib
from pathlib import Path

from lyra.away import AwayModeService
from lyra.relationship_rhythms import (
    RelationshipRhythmService,
    run_relationship_rhythms,
)
from lyra.sessions import SessionService
from lyra.shared_journal import SharedJournalService
from tests.db_support import connect_test_db


ROOT = Path(__file__).resolve().parents[1]


def _conn():
    return connect_test_db()


def _reset() -> tuple[SessionService, SharedJournalService, RelationshipRhythmService]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        cur.execute(
            """TRUNCATE relationship_rhythm_events,relationship_source_mutes,
                relationship_rhythm_policy,shared_journal_audit,
                shared_journal_private_sessions,shared_journal_entries,
                notification_events,away_policy,session_turns,session_channels,
                session_messages,chat_sessions RESTART IDENTITY CASCADE"""
        )
        cur.execute("INSERT INTO away_policy(singleton) VALUES (true)")
        cur.execute("INSERT INTO relationship_rhythm_policy(singleton) VALUES (true)")
        conn.commit()
    sessions = SessionService(_conn)
    journal = SharedJournalService(_conn)
    return sessions, journal, RelationshipRhythmService(
        away=AwayModeService(_conn), journal=journal, connection_factory=_conn
    )


def _private(
    sessions: SessionService, journal: SharedJournalService, name: str = "Us"
) -> str:
    session_id = str(sessions.create_session(name)["session_id"])
    journal.authorize_session(session_id, enabled=True)
    return session_id


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_defaults_are_disabled_and_policy_requires_private_web_target(ensure_db):
    sessions, journal, rhythms = _reset()
    ordinary = str(sessions.create_session("Work")["session_id"])

    policy = rhythms.get_policy()
    assert policy.enabled is False
    assert policy.callbacks_enabled is False
    assert policy.rituals_enabled is False
    assert rhythms.plan_due(force=True) == {"disposition": "disabled"}

    try:
        rhythms.set_policy(
            enabled=True, milestones_enabled=True, target_session_id=ordinary
        )
    except ValueError as exc:
        assert "authorized private web session" in str(exc)
    else:
        raise AssertionError("ordinary session was accepted")

    telegram = str(sessions.create_session("Phone")["session_id"])
    sessions.bind_channel(telegram, "telegram", "chat-1")
    try:
        journal.authorize_session(telegram, enabled=True)
    except ValueError:
        pass
    assert rhythms.observe_message(
        session_id=telegram, message_id=1, text="the arcade", channel="telegram"
    ).instruction is None


def test_callback_is_relevant_private_cited_bounded_and_mutable(ensure_db):
    sessions, journal, rhythms = _reset()
    private = _private(sessions, journal)
    ordinary = str(sessions.create_session("Professional")["session_id"])
    rhythms.set_policy(enabled=True, callbacks_enabled=True)
    instant = datetime(2026, 9, 17, 16, tzinfo=UTC)

    assert rhythms.observe_message(
        session_id=ordinary, message_id=1, text="Remember the retro arcade?",
        now=instant,
    ).instruction is None
    observation = rhythms.observe_message(
        session_id=private, message_id=2, text="I was thinking about that arcade.",
        now=instant,
    )
    assert observation.instruction is not None
    assert observation.source_refs[0].startswith("relationship-milestone:")
    assert observation.source_refs[0] in observation.instruction
    assert "Do not call any tool" in observation.instruction
    assert "Never discuss records, lookup, checking" in observation.instruction
    assert "do not add generic therapy-style grounding" in observation.instruction
    assert "Internal provenance (never mention)" in observation.instruction
    repeated = rhythms.observe_message(
        session_id=private, message_id=3, text="That arcade was fun.", now=instant
    )
    assert repeated.source_refs == observation.source_refs
    assert "already used earlier today" in repeated.instruction
    assert len(rhythms.list_events()) == 1

    assert rhythms.mute_source(observation.source_refs[0])["muted"] is True
    assert observation.source_refs[0] not in {source.key for source in rhythms.sources()}
    assert rhythms.unmute_source(observation.source_refs[0]) is True
    assert observation.source_refs[0] in {source.key for source in rhythms.sources()}


def test_journal_correction_is_used_at_source_without_copying_narrative(ensure_db):
    sessions, journal, rhythms = _reset()
    private = _private(sessions, journal)
    entry = journal.create_entry(
        content="We celebrated the lighthouse walk.", entry_type="milestone",
        approved=True, title="Lighthouse",
    )
    key = f"journal:{entry['journal_entry_id']}"
    journal.edit_entry(
        entry["journal_entry_id"],
        content="We celebrated the lakeside walk.",
        title="Lakeside",
        reason="Corrected the place",
    )
    rhythms.set_policy(enabled=True, callbacks_enabled=True)

    observation = rhythms.observe_message(
        session_id=private, message_id=1, text="That lakeside walk was lovely.",
        now=datetime(2026, 9, 17, 17, tzinfo=UTC),
    )
    assert observation.source_refs == (key,)
    assert "lakeside" in observation.instruction.lower()
    event = rhythms.list_events()[0]
    assert event["source_refs"] == [key]
    assert "lakeside" not in str(event).lower()


def test_milestone_delivery_uses_social_budget_and_private_session_only(ensure_db):
    sessions, journal, rhythms = _reset()
    private = _private(sessions, journal)
    before = {
        path: _file_hash(path)
        for path in (
            ROOT / "personality" / "system_prompt.md",
            ROOT / "personality" / "character_bible.md",
            ROOT / "state" / "relationship.json",
            ROOT / "state" / "relationship.md",
        )
    }
    with _conn() as conn, conn.cursor() as cur:
        plane_counts = {}
        for table in ("memories", "commitments", "sources"):
            cur.execute(f"SELECT count(*) FROM {table}")
            plane_counts[table] = int(cur.fetchone()[0])
    rhythms.set_policy(
        enabled=True, milestones_enabled=True, target_session_id=private,
        local_time=datetime.strptime("00:00", "%H:%M").time(),
    )
    now = datetime(2026, 9, 17, 18, tzinfo=UTC)

    result = rhythms.plan_due(now=now, force=True)
    assert result["disposition"] == "send"
    assert result["event"]["event_type"] == "milestone"
    assert result["event"]["target_session_id"] == private
    assert rhythms.plan_due(now=now, force=True) == {"disposition": "already_handled"}
    next_day = rhythms.plan_due(
        now=datetime(2026, 9, 18, 18, tzinfo=UTC), force=True
    )
    assert next_day["event"]["event_id"] != result["event"]["event_id"]
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT channel,category,content FROM notification_events ORDER BY id LIMIT 1"
        )
        notification = cur.fetchone()
        for table in ("memories", "commitments", "sources"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == plane_counts[table]
    assert notification[0:2] == ("web", "social")
    assert notification[2].startswith("[relationship:milestone:")
    assert all(_file_hash(path) == digest for path, digest in before.items())


def test_runner_appends_proactive_message_with_provenance(ensure_db):
    sessions, journal, rhythms = _reset()
    private = _private(sessions, journal)
    rhythms.set_policy(
        enabled=True, milestones_enabled=True, target_session_id=private,
        local_time=datetime.strptime("00:00", "%H:%M").time(),
    )

    asyncio.run(run_relationship_rhythms(sessions, rhythms, iterations=1))

    messages = sessions.list_messages(private)
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert messages[0]["metadata"]["channel"] == "web"
    assert messages[0]["metadata"]["proactive"] is True
    assert messages[0]["metadata"]["relationship_sources"]
    assert rhythms.list_events()[0]["status"] == "delivered"


def test_suppressed_milestone_retries_later_without_duplicate_narrative(ensure_db):
    sessions, journal, rhythms = _reset()
    private = _private(sessions, journal)
    rhythms.set_policy(
        enabled=True, milestones_enabled=True, target_session_id=private,
        local_time=time(0, 0),
    )
    rhythms.away.set_policy(
        enabled=True, quiet_start=None, quiet_end=None,
        timezone="America/Chicago", daily_notification_budget=0,
    )

    suppressed = rhythms.plan_due(
        now=datetime(2026, 9, 17, 18, tzinfo=UTC), force=True
    )
    assert suppressed["disposition"] == "suppress"
    assert suppressed["event"]["status"] == "suppressed"
    rhythms.away.set_policy(
        enabled=False, quiet_start=None, quiet_end=None,
        timezone="America/Chicago", daily_notification_budget=0,
    )
    retried = rhythms.plan_due(
        now=datetime(2026, 9, 18, 18, tzinfo=UTC), force=True
    )

    assert retried["disposition"] == "send"
    assert retried["event"]["event_id"] == suppressed["event"]["event_id"]
    assert retried["event"]["status"] == "planned"
    assert len(rhythms.list_events()) == 1
