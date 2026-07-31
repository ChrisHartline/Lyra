"""D4.1 — gated KG MCP surface (no raw mutation tools for agents)."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import numpy as np
import psycopg
import pytest

from lyra.kg_gatekeeper import (
    ALLOWED_TOOLS,
    FORBIDDEN_MUTATION_TOOLS,
    KgGatekeeperRouter,
    RejectingGraphWriter,
)
from lyra.knowledge_graph import MCPKnowledgeGraphWriter, ObservationService

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
            vector = np.zeros(384, dtype=np.float32)
            vector[0] = max(len(text), 1)
            vectors.append(vector / np.linalg.norm(vector))
        return np.array(vectors)


def _router(memory_file: Path) -> KgGatekeeperRouter:
    return KgGatekeeperRouter(
        memory_file=memory_file,
        embedding_service=FakeEmbedder(),
        connection_factory=_conn,
    )


def test_d41_forbidden_mutation_tools_are_blocked():
    case = (Path("data/test_tmp") / f"d41_{uuid.uuid4().hex[:8]}").resolve()
    case.mkdir(parents=True, exist_ok=True)
    memory_file = case / "memory.jsonl"
    try:
        router = _router(memory_file)
        assert "propose_observation" in router.list_tools()
        assert "search_nodes" in router.list_tools()
        for tool in FORBIDDEN_MUTATION_TOOLS:
            assert tool not in ALLOWED_TOOLS
            with pytest.raises(PermissionError):
                router.call_tool(tool, {})
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_d41_propose_does_not_write_kg_and_search_reads_approved_file(ensure_db):
    _reset_tables()
    case = (Path("data/test_tmp") / f"d41_prop_{uuid.uuid4().hex[:8]}").resolve()
    case.mkdir(parents=True, exist_ok=True)
    memory_file = case / "memory.jsonl"
    try:
        router = _router(memory_file)
        proposed = router.call_tool(
            "propose_observation",
            {
                "text": "Christopher prefers gated knowledge-graph writes for Lyra.",
                "entity_name": "Christopher",
                "entity_type": "person",
            },
        )
        assert proposed["count"] >= 1
        assert proposed["written_to_kg"] is False
        assert not memory_file.exists() or memory_file.read_text(encoding="utf-8").strip() == ""

        pending = router.call_tool("list_pending_observations", {"limit": 5})
        assert pending["count"] >= 1
        observation_id = pending["pending"][0]["observation_id"]

        # Approve via the CLI path writer (raw MCP still allowed for approval only).
        if shutil.which("npx") is None:
            pytest.skip("npx not available for approval-path writer")

        service = ObservationService(
            embedding_service=FakeEmbedder(),
            graph_writer=MCPKnowledgeGraphWriter(memory_file),
            connection_factory=_conn,
        )
        approved = service.approve_observation(observation_id)
        assert approved["written"] is True

        search = router.call_tool("search_nodes", {"query": "gated"})
        names = {entity["name"] for entity in search["entities"]}
        assert "Christopher" in names
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_d41_mcp_json_points_at_gatekeeper_not_raw_memory_server():
    config = json.loads(Path(".cursor/mcp.json").read_text(encoding="utf-8"))
    memory = config["mcpServers"]["lyra-memory"]
    assert memory["command"].endswith("python") or "python" in memory["command"]
    assert any("kg_gatekeeper.py" in str(arg) for arg in memory["args"])
    assert "@modelcontextprotocol/server-memory" not in memory.get("args", [])


def test_d41_rejecting_writer_blocks_direct_writes():
    writer = RejectingGraphWriter()
    with pytest.raises(RuntimeError, match="approve_observation"):
        writer.add_observation("Christopher", "person", "should fail")
