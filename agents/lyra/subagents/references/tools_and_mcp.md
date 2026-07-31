# Tools and MCP available to Lyra subagents

Cursor subagents inherit the parent agent's tools. There is no per-agent
`tools:` frontmatter. This file tells each worker what to use — and what to
leave for the parent.

## Always available (typical Cursor parent)

- Filesystem read/write (unless `readonly: true`)
- Shell / terminal
- Repo search (grep/glob equivalents)
- Parent MCP servers registered in `.cursor/mcp.json`

## Project MCP servers

| Server | Purpose | Agent use |
|---|---|---|
| `lyra-corpus` | Corpus + episodic memory tools | Researcher: search; Python: debug ingest/search; never approve memories |
| `lyra-memory` | **Gated** KG (D4.1) | Search/read/propose only; never treat propose as approved write |
| `linear` / `supabase` / `vercel` | External product MCP | Only if the task packet explicitly requires them |

### `lyra-corpus` tools

Contracts: `mcp/tools/*.md`

- `search_corpus` — semantic chunk search with citations
- `add_source` — ingest URL/file into corpus (parent or Python when tasked)
- `search_memories` — approved episodic memory search by default
- `propose_memory` — pending memory only (`approved=false`)

### `lyra-memory` gatekeeper tools

Contract: `mcp/tools/knowledge_graph.md`

- `search_nodes`, `read_graph`, `open_nodes` — read local KG
- `propose_observation` — pending candidates only
- `list_pending_observations` — approval queue
- **Blocked:** `create_entities`, `add_observations`, deletes

Approval CLIs (parent / Christopher only):

- `venv\Scripts\python scripts/approve_memory.py <id>`
- `venv\Scripts\python scripts/approve_observation.py <id>`

## Per-agent tool policy

### `researcher` (`readonly: true`)

Use:

- `search_corpus`, `search_memories` (read)
- Web/docs fetch if available from the parent
- Read repo files for existing notes/contracts

Do not:

- Edit product code
- `add_source` unless the parent packet explicitly requests ingestion
- Propose/approve memories or KG observations
- Publish Notion digests/briefings
- Call blocked KG mutation tools (they should error anyway)

### `python-developer`

Use:

- Filesystem + shell + pytest
- `lyra-corpus` when implementing/debugging ingest/search/memory paths
- `lyra-memory` search/propose only when the packet is about observation code

Do not:

- Live Notion publish unless explicitly authorized
- Approve memories/observations
- Commit/push unless asked
- Expand gate scope without direction

### `cpp-developer`

Use:

- Filesystem + shell in the **named C++ repository**
- That repo's build/test tooling

Do not:

- Assume Lyra MCP/Python tools are relevant
- Touch Lyra Notion/KG/memory planes unless the packet says so

## Parent must include in the task packet

- Which MCP servers (if any) the worker should use
- Whether ingestion (`add_source`) or live external writes are allowed
- Paths to contracts the worker should open first
