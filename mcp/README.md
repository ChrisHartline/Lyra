# Lyra MCP Layout

This repository uses a local-first MCP server and contract structure.

## Purpose

- Keep executable MCP servers and tool contracts in version control.
- Make local iteration easy before publishing stable integrations.
- Keep tool authority explicit, especially for memory and observation writes.

## Directory structure

- `mcp/server/main.py` exposes the corpus/search server.
- `mcp/server/kg_gatekeeper.py` exposes knowledge-graph search/read/propose
  operations while withholding raw mutation tools.
- `mcp/tools/` documents the current contracts: source ingestion, corpus and
  memory search, gated memory proposals, and knowledge-graph access.

Current contracts:

- [Add source](tools/add_source.md)
- [Search corpus](tools/search_corpus.md)
- [Search memories](tools/search_memories.md)
- [Propose memory](tools/propose_memory.md)
- [Knowledge graph](tools/knowledge_graph.md)

Reusable prompts or static MCP resources may be added when a concrete runtime
consumer exists; empty placeholder directories are not maintained.

## Local and remote strategy

The executable servers are local. Stable contract documentation remains in
this repository and may later be split or published only when a real consumer
requires it. Live secrets never belong in MCP content or configuration tracked
by Git.

## Conventions

- Use kebab-case filenames for tool contracts.
- Keep each contract focused on one concern with explicit inputs and authority.
- Route semantic memory and knowledge-graph writes through their proposal and
  approval gates; agents do not receive raw mutation tools.
- Keep story/campaign ledgers isolated from biography observations.

## Adding tools, including n8n workflows

The current contracts are a starter set, not a closed API. To onboard a
capability via n8n, follow [ADR-001](../docs/adr/001-n8n-automation-plane.md):
workflow -> webhook -> `mcp/tools/<name>.md` contract -> thin MCP handler ->
mocked pytest. Prefer named tools for stable workflows; use a generic
`run_n8n_workflow` only while experimenting. n8n remains optional workflow
glue, never a second memory or corpus store.
