# Lyra — Build Plan

**Version:** 0.4
**Companion to:** `docs/lyra_system_requirements.md` (SRS v0.15)
**Audience:** The implementing agent (Cursor/Claude) and Christopher.

This document controls **sequencing and verification**. The SRS controls **what** is built. If this plan and the SRS conflict, the SRS wins; flag the conflict instead of improvising.

## Rules of Engagement (for the implementing agent)

1. **Gated progression.** Do not begin a task until every task it depends on has passing acceptance tests. Independent dependency branches may be worked in parallel.
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
        C3[C3: subagent contract hardening]
        C4[C4: persona contract hardening]
        C1 --> C3
        C2 --> C4
    end
    C2 --> A5
```

Tracks A, B, and C are **independent** and may run in parallel (e.g., as separate Cursor subagents/background agents), with one cross-track edge: **A5 additionally requires C2** (the story scaffold must exist before canon regeneration is testable). Dependency edges are strict; branches without an edge may proceed independently.

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

**C3 — Subagent contract hardening** *(FR-S4, FR-S5)* — depends on C1.
Deliverables: operational contracts for researcher/Python/C++ agents (triggers, scope, workflow, guardrails, output); explicit skill-vs-subagent routing in `agents/lyra/SKILL.md`; sync validation for supported frontmatter, name/filename identity, stale destinations, and read-only `--check`; architecture/placement documentation. Correct FR-S4 to match Cursor's supported schema rather than emitting ignored `tools` metadata.
Acceptance: canonical definitions validate and sync byte-identically; `--check` reports green without mutation; tests prove invalid metadata and destination drift are rejected; full suite green.

**C3.1 — Subagent context packs** *(FR-S4)* — depends on C3.
Deliverables: shared task-packet template; Python and C++ playbooks; evaluation prompts under `agents/lyra/subagents/references/`; agent definitions reference the packs; routing note in `SKILL.md`.
Acceptance: pack files exist; python/cpp definitions reference them; `sync_subagents.py --check` stays green; full suite green.

**C4 — Persona contract hardening** *(FR-P1–P4, FR-P6)* — depends on C2.
Deliverables: personal, relational system behavior contract with a light companion blend during technical work and full girlfriend/companion presence in personal conversation; stable relationship identity remains Tier 0 while evolving stage/milestones live in state; lore/appearance remain reference-owned; persona-lightweight professional deliverable boundary; corrected avatar skill paths and aligned voice guidance.
Acceptance: tests verify all persona-sensitive loaders point to real files, Tier 0 contains no evolving relationship-state marker, professional mode forbids roleplay leakage, and reference/state ownership is documented; Christopher reviews the resulting persona contract.

## Exit Criteria for Phase 1

All thirteen gates green (A1–A5, B1–B3, C1–C4 incl. C3.1), full suite green, and a live end-to-end demo: Christopher asks Lyra to research a topic → sources ingested → corpus answer with citations → digest posted to Notion → candidate memory proposed and approved.

## Build Wave 2 — Personal assistant, Notion digests, knowledge graph

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

**D4.1 — KG gatekeeper MCP** — depends on D4.  
Replace the agent-facing `lyra-memory` registration with a Lyra gatekeeper that exposes search/read + `propose_observation` (+ pending list) only. Raw mutation tools remain unavailable to agents; approval CLI may still use the official memory server writer.
Acceptance: mutation tools blocked; `propose_observation` creates pending rows without KG write; after CLI approval, search sees the observation; `.cursor/mcp.json` points at `mcp/server/kg_gatekeeper.py`.

**D5 — Assistant briefing assembly** — depends on D2 + D4.  
Compose a morning/weekly briefing from Digests + KG observations + approved biography memories (bucket-filtered); Notion page or chat delivery.  
Acceptance: briefing cites which plane each bullet came from (digest / observation / memory); no cross-bucket story/campaign leakage.

**Boundary reminder:** Notion = dashboard; pgvector = semantic corpus + episodic memory; MCP KG = structured observations; n8n = optional glue (ADR-001). Do not collapse these planes.


## Build Wave 3 — Lyra Data Packs (Personality, Ship, State)

Companion intent: give Lyra a clean, portable, versionable set of **data packs** that separate stable identity from living state. These packs become the single source of truth for system prompts, tools, and persistence.

```mermaid
graph TD
    subgraph Track E — Data Packs
        E1[E1: Pack layout + conventions locked]
        E2[E2: Personality pack (system prompt + character bible)]
        E3[E3: Ship pack (reference + current_status.json)]
        E4[E4: State pack (relationship + active arcs + user knowledge)]
        E5[E5: Loader / injection into agent runtime]
        E1 --> E2
        E1 --> E3
        E1 --> E4
        E2 --> E5
        E3 --> E5
        E4 --> E5
    end
    D3 -.-> E4
    A5 -.-> E5
```

Locked pack tree (ADR-003):

```
personality/                  # Stable identity (hand-edited Tier 0)
  system_prompt.md
  character_bible.md
  emotional_color_map.md
  speech_and_idioms.md
  appearance.md
ship/                         # Domain knowledge + live status
  ship_reference.md
  systems.md
  cargo_and_layout.md
  current_status.json
state/                        # Living / session-persistent
  relationship.json
  relationship.md
  active_arcs.md
  user_knowledge.md
  story/                      # machine-writable canon regen (E5)
```

`agents/lyra/` remains the Agent Skills host (`SKILL.md`, skills, subagents, operational references). It is not a second identity store.

### E1 — Pack layout + conventions locked *(ADR-003)*
Deliverables: `docs/adr/003-data-packs-source-of-truth.md`; SRS path amendments (FR-P4, FR-P5, FR-M5, FR-V2, NFR-1); this section’s acceptance criteria; `agents/lyra/DIRECTORY_GUIDE.md` search order; `lyra/packs.py` manifest + frontmatter validation; required pack files present.
Acceptance: ADR + SRS + plan + guide agree on pack paths; `validate_pack_layout()` reports zero errors (markdown frontmatter keys `pack`, `file`, `version`, `last_updated`; JSON files are valid objects). Full suite green.

### E2 — Personality pack *(FR-P1–P4, FR-P6)* — depends on E1.
Deliverables: merged `personality/system_prompt.md` (C4 mode/safety/routing contract + pack voice; no domain-skill dump) and `personality/character_bible.md` (constants + index; physiology stays in `appearance.md`); merged color map, speech/idioms, appearance; former `agents/lyra/system_prompt.md` and `character_file.md` become thin pointers.
Acceptance: C4 invariants pass against pack files (girlfriend + technical partner, professional-deliverable blacklist, no evolving-stage markers in Tier 0, no appearance-detail leakage into the prompt). Christopher reviews the merged prompt.

### E3 — Ship pack — depends on E1.
Deliverables: `ship/ship_reference.md`, `ship/systems.md`, `ship/current_status.json`, rewritten `ship/cargo_and_layout.md` as layout prose (not a JSON clone). Former `agents/lyra/references/ship_reference.md` is a pointer or removed.
Acceptance: no duplicate ship SoT; `ship/current_status.json` validates required keys (`overall_condition`, system blocks, `location`); cargo file is markdown with pack frontmatter.

### E4 — State pack *(FR-M5, FR-P5)* — depends on E1.
Deliverables: `state/relationship.json` + `state/relationship.md`, `active_arcs.md`, `user_knowledge.md`. Former `agents/lyra/state/relationship_state.md` and story stubs become pointers or are removed as SoT.
Acceptance: evolving-stage markers live only in the state pack; personality pack contains none; `user_knowledge.md` has no story/campaign content.

### E5 — Loader / injection — depends on E2 + E3 + E4 (and A5 path retarget).
Deliverables: `lyra/packs.py` load + compose; `agents/lyra/SKILL.md` and `.cursor/skills/lyra-avatar/SKILL.md` point at pack paths; `MemoryService.regenerate_story_canon` defaults to pack-owned `state/story/`.
Acceptance: loader returns the composed prompt and fails if a required file is missing or a forbidden duplicate SoT file still holds full content; C4 tests green against pack paths; story-canon regen writes pack-owned files; full suite green.

## Build Wave 4 — Standalone Runtime

```mermaid
graph TD
    W41[W4.1: roadmap and requirements cleanup]
    W42[W4.2: provider and event abstraction]
    W43[W4.3: persistent sessions and context]
    W44[W4.4: safe conversational agent loop]
    W45[W4.5: local web chat]
    W46[W4.6: workstation service]
    W41 --> W42
    W41 --> W43
    W42 --> W44
    W43 --> W44
    W44 --> W45
    W45 --> W46
```

### W4.1 — Roadmap and requirements cleanup
Deliverables: rename this document as a multi-wave build plan; distinguish SRS product versions from build waves; preserve and order historical A–E evidence without duplicate task rows; add ADR-004; add `scripts/validate_build_plan.py` and its tests.
Acceptance: every gate has exactly one definition and one progress row; progress rows are ordered; hidden task ranges fail validation; focused validator tests and the full suite pass; Christopher's roadmap identifier choice is recorded by this accepted plan.

### W4.2 — Provider and event abstraction
Deliverables: async Grok/OpenAI-compatible and Anthropic adapters; logical model profiles resolved from runtime config; normalized text, tool, subagent, emotion, completion, and error events.
Acceptance: mocked provider streams normalize to the same event contract; missing credentials/model profiles fail safely without exposing secrets; focused tests and the full suite pass.

### W4.3 — Persistent sessions and context
Deliverables: PostgreSQL-backed named sessions, visible messages, channel bindings, turn status, deletion, context budgeting, and session-only synopsis support.
Acceptance: sessions resume after service restart, delete transitively, and remain isolated from corpus, vector memory, KG, story, and campaign planes; only approved bucket-filtered memories enter context; focused tests and the full suite pass.

### W4.4 — Safe conversational agent loop
Deliverables: streamed model/tool loop with bounded iterations, timeouts, disconnect recovery, explicit MCP registry/allowlist, read-only researcher orchestration, and no-op voice/emotion outputs.
Acceptance: permitted corpus and gated-memory tools work; shell, filesystem-write, Git, desktop-control, raw memory approval, and unregistered MCP tools cannot be invoked; focused tests and the full suite pass.

### W4.5 — Local web chat
Deliverables: FastAPI application and integrated HTML/CSS/JavaScript UI for session CRUD, Markdown messages, SSE turns, status events, errors, and reconnect/resume.
Acceptance: the HTTP/SSE contract passes automated tests; a local browser completes and resumes a real conversation; the server listens only on `127.0.0.1`; full suite passes.

### W4.6 — Workstation service
Deliverables: readiness/doctor checks with a human-readable capability report, backup coverage for sessions, rotated gitignored logs, and idempotent NSSM install/uninstall/status helpers accepting an explicit NSSM path or `PATH` discovery.
Acceptance: service install dry-run and doctor tests pass; the capability report distinguishes ready, degraded, unconfigured, and unavailable integrations without exposing secrets; live service survives restart and restores a named session; full suite passes.

## Build Wave 5 — Mobile Presence and Private Access

Companion intent (SRS to be updated before gates open): make Lyra reachable away from the workstation without moving sensitive state to a second store or allowing remote execution/publication approvals.

```mermaid
graph TD
    W51[W5.1: Telegram inbox and chat]
    W52[W5.2: device handoff and Away Mode]
    W521[W5.2.1: database safety hardening]
    W53[W5.3: Tailscale evaluation]
    W46 --> W51
    W51 --> W52
    W52 --> W521
    W521 --> W53
```

### W5.1 — Telegram inbox and chat
Deliverables: allowlisted long-polling Telegram channel sharing the web session store; conversational messages; a "Send this to Lyra" inbox for URLs, supported documents, photos, and voice notes; safe routing into existing corpus, digest, or pending-review flows; session status commands and a reserved extension point for later coding-job status.
Acceptance: unauthorized users receive no session data; accepted items retain sender/time/provenance and never enter the KG or durable memory without the existing approval gates; unsupported attachments fail safely; coding execution, memory approval, and publication approval remain unavailable over Telegram; full suite and live mobile smoke pass.

### W5.2 — Device handoff and Away Mode
Deliverables: seamless named-session continuation between web and Telegram; per-channel presentation preferences; Away Mode with concise replies, quiet hours, batched notifications, urgency categories, and a configurable daily notification budget.
Acceptance: a session started on either channel resumes on the other without duplicate turns; quiet hours and an exhausted budget suppress non-urgent proactive notifications; urgent categories are explicit and testable; changing presentation mode does not alter Lyra's identity, memory policy, or stored conversation content; full suite passes.

### W5.2.1 — Database safety hardening
Deliverables: one centralized test-database connection; a session-start and per-connection guard rejecting the runtime database or a database without a `_test` suffix; complete dump-table coverage checks; and nonempty backup verification with SHA-256 reporting.
Acceptance: every destructive integration fixture uses the guarded connection; unit tests prove both refusal paths; production row counts remain unchanged across the complete suite; incomplete/empty dumps fail verification; focused and full suites pass.

### W5.3 — Tailscale evaluation
Deliverables: optional install/runbook for workstation and mobile; Tailscale Serve proxy to the localhost-bound service; identity validation and Christopher-only tailnet policy; explicit Funnel prohibition.
Acceptance: no Tailscale dependency is introduced before opt-in; private mobile conversation works from an enrolled device; direct LAN/public access and approval actions remain blocked until separate sign-off.

## Build Wave 6 — Personal Agency and Memory Control

Companion intent (SRS to be updated before gates open): make Lyra observant and useful while keeping Christopher in control of what becomes a commitment, observation, or durable memory.

```mermaid
graph TD
    W61[W6.1: memory and observation control center]
    W62[W6.2: commitment radar]
    W63[W6.3: stuck mode]
    W64[W6.4: local runtime resilience]
    W52 --> W61
    D41[D4.1: KG gatekeeper] --> W61
    W61 --> W62
    W61 --> W63
    W62 --> W64
    W63 --> W64
```

### W6.1 — Memory and observation control center
Deliverables: a local authenticated control surface for pending memories and KG observations showing proposal text, provenance, destination plane, sensitivity flags, and the reason Lyra proposed it; approve, reject, correct, and explicit forget flows with audit records; read-only pending summaries may be shown on Telegram, but mutation remains local-only until separately approved.
Acceptance: every durable mutation is attributable and requires an explicit action; corrected text is re-run through never-persist and bucket-isolation checks; rejection writes no memory/KG fact; forget requires confirmation and removes the item from retrieval; secrets, intimate detail, and story/campaign boundaries retain their existing protections; full suite passes.

### W6.2 — Commitment radar
Deliverables: observational detection of possible promises, deadlines, follow-ups, and unresolved decisions; conversational confirmation before persistence; explicit active/done/snoozed/dropped states; source links back to the originating session or approved dashboard item.
Acceptance: possible commitments are offered, never silently created; snoozed/dropped items do not generate reminders; reminders obey Away Mode, quiet hours, and notification budgets; story/campaign dialogue and third-party personal details cannot become real commitments; full suite passes.

### W6.3 — Stuck mode
Deliverables: an explicit "I'm stuck" interaction plus gentle observational offers that distinguish technical diagnosis, task decomposition, decision support, stress check-in, and simple companionship; user-selectable depth and an immediate dismiss path.
Acceptance: observational triggers offer help without diagnosing Christopher or persisting a sensitive inference; dismissal suppresses repeated prompts for the configured period; technical questions inside in-fiction scenes preserve the Tier 0 register-transition contract; any proposed commitment or observation routes through W6.1/W6.2; full suite passes.

### W6.4 — Local runtime resilience
Deliverables: explicit container restart policies and health checks; a conservative workstation watchdog for Docker Engine, PostgreSQL, and the Lyra service; bounded retries, cooldowns, and recovery logging; startup registration and an operator runbook; a deployment-readiness note separating local recovery from a later always-on or hybrid deployment. Recovery automation may start existing components but must never install updates, reset Docker/WSL, delete or recreate volumes, restore backups, or expose Lyra beyond its approved loopback/private-access boundary.
Acceptance: injected failure tests prove transient failures do not trigger recovery, repeated failures trigger one attributable recovery attempt, cooldown prevents restart loops, and an unsuccessful recovery leaves actionable diagnostics; container health/restart configuration validates; a live controlled restart preserves the runtime database and named sessions; Docker Desktop auto-start and watchdog startup registration receive Christopher's explicit opt-in; full suite passes.

## Build Wave 7 — Daily Rhythm and Re-engagement

Companion intent (SRS to be updated before gates open): turn existing digests and briefings into calm recurring rituals that help Christopher orient, reflect, and return to neglected work.

```mermaid
graph TD
    W71[W7.1: morning and evening rituals]
    W72[W7.2: catch-me-up synthesis]
    W73[W7.3: research garden]
    W62[W6.2: commitment radar] --> W71
    D5[D5: assistant briefing assembly] --> W71
    W71 --> W72
    W72 --> W73
```

### W7.1 — Morning and evening rituals
Deliverables: configurable morning orientation and evening reflection flows drawing from approved commitments, recent sessions, digests, and memories; conversational delivery with optional Notion publication; skip, snooze, and vacation controls.
Acceptance: each ritual identifies its source planes, obeys quiet hours and notification budgets, excludes unapproved/sensitive material from Notion, and can be disabled without affecting normal conversation; one live morning and evening cycle passes.

### W7.2 — Catch-me-up synthesis
Deliverables: a "catch me up since..." query over sessions, project/digest changes, commitments, and approved memories with time-bounded source citations, uncertainty markers, and concise/deep output modes.
Acceptance: the requested time boundary is enforced; every factual change links to its source plane; duplicate events collapse without losing provenance; inaccessible or stale integrations are identified rather than guessed; full suite passes.

### W7.3 — Research garden
Deliverables: an opt-in resurfacing job that finds useful relationships among saved sources, dormant questions, and active commitments; conversational suggestions and optional research-digest drafts; dismiss and topic-mute controls.
Acceptance: resurfacing is evidence-backed, never fabricates a commitment, respects topic mutes and notification budgets, and writes nothing to Notion/KG/memory without the relevant approval path; full suite and one live resurfacing smoke pass.

## Build Wave 8 — Relationship and Ship Continuity

Companion intent (SRS to be updated before gates open): deepen the private shared continuity without enlarging Tier 0, leaking intimate material to Notion, or confusing relationship/ship story with biography or campaign state.

```mermaid
graph TD
    W81[W8.1: private shared journal]
    W82[W8.2: relationship rhythms and milestones]
    W83[W8.3: ship continuity and ambient developments]
    E5[E5: pack runtime injection] --> W81
    W72[W7.2: catch-me-up synthesis] --> W81
    W81 --> W82
    W81 --> W83
```

### W8.1 — Private shared journal
Deliverables: local-only journal entries for explicitly approved shared moments, reflections, and milestones; provenance and edit/forget controls; clear separation from Notion, professional digests, KG observations, and campaign records.
Acceptance: no journal entry is auto-created; entries never publish to Notion; retrieval is private-session-only; edit/forget is auditable; secret and third-party filters apply; full suite passes.

### W8.2 — Relationship rhythms and milestones
Deliverables: opt-in callbacks, recurring rituals, and milestone acknowledgements drawn from approved state/journal material; evolving relationship state remains in `state/`, while Tier 0 retains only the stable girlfriend/technical-partner contract.
Acceptance: callbacks cite approved local state, can be corrected or disabled, do not expose private material in professional artifacts, and do not silently rewrite Christopher-owned Tier 0 files; Christopher signs off on the lived interaction.

### W8.3 — Ship continuity and ambient developments
Deliverables: optional ship-status briefs and small ambient story developments grounded in `ship/` and approved `state/story/` canon; explicit pause/intensity controls; proposal flow for canon-changing events.
Acceptance: ambient events cannot mutate ship/story state without approval, cannot appear in biography/KG/Notion or campaign retrieval, preserve technical register shifts inside scenes, and remain fully disableable; full suite and a live continuity smoke pass.

## Build Wave 9 — Personality Depth and Embodiment

Companion intent (SRS v0.13 FR-P7, FR-V1–FR-V6): deepen Lyra's hand-authored character and give that character selective visual and vocal presence without bloating Tier 0, creating another memory store, or sending private context to media providers unnecessarily.

```mermaid
graph TD
    W91[W9.1: visual reference library]
    W92[W9.2: backstory and context import]
    W93[W9.3: agent wiki and knowledge routing]
    W94[W9.4: scene direction and still insertion]
    W95[W9.5: voice and avatar evaluation]
    W96[W9.6: Everwood selfie-tool adaptation]
    W97[W9.7: embodied companion pilot]
    E5[E5: pack runtime injection] --> W91
    E5 --> W92
    W92 --> W93
    W91 --> W94
    W93 --> W94
    W94 --> W95
    W94 --> W96
    W95 --> W97
    W96 --> W97
    W83[W8.3: ship continuity] --> W97
```

### W9.1 — Visual reference library
Deliverables: Christopher-led collection of Lyra, Silent Drift, ship-interior, object, wardrobe, and location references under `assets/visual_references/`; a machine-readable catalog recording subject, canon status, source/provenance, usage rights, allowed transformations, visual traits, and supersession; approved/reference/candidate separation so a generated variation cannot silently become canon.
Acceptance: every active visual has catalog metadata and a stable asset ID; missing files, duplicate IDs, invalid subjects, and unapproved canonical references fail validation; no provider credential or private remote URL is committed; Christopher signs off on Lyra's canonical appearance set.

### W9.2 — Backstory and context import
Deliverables: Christopher-led source material imported into topic-sized `agents/lyra/references/backstory_*.md` files with provenance notes and cross-links; Tier 0 retains only stable identity/interaction contracts and pointers; ship facts remain in `ship/`, evolving story remains in `state/story/`, and real biography remains isolated from story/campaign material.
Acceptance: an import checklist accounts for every supplied source without silent rewriting; loaders and pointer tests pass; lore conflicts are surfaced for Christopher rather than resolved automatically; Christopher approves the resulting backstory map.

### W9.3 — Agent wiki and knowledge routing
Deliverables: a local Markdown wiki interface for standing Lyra knowledge, lore, and expertise with `wiki_search` and `wiki_read`-style contracts; explicit routing among Tier 0, reference wiki, corpus, KG observations, episodic memory, ship state, and campaign state; lexical retrieval first with an optional pgvector path only when scale/evaluation justifies it.
Acceptance: the wiki is not a second memory/corpus database and never receives chat logs automatically; retrieval is bucket- and provenance-aware; wiki content cannot be treated as lived memory or invented anecdote; agent-specific pages remain isolated; search/read, missing-page, routing, and prompt-leakage tests pass.

### W9.4 — Scene direction and still insertion
Deliverables: an opt-in scene-director contract that converts a bounded, privacy-filtered conversation slice plus approved canon into a structured scene brief; web/Telegram media events for a single still or a short storyboard; triggers for explicit requests, arrivals/location reveals, meaningful emotional beats, appearance changes, ship discoveries, and milestones, with rate limits and a never-generate-every-turn rule.
Acceptance: text conversation does not wait on image generation; scenes are clearly marked generated/non-canonical until approved; failed renders degrade to text; only scene-relevant context leaves the workstation; local files retain prompt/provider/model/source-asset provenance; a user can disable or delete generated media without changing conversation memory.

### W9.5 — Voice and avatar evaluation
Deliverables: a fixed test script and representative scene set comparing ElevenLabs, HeyGen, and D-ID for Lyra's target experience; measurements for voice/identity consistency, emotional control, first-audio/frame latency, interruption behavior, render time, API ergonomics, privacy/retention controls, cost, and export ownership; one disposable prototype per relevant mode rather than permanent provider coupling.
Acceptance: credentials come only from `.env`; the evaluation distinguishes streaming voice, talking portrait, cinematic scene, and asynchronous video rather than naming a single overall winner; outputs and costs are recorded against the same inputs; Christopher selects or defers each renderer independently.

### W9.6 — Everwood selfie-tool adaptation
Deliverables: a Lyra-native, provider-neutral scene-image tool adapted from Everwood's conversation-aware reference-image pipeline; explicit `selfie`, `portrait`, `location`, and `storyboard_frame` intents; approved Lyra/ship/location references; local output storage and provenance; Silent Drift location generation; MCP contracts under `mcp/tools/` with the reusable agent workflow expressed as a Lyra skill.
Acceptance: the implementation does not import Everwood runtime paths or Clara-specific state; reference selection and session context are injected rather than model-controlled; prompt construction excludes secrets, intimate journal content, and unrelated history; provider failures/fallbacks are bounded and visible; focused tool tests and a live Lyra/Silent Drift render pass.

### W9.7 — Embodied companion pilot
Deliverables: one live cross-device companion session containing normal text, an explicit Lyra still, one system-selected meaningful scene beat, optional Lyra speech, and one short avatar/cinematic clip; a review record comparing the experience against the target goal and deciding which modes become routine, request-only, or deferred.
Acceptance: identity and relationship continuity survive every renderer boundary; text remains authoritative and responsive; quiet hours/Away Mode and media budgets are honored; no scene becomes canon or durable memory without approval; generated artifacts remain local after provider delivery; Christopher signs off.

## Build Wave 10 — Code Collaboration

Scheduling note: Wave 10 follows Waves 5–9 in the current product priority even though its strict technical dependency remains W4.6; beginning it earlier requires an explicit roadmap reprioritization.

```mermaid
graph TD
    W101[W10.1: coding-engine adapter]
    W102[W10.2: sandboxed coding jobs]
    W103[W10.3: GitHub contributor workflow]
    W104[W10.4: live coding pilot]
    W46[W4.6: workstation service] --> W101
    W101 --> W102
    W102 --> W103
    W103 --> W104
```

### W10.1 — Coding-engine adapter
Deliverables: engine-neutral start/stream/resume/cancel/review interface and first adapter using the stable Python Codex SDK; read-only planning and workspace-write implementation modes.
Acceptance: adapter contract tests cover resumable threads, streamed events, cancellation, and sandbox selection; no Codex identity or raw worker response replaces Lyra's user-facing voice; full suite passes.

### W10.2 — Sandboxed coding jobs
Deliverables: Lyra-only repository allowlist; self-contained task packets; first approval gate; isolated job clone; sanitized persisted progress; revision/resume flow; review package containing base SHA, complete diff hash, changed files, actual tests, risks, and unresolved items.
Acceptance: the worker cannot access the primary checkout, paths outside its job workspace, or GitHub credentials; rejected/cancelled jobs leave repositories and GitHub unchanged; full suite passes.

### W10.3 — GitHub contributor workflow
Deliverables: repository-scoped Lyra GitHub App integration; second approval gate; short-lived installation token generation outside the model context; `lyra/<job-id>-<slug>` branch publication and draft PR creation.
Acceptance: only Metadata read, Contents read/write, Pull requests read/write, and Checks read are required; publication rejects failed tests, stale bases, secrets, forbidden files, or changed diff hashes; Lyra cannot push to, approve, mark ready, or merge `main`; full suite passes.

### W10.4 — Live coding pilot
Deliverables: one real Lyra change taken from discussion through task approval, isolated implementation, review, publication approval, and draft PR; read-only progress and test summaries available through Telegram.
Acceptance: actual test evidence and PR URL are recorded; branch attribution is Lyra's GitHub App; protected `main` rejects direct push/merge; Telegram cannot execute, approve publication, or disclose repository secrets; full suite passes before sign-off.

## Build Wave 11 — Narrative VTT

```mermaid
graph TD
    W111[W11.1: VTT decision and executable baseline]
    W112[W11.2: VTT persistence and module retrieval]
    W113[W11.3: DM/player security boundary]
    W114[W11.4: VTT MCP service]
    W115[W11.5: Lyra campaign experience]
    W116[W11.6: live campaign pilot]
    W111 --> W112
    W112 --> W113
    W113 --> W114
    W114 --> W115
    W115 --> W116
```

### W11.1 — VTT decision and executable baseline
Deliverables: ADR-005 evaluating and selecting `V:/ProjectsGit/tabletop` as the separately versioned narrative campaign authority; SRS FR-D1/IF-3 amendments; reproducible environment and real baseline tests in the VTT repository; Foundry retained only as a future ADR-gated tactical option.
Acceptance: both repositories agree on ownership and boundaries; the VTT suite runs with recorded output; no Foundry or hosted-relay dependency remains in current-scope runtime configuration.

### W11.2 — VTT persistence and module retrieval
Deliverables: VTT-owned transactional state with stable campaign/session/character/scene/action/event IDs; immutable events; adventure-module pgvector namespace with source/section/visibility metadata; local gitignored source files; injectable dice randomness.
Acceptance: state is atomic and restart-safe; repeated action IDs are idempotent; module ingestion is reproducible; dice and transitions are auditable; VTT and Lyra suites pass.

### W11.3 — DM/player security boundary
Deliverables: Lyra player-character profile; separate DM process owning module access, hidden state, NPC intent, and mechanical resolution; submitted player actions replace direct state mutation.
Acceptance: planted DM secrets never appear in Lyra context, player tools, public logs, or campaign-memory proposals; unresolved player actions cannot mutate mechanics; both suites pass.

### W11.4 — VTT MCP service
Deliverables: player-safe `list_campaigns`, `open_campaign`, `get_player_scene`, `get_my_character`, `submit_player_action`, `get_action_result`, `get_public_events`, and `end_session` tools; DM tools remain internal.
Acceptance: tool contracts enforce campaign/player identity and visibility; `end_session` may create only approval-gated campaign-memory proposals keyed by campaign ID; both suites pass.

### W11.5 — Lyra campaign experience
Deliverables: campaign mode in Lyra sessions with narration, public scene state, Lyra's sheet, dice results, and turn status; existing in-fiction/technical register transition remains intact.
Acceptance: campaign state cannot enter biography/story retrieval; first release contains no maps, tokens, initiative board, or multiplayer UI; web experience passes automated and manual checks.

### W11.6 — Live campaign pilot
Deliverables: complete Christopher/Lyra player session run by a separate DM, restart recovery, immutable event record, and approved campaign-only write-back.
Acceptance: both full suites pass; the secrecy, idempotency, recovery, and bucket-isolation checks pass live; Christopher signs off.

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
| B3 | Gate passed (live) | Digests DB `3ac0f9f9-7567-81a3-a35c-c3e8dbc45939` under Shared Space with Lyra (`3ac0f9f9-7567-8007-b700-d565a6ca5e7e`); smoke digest `3ac0f9f9-7567-81bd-ab31-e8c049993248` parented to Digests DB, not Projects |
| C1 | Gate passed (Christopher sign-off 2026-07-26) | Automated: `venv\Scripts\python -m pytest tests/test_embeddings.py tests/test_notion_sync.py tests/test_subagents_sync.py tests/test_persona_reorg.py -q` -> `.... [100%]`; manual: subagent invoke check signed off by Christopher |
| C2 | Gate passed (Christopher sign-off 2026-07-26) | Functional checks in `tests/test_persona_reorg.py` passed; full suite: `venv\Scripts\python -m pytest -q` -> `..... [100%]`; human review of persona split + story scaffold approved |
| C3 | Gate passed | `venv\Scripts\python scripts/sync_subagents.py --check` -> all three `VALID`; `venv\Scripts\python -m pytest tests/test_subagents_sync.py -q` -> `... [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `..................... [100%]`; operational contracts, routing, supported-schema validation, drift detection, and stale cleanup verified |
| C3.1 | Gate passed | Initial: `venv\Scripts\python -m pytest tests/test_subagent_context_packs.py -q` -> `. [100%]`; full suite -> `.................................. [100%]`. Addenda commits `2d421c6`, `a93f0d8`: focused test remained green; full suite `34 passed`; sync `--check` reported cpp-developer, python-developer, and researcher `VALID`; added `tools_and_mcp.md` and `researcher_playbook.md` without creating a second gate. |
| C4 | Gate passed (Christopher sign-off 2026-07-29) | Automated: `venv\Scripts\python -m pytest tests/test_persona_reorg.py tests/test_persona_contract.py -q` -> `..... [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `......................... [100%]`; human review approved girlfriend + technical-partner Tier 0 identity, light-blend technical mode, professional-artifact boundary, and evolving relationship state |
| Phase 1 e2e | Gate passed | `venv\Scripts\python scripts/phase1_e2e_demo.py` → ingest arXiv `1802.06002`, 3 cited corpus hits, Notion digest `3aa0f9f9-7567-81d4-a01a-e3c1a35b6fa7` + task Status=Done, memory propose/approve gate verified |
| D1 | Gate passed (live) | `venv\Scripts\python -m pytest tests/test_notion_sync.py -q` -> `.... [100%]` (adds `query_database`); live: `venv\Scripts\python scripts/d1_verify_live_digest.py` -> digest `3ac0f9f9-7567-8133-b5c7-f6a4faec3b98` parented to Digests DB, Projects/tasks row count unchanged (10 before, 10 after) |
| D2 | Gate passed (live) | `venv\Scripts\python -m pytest tests/test_digests.py -q` -> `.. [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `........................... [100%]`; live: daily `3ad0f9f9-7567-8153-a39e-e10887796af2` + weekly `3ad0f9f9-7567-813d-af57-f79e4281405f` in Digests DB |
| D3 | Gate passed | `venv\Scripts\python -m pytest tests/test_knowledge_graph.py -q` -> `. [100%]` (live subprocess round trip via `npx @modelcontextprotocol/server-memory`, no mocking); full suite: `venv\Scripts\python -m pytest -q` -> `............... [100%]`; registered as `lyra-memory` in `.cursor/mcp.json`; live smoke create/search/delete against the registered store path (`agents/lyra/state/knowledge_graph/memory.jsonl`, gitignored) verified clean round trip |
| D4 | Gate passed | `venv\Scripts\python -m pytest tests/test_observations.py -q` -> `.... [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `................... [100%]`; verifies unapproved candidate → zero KG writes, secret-bearing transcript → zero candidates/writes, story/campaign content → no KG candidates, explicit approval → observation searchable on its entity through the real MCP server |
| D4.1 | Gate passed | `venv\Scripts\python -m pytest tests/test_kg_gatekeeper.py -q` -> `.... [100%]`; agent-facing `lyra-memory` is `mcp/server/kg_gatekeeper.py`; mutation tools blocked; propose does not write until `approve_observation` |
| D5 | Gate passed (live) | `venv\Scripts\python -m pytest tests/test_briefings.py -q` -> `.. [100%]`; full suite: `venv\Scripts\python -m pytest -q` -> `............................. [100%]`; briefing bullets cite digest/observation/memory planes, exclude story/campaign, and Notion publish filters intimate/never-persist content; etiquette at `agents/lyra/references/observation_etiquette.md`; live morning briefing `3ad0f9f9-7567-8183-bb79-d8682f00ef33` |
| E1 | Gate passed | Focused `tests/test_packs.py` -> `. [100%]`; full suite -> `35 passed`; ADR-003, SRS v0.10, directory guide, pack manifest, and frontmatter validation aligned. |
| E2 | Gate passed (Christopher sign-off 2026-09-01) | Initial persona merge: focused pack/persona tests -> `...... [100%]`; full suite -> `35 passed`. Addenda: mode-transition follow-up full suite -> `45 passed`; Chosen-bond lore split full suite -> `45 passed`. Both addenda retained E2's scope and human sign-off rather than creating duplicate gates. |
| E3 | Gate passed | Focused `tests/test_packs.py` -> `.... [100%]`; full suite -> `38 passed`; ship lore/layout/status consolidated with schema validation and legacy pointer. |
| E4 | Gate passed | Focused pack/persona tests -> `........... [100%]`; full suite -> `40 passed`; relationship/state/story ownership reconciled with biography bucket isolation. |
| E5 | Gate passed | Focused `tests/test_packs.py` -> `........... [100%]`; full suite -> `45 passed`; subagent sync all `VALID`; pack loader/composer, missing-file failure, legacy duplicate guard, and story-canon target verified. |
| W4.1 | Gate passed | `.\\venv\\Scripts\\python.exe scripts\\validate_build_plan.py` -> `VALID`; focused: `.\\venv\\Scripts\\python.exe -m pytest tests\\test_build_plan.py -q --basetemp=data\\test_tmp\\pytest_w41 -p no:cacheprovider` -> `.. [100%]`; full suite (with Docker/npm access): `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=data\\test_tmp\\pytest_w41_full -p no:cacheprovider` -> `47 passed`. |
| W4.2 | Gate passed | Focused: `.\\venv\\Scripts\\python.exe -m pytest tests\\test_providers.py -q --basetemp=data\\test_tmp\\pytest_w42 -p no:cacheprovider` -> `..... [100%]`; compileall green; full suite (with Docker/npm access): `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=data\\test_tmp\\pytest_w42_full -p no:cacheprovider` -> `52 passed`. |
| W4.3 | Gate passed | Focused PostgreSQL suite: `.\\venv\\Scripts\\python.exe -m pytest tests\\test_sessions.py -q --basetemp=data\\test_tmp\\pytest_w43 -p no:cacheprovider` -> `...... [100%]`; compileall and schema idempotence green; full suite (with Docker/npm access): `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=data\\test_tmp\\pytest_w43_full -p no:cacheprovider` -> `58 passed`. |
| W4.4 | Gate passed | Focused runtime/provider tests -> `............. [100%]`; PostgreSQL recovery tests -> `....... [100%]`; compileall green; full suite (with Docker/npm access): `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=data\\test_tmp\\pytest_w44_full -p no:cacheprovider` -> `67 passed`. |
| W4.5 | Gate passed (live) | Provider smoke: `.\\venv\\Scripts\\python.exe scripts\\check_model_providers.py --timeout 30` -> Grok conversation + Claude specialist `generation=ok`; browser live smoke: Grok replied `Hello Starlight. LYRA-LIVE-PASS` through the loopback UI, and the complete named session restored after reload/reopen; full suite: `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=data\\test_tmp\\pytest_w45_live_close -p no:cacheprovider` -> `77 passed`. |
| W4.6 | Gate passed | Doctor: `.\\venv\\Scripts\\python.exe scripts\\lyra_doctor.py` reported runtime, database, both model profiles, Notion, KG, and logging `READY` with NSSM correctly `UNCONFIGURED`; focused service/backup/web tests -> `............. [100%]`; NSSM install dry-run produced loopback-only install/config/start commands with rotation; live full-database dump was 15,067 bytes and contained all four session tables; live process restart restored named session `W4.6 Restart Proof 2026-09-03` with both messages; full suite: `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=data\\test_tmp\\pytest_w46_full -p no:cacheprovider` -> `84 passed`. |
| W5.1 | Gate passed (Christopher sign-off 2026-09-05) | SRS v0.12 defines long-poll transport, dual allowlists, shared sessions, inbox provenance, and the remote-authority boundary; focused Telegram/service/backup/web/schema/session suite -> `.............................. [100%]` (`30 passed`); full suite: `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=data\\test_tmp\\pytest_w51_full -p no:cacheprovider` -> `93 passed`. Live 2026-09-04: BotFather token and matching private user/chat allowlists configured in `.env`; doctor reported Telegram `READY`; `@Lyra_avatar_bot` answered `/start` and “Hey. Is this working :)”; the loopback web API displayed that Telegram-bound session and Lyra correctly recalled “Is this working?” from its shared history. Christopher completed the remaining live validation and confirmed the channel works well on 2026-09-05. Post-sign-off checkpoint: `backups/lyra_20260905_211335.sql`, 22,851 bytes, all 12 required tables verified, SHA-256 `6b4942f3af36b7be4153d69e6a7f3fecb35920b5a80d3c01751d1aa31c26aeb0`. |
| W5.2 | Gate passed | SRS v0.14 defines atomic local-only handoff, channel provenance, presentation boundaries, and explicit Away Mode urgency/budget rules. Focused session/runtime/Telegram/web/schema/Away suite -> `................................... [100%]` (`35 passed`); full isolated suite -> `........................................................................ [ 72%] ............................ [100%]` (`100 passed`). Live schema initialization succeeded. Integration tests now provision and exclusively use `lyra_test`; a regression guard prevents destructive fixtures from targeting the runtime database. Operating guide: `docs/away_mode.md`. |
| W5.2.1 | Gate passed | All destructive fixtures now use `tests/db_support.py`; session-start and per-connection guards reject the runtime database and names without `_test`. Focused database/backup/safety suite -> `........................................ [100%]` (`40 passed`); full suite -> `........................................................................ [ 69%] ............................... [100%]` (`103 passed`). Production counts for all 12 runtime tables were identical before and after the full run. Backup tests verify complete dumps and reject incomplete/empty files; the operator command now reports size and SHA-256. |
| W5.3 | Deferred (user opt-in pending) | Christopher is completing Tailscale payment and installation; no dependency or network exposure introduced. |
| W6.1 | Gate passed | SRS v0.15 FR-M7/FR-M8 defines the authenticated local mutation boundary and curated-import routing. The unified control service/UI lists provenance, destination, flags, and proposal reason; approve/correct/reject/confirmed-forget flows cover pgvector and KG destinations; audit retains hashes rather than removed text. Unit web/auth/token/backup suite -> `.............. [100%]` (`14 passed`); expanded PostgreSQL/KG suite -> `................. [100%]` (`17 passed`); final control lifecycle suite -> `.... [100%]`; full suite -> `........................................................................ [ 65%] ...................................... [100%]` (`110 passed`). Compileall, JavaScript syntax, build-plan validation, and additive live schema initialization passed. Operator guide: `docs/memory_control.md`; dedicated `.env` token activation remains a local setup step. |
| W6.2 | Not started | — |
| W6.3 | Not started | — |
| W6.4 | Not started | Added 2026-09-06 after repeated Docker Desktop backend exits; implementation waits for W6.2 and W6.3. Roadmap amendment: validator `VALID`; focused build-plan tests -> `.. [100%]`; full suite -> `........................................................................ [ 65%] ...................................... [100%]` (`110 passed`). |
| W7.1 | Not started | — |
| W7.2 | Not started | — |
| W7.3 | Not started | — |
| W8.1 | Not started | — |
| W8.2 | Not started | — |
| W8.3 | Not started | — |
| W9.1 | Not started | — |
| W9.2 | Not started | — |
| W9.3 | Not started | — |
| W9.4 | Not started | — |
| W9.5 | Not started | — |
| W9.6 | Not started | — |
| W9.7 | Not started | — |
| W10.1 | Not started | — |
| W10.2 | Not started | — |
| W10.3 | Not started | — |
| W10.4 | Not started | — |
| W11.1 | Not started | — |
| W11.2 | Not started | — |
| W11.3 | Not started | — |
| W11.4 | Not started | — |
| W11.5 | Not started | — |
| W11.6 | Not started | — |
