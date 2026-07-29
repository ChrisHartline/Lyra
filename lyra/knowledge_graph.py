from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import psycopg
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .db import connect
from .embeddings import EmbeddingService
from .memory import MemoryService, _vector_literal


class KnowledgeGraphWriter(Protocol):
    def add_observation(
        self,
        entity_name: str,
        entity_type: str,
        content: str,
    ) -> dict[str, Any]: ...


@dataclass
class MCPKnowledgeGraphWriter:
    memory_file: str | Path
    command: str = "npx"
    package: str = "@modelcontextprotocol/server-memory"

    async def _add_observation(
        self,
        entity_name: str,
        entity_type: str,
        content: str,
    ) -> dict[str, Any]:
        memory_path = Path(self.memory_file).resolve()
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        params = StdioServerParameters(
            command=self.command,
            args=["-y", self.package],
            env={"MEMORY_FILE_PATH": str(memory_path)},
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                created = await session.call_tool(
                    "create_entities",
                    {
                        "entities": [
                            {
                                "name": entity_name,
                                "entityType": entity_type,
                                "observations": [],
                            }
                        ]
                    },
                )
                if created.is_error:
                    raise RuntimeError(f"create_entities failed: {created.content}")

                added = await session.call_tool(
                    "add_observations",
                    {
                        "observations": [
                            {
                                "entityName": entity_name,
                                "contents": [content],
                            }
                        ]
                    },
                )
                if added.is_error:
                    raise RuntimeError(f"add_observations failed: {added.content}")
                return added.structured_content or {}

    def add_observation(
        self,
        entity_name: str,
        entity_type: str,
        content: str,
    ) -> dict[str, Any]:
        return asyncio.run(self._add_observation(entity_name, entity_type, content))


@dataclass
class ObservationService:
    embedding_service: EmbeddingService
    graph_writer: KnowledgeGraphWriter
    connection_factory: Callable[[], psycopg.Connection] = connect

    def propose_observations(
        self,
        text: str,
        *,
        entity_name: str,
        entity_type: str,
        source_type: str = "session",
    ) -> list[dict[str, Any]]:
        memory_service = MemoryService(
            embedding_service=self.embedding_service,
            connection_factory=self.connection_factory,
        )
        contents = [
            candidate.content.removeprefix("Session note: ")
            for candidate in memory_service.summarize_transcript(text)
            if candidate.ledger == "biography"
        ]

        if not contents:
            return []

        vectors = self.embedding_service.embed_texts(contents)
        created: list[dict[str, Any]] = []
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                for content, vector in zip(contents, vectors):
                    metadata = {
                        "plane": "knowledge_graph",
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                        "source_type": source_type,
                        "proposed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    cur.execute(
                        """
                        INSERT INTO memories (
                            content,
                            embedding,
                            memory_type,
                            salience,
                            metadata,
                            approved
                        )
                        VALUES (%s, %s::vector, 'observation', 5, %s::jsonb, false)
                        RETURNING id, approved
                        """,
                        (content, _vector_literal(vector), json.dumps(metadata)),
                    )
                    row = cur.fetchone()
                    created.append(
                        {
                            "observation_id": int(row[0]),
                            "approved": bool(row[1]),
                            "entity_name": entity_name,
                            "entity_type": entity_type,
                            "content": content,
                        }
                    )
            conn.commit()
        return created

    def approve_observation(self, observation_id: int) -> dict[str, Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT content, metadata, approved
                    FROM memories
                    WHERE id = %s
                      AND memory_type = 'observation'
                      AND metadata->>'plane' = 'knowledge_graph'
                    """,
                    (observation_id,),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError(f"Observation id not found: {observation_id}")

        content, metadata, approved = row
        metadata = dict(metadata or {})
        if approved and metadata.get("kg_written_at"):
            return {
                "observation_id": observation_id,
                "approved": True,
                "written": False,
                "already_written": True,
            }

        entity_name = metadata["entity_name"]
        entity_type = metadata["entity_type"]
        self.graph_writer.add_observation(entity_name, entity_type, content)

        metadata["kg_written_at"] = datetime.now(timezone.utc).isoformat()
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE memories
                    SET approved = true, metadata = %s::jsonb
                    WHERE id = %s
                    RETURNING approved
                    """,
                    (json.dumps(metadata), observation_id),
                )
                updated = cur.fetchone()
            conn.commit()

        return {
            "observation_id": observation_id,
            "approved": bool(updated[0]),
            "written": True,
            "already_written": False,
        }
