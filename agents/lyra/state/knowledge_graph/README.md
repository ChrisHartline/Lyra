# Knowledge Graph local store (D3, ADR-002)

`memory.jsonl` in this folder is the live local store for the MCP knowledge
graph server (`@modelcontextprotocol/server-memory`, registered as
`lyra-memory` in `.cursor/mcp.json`). It is created automatically by the
server on first write and is **gitignored** — it holds real entities,
relations, and observations about Christopher and his projects, not fiction,
and is never checked into version control.

- Tool contracts + entity taxonomy: `mcp/tools/knowledge_graph.md`
- Observation etiquette: `agents/lyra/references/observation_etiquette.md`
- Design decision: `docs/adr/002-mcp-knowledge-graph-memory.md`
- Env var controlling the path: `LYRA_KG_MEMORY_FILE_PATH` (must be an
  **absolute** path — the server resolves relative paths against its own
  install directory, not the caller's working directory)

## Boundary reminder

This store is the **structured observation plane** only. It does not
replace pgvector episodic memory (approved session summaries, FR-M*) or the
corpus (ingested documents). See ADR-002 for the full split.
