"""Explicit allowlist for tools available to Lyra's conversation runtime."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolAccess(str, Enum):
    READ = "read"
    PROPOSE = "propose"


class ToolDeniedError(PermissionError):
    """Raised when a model requests a tool outside its explicit registry."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    access: ToolAccess = ToolAccess.READ

    def provider_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.input_schema),
            },
        }


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec] | tuple[ToolSpec, ...] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Duplicate runtime tool: {spec.name}")
        self._specs[spec.name] = spec

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def definitions(self) -> list[dict[str, Any]]:
        return [self._specs[name].provider_definition() for name in self.names]

    def read_only(self) -> "ToolRegistry":
        return ToolRegistry(
            tuple(spec for spec in self._specs.values() if spec.access is ToolAccess.READ)
        )

    async def invoke(self, name: str, arguments: Mapping[str, Any]) -> Any:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolDeniedError(f"Tool '{name}' is not available in this runtime")
        if not isinstance(arguments, Mapping):
            raise ToolDeniedError(f"Tool '{name}' requires object arguments")
        payload = dict(arguments)
        if inspect.iscoroutinefunction(spec.handler):
            return await spec.handler(payload)
        return await asyncio.to_thread(spec.handler, payload)


def build_conversation_registry(
    *,
    corpus_router: Any,
    memory_router: Any,
    wiki_router: Any | None = None,
) -> ToolRegistry:
    """Build the fixed MCP facade; routers remain independently testable."""

    def search_corpus(arguments: dict[str, Any]) -> Any:
        return corpus_router.call_tool(
            "search_corpus",
            {
                "query": str(arguments["query"]),
                "limit": min(max(int(arguments.get("limit", 5)), 1), 10),
            },
        )

    def search_memories(arguments: dict[str, Any]) -> Any:
        ledger = str(arguments["ledger"])
        if ledger not in {"biography", "story", "campaign"}:
            raise ToolDeniedError("Memory search requires an approved ledger bucket")
        return corpus_router.call_tool(
            "search_memories",
            {
                "query": str(arguments["query"]),
                "limit": min(max(int(arguments.get("limit", 5)), 1), 10),
                "approved_only": True,
                "ledger": ledger,
            },
        )

    def kg(name: str) -> Callable[[dict[str, Any]], Any]:
        return lambda arguments: memory_router.call_tool(name, arguments)

    object_schema = {"type": "object", "additionalProperties": False}
    specs = [
            ToolSpec(
                "search_corpus",
                "Search the local source corpus and return cited passages.",
                {
                    **object_schema,
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                },
                search_corpus,
            ),
            ToolSpec(
                "search_memories",
                "Search approved semantic memories in one explicit bucket.",
                {
                    **object_schema,
                    "properties": {
                        "query": {"type": "string"},
                        "ledger": {
                            "type": "string",
                            "enum": ["biography", "story", "campaign"],
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query", "ledger"],
                },
                search_memories,
            ),
            ToolSpec(
                "search_nodes",
                "Search approved knowledge-graph nodes.",
                {
                    **object_schema,
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                kg("search_nodes"),
            ),
            ToolSpec(
                "open_nodes",
                "Open approved knowledge-graph nodes by name.",
                {
                    **object_schema,
                    "properties": {
                        "names": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["names"],
                },
                kg("open_nodes"),
            ),
            ToolSpec(
                "read_graph",
                "Read the approved knowledge graph.",
                object_schema,
                kg("read_graph"),
            ),
            ToolSpec(
                "list_pending_observations",
                "List proposed observations awaiting human approval.",
                {
                    **object_schema,
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100}
                    },
                },
                kg("list_pending_observations"),
            ),
            ToolSpec(
                "propose_observation",
                "Propose a non-sensitive observation for later human approval.",
                {
                    **object_schema,
                    "properties": {
                        "text": {"type": "string"},
                        "entity_name": {"type": "string"},
                        "entity_type": {"type": "string"},
                        "source_type": {"type": "string"},
                    },
                    "required": ["text"],
                },
                kg("propose_observation"),
                access=ToolAccess.PROPOSE,
            ),
        ]
    if wiki_router is not None:
        from lyra.knowledge_routing import ROUTES, route_knowledge

        def wiki(name: str) -> Callable[[dict[str, Any]], Any]:
            return lambda arguments: wiki_router.call_tool(name, arguments)

        specs.extend(
            (
                ToolSpec(
                    "wiki_search",
                    "Search standing reference pages. Results are not lived memory.",
                    {
                        **object_schema,
                        "properties": {
                            "query": {"type": "string", "minLength": 1, "maxLength": 500},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                            "bucket": {
                                "type": "string",
                                "enum": [
                                    "lore", "place", "expertise",
                                    "creative_constraint", "terminology", "person",
                                ],
                            },
                        },
                        "required": ["query"],
                    },
                    wiki("wiki_search"),
                ),
                ToolSpec(
                    "wiki_read",
                    "Read one allowlisted standing-reference page by ID; never treat it as recollection.",
                    {
                        **object_schema,
                        "properties": {"page_id": {"type": "string"}},
                        "required": ["page_id"],
                    },
                    wiki("wiki_read"),
                ),
                ToolSpec(
                    "knowledge_route",
                    "Identify the authoritative knowledge plane before retrieval or persistence.",
                    {
                        **object_schema,
                        "properties": {
                            "information_type": {
                                "type": "string",
                                "enum": sorted(ROUTES),
                            }
                        },
                        "required": ["information_type"],
                    },
                    lambda arguments: route_knowledge(str(arguments["information_type"])),
                ),
            )
        )
    return ToolRegistry(tuple(specs))
