from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time
import hashlib
from pathlib import Path

import numpy as np

from lyra.away import AwayModeService
from lyra.memory_control import MemoryControlService
from lyra.sessions import SessionService
from lyra.ship_continuity import ShipContinuityService, run_ship_continuity
from tests.db_support import connect_test_db


ROOT = Path(__file__).resolve().parents[1]


def _conn():
    return connect_test_db()


class FakeEmbedding:
    def embed_texts(self, texts):
        values = list(texts)
        return np.zeros((len(values), 384), dtype=np.float32)


class FakeGraphWriter:
    def add_observations(self, observations):
        raise AssertionError(f"ship continuity must not write to the KG: {observations}")


def _reset() -> tuple[SessionService, ShipContinuityService]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        cur.execute(
            """TRUNCATE ship_continuity_events,ship_continuity_policy,
                memory_review_audit,memories,notification_events,away_policy,
                session_turns,session_channels,session_messages,chat_sessions
                RESTART IDENTITY CASCADE"""
        )
        cur.execute("INSERT INTO away_policy(singleton) VALUES (true)")
        cur.execute("INSERT INTO ship_continuity_policy(singleton) VALUES (true)")
        conn.commit()
    embedding = FakeEmbedding()
    control = MemoryControlService(
        embedding_service=embedding,  # type: ignore[arg-type]
        graph_writer=FakeGraphWriter(),  # type: ignore[arg-type]
        connection_factory=_conn,
    )
    story_dir = ROOT / "data" / "test_tmp" / "ship_continuity" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    for path in story_dir.glob("*.md"):
        path.unlink()
    service = ShipContinuityService(
        away=AwayModeService(_conn),
        embedding_service=embedding,  # type: ignore[arg-type]
        memory_control=control,
        connection_factory=_conn,
        story_dir=story_dir,
    )
    return SessionService(_conn), service


def _story(sessions: SessionService, name: str = "Silent Drift") -> str:
    return str(sessions.create_session(name, context_scope="story")["session_id"])


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_defaults_pause_everything_and_target_must_be_story_web(ensure_db):
    sessions, service = _reset()
    ordinary = str(sessions.create_session("Work")["session_id"])
    story = _story(sessions)

    policy = service.get_policy()
    assert policy.enabled is False
    assert policy.paused is True
    assert service.plan_due(force=True) == {"disposition": "paused"}

    try:
        service.set_policy(
            enabled=True, paused=False, ambient_enabled=True,
            target_session_id=ordinary,
        )
    except ValueError as exc:
        assert "story-scoped web session" in str(exc)
    else:
        raise AssertionError("ordinary session was accepted")

    sessions.bind_channel(story, "telegram", "chat-1")
    try:
        service.set_policy(
            enabled=True, paused=False, ambient_enabled=True,
            target_session_id=story,
        )
    except ValueError as exc:
        assert "story-scoped web session" in str(exc)
    else:
        raise AssertionError("Telegram-bound story session was accepted")


def test_explicit_brief_is_grounded_story_only_and_has_no_lookup_preamble(ensure_db):
    sessions, service = _reset()
    story = _story(sessions)
    ordinary = str(sessions.create_session("Us")["session_id"])
    service.set_policy(enabled=True, paused=False, briefs_enabled=True)

    assert service.observe_message(
        session_id=ordinary, message_id=1, text="What's the ship status?"
    ).instruction is None
    observation = service.observe_message(
        session_id=story, message_id=2, text="What's the ship status?"
    )

    assert observation.source_refs[0].startswith("ship-status:")
    assert "do not announce a lookup" in observation.instruction
    assert "preserving any technical register" in observation.instruction
    assert "do not invent a repair" in observation.instruction


def test_ambient_delivery_is_noncanonical_budgeted_and_does_not_mutate_packs(ensure_db):
    sessions, service = _reset()
    story = _story(sessions)
    tracked = [
        ROOT / "ship" / "current_status.json",
        ROOT / "state" / "active_arcs.md",
    ]
    before = {path: _hash(path) for path in tracked}
    with _conn() as conn, conn.cursor() as cur:
        counts = {}
        for table in ("memories", "commitments", "sources"):
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = int(cur.fetchone()[0])
    service.set_policy(
        enabled=True, paused=False, ambient_enabled=True,
        intensity="balanced", target_session_id=story, local_time=time(0, 0),
    )

    planned = service.plan_due(
        now=datetime(2026, 9, 20, 18, tzinfo=UTC), force=True
    )
    assert planned["disposition"] == "send"
    assert planned["event"]["canon_status"] == "ephemeral_noncanonical"
    assert service.plan_due(
        now=datetime(2026, 9, 20, 19, tzinfo=UTC), force=True
    ) == {"disposition": "already_handled"}

    service.plan_due = lambda: planned  # type: ignore[method-assign]
    asyncio.run(run_ship_continuity(sessions, service, iterations=1))
    messages = sessions.list_messages(story)
    assert messages[-1]["metadata"]["ship_continuity"] == "ambient"
    assert messages[-1]["metadata"]["canon_status"] == "ephemeral_noncanonical"
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT channel,category,content FROM notification_events ORDER BY id LIMIT 1"
        )
        notification = cur.fetchone()
        for table, count in counts.items():
            cur.execute(f"SELECT count(*) FROM {table}")
            assert int(cur.fetchone()[0]) == count
    assert notification[0:2] == ("web", "status")
    assert notification[2].startswith("[ship-continuity:ambient:")
    assert all(_hash(path) == digest for path, digest in before.items())


def test_canon_change_stays_pending_until_local_approval_then_regenerates(ensure_db):
    sessions, service = _reset()
    story = _story(sessions)
    before_status = _hash(ROOT / "ship" / "current_status.json")

    proposal = service.propose_canon_update(
        content="The cargo-bay reading nook now has a secured shelf.",
        session_id=story,
        source_message_id=42,
    )
    assert proposal["status"] == "pending"
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT approved,review_status,memory_type,metadata->>'ledger' FROM memories WHERE id=%s",
            (proposal["proposal_id"],),
        )
        assert cur.fetchone() == (False, "pending", "story", "story")
    assert not (service.story_dir / "arcs.md").exists()

    approved = service.approve_canon_update(proposal["proposal_id"])
    assert approved["status"] == "approved"
    assert approved["story_canon"]["story_memory_count"] == 1
    assert "secured shelf" in (service.story_dir / "arcs.md").read_text(encoding="utf-8")
    assert _hash(ROOT / "ship" / "current_status.json") == before_status
