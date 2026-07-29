from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

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


class RecordingGraphWriter:
    def __init__(self) -> None:
        self.writes: list[dict[str, str]] = []

    def add_observation(
        self,
        entity_name: str,
        entity_type: str,
        content: str,
    ) -> dict[str, Any]:
        self.writes.append(
            {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "content": content,
            }
        )
        return {"results": [{"entityName": entity_name}]}


async def _search_graph(memory_file: Path, query: str) -> dict[str, Any]:
    params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        env={"MEMORY_FILE_PATH": str(memory_file)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_nodes", {"query": query})
            return result.structured_content or {}


def test_d4_unapproved_observation_is_not_written(ensure_db):
    _reset_tables()
    writer = RecordingGraphWriter()
    service = ObservationService(
        embedding_service=FakeEmbedder(),
        graph_writer=writer,
        connection_factory=_conn,
    )

    proposed = service.propose_observations(
        "Christopher prefers gated and test-verified delivery for Lyra.",
        entity_name="Christopher",
        entity_type="person",
    )

    assert len(proposed) == 1
    assert proposed[0]["approved"] is False
    assert writer.writes == []

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT approved FROM memories WHERE id = %s",
                (proposed[0]["observation_id"],),
            )
            assert cur.fetchone()[0] is False


def test_d4_secret_bearing_transcript_produces_zero_candidates_or_writes(ensure_db):
    _reset_tables()
    writer = RecordingGraphWriter()
    service = ObservationService(
        embedding_service=FakeEmbedder(),
        graph_writer=writer,
        connection_factory=_conn,
    )

    proposed = service.propose_observations(
        "API key is xai-123456789SECRET and password is hunter2.",
        entity_name="Christopher",
        entity_type="person",
    )

    assert proposed == []
    assert writer.writes == []
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM memories
                WHERE memory_type = 'observation'
                  AND metadata->>'plane' = 'knowledge_graph'
                """
            )
            assert cur.fetchone()[0] == 0


def test_d4_story_and_campaign_content_never_becomes_kg_candidates(ensure_db):
    _reset_tables()
    writer = RecordingGraphWriter()
    service = ObservationService(
        embedding_service=FakeEmbedder(),
        graph_writer=writer,
        connection_factory=_conn,
    )

    proposed = service.propose_observations(
        "We reviewed the D.Eng task roadmap for this week. "
        "Lyra repaired the ship phase regulator and stabilized the coils. "
        "In campaign combat we rolled initiative against an orc patrol.",
        entity_name="Christopher",
        entity_type="person",
    )

    assert len(proposed) == 1
    assert "task roadmap" in proposed[0]["content"]
    assert all("ship" not in item["content"].lower() for item in proposed)
    assert all("campaign" not in item["content"].lower() for item in proposed)
    assert writer.writes == []


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not available on PATH")
def test_d4_approved_observation_appears_on_entity(ensure_db):
    _reset_tables()
    case_dir = (
        Path("data/test_tmp") / f"d4_observations_{uuid.uuid4().hex[:8]}"
    ).resolve()
    case_dir.mkdir(parents=True, exist_ok=True)
    memory_file = case_dir / "memory.jsonl"
    try:
        service = ObservationService(
            embedding_service=FakeEmbedder(),
            graph_writer=MCPKnowledgeGraphWriter(memory_file),
            connection_factory=_conn,
        )
        proposed = service.propose_observations(
            "Christopher prefers gated and test-verified delivery for Lyra.",
            entity_name="Christopher",
            entity_type="person",
            source_type="session",
        )

        result = service.approve_observation(proposed[0]["observation_id"])
        assert result["approved"] is True
        assert result["written"] is True

        graph = asyncio.run(_search_graph(memory_file, "test-verified"))
        entities = {entity["name"]: entity for entity in graph["entities"]}
        assert "Christopher" in entities
        assert (
            "Christopher prefers gated and test-verified delivery for Lyra"
            in entities["Christopher"]["observations"]
        )
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
