from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

import numpy as np
import psycopg

from .db import connect
from .embeddings import EmbeddingService
from .ingest import IngestPipeline
from .memory import sensitivity_flags, validate_persistable_text


def _vector_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vec.tolist()) + "]"


@dataclass
class CorpusService:
    embedding_service: EmbeddingService
    ingest_pipeline: IngestPipeline
    connection_factory: Callable[[], psycopg.Connection] = connect

    def search_corpus(self, query: str, limit: int = 5) -> dict[str, Any]:
        qvec = self.embedding_service.embed_texts([query])[0]
        vector = _vector_literal(qvec)
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      c.id,
                      c.content,
                      s.id,
                      s.title,
                      s.url,
                      s.file_path,
                      1 - (c.embedding <=> %s::vector) AS score
                    FROM chunks c
                    JOIN sources s ON s.id = c.source_id
                    WHERE s.superseded_by IS NULL
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector, vector, limit),
                )
                rows = cur.fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "chunk_id": int(row[0]),
                    "content": row[1],
                    "score": float(row[6]),
                    "citation": {
                        "source_id": int(row[2]),
                        "title": row[3],
                        "url": row[4],
                        "file_path": row[5],
                    },
                }
            )
        return {"query": query, "results": results}

    def add_source(self, source: str, source_type: str = "url", title: str | None = None) -> dict[str, Any]:
        if source_type == "url":
            result = self.ingest_pipeline.ingest_url(source, title=title)
        elif source_type == "file":
            result = self.ingest_pipeline.ingest_file(source, title=title)
        else:
            raise ValueError(f"Unsupported source_type: {source_type}")
        return {
            "source_id": result.source_id,
            "active_source_id": result.active_source_id,
            "was_deduped": result.was_deduped,
        }

    def search_memories(
        self,
        query: str,
        limit: int = 5,
        approved_only: bool = True,
        ledger: str | None = None,
    ) -> dict[str, Any]:
        qvec = self.embedding_service.embed_texts([query])[0]
        vector = _vector_literal(qvec)
        approved_filter = "AND approved = true" if approved_only else ""
        ledger_filter = "AND metadata->>'ledger' = %s" if ledger else ""
        sql = f"""
            SELECT id, content, memory_type, salience, metadata, approved,
                   1 - (embedding <=> %s::vector) AS score
            FROM memories
            WHERE embedding IS NOT NULL
              {approved_filter}
              {ledger_filter}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                params: tuple[Any, ...]
                if ledger:
                    params = (vector, ledger, vector, limit)
                else:
                    params = (vector, vector, limit)
                cur.execute(sql, params)
                rows = cur.fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "memory_id": int(row[0]),
                    "content": row[1],
                    "memory_type": row[2],
                    "salience": int(row[3]),
                    "metadata": row[4] or {},
                    "approved": bool(row[5]),
                    "score": float(row[6]),
                }
            )
        return {"query": query, "results": results}

    def propose_memory(
        self,
        content: str,
        memory_type: str = "fact",
        salience: int = 5,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = validate_persistable_text(content)
        if memory_type == "observation" or (metadata or {}).get("plane") == "knowledge_graph":
            raise ValueError("Knowledge-graph facts must use propose_observation")
        if not 1 <= salience <= 10:
            raise ValueError("Memory salience must be between 1 and 10")
        meta = dict(metadata or {})
        ledger = str(
            meta.get("ledger")
            or (memory_type if memory_type in {"story", "campaign"} else "biography")
        )
        if ledger not in {"biography", "story", "campaign"}:
            raise ValueError("Memory ledger must be biography, story, or campaign")
        meta["ledger"] = ledger
        meta.setdefault("destination_plane", "semantic_memory")
        meta.setdefault("source_type", "agent_proposal")
        meta.setdefault("proposal_reason", "Agent-proposed durable memory")
        meta.setdefault("sensitivity_flags", sensitivity_flags(normalized))
        vec = self.embedding_service.embed_texts([normalized])[0]
        vector = _vector_literal(vec)
        meta_json = json.dumps(meta)
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memories (
                        content, embedding, memory_type, salience, metadata,
                        approved, review_status
                    )
                    VALUES (%s, %s::vector, %s, %s, %s::jsonb, false, 'pending')
                    RETURNING id
                    """,
                    (normalized, vector, memory_type, salience, meta_json),
                )
                memory_id = int(cur.fetchone()[0])
            conn.commit()
        return {"memory_id": memory_id, "approved": False}


class MCPToolRouter:
    def __init__(self, service: CorpusService) -> None:
        self.service = service

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "search_corpus":
            return self.service.search_corpus(
                query=arguments["query"],
                limit=int(arguments.get("limit", 5)),
            )
        if name == "add_source":
            return self.service.add_source(
                source=arguments["source"],
                source_type=arguments.get("source_type", "url"),
                title=arguments.get("title"),
            )
        if name == "search_memories":
            return self.service.search_memories(
                query=arguments["query"],
                limit=int(arguments.get("limit", 5)),
                approved_only=bool(arguments.get("approved_only", True)),
                ledger=arguments.get("ledger"),
            )
        if name == "propose_memory":
            return self.service.propose_memory(
                content=arguments["content"],
                memory_type=arguments.get("memory_type", "fact"),
                salience=int(arguments.get("salience", 5)),
                metadata=arguments.get("metadata", {}),
            )
        raise ValueError(f"Unknown tool: {name}")
