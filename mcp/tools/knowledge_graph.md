# MCP server: lyra-memory (knowledge graph)

## Purpose
Structured observation plane for the personal/professional assistant
(Phase 2, D3–D5; ADR-002). Distinct from the corpus (documents) and the
pgvector episodic memory (approved session summaries, FR-M*).

## Server
- Package: [`@modelcontextprotocol/server-memory`](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md)
  (official MCP reference server), registered as `lyra-memory` in
  `.cursor/mcp.json`.
- Storage: local JSONL file at `LYRA_KG_MEMORY_FILE_PATH` (must be absolute).
  See `agents/lyra/state/knowledge_graph/README.md`.

## Entity taxonomy
Entity `entityType` values Lyra should use when writing to this graph:

| entityType | Examples |
|---|---|
| `person` | Christopher, named collaborators/contacts |
| `project` | Lyra, everwood, other named workstreams |
| `org` | Employers, companies, institutions |
| `habit` | Recurring behaviors/routines worth remembering |
| `commitment` | Standing obligations, recurring tasks, promises |

Relations are directed, active-voice edges between entities (e.g.
`Christopher --works_on--> Lyra`). Observations are atomic, one fact per
string, attached to a single entity.

## Tools (via MCP stdio, JSON-RPC `tools/call`)
- `create_entities` — `{ entities: [{ name, entityType, observations[] }] }`; ignores existing names.
- `create_relations` — `{ relations: [{ from, to, relationType }] }`; skips duplicates.
- `add_observations` — `{ observations: [{ entityName, contents[] }] }`; fails if entity missing.
- `delete_entities` / `delete_observations` / `delete_relations` — cascading/targeted removal.
- `read_graph` — full graph dump, no input.
- `search_nodes` — `{ query }`; matches entity names, types, and observation text.
- `open_nodes` — `{ names[] }`; fetch specific entities + relations between them.

## Write policy (FR-M3 / FR-M4 spirit, per ADR-002 decision 4)
Observations touching biography/relationship content must go through the
same approve-before-persist and never-persist discipline as pgvector
memory (FR-M3/FR-M4). `ObservationService.propose_observations` stores
filtered candidates as unapproved rows in pgvector; it does not call the
KG. Only the explicit `approve_observation` action mirrors the candidate
through the MCP server and marks it approved. Use
`scripts/approve_observation.py <id>` for the human approval action.

## Verification
`tests/test_knowledge_graph.py` spawns the real server over stdio (no
mocking) against an isolated temp store and exercises
`create_entities` → `add_observations` → `search_nodes`.

`tests/test_observations.py` verifies the D4 policy: unapproved candidates
produce no KG writes, sensitive transcripts produce no candidates or
writes, and an explicitly approved candidate appears on its entity in the
real MCP server.
