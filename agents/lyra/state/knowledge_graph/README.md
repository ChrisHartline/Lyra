# Knowledge Graph local store (D3, ADR-002)

`memory.jsonl` in this folder is the live local store for Lyra's knowledge
graph. Cursor agents reach it through the **gatekeeper** (`lyra-memory` →
`mcp/server/kg_gatekeeper.py`): search/read + propose only. Approved writes
still use the official memory server under `scripts/approve_observation.py`.
The file is created on first write and is **gitignored**.

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
