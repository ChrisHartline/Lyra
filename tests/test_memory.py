from __future__ import annotations

from pathlib import Path
import shutil
import uuid

import numpy as np
import psycopg

from lyra.corpus_mcp import CorpusService
from lyra.memory import MemoryService

TEST_DB = {
    "host": "127.0.0.1",
    "port": 55432,
    "dbname": "lyra",
    "user": "lyra",
    "password": "lyra",
}


def _conn():
    return psycopg.connect(**TEST_DB, connect_timeout=3)


def _reset_tables() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cur.execute("TRUNCATE chunks, sources, memories RESTART IDENTITY CASCADE")
        conn.commit()


class FakeEmbedder:
    def embed_texts(self, texts):
        vectors = []
        for text in texts:
            t = text.lower()
            v = np.zeros(384, dtype=np.float32)
            if "story" in t or "ship" in t or "repair" in t:
                v[0] += 1.0
            if "campaign" in t or "combat" in t or "initiative" in t:
                v[1] += 1.0
            if "session" in t or "task" in t or "research" in t:
                v[2] += 1.0
            if not v.any():
                v[10] = 1.0
            n = np.linalg.norm(v)
            vectors.append(v / n if n else v)
        return np.array(vectors)


class _NoopIngest:
    def ingest_url(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def ingest_file(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _memory_service() -> MemoryService:
    return MemoryService(embedding_service=FakeEmbedder(), connection_factory=_conn)


def _corpus_service() -> CorpusService:
    return CorpusService(
        embedding_service=FakeEmbedder(),
        ingest_pipeline=_NoopIngest(),  # type: ignore[arg-type]
        connection_factory=_conn,
    )


def _case_dir(name: str) -> Path:
    root = Path("data/test_tmp")
    root.mkdir(parents=True, exist_ok=True)
    case = root / f"{name}_{uuid.uuid4().hex[:8]}"
    case.mkdir(parents=True, exist_ok=True)
    return case


def test_a5_candidate_memory_approval_and_search_gate(ensure_db):
    _reset_tables()
    mem = _memory_service()
    corpus = _corpus_service()

    transcript = "We finalized the research task plan for next sprint and agreed execution checkpoints."
    created = mem.writeback_session(transcript)
    assert len(created) >= 1

    hidden = corpus.search_memories("research task", approved_only=True)
    assert hidden["results"] == []

    first_id = created[0]["memory_id"]
    approved = mem.approve_memory(first_id)
    assert approved["approved"] is True

    visible = corpus.search_memories("research task", approved_only=True)
    assert len(visible["results"]) >= 1
    assert any(r["memory_id"] == first_id for r in visible["results"])


def test_a5_never_persist_filter_blocks_sensitive_content(ensure_db):
    _reset_tables()
    mem = _memory_service()

    transcript = (
        "API key is xai-123456789SECRET and password is hunter2. "
        "My friend Sarah's phone is 555-111-2222."
    )
    created = mem.writeback_session(transcript)
    assert created == []

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memories")
            assert cur.fetchone()[0] == 0


def test_a5_ledger_isolation_and_story_regeneration(ensure_db):
    _reset_tables()
    mem = _memory_service()
    corpus = _corpus_service()

    transcript = (
        "We reviewed the D.Eng task roadmap for this week. "
        "Lyra repaired the ship phase regulator and stabilized entanglement coils. "
        "In campaign combat we rolled initiative and fought an orc patrol."
    )
    created = mem.writeback_session(transcript)
    assert len(created) >= 3

    ledgers = {c["ledger"] for c in created}
    assert {"biography", "story", "campaign"}.issubset(ledgers)

    for item in created:
        mem.approve_memory(item["memory_id"])

    bio_only = corpus.search_memories("task roadmap", approved_only=True, ledger="biography")
    assert bio_only["results"], "Expected biography-ledger results"
    assert all((r["metadata"] or {}).get("ledger") == "biography" for r in bio_only["results"])

    case = _case_dir("a5_story_regen")
    try:
        story_out = case / "story"
        regen = mem.regenerate_story_canon(story_out)
        assert regen["story_memory_count"] >= 1
        ship = (story_out / "ship.md").read_text(encoding="utf-8").lower()
        assert "phase regulator" in ship or "repair" in ship
    finally:
        shutil.rmtree(case, ignore_errors=True)
