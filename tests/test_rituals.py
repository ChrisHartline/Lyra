from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import asyncio
from pathlib import Path
from types import SimpleNamespace
import uuid

from lyra.rituals import RitualService
from lyra.sessions import SessionService
from lyra.telegram import run_configured_rituals
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


class FakeBriefing:
    def assemble(self, *_args, **_kwargs):
        return {"bullets": [
            {"plane": "digest", "text": "Recent progress"},
            {"plane": "memory", "text": "Approved professional context"},
        ]}


class FakeAway:
    def __init__(self, disposition="send"):
        self.disposition = disposition
        self.calls = []

    def plan_notification(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(disposition=self.disposition)


def _service(disposition="send"):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
        cur.execute(
            """TRUNCATE ritual_runs,ritual_policy,commitments,
                commitment_candidates,chat_sessions RESTART IDENTITY CASCADE"""
        )
        cur.execute("INSERT INTO ritual_policy (singleton) VALUES (true)")
        conn.commit()
    sessions = SessionService(_conn)
    sessions.create_session("Recent project conversation")
    away = FakeAway(disposition)
    return RitualService(FakeBriefing(), away, _conn), away


def test_morning_and_evening_are_source_labeled_and_calm(ensure_db):
    service, _away = _service()
    now = datetime(2026, 9, 14, 14, tzinfo=UTC)

    morning = service.build("morning", now=now)
    evening = service.build("evening", now=now)

    assert "calm orientation" in morning["body"]
    assert "Evening check-in" in evening["body"]
    assert "[session] Recent project conversation" in morning["body"]
    assert "[digest] Recent progress" in morning["body"]
    assert set(morning["source_planes"]) == {"digest", "memory", "session"}


def test_due_flow_obeys_disabled_vacation_snooze_away_and_idempotency(ensure_db):
    service, away = _service()
    now = datetime(2026, 9, 14, 14, tzinfo=UTC)
    assert service.plan_due("morning", now=now)["disposition"] == "disabled"

    service.set_policy(
        morning_enabled=True, evening_enabled=True,
        morning_time=time(8), evening_time=time(20),
        timezone="America/Chicago", channel="telegram", notion_publish=False,
        vacation_until=date(2026, 9, 14),
        morning_snoozed_until=None, evening_snoozed_until=None,
    )
    assert service.plan_due("morning", now=now)["disposition"] == "vacation"
    service.set_policy(vacation_until=None)
    service.snooze("morning", datetime.now(UTC) + timedelta(hours=1))
    assert service.plan_due("morning", now=now)["disposition"] == "snoozed"
    service.set_policy(morning_snoozed_until=None)

    planned = service.plan_due("morning", now=now)
    repeated = service.plan_due("morning", now=now)
    assert planned["disposition"] == "send"
    assert planned["run"]["status"] == "planned"
    assert repeated["disposition"] == "already_handled"
    assert away.calls[0]["category"] == "digest"


def test_quiet_hours_batch_and_skip_are_recorded_without_delivery(ensure_db):
    service, _away = _service("batch")
    now = datetime(2026, 9, 14, 14, tzinfo=UTC)
    service.set_policy(morning_enabled=True)

    result = service.plan_due("morning", now=now, force=True)
    skipped = service.skip("evening", now=now)

    assert result["disposition"] == "batch"
    assert result["run"]["status"] == "batched"
    assert skipped["status"] == "skipped"


def test_scheduler_delivers_web_ritual_into_normal_session_history():
    class FakeRituals:
        def __init__(self):
            self.delivered = []
            self.briefing = SimpleNamespace(publisher=None)

        def plan_due(self, kind):
            if kind == "evening":
                return {"disposition": "disabled"}
            return {
                "disposition": "send",
                "draft": {"body": "Good morning from the ritual."},
                "run": {"run_id": "run-1"},
                "notion_publish": False,
            }

        def get_policy(self):
            return SimpleNamespace(channel="web", target_session_id="command-deck")

        def mark_delivered(self, run_id, session_id=None):
            self.delivered.append((run_id, session_id))

        def mark_failed(self, run_id):
            raise AssertionError(run_id)

    class FakeSessions:
        def __init__(self):
            self.messages = []

        def append_message(self, session_id, role, content, metadata=None):
            self.messages.append((session_id, role, content, metadata))

    rituals = FakeRituals()
    sessions = FakeSessions()

    asyncio.run(run_configured_rituals(sessions, rituals, iterations=1))

    assert sessions.messages[0][0:3] == (
        "command-deck", "assistant", "Good morning from the ritual."
    )
    assert sessions.messages[0][3]["proactive"] is True
    assert rituals.delivered == [("run-1", "command-deck")]


def test_web_rituals_require_a_safe_explicit_target(ensure_db):
    service, _away = _service()
    sessions = SessionService(_conn)
    command_deck = sessions.create_session("Command Deck")
    private = sessions.create_session("Us")
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO shared_journal_private_sessions(session_id) VALUES (%s)",
            (private["session_id"],),
        )
        conn.commit()

    import pytest
    with pytest.raises(ValueError, match="explicit target"):
        service.set_policy(channel="web", morning_enabled=True)
    with pytest.raises(ValueError, match="Private shared"):
        service.set_policy(
            channel="web",
            target_session_id=private["session_id"],
            morning_enabled=True,
        )

    policy = service.set_policy(
        channel="web",
        target_session_id=command_deck["session_id"],
        morning_enabled=True,
    )
    assert policy.target_session_id == command_deck["session_id"]


def test_ritual_preview_excludes_private_commitments(ensure_db):
    service, _away = _service()
    with _conn() as conn, conn.cursor() as cur:
        for summary, scope in (
            ("Prepare tomorrow's class", "professional"),
            ("Plan a private evening", "private_shared"),
        ):
            candidate_id = uuid.uuid4()
            cur.execute(
                """INSERT INTO commitment_candidates
                   (id,summary,kind,visibility_scope,source_type,source_url,
                    source_approved,detection_reason,status,resolved_at)
                   VALUES (%s,%s,'task',%s,'dashboard','https://local',true,
                           'test','confirmed',now())""",
                (candidate_id, summary, scope),
            )
            cur.execute(
                """INSERT INTO commitments
                   (id,candidate_id,summary,kind,status,visibility_scope)
                   VALUES (%s,%s,%s,'task','active',%s)""",
                (uuid.uuid4(), candidate_id, summary, scope),
            )
        conn.commit()

    preview = service.build("morning")
    assert "Prepare tomorrow's class" in preview["body"]
    assert "Plan a private evening" not in preview["body"]
