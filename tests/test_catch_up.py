from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import uuid

from lyra.catch_up import CatchUpItem, CatchUpService
from lyra.providers import ModelProfile
from lyra.runtime import AgentLoop, ModelToolRunner
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.runtime_tools import ToolRegistry
from lyra.sessions import ContextBuilder, SessionService
from tests.db_support import connect_test_db


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ModelProfile("conversation", "openai-compatible", "fake", "FAKE", "https://fake")


def _conn():
    return connect_test_db()


class FakeChanges:
    def changes(self, since, until):
        return ([CatchUpItem(
            "Project updated: Finish lecture preparation",
            datetime(2026, 9, 14, 15, tzinfo=UTC),
            ("project:notion:page-1@2026-09-14T15:00:00+00:00",),
        )], ["[integration:digest] inaccessible: TimeoutError; no changes inferred"])


def _seed():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        cur.execute("TRUNCATE commitments,commitment_candidates,memories,chat_sessions RESTART IDENTITY CASCADE")
        session_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        commitment_id = uuid.uuid4()
        cur.execute("""INSERT INTO chat_sessions(id,name,synopsis,created_at,updated_at)
            VALUES (%s,'Class planning','Prepared the next lecture.',%s,%s)""",
            (session_id, datetime(2026, 9, 14, 14, tzinfo=UTC),
             datetime(2026, 9, 14, 14, tzinfo=UTC)))
        cur.execute("""INSERT INTO session_messages
            (session_id,sequence,role,content,created_at)
            VALUES (%s,1,'user','Please track this task.',%s) RETURNING id""",
            (session_id, datetime(2026, 9, 14, 14, tzinfo=UTC)))
        source_message_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO commitment_candidates
            (id,summary,kind,source_type,source_session_id,source_message_id,
             detection_reason,status,created_at,resolved_at)
            VALUES (%s,'Finish lecture preparation','task','session',%s,%s,
                    'explicit','confirmed',%s,%s)""",
            (candidate_id, session_id, source_message_id,
             datetime(2026, 9, 14, 14, tzinfo=UTC),
             datetime(2026, 9, 14, 14, tzinfo=UTC)))
        cur.execute("""INSERT INTO commitments
            (id,candidate_id,summary,kind,status,confirmed_at,updated_at)
            VALUES (%s,%s,'Finish lecture preparation','task','active',%s,%s)""",
            (commitment_id, candidate_id, datetime(2026, 9, 14, 14, tzinfo=UTC),
             datetime(2026, 9, 14, 15, tzinfo=UTC)))
        cur.execute("""INSERT INTO memories
            (content,memory_type,created_at,metadata,approved,review_status)
            VALUES ('Use short class examples','fact',%s,
                    '{"ledger":"biography"}'::jsonb,true,'approved'),
                   ('Too old to include','fact',%s,
                    '{"ledger":"biography"}'::jsonb,true,'approved')""",
            (datetime(2026, 9, 14, 16, tzinfo=UTC),
             datetime(2026, 9, 1, 16, tzinfo=UTC)))
        conn.commit()


def test_catch_up_enforces_boundary_cites_planes_and_merges_duplicates(ensure_db):
    _seed()
    service = CatchUpService(_conn, FakeChanges())

    result = service.respond(
        "catch me up since 2026-09-13 in detail",
        now=datetime(2026, 9, 14, 20, tzinfo=UTC),
    )

    assert result is not None
    assert result["mode"] == "deep"
    assert "Too old to include" not in result["body"]
    assert "[session:" in result["body"]
    assert "[commitment:" in result["body"]
    assert "[project:notion:page-1" in result["body"]
    assert "[memory:" in result["body"]
    assert "inaccessible" in result["body"]
    lecture = [item for item in result["items"] if "lecture preparation" in item["text"]]
    assert len(lecture) == 1
    assert len(lecture[0]["citations"]) == 2


def test_catch_up_rejects_ambiguous_boundary_without_guessing():
    service = CatchUpService(change_reader=None)
    result = service.respond(
        "catch me up since whenever things got weird",
        now=datetime(2026, 9, 14, 20, tzinfo=UTC),
    )

    assert result is not None
    assert result["since"] is None
    assert "couldn't determine the time boundary" in result["body"]


def test_agent_loop_handles_catch_up_without_calling_model_or_observers():
    class Sessions:
        def __init__(self):
            self.messages = []
            self.turns = []

        def recover_interrupted_turns(self, _session_id): return 0
        def append_message(self, session_id, role, content, metadata=None):
            self.messages.append((session_id, role, content, metadata or {}))
            return {"message_id": len(self.messages)}
        def start_turn(self, _session_id, status):
            self.turns.append(status); return {"turn_id": "turn-1"}
        def update_turn(self, _turn_id, status, **_kwargs): self.turns.append(status)

    class CatchUp:
        def respond(self, text, **_kwargs):
            return {"body": "Bounded recap [session:s-1@time]", "since": "then",
                    "until": "now", "mode": "concise"} if "catch me up" in text.lower() else None

    class Provider:
        async def stream(self, *_args, **_kwargs):
            raise AssertionError("model must not be called for deterministic catch-up")
            yield

    class Context:
        def build(self, *_args, **_kwargs): raise AssertionError("context must not be built")

    sessions = Sessions()
    loop = AgentLoop(
        sessions=sessions, context=Context(),
        runner=ModelToolRunner(Provider(), PROFILE, ToolRegistry()),
        system_prompt="Lyra", catch_up=CatchUp(),
    )
    events = asyncio.run(_collect(loop.stream_turn("s-1", "Catch me up since yesterday")))

    assert [event.kind for event in events] == [EventKind.TEXT, EventKind.COMPLETION]
    assert sessions.messages[1][3]["catch_up"] is True
    assert sessions.turns == ["running", "completed"]


async def _collect(stream):
    return [event async for event in stream]
