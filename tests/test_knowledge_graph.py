"""D3 — MCP knowledge-graph server round-trip (ADR-002).

Spawns the official `@modelcontextprotocol/server-memory` over stdio (the
same command registered in `.cursor/mcp.json`) and exercises a real
create-entity -> add-observation -> search-nodes round trip against an
isolated temp store. No mocking: this is a live subprocess + stdio JSON-RPC
integration test, mirroring how `tests/conftest.py` treats the live Postgres
dependency for Track A.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

KG_SERVER_COMMAND = "npx"
KG_SERVER_ARGS = ["-y", "@modelcontextprotocol/server-memory"]


def _npx_available() -> bool:
    return shutil.which("npx") is not None


async def _round_trip(memory_file: Path) -> dict:
    params = StdioServerParameters(
        command=KG_SERVER_COMMAND,
        args=KG_SERVER_ARGS,
        env={"MEMORY_FILE_PATH": str(memory_file)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            for required in ("create_entities", "add_observations", "search_nodes"):
                assert required in tool_names, f"missing tool: {required}"

            await session.call_tool(
                "create_entities",
                {
                    "entities": [
                        {
                            "name": "Christopher",
                            "entityType": "person",
                            "observations": ["Building Lyra as a personal assistant"],
                        }
                    ]
                },
            )

            await session.call_tool(
                "add_observations",
                {
                    "observations": [
                        {
                            "entityName": "Christopher",
                            "contents": ["Prefers gated, test-verified progress"],
                        }
                    ]
                },
            )

            result = await session.call_tool("search_nodes", {"query": "gated"})
            return result.structured_content


@pytest.mark.skipif(not _npx_available(), reason="npx not available on PATH")
def test_d3_create_entity_add_observation_search_round_trip():
    case_dir = (Path("data/test_tmp") / f"d3_kg_{uuid.uuid4().hex[:8]}").resolve()
    case_dir.mkdir(parents=True, exist_ok=True)
    memory_file = case_dir / "memory.jsonl"
    try:
        payload = asyncio.run(_round_trip(memory_file))

        entities = {e["name"]: e for e in payload["entities"]}
        assert "Christopher" in entities
        observations = entities["Christopher"]["observations"]
        assert "Building Lyra as a personal assistant" in observations
        assert "Prefers gated, test-verified progress" in observations

        # Durable local store: never-persist (FR-M4) applies before any KG
        # write in the future observation write-back path (D4); for D3 we
        # only assert the store is a local file, not a remote/hosted service.
        assert memory_file.exists()
        assert memory_file.parent == case_dir
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
