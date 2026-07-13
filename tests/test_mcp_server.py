from __future__ import annotations

from pathlib import Path
import shutil
import uuid

import numpy as np
import psycopg
import responses

from lyra.corpus_mcp import CorpusService, MCPToolRouter
from lyra.ingest import IngestPipeline

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
        out = []
        for text in texts:
            t = text.lower()
            v = np.zeros(384, dtype=np.float32)
            if "quantum" in t:
                v[0] += 1.0
            if "qnn" in t or "ansatz" in t:
                v[1] += 0.7
            if "pizza" in t:
                v[200] += 1.0
            if not v.any():
                v[50] = 1.0
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return np.array(out)


def _router(tmp_suffix: str) -> MCPToolRouter:
    root = Path("data/test_tmp")
    root.mkdir(parents=True, exist_ok=True)
    case = root / f"a4_{tmp_suffix}_{uuid.uuid4().hex[:8]}"
    case.mkdir(parents=True, exist_ok=True)
    embedder = FakeEmbedder()
    ingest = IngestPipeline(embedding_service=embedder, connection_factory=_conn, raw_root=case / "raw")
    service = CorpusService(embedding_service=embedder, ingest_pipeline=ingest, connection_factory=_conn)
    router = MCPToolRouter(service)
    router._tmp_case = case  # type: ignore[attr-defined]
    return router


@responses.activate
def test_a4_search_corpus_returns_citations_and_add_source_triggers_ingest(ensure_db):
    _reset_tables()
    router = _router("clientcall")
    case = router._tmp_case  # type: ignore[attr-defined]
    try:
        url = "https://example.com/quantum"
        html = "<html><body><p>Quantum circuit and QNN ansatz guidance.</p></body></html>"
        responses.add(responses.GET, url, body=html, status=200)

        add_result = router.call_tool("add_source", {"source": url, "source_type": "url", "title": "QNN Note"})
        assert add_result["source_id"] >= 1

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT file_path FROM sources WHERE id = %s", (add_result["source_id"],))
                row = cur.fetchone()
                assert row and Path(row[0]).exists()
                cur.execute("SELECT COUNT(*) FROM chunks WHERE source_id = %s", (add_result["active_source_id"],))
                assert cur.fetchone()[0] >= 1

        # Simulated MCP client call path through router.
        result = router.call_tool("search_corpus", {"query": "quantum circuit", "limit": 3})
        assert result["results"], "Expected at least one retrieved chunk"
        top = result["results"][0]
        assert "citation" in top
        assert top["citation"]["source_id"] >= 1
        assert top["citation"]["title"] == "QNN Note"
    finally:
        shutil.rmtree(case, ignore_errors=True)
