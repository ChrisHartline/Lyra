from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from lyra.research_garden import ResearchGardenService
from lyra.telegram import run_configured_research_garden
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


@pytest.fixture(autouse=True)
def _clean_live_rows(ensure_db):
    yield
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """TRUNCATE research_garden_suggestions,
                research_garden_topic_mutes,research_garden_policy,
                commitments,commitment_candidates,chunks,sources,chat_sessions
                RESTART IDENTITY CASCADE"""
        )
        cur.execute("INSERT INTO research_garden_policy (singleton) VALUES (true)")
        conn.commit()


class FakeAway:
    def __init__(self, disposition: str = "send"):
        self.disposition = disposition
        self.calls: list[dict] = []

    def plan_notification(self, **values):
        self.calls.append(values)
        return SimpleNamespace(disposition=self.disposition)


def _service(disposition: str = "send"):
    now = datetime(2026, 9, 15, 18, tzinfo=UTC)
    session_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    commitment_id = uuid.uuid4()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
        cur.execute(
            """TRUNCATE research_garden_suggestions,
                research_garden_topic_mutes,research_garden_policy,
                commitments,commitment_candidates,chunks,sources,chat_sessions
                RESTART IDENTITY CASCADE"""
        )
        cur.execute("INSERT INTO research_garden_policy (singleton) VALUES (true)")
        cur.execute(
            """INSERT INTO sources (title,url,fetched_at)
                VALUES (%s,%s,%s) RETURNING id""",
            ("Quantum optimization methods", "https://example.invalid/quantum", now),
        )
        source_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO chunks (source_id,content) VALUES (%s,%s)",
            (source_id, "Quantum optimization methods for routing studies."),
        )
        cur.execute(
            """INSERT INTO chat_sessions (id,name,created_at,updated_at)
                VALUES (%s,%s,%s,%s)""",
            (session_id, "Dormant research", now - timedelta(days=30),
             now - timedelta(days=30)),
        )
        cur.execute(
            """INSERT INTO session_messages
                (session_id,sequence,role,content,created_at)
                VALUES (%s,1,'user',%s,%s)""",
            (session_id, "Could quantum optimization help the routing study?",
             now - timedelta(days=30)),
        )
        cur.execute(
            """INSERT INTO commitment_candidates
                (id,summary,kind,source_type,source_session_id,source_message_id,
                 detection_reason,status,resolved_at)
                VALUES (%s,%s,'task','session',%s,
                    (SELECT id FROM session_messages WHERE session_id=%s),
                    'Explicit test commitment','confirmed',%s)""",
            (candidate_id, "Apply quantum optimization to the routing study",
             session_id, session_id, now),
        )
        cur.execute(
            """INSERT INTO commitments
                (id,candidate_id,summary,kind,status,confirmed_at,updated_at)
                VALUES (%s,%s,%s,'task','active',%s,%s)""",
            (commitment_id, candidate_id,
             "Apply quantum optimization to the routing study", now, now),
        )
        conn.commit()
    away = FakeAway(disposition)
    return ResearchGardenService(away=away, connection_factory=_conn), away, now


def test_discovery_requires_stored_evidence_and_labels_every_plane(ensure_db):
    service, _away, now = _service()

    candidates = service.discover(now=now)

    assert candidates
    assert all(len(item.evidence) == 2 for item in candidates)
    assert {evidence["plane"] for item in candidates for evidence in item.evidence} == {
        "source", "question", "commitment"
    }
    assert all(evidence["id"] for item in candidates for evidence in item.evidence)
    assert service.get_policy().enabled is False


def test_planning_obeys_away_mode_is_idempotent_and_does_not_publish(ensure_db):
    service, away, now = _service("send")

    assert service.plan_due(now=now)["disposition"] == "disabled"
    planned = service.plan_due(now=now, force=True)
    repeated = service.plan_due(now=now + timedelta(minutes=1), force=True)
    draft = service.draft_digest(planned["suggestions"][0]["suggestion_id"])

    assert planned["disposition"] == "send"
    assert planned["suggestions"][0]["status"] == "planned"
    assert "not new commitments" in planned["body"]
    assert away.calls[0]["category"] == "research"
    assert repeated["disposition"] == "no_candidates"
    assert draft["published"] is False
    assert "Nothing has been published" in draft["body"]


def test_topic_mute_and_dismiss_controls_are_durable(ensure_db):
    service, _away, now = _service()
    service.mute_topic("quantum optimization", now=now)

    assert service.discover(now=now) == []
    assert service.list_mutes(now=now)[0]["topic_key"] == "optimization"
    assert service.unmute_topic("quantum optimization") is True

    planned = service.plan_due(now=now, force=True)
    suggestion_id = planned["suggestions"][0]["suggestion_id"]
    dismissed = service.dismiss(suggestion_id, now=now)
    assert dismissed["status"] == "dismissed"
    assert dismissed["dismissed_at"] == now


def test_away_batch_is_persisted_without_delivery(ensure_db):
    service, _away, now = _service("batch")

    result = service.plan_due(now=now, force=True)

    assert result["disposition"] == "batch"
    assert all(item["status"] == "batched" for item in result["suggestions"])


def test_scheduler_delivers_web_suggestions_into_session_history():
    class FakeGarden:
        def __init__(self):
            self.delivered = []

        def plan_due(self):
            return {
                "disposition": "send", "channel": "web", "body": "A connection.",
                "suggestions": [{"suggestion_id": str(uuid.uuid4())}],
            }

        def mark_delivered(self, ids, session_id):
            self.delivered.append((list(ids), session_id))

        def mark_failed(self, ids):
            raise AssertionError(list(ids))

    class FakeSessions:
        def __init__(self):
            self.messages = []

        def list_sessions(self):
            return [{"session_id": "session-1"}]

        def append_message(self, session_id, role, content, metadata=None):
            self.messages.append((session_id, role, content, metadata))

    garden = FakeGarden()
    sessions = FakeSessions()
    asyncio.run(run_configured_research_garden(sessions, garden, iterations=1))

    assert sessions.messages[0][0:3] == ("session-1", "assistant", "A connection.")
    assert sessions.messages[0][3]["research_garden"] is True
    assert garden.delivered[0][1] == "session-1"
