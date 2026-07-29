# Lyra — Phase 1 Build Plan

**Version:** 0.1
**Companion to:** `docs/lyra_system_requirements.md` (SRS v0.7)
**Audience:** The implementing agent (Cursor/Claude) and Christopher.

This document controls **sequencing and verification**. The SRS controls **what** is built. If this plan and the SRS conflict, the SRS wins; flag the conflict instead of improvising.

## Rules of Engagement (for the implementing agent)

1. **Gated progression.** Do not begin a task until every task it depends on has passing acceptance tests. Parallel tracks (A/B/C) may be worked in any interleaving.
2. **Run the tests; report real output.** Never assert a test passed without executing it (SRS VA-3 / NFR-7). Paste actual pytest output when marking a task done.
3. **One task, one commit (minimum).** Commit at each green gate with the task ID in the message (e.g., `A3: ingestion pipeline`), so progress is bisectable.
4. **Full suite before "done."** A task is complete only when the entire test suite is green, not just its own tests (VA-4).
5. **Stay in scope.** If a task appears to require work not in the SRS, stop and ask rather than expanding scope.
6. **Secrets discipline.** Connection strings and API keys come from `.env` only. Never write a credential into code, tests, fixtures, or this plan.
7. **Test layout.** All tests live under `tests/`, mirroring the package structure (`tests/test_ingest.py` for `lyra/ingest.py`, etc.), with shared fixtures in `tests/conftest.py`. Pytest is configured in `pyproject.toml` (`testpaths = ["tests"]`). No test files in the repo root — ever.
8. **Stack coherence (SRS NFR-8).** Do not introduce new services, databases, hosting locations, or heavyweight dependencies beyond the deployment map (SRS §2.5). If a task seems to need one, stop and raise it as an ADR candidate (SRS §10) instead of adding it.

## Task DAG

```mermaid
graph TD
    subgraph Track A — Data Plane
        A1[A1: pgvector deploy + schema]
        A2[A2: embedding module]
        A3[A3: ingestion pipeline]
        A4[A4: corpus MCP server]
        A5[A5: memory write-back + approval gate]
        A1 --> A3
        A2 --> A3
        A3 --> A4
        A4 --> A5
    end
    subgraph Track B — Notion
        B1[B1: Notion inbound read]
        B2[B2: Notion outbound update]
        B1 --> B2
    end
    subgraph Track C — Orchestration & Persona
        C1[C1: subagent definitions + sync script]
        C2[C2: persona layer reorg + story scaffold]
    end
    C2 --> A5
```

Tracks A, B, and C are **independent** and may run in parallel (e.g., as separate Cursor subagents/background agents), with one cross-track edge: **A5 additionally requires C2** (the story scaffold must exist before canon regeneration is testable). Within a track, order is strict.

## Task Definitions & Acceptance Criteria

### Track A — Data Plane

**A1 — pgvector deployment + schema** *(SRS §4, Appendix A)*
Deliverables: `docker-compose.yml`, `db/schema.sql`, `scripts/db_init.(ps1|py)`, `scripts/db_backup.(ps1|py)` with documented restore procedure (NFR-9); repo scaffolding — `pyproject.toml` with pytest config and all dependencies (delete the empty `requirements.txt`), plus the `tests/` directory (Rule 7).
Acceptance: container healthy; `vector` extension present; `sources`, `chunks`, `memories` tables exist; test inserts a row with a 384-dim vector and retrieves it by cosine similarity.

**A2 — Embedding module** *(SRS §2.3)* — no dependencies; may start immediately in parallel with A1.
Deliverables: `lyra/embeddings.py` wrapping sentence-transformers (MiniLM-class, CPU).
Acceptance: embeds a list of strings → 384-dim vectors; sanity test asserts cosine("quantum circuit", "QNN ansatz") > cosine("quantum circuit", "pizza recipe").

**A3 — Ingestion pipeline** *(FR-R1, FR-R2)* — depends on A1 + A2.
Deliverables: `lyra/ingest.py` (fetch → store raw under `data/` → chunk → embed → insert with provenance).
Acceptance: ingesting one URL and one local PDF produces `sources` rows with correct provenance, ≥1 `chunks` row each with non-null embeddings, and raw files on disk referenced by `file_path`. Dedup test (FR-R5): ingesting the same article twice, and as both PDF and DOCX, yields exactly one active source (preferred format) with the superseded copy's chunks removed and its `sources` row marked `superseded_by`.

**A4 — Corpus MCP server** *(FR-R6, IF-4)* — depends on A3.
Deliverables: `mcp/server/` Python MCP server exposing `search_corpus`, `add_source`, `search_memories`, `propose_memory`; contracts documented in `mcp/tools/`; registered in `.cursor/mcp.json`.
Acceptance: an MCP client call to `search_corpus` over A3's test data returns relevant chunks **with source citations**; `add_source` triggers ingestion end-to-end.

**A5 — Memory write-back with approval gate** *(FR-M1–M5, FR-P5, FR-D2)* — depends on A4 and C2.
Deliverables: `lyra/memory.py` write-back job (session → candidate memories with `approved=false`) with bucket typing (biography/story/campaign per FR-D2); approval CLI/flow; retrieval respects the flag and filters by bucket; story-canon regeneration producing `agents/lyra/state/story/*.md` from approved `story` memories (FR-P5).
**v1 honesty note:** Phase 1 acceptance is met by a deterministic stub (sentence split, keyword bucket tags, regex never-persist). That is enough to prove the approve-before-recall contract. LLM summarization and stronger classification are follow-ons; they must not weaken FR-M3/FR-M4.
Acceptance: a sample session transcript yields ≥1 candidate memory; unapproved memories are excluded from `search_memories`; approving flips inclusion; never-persist filter test (FR-M4): a transcript containing a fake API key and a third party's personal details produces zero candidate memories containing either; bucket isolation test (FR-D2): a mixed transcript (real task discussion + in-story ship repair + campaign combat) yields memories correctly typed to their buckets, and a biography query returns no story/campaign content; regenerating `ship.md` from approved story memories reflects the session's repair progress.

### Track B — Notion

**B1 — Inbound read** *(FR-N1)*
Deliverables: `lyra/notion_sync.py` read path against a designated sandbox page + database.
Acceptance: given the sandbox page ID, returns its current content/properties; a manual edit to the page is reflected on the next read.

**B2 — Outbound update** *(FR-N2)* — depends on B1.
Deliverables: write path — update task status, create digest page.
Acceptance: test creates a digest page in the sandbox database with title, body, and source links; updates a task property; both verified by reading back via B1's path.

**B3 — Digests vs Projects split** *(FR-N2 hygiene)* — depends on B2; Phase 1 follow-on.
Deliverables: separate Notion targets — Projects/tasks DB for status only; dedicated Digests DB for research/daily/weekly digests; `scripts/notion_ensure_digests_db.py`; env keys `LYRA_NOTION_TASKS_DATABASE_ID` + `LYRA_NOTION_DIGESTS_DATABASE_ID`; e2e writes digests only to Digests.
Acceptance: creating a digest does not insert a row into the Projects DB; task Status updates still target a Projects row; Digests row has Type ∈ {research, daily, weekly, personal, professional}.

### Track C — Orchestration

**C1 — Subagent definitions + sync script** *(FR-S4, FR-S5)*
Deliverables: `agents/lyra/subagents/{researcher,python-developer,cpp-developer}.md` with frontmatter (name, description, model); `scripts/sync_subagents.(ps1|py)` copying to `.cursor/agents/`.
Acceptance: frontmatter validates (script-checked); sync produces byte-identical copies in `.cursor/agents/`; one subagent successfully invoked on a trivial task in Cursor (manual check, noted in the task log).

**C2 — Persona layer reorganization** *(FR-P4, FR-P5)* — no dependencies; gates A5.
Deliverables: split `agents/lyra/references/` backstory into per-topic files (mechanical split, no rewording); scaffold `agents/lyra/state/story/` with templated `ship.md`, `arcs.md`, `timeline.md`; update `DIRECTORY_GUIDE.md`. **Note:** PRIV-1 is decided (private repo) — `state/` content commits normally.
Acceptance: per-topic reference files exist with zero content loss (script compares total normalized text before/after); story scaffold present; guide updated; Christopher's review sign-off recorded in the progress log (persona-adjacent content requires human eyes, per FR-P6 spirit).

## Exit Criteria for Phase 1

All ten gates green, full suite green, and a live end-to-end demo: Christopher asks Lyra to research a topic → sources ingested → corpus answer with citations → digest posted to Notion → candidate memory proposed and approved.

## Phase 2 preview — Personal assistant, Notion digests, knowledge graph

Companion intent (SRS to be updated before gates open): Lyra as a **daily / weekly personal + professional assistant**, with Notion as the human dashboard and an MCP knowledge graph for structured observations.

```mermaid
graph TD
    subgraph Track D — Assistant plane
        D1[D1: Digests taxonomy + Notion Digests DB live]
        D2[D2: Daily/weekly digest jobs]
        D3[D3: MCP knowledge-graph server]
        D4[D4: Observation write path with approval]
        D5[D5: Assistant briefing assembly]
        D1 --> D2
        D3 --> D4
        D2 --> D5
        D4 --> D5
    end
    B3 -.-> D1
    A5 -.-> D4
```

**D1 — Digests taxonomy live** — depends on B3.  
Wire `LYRA_NOTION_DIGESTS_DATABASE_ID` to a real Digests DB; research digests land there; Projects board only receives Status updates.  
Acceptance: live e2e creates a Digests row (Type=research) and does not create a Projects row.

**D2 — Daily / weekly digest jobs** — depends on D1.  
Scheduled or on-demand generators for personal + professional digests (sources: recent tasks, corpus hits, approved memories). Publish to Digests DB; optional notify via n8n/Telegram later.  
Acceptance: one daily and one weekly digest created with Type set; body includes dated sections; no secrets from never-persist list.

**D3 — MCP knowledge-graph server** — *(ADR-002)*; may start in parallel with D1.  
Register official MCP Memory / knowledge-graph server (`entities`, `relations`, `observations`) in `.cursor/mcp.json` with local durable store path; document taxonomy (person, project, org, habit, commitment).  
Acceptance: create entity + add observation + `search_nodes` round-trip via MCP tool calls; store file is local and gitignored if sensitive.

**D4 — Observation write path with approval** — depends on D3 + A5.  
Extract candidate observations from sessions/digests; route through approval (reuse FR-M3 spirit); never-persist (FR-M4) applies before KG write.  
Acceptance: unapproved observations are not written to the KG; approved observation appears on the entity; secret-bearing transcript yields zero KG writes.

**D5 — Assistant briefing assembly** — depends on D2 + D4.  
Compose a morning/weekly briefing from Digests + KG observations + approved biography memories (bucket-filtered); Notion page or chat delivery.  
Acceptance: briefing cites which plane each bullet came from (digest / observation / memory); no cross-bucket story/campaign leakage.

**Boundary reminder:** Notion = dashboard; pgvector = semantic corpus + episodic memory; MCP KG = structured observations; n8n = optional glue (ADR-001). Do not collapse these planes.

## Progress Log

| Task | Status | Test evidence (commit / run) |
|---|---|---|
| A1 | Gate passed | `venv\Scripts\python -m pytest tests/test_db_schema.py -q` -> `. [100%]` |
| A2 | Gate passed | `venv\Scripts\python -m pytest tests/test_embeddings.py tests/test_notion_sync.py tests/test_subagents_sync.py tests/test_persona_reorg.py -q` -> `.... [100%]` |
| A3 | Gate passed | `venv\Scripts\python -m pytest tests/test_ingest.py -q` -> `.. [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `....... [100%]` |
| A4 | Gate passed | `venv\Scripts\python -m pytest tests/test_mcp_server.py -q` -> `. [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `........ [100%]` |
| A5 | Gate passed | `venv\Scripts\python -m pytest tests/test_memory.py -q` -> `... [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `........... [100%]` |
| B1 | Gate passed | `venv\Scripts\python -m pytest tests/test_embeddings.py tests/test_notion_sync.py tests/test_subagents_sync.py tests/test_persona_reorg.py -q` -> `.... [100%]` |
| B2 | Gate passed | `venv\Scripts\python -m pytest tests/test_notion_sync.py -q` -> `.. [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `............ [100%]` |
| C1 | Gate passed (Christopher sign-off 2026-07-26) | Automated: `venv\Scripts\python -m pytest tests/test_embeddings.py tests/test_notion_sync.py tests/test_subagents_sync.py tests/test_persona_reorg.py -q` -> `.... [100%]`; manual: subagent invoke check signed off by Christopher |
| C2 | Gate passed (Christopher sign-off 2026-07-26) | Functional checks in `tests/test_persona_reorg.py` passed; full suite: `venv\Scripts\python -m pytest -q` -> `..... [100%]`; human review of persona split + story scaffold approved |
| Phase 1 e2e | Gate passed | `venv\Scripts\python scripts/phase1_e2e_demo.py` → ingest arXiv `1802.06002`, 3 cited corpus hits, Notion digest `3aa0f9f9-7567-81d4-a01a-e3c1a35b6fa7` + task Status=Done, memory propose/approve gate verified |
| B3 | Gate passed (live) | Digests DB `3ac0f9f9-7567-81a3-a35c-c3e8dbc45939` under Shared Space with Lyra (`3ac0f9f9-7567-8007-b700-d565a6ca5e7e`); smoke digest `3ac0f9f9-7567-81bd-ab31-e8c049993248` parented to Digests DB, not Projects |
| D1–D5 | Planned | Phase 2 preview — personal assistant + Notion digests + MCP knowledge graph (ADR-002) |
