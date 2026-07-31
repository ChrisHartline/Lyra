# MCP server: lyra-memory (knowledge graph)

## Purpose
Structured observation plane for the personal/professional assistant
(Phase 2, D3–D5; ADR-002). Distinct from the corpus (documents) and the
pgvector episodic memory (approved session summaries, FR-M*).

## Server (D4.1 gatekeeper)
- **Agent-facing registration** in `.cursor/mcp.json`: `lyra-memory` →
  `mcp/server/kg_gatekeeper.py` (Python FastMCP).
- **Storage:** local JSONL at `LYRA_KG_MEMORY_FILE_PATH` (absolute path).
  See `agents/lyra/state/knowledge_graph/README.md`.
- **Approval-only writer:** `scripts/approve_observation.py` may still spawn
  the official `@modelcontextprotocol/server-memory` package under the hood.
  That raw mutation surface is **not** registered for Cursor agents.

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

## Agent-facing tools (gatekeeper)
- `search_nodes` — `{ query }`; local JSONL search over names/types/observations.
- `read_graph` — full entity dump from the local store.
- `open_nodes` — `{ names[] }`; fetch specific entities.
- `propose_observation` — `{ text, entity_name?, entity_type?, source_type? }`;
  creates pending pgvector candidates only (`written_to_kg=false`).
- `list_pending_observations` — `{ limit? }`; pending approve queue.

## Blocked on the agent surface
`create_entities`, `create_relations`, `add_observations`, `delete_entities`,
`delete_observations`, `delete_relations` — return permission errors if called
through the gatekeeper router.

## Write policy
1. Agents propose only.
2. Christopher approves via `scripts/approve_observation.py <id>`.
3. Never-persist + biography-only filtering apply before candidates are created.
4. Story/campaign content never becomes KG observations.
5. Etiquette: `agents/lyra/references/observation_etiquette.md`.

## Verification
- D3: `tests/test_knowledge_graph.py` — raw server round-trip (approve path).
- D4: `tests/test_observations.py` — propose/approve policy.
- D4.1: `tests/test_kg_gatekeeper.py` — mutation tools blocked; mcp.json points
  at gatekeeper; propose does not write until approval.
