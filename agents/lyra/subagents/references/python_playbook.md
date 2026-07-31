# Python developer playbook (C3.1)

Read this when implementing Lyra Python work. Canonical agent contract:
`agents/lyra/subagents/python-developer.md`.

## Repository map

| Path | Role |
|---|---|
| `lyra/` | Product services (ingest, memory, digests, briefings, KG) |
| `tests/` | Mirrored pytest suite (`testpaths = ["tests"]`) |
| `scripts/` | Operator CLIs (db, Notion, approve, generate digests/briefings) |
| `mcp/server/` | Stdio MCP entrypoints (`main.py` corpus, `kg_gatekeeper.py` gated KG) |
| `mcp/tools/` | Tool contracts |
| `docs/lyra_build_plan.md` | Gate sequencing and acceptance |
| `docs/lyra_system_requirements.md` | Engineering SRS (not private persona authority) |
| `agents/lyra/` | Persona, skills, subagents, state |

## Architecture invariants

- **Notion** = human dashboard (tasks status + Digests). Never dump intimate personal detail.
- **pgvector** = corpus chunks + episodic memories (approve-before-recall).
- **MCP KG** = structured observations; agents use gatekeeper (`propose`/`search` only).
- **Story/campaign** ledgers stay out of biography KG observations and briefings.
- Secrets only from `.env`. Never commit credentials.

## Test matrix

| Kind | Example | Notes |
|---|---|---|
| Pure unit | Notion responses mocks, digest body builders | No Docker |
| Postgres | `ensure_db` fixture | Docker compose on `55432` |
| MCP subprocess | KG round-trip / gatekeeper | May need `npx` for approve-path writer |
| Live external | Notion publish scripts | Only with explicit user authorization |

## Windows runbook

```text
venv\Scripts\python -m pytest tests/test_<module>.py -q
venv\Scripts\python -m pytest -q
venv\Scripts\python scripts\<cli>.py
```

Prefer repo-root-relative paths. Use `bash -lc "..."` only when a bash installer is required.

## Skill routing

Load domain skills for specialized work (GCP, Vertex, scholarly authoring, etc.).
Do not duplicate skill content into the subagent definition.

## Good handoff pattern

1. What changed (files + behavior)
2. Commands run + real output
3. Risks / skipped checks
4. Human approvals still needed
