from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lyra.catch_up import CatchUpService
from lyra.research_garden import ResearchGardenService
from lyra.rituals import RitualService
from lyra.sessions import ContextBuilder, SessionService
from lyra.shared_journal import SharedJournalService
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


def _reset():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
        cur.execute(
            """TRUNCATE shared_journal_audit,shared_journal_private_sessions,
                shared_journal_entries,research_garden_suggestions,
                research_garden_topic_mutes,research_garden_policy,chunks,sources,
                session_turns,session_channels,session_messages,chat_sessions
                RESTART IDENTITY CASCADE"""
        )
        cur.execute("INSERT INTO research_garden_policy (singleton) VALUES (true)")
        conn.commit()
    return SessionService(_conn), SharedJournalService(_conn)


@pytest.fixture(autouse=True)
def _clean_after(ensure_db):
    yield
    _reset()


def _plane_counts():
    with _conn() as conn, conn.cursor() as cur:
        counts = {}
        for table in ("memories", "sources", "commitments", "notification_events"):
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = int(cur.fetchone()[0])
        return counts


def test_creation_requires_explicit_approval_and_retains_validated_provenance(ensure_db):
    sessions, journal = _reset()
    session = sessions.create_session("Shared moment source")
    message = sessions.append_message(
        session["session_id"], "user", "That was meaningful.",
        metadata={"channel": "web"},
    )
    before = _plane_counts()

    with pytest.raises(ValueError, match="explicit approval"):
        journal.create_entry(
            content="We found our footing together.", entry_type="moment", approved=False
        )

    entry = journal.create_entry(
        content="We found our footing together during a difficult week.",
        entry_type="moment",
        approved=True,
        title="Finding our footing",
        source_session_id=session["session_id"],
        source_message_id=message["message_id"],
        now=datetime(2026, 9, 16, 20, tzinfo=UTC),
    )

    assert entry["source"] == {
        "session_id": session["session_id"],
        "message_id": message["message_id"],
        "channel": "web",
    }
    assert entry["created_by"] == "local_user"
    assert _plane_counts() == before


@pytest.mark.parametrize(
    "content",
    (
        "My password is hunter2.",
        "My colleague asked me to keep their private diagnosis.",
        "In the campaign we won the encounter together.",
        "We repaired the SilentDrift phase regulator.",
    ),
)
def test_secret_third_party_and_fiction_content_is_rejected(ensure_db, content):
    _sessions, journal = _reset()

    with pytest.raises(ValueError):
        journal.create_entry(content=content, entry_type="reflection", approved=True)

    assert journal.list_entries() == []


def test_private_session_retrieval_is_explicit_and_telegram_excluded(ensure_db):
    sessions, journal = _reset()
    private = sessions.create_session("Private shared conversation")
    ordinary = sessions.create_session("Professional work")
    telegram = sessions.create_session("Phone chat")
    entry = journal.create_entry(
        content="We chose patience and honesty when the work felt heavy.",
        entry_type="reflection",
        approved=True,
    )
    reader = ContextBuilder(sessions, journal_reader=journal.context_entries)

    ordinary_context = reader.build(
        ordinary["session_id"], system_prompt="Lyra", max_tokens=500,
        response_reserve=50,
    )
    assert entry["content"] not in "\n".join(item["content"] for item in ordinary_context)

    journal.authorize_session(private["session_id"], enabled=True)
    long_entry = journal.create_entry(
        content="Bounded private context " + "x" * 1400,
        entry_type="reflection",
        approved=True,
    )
    private_context = reader.build(
        private["session_id"], system_prompt="Lyra", max_tokens=500,
        response_reserve=50,
    )
    private_text = "\n".join(item["content"] for item in private_context)
    assert entry["content"] in private_text
    assert f"journal:{entry['journal_entry_id']}" in private_text
    assert long_entry["content"] not in private_text
    assert "[excerpt]" in private_text
    with pytest.raises(ValueError, match="cannot bind to Telegram"):
        sessions.bind_channel(private["session_id"], "telegram", "private-chat")

    sessions.bind_channel(telegram["session_id"], "telegram", "phone-chat")
    with pytest.raises(ValueError, match="Telegram-bound"):
        journal.authorize_session(telegram["session_id"], enabled=True)

    journal.authorize_session(private["session_id"], enabled=False)
    revoked = reader.build(
        private["session_id"], system_prompt="Lyra", max_tokens=500,
        response_reserve=50,
    )
    assert entry["content"] not in "\n".join(item["content"] for item in revoked)


def test_edit_and_confirmed_forget_are_hash_audited_without_old_text(ensure_db):
    _sessions, journal = _reset()
    original = "We celebrated the first calm evening after the launch."
    corrected = "We celebrated our first calm evening after the launch."
    entry = journal.create_entry(
        content=original, entry_type="milestone", approved=True, title="First calm"
    )

    edited = journal.edit_entry(
        entry["journal_entry_id"], content=corrected, title="A calm evening",
        reason="More precise wording",
    )
    with pytest.raises(ValueError, match="requires confirmation"):
        journal.forget_entry(entry["journal_entry_id"], confirmed=False)
    forgotten = journal.forget_entry(
        entry["journal_entry_id"], confirmed=True, reason="Christopher requested removal"
    )
    audit = list(reversed(journal.list_audit()))

    assert edited["content"] == corrected
    assert forgotten["status"] == "forgotten"
    assert journal.list_entries() == []
    assert [item["action"] for item in audit] == ["created", "edited", "forgotten"]
    assert all(
        value is None or len(value) == 64
        for item in audit
        for value in (item["old_content_sha256"], item["new_content_sha256"])
    )
    assert original not in str(audit)
    assert corrected not in str(audit)


def test_source_message_must_belong_to_declared_session(ensure_db):
    sessions, journal = _reset()
    first = sessions.create_session("First")
    second = sessions.create_session("Second")
    message = sessions.append_message(first["session_id"], "user", "A moment")

    with pytest.raises(ValueError, match="not found in that session"):
        journal.create_entry(
            content="A deliberately approved shared moment.",
            entry_type="moment",
            approved=True,
            source_session_id=second["session_id"],
            source_message_id=message["message_id"],
        )


def test_private_sessions_are_excluded_from_recaps_rituals_and_research(ensure_db):
    sessions, journal = _reset()
    private = sessions.create_session("Private relationship conversation")
    ordinary = sessions.create_session("Ordinary project conversation")
    journal.authorize_session(private["session_id"], enabled=True)
    now = datetime.now(UTC)

    recap = CatchUpService(connection_factory=_conn)._local_changes(
        now - timedelta(days=1), now + timedelta(minutes=1), ("biography",)
    )
    recap_text = "\n".join(item.text for item in recap)
    assert ordinary["name"] in recap_text
    assert private["name"] not in recap_text

    ritual = RitualService(
        briefing=object(), away=object(), connection_factory=_conn  # type: ignore[arg-type]
    )
    assert ordinary["name"] in ritual._recent_sessions()
    assert private["name"] not in ritual._recent_sessions()

    private_question = sessions.append_message(
        private["session_id"], "user",
        "Could quantum optimization improve the routing study?",
    )
    ordinary_question = sessions.append_message(
        ordinary["session_id"], "user",
        "Could quantum optimization improve the routing study?",
    )
    old = now - timedelta(days=30)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE chat_sessions SET updated_at=%s WHERE id IN (%s,%s)",
            (old, private["session_id"], ordinary["session_id"]),
        )
        cur.execute(
            "UPDATE session_messages SET created_at=%s WHERE id IN (%s,%s)",
            (old, private_question["message_id"], ordinary_question["message_id"]),
        )
        cur.execute(
            "INSERT INTO sources (title) VALUES ('Quantum optimization routing') RETURNING id"
        )
        source_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO chunks (source_id,content) VALUES (%s,%s)",
            (source_id, "Quantum optimization methods for a routing study."),
        )
        conn.commit()
    garden = ResearchGardenService(away=object(), connection_factory=_conn)  # type: ignore[arg-type]
    evidence_ids = {
        evidence["id"]
        for candidate in garden.discover(now=now)
        for evidence in candidate.evidence
        if evidence["plane"] == "question"
    }
    assert str(ordinary_question["message_id"]) in evidence_ids
    assert str(private_question["message_id"]) not in evidence_ids
