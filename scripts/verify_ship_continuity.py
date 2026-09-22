"""Run a bounded live W8.3 brief smoke and restore production state."""

from __future__ import annotations

import hashlib
from pathlib import Path
import uuid

from lyra.away import AwayModeService
from lyra.db import connect
from lyra.embeddings import EmbeddingService
from lyra.sessions import SessionService
from lyra.ship_continuity import ShipContinuityService


ROOT = Path(__file__).resolve().parents[1]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    sessions = SessionService(connect)
    continuity = ShipContinuityService(
        away=AwayModeService(connect),
        embedding_service=EmbeddingService(),
        connection_factory=connect,
    )
    original = continuity.policy_dict()
    tracked = [ROOT / "ship" / "current_status.json", ROOT / "state" / "active_arcs.md"]
    before_hashes = {path: _hash(path) for path in tracked}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ship_continuity_events")
        before_events = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM memories")
        before_memories = int(cur.fetchone()[0])

    session_id: str | None = None
    try:
        session = sessions.create_session(
            f"W8.3 Live Smoke {uuid.uuid4()}", context_scope="story"
        )
        session_id = str(session["session_id"])
        continuity.set_policy(
            enabled=True,
            paused=False,
            briefs_enabled=True,
            ambient_enabled=False,
            intensity="quiet",
            cadence_days=7,
            local_time=original["local_time"],
            timezone=original["timezone"],
            target_session_id=None,
        )
        observation = continuity.observe_message(
            session_id=session_id,
            message_id=1,
            text="What's the ship status?",
            ledger="story",
            channel="web",
        )
        if not observation.instruction or not observation.source_refs:
            raise RuntimeError("Ship continuity did not produce a grounded brief")
        if "do not announce a lookup" not in observation.instruction:
            raise RuntimeError("Direct-response constraint is missing")
        print("Grounded brief: PASS")
        print("Sources: " + ", ".join(observation.source_refs))
    finally:
        continuity.set_policy(**original)
        if session_id is not None:
            sessions.delete_session(session_id)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ship_continuity_events")
        after_events = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM memories")
        after_memories = int(cur.fetchone()[0])
    if (before_events, before_memories) != (after_events, after_memories):
        raise RuntimeError("Smoke changed event or memory counts")
    if any(_hash(path) != digest for path, digest in before_hashes.items()):
        raise RuntimeError("Smoke changed canonical ship or story inputs")
    if continuity.policy_dict() != original:
        raise RuntimeError("Smoke did not restore ship-continuity policy")
    print("Cleanup and policy restoration: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
