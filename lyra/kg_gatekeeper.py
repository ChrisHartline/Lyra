"""D4.1 — gated knowledge-graph MCP surface for agents.

Agents may search/read and propose observations. Raw mutation tools
(create_entities, add_observations, deletes) are unavailable here.
Writes happen only via scripts/approve_observation.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psycopg

from .config import settings
from .db import connect
from .embeddings import EmbeddingService
from .knowledge_graph import ObservationService


FORBIDDEN_MUTATION_TOOLS = frozenset(
    {
        "create_entities",
        "create_relations",
        "add_observations",
        "delete_entities",
        "delete_observations",
        "delete_relations",
    }
)

ALLOWED_TOOLS = frozenset(
    {
        "search_nodes",
        "read_graph",
        "open_nodes",
        "propose_observation",
        "list_pending_observations",
    }
)


class RejectingGraphWriter:
    """Ensure propose paths never accidentally write to the KG."""

    def add_observation(
        self,
        entity_name: str,
        entity_type: str,
        content: str,
    ) -> dict[str, Any]:
        raise RuntimeError(
            "KG writes are only allowed via scripts/approve_observation.py"
        )


@dataclass
class KgGatekeeperRouter:
    memory_file: str | Path
    embedding_service: EmbeddingService
    connection_factory: Callable[[], psycopg.Connection] = connect

    def list_tools(self) -> list[str]:
        return sorted(ALLOWED_TOOLS)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        if name in FORBIDDEN_MUTATION_TOOLS:
            raise PermissionError(
                f"Tool '{name}' is blocked on lyra-memory gatekeeper. "
                "Propose with propose_observation; approve via "
                "scripts/approve_observation.py."
            )
        if name not in ALLOWED_TOOLS:
            raise ValueError(f"Unknown gatekeeper tool: {name}")

        if name == "read_graph":
            return self._read_graph()
        if name == "search_nodes":
            return self._search_nodes(str(args.get("query", "")))
        if name == "open_nodes":
            names = args.get("names") or []
            if not isinstance(names, list):
                raise ValueError("names must be a list of entity names")
            return self._open_nodes([str(n) for n in names])
        if name == "propose_observation":
            return self._propose_observation(args)
        if name == "list_pending_observations":
            return self._list_pending(int(args.get("limit", 20)))
        raise ValueError(f"Unhandled tool: {name}")

    def _load_entities(self) -> list[dict[str, Any]]:
        path = Path(self.memory_file)
        if not path.exists():
            return []
        entities: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "entity":
                entities.append(
                    {
                        "name": row.get("name"),
                        "entityType": row.get("entityType"),
                        "observations": list(row.get("observations") or []),
                    }
                )
        return entities

    def _read_graph(self) -> dict[str, Any]:
        return {"entities": self._load_entities(), "relations": []}

    def _search_nodes(self, query: str) -> dict[str, Any]:
        needle = query.strip().lower()
        if not needle:
            return {"entities": [], "relations": []}
        matched = []
        for entity in self._load_entities():
            haystacks = [
                str(entity.get("name") or ""),
                str(entity.get("entityType") or ""),
                *list(entity.get("observations") or []),
            ]
            if any(needle in text.lower() for text in haystacks):
                matched.append(entity)
        return {"entities": matched, "relations": []}

    def _open_nodes(self, names: list[str]) -> dict[str, Any]:
        wanted = {name.lower() for name in names}
        matched = [
            entity
            for entity in self._load_entities()
            if str(entity.get("name") or "").lower() in wanted
        ]
        return {"entities": matched, "relations": []}

    def _propose_observation(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text") or args.get("content") or "").strip()
        entity_name = str(args.get("entity_name") or "Christopher")
        entity_type = str(args.get("entity_type") or "person")
        source_type = str(args.get("source_type") or "session")
        if not text:
            raise ValueError("text is required")

        service = ObservationService(
            embedding_service=self.embedding_service,
            graph_writer=RejectingGraphWriter(),
            connection_factory=self.connection_factory,
        )
        created = service.propose_observations(
            text,
            entity_name=entity_name,
            entity_type=entity_type,
            source_type=source_type,
        )
        return {
            "proposed": created,
            "count": len(created),
            "written_to_kg": False,
            "next_step": "Approve with: venv\\Scripts\\python scripts/approve_observation.py <id>",
        }

    def _list_pending(self, limit: int) -> dict[str, Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content, metadata, approved
                    FROM memories
                    WHERE memory_type = 'observation'
                      AND metadata->>'plane' = 'knowledge_graph'
                      AND approved = false
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        pending = []
        for row in rows:
            meta = row[2] or {}
            pending.append(
                {
                    "observation_id": int(row[0]),
                    "content": row[1],
                    "entity_name": meta.get("entity_name"),
                    "entity_type": meta.get("entity_type"),
                    "approved": bool(row[3]),
                }
            )
        return {"pending": pending, "count": len(pending)}


def build_gatekeeper_router() -> KgGatekeeperRouter:
    return KgGatekeeperRouter(
        memory_file=settings.kg_memory_file_path,
        embedding_service=EmbeddingService(),
    )
