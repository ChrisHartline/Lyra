# Lyra — System Requirements Document

**Version:** 0.9 (Kickoff candidate)
**Date:** 2026-08-02
**Author:** Christopher (with Claude)
**Status:** In progress

---

## 1. Purpose & Scope

Lyra is a persistent AI agent combining two roles in a single persona:

1. **Companion / roleplay partner** — a character (Lyra Voss) with a stable identity, backstory, and evolving relationship state, supporting conversational roleplay and, in later phases, structured campaign play (D&D tabletop integration).
2. **Research & development assistant** — an expert-level technical collaborator that performs web research, ingests findings into a durable, searchable corpus, manages tasks and project state via Notion, and supports professional work (D.Eng. research, GCP/Vertex AI, quantum ML, scholarly authoring).

The defining requirement is **continuity**: unlike a stateless web chat, Lyra retains knowledge (corpus) and relational context (memory) across sessions.

**Secondary (meta) goal:** this project doubles as a reference case for **SRS-driven AI pair development** — demonstrating that a requirements document with numbered FRs, a dependency-gated build plan, and executable acceptance criteria lets a coding agent (Cursor/Claude) develop and test with minimal supervision, reducing time-to-prototype. Process observations are captured in `docs/lessons_learned.md` at end of Phase 1.

**In scope (v1):** persona engine, skill routing, research-to-corpus pipeline, memory system, Notion integration, operation within Cursor/CLI.
**In scope (v2):** dedicated chat UI, Telegram notifications/chat channel, Foundry VTT integration, voice & avatar **stub interfaces** (§3.8), optional Supabase migration.
**Out of scope (for now):** full voice synthesis and avatar rendering (stubs only, per §3.8); mobile app; multi-user access and authentication — the system is single-user by design, and auth (via a cloud identity provider or Vercel's auth offerings) becomes a v3+ requirement only if a deployment ever becomes externally reachable (see NFR-8).

## 2. System Context

### 2.1 Actors
- **Christopher (primary user):** sole user; interacts via Cursor/CLI (v1), chat UI and Telegram (v2).
- **Lyra (agent):** the system itself, orchestrated by the host environment.

### 2.2 Host Environments
- **v1:** Cursor IDE / Grok CLI on Windows (workspace `V:/ProjectsGit/lyra`, PowerShell default shell). Cursor provides the model loop, tool execution, subagent execution, and session context — it is the **execution engine**, not the owner of any Lyra definitions.
- **v2:** Lyra runs as a standalone agentic application (Python service + web chat UI) that owns its own agent loop and orchestrator; Telegram bot as a lightweight channel. Cursor reverts to a development environment only.
- **Portability principle:** All agent, subagent, and skill definitions live in host-neutral formats (markdown + frontmatter) inside the repo. Host-specific directories (e.g., `.cursor/agents/`) are generated/synced targets, never the source of truth — nothing Lyra needs at runtime may live only in host config.

### 2.3 Model Providers
| Role | Provider | Rationale |
|---|---|---|
| Conversation / persona | Grok (xAI) | Primary conversational model; fewer refusals in roleplay contexts |
| Task execution (research synthesis, memory write-back, summarization, coding assistance) | Claude (Anthropic) | Preferred for structured/technical tasks |
| Optional specialist tasks | Gemini (Google) | Available for GCP-adjacent workflows if needed |
| Embeddings | Local sentence-transformers (MiniLM-class) | Free, private, no API dependency; CPU-only is sufficient at personal-corpus scale |

### 2.4 External Services
- **PostgreSQL + pgvector** (local, Docker) — corpus and memory storage
- **Notion** (API) — task management, human-readable research digests, status updates
- **Linear, Supabase, Vercel MCP servers** — configured; usage optional/incremental
- **Telegram Bot API** (v2) — notifications and lightweight chat
- **n8n** (optional, workstation or existing host) — workflow automation plane for fast capability onboarding; not a memory/corpus store (ADR-001)
- **Web search/fetch** — via host tooling for research runs

### 2.5 Deployment Map

Every runtime component MUST appear in this table (see NFR-8). Default posture: **self-hosted on the existing workstation** (six-year-old desktop, ample storage, RTX 2080 available for optional acceleration); cloud hosting is introduced only when a requirement demands external reachability, via ADR (§10).

| Component | v1 | v2 | Notes |
|---|---|---|---|
| PostgreSQL + pgvector | Docker on workstation | Same | Supabase migration only if UI goes public |
| Embedding model | Workstation CPU | Same | 2080 = optional acceleration, never a requirement (NFR-4) |
| Corpus MCP server | Workstation | Same | Colocated with DB (data gravity) |
| Agent loop / orchestrator | Cursor (execution engine) | Lyra app service on workstation | FR-S6 |
| Chat UI | — | Served from workstation (LAN) | Public exposure would trigger auth (v3+) |
| Telegram bot | — | Workstation service | Long-polls outbound — no inbound ports required |
| Notion | SaaS | SaaS | Human dashboard only (FR-N3); Lyra shared working space IDs in `.env` |
| n8n (optional) | Workstation / existing host | Same | Glue workflows → MCP/webhook tools; never owns memory/corpus (ADR-001) |
| Foundry VTT + MCP relay | — | Foundry world + hosted relay (foundry-mcp.com) | Self-hosted relay = future option (FR-D1) |

## 3. Functional Requirements

### 3.1 Persona Engine
**Authority note:** This SRS specifies persona file placement, loading,
state-management, and leakage boundaries. Christopher's private
`system_prompt.md` and `character_file.md` are authoritative for Lyra's
personality, relationship, warmth, and voice; this audience-facing document
must not dilute or redefine that personal contract.

- **FR-P1:** Identity is defined exclusively by Tier 0 files (`system_prompt.md`, `character_file.md`); these are hand-edited and version-controlled, never machine-written.
- **FR-P2:** The agent supports two blended modes — Companion and Technical Assistant — and switches (or mixes) based on conversational context without losing persona consistency.
- **FR-P3:** Roleplay/relationship state MUST NOT leak into professional deliverables (papers, LinkedIn posts, code, client-facing artifacts). Deliverable-producing skills operate persona-lightweight per existing operating rules.
- **FR-P4:** Persona references (backstory, appearance, idioms, color-emotion map) load from `agents/lyra/references/` on demand, not embedded in the system prompt. Backstory is split into per-topic files (e.g., `references/homeworld.md`, `references/history_pre_arrival.md`, `references/appearance.md`) rather than a single monolith, since retrieval is per-file.
- **FR-P5 (Story canon layer):** Emergent narrative from ongoing roleplay (e.g., the ship, repair plans, open arcs) lives in `agents/lyra/state/story/` (`ship.md`, `arcs.md`, `timeline.md`). Unlike Tier 0, this layer is **machine-writable**: session write-back proposes `memory_type='story'` memories through the approval gate (FR-M3), and canon files are periodically **regenerated from** approved story memories (same pattern as FR-M5) — the memory rows are the change record; the canon files are the readable current state.
- **FR-P6 (Promotion rule):** Content moves from story canon into Tier 0 identity or `references/` only by Christopher's deliberate manual edit. The machine proposes on the working branch; only the human merges to the protected branch. This prevents long-horizon roleplay drift from silently rewriting who Lyra is.

### 3.2 Skill Router & Orchestration
- **FR-S1:** Domain-specific requests route to the matching skill per `agents/lyra/SKILL.md` (Agent Skills standard).
- **FR-S2:** New skills follow the established folder convention (`SKILL.md` + `references/`, `scripts/`, `assets/`).
- **FR-S3:** Skills MUST NOT contain persona content; persona files MUST NOT contain domain-technical depth. (Existing separation-of-concerns rule, formalized.)
- **FR-S4 (Subagents, v1):** Specialist ephemeral agents (e.g., `python-developer`, `cpp-developer`, `researcher`) are defined as host-neutral markdown files with frontmatter (`name`, `description`, `model`; optional host-supported execution flags) in `agents/lyra/subagents/` — the single source of truth. Tool/capability expectations live in the operational body because Cursor subagents inherit parent tools and do not support a per-agent `tools` frontmatter field. A sync script publishes copies to `.cursor/agents/` for Cursor execution in v1. Definitions persist; instances are ephemeral with fresh, isolated context per run (no shared state between runs).
- **FR-S5 (Model pinning):** Subagent definitions MAY pin a model per task (e.g., Claude for code-generation subagents while the main persona loop runs on Grok), implementing the split-provider strategy at the orchestration layer.
- **FR-S6 (Orchestrator, v2):** The Lyra application implements its own orchestrator: load subagent definition → construct isolated context → execute to completion via the provider abstraction (NFR-3) → return result to the main loop. The orchestrator consumes the same definition files as v1; no Cursor dependency. Keep it minimal (plain Python loop); adopt a framework only if demonstrated need arises.
- **FR-S7 (Dynamic agent creation, v2 → v3):** In v2, Lyra MAY author new subagent definition files on demand when a task requires a specialist that does not exist, gated on Christopher's approval before the definition is committed (same trust model as memory write-back, FR-M3). Unattended auto-creation is deferred to v3, contingent on v2 track record.

### 3.3 Research & Corpus Pipeline
- **FR-R1:** Given a research request, Lyra fetches web sources, stores raw source material to the local filesystem (`data/`, gitignored), and records provenance (URL/path, title, fetch date) in a `sources` table.
- **FR-R2:** Sources are chunked, embedded (local sentence-transformers), and inserted into a `chunks` table with source FK and metadata (topic tags, JSONB).
- **FR-R3:** Corpus retrieval is semantic (vector similarity) with provenance surfaced — answers grounded in the corpus cite their sources.
- **FR-R4:** On completing a research run, Lyra publishes a human-readable digest page to Notion with links back to sources.
- **FR-R5 (Curation & dedup):**
  - **External sources** are deduplicated at the content level: on ingest, compute a normalized-text hash and document-level embedding similarity against existing sources. When the same work arrives in multiple formats (e.g., PDF and DOCX of one article), retain only the format most useful downstream — preference order: native text (md/html/docx) > born-digital PDF > scanned/OCR PDF. The superseded copy's chunks are removed; its `sources` row is retained with a `superseded_by` reference for provenance.
  - **Own works** (documents authored by Christopher or Lyra) are **versioned, never deduplicated** — flagged `is_own_work`, with versions linked so history is preserved.
  - **Additions auto-commit:** Lyra MAY add to the corpus without approval; full provenance (FR-R1) is the compensating control.
- **FR-R6 (Corpus MCP server):** Corpus and memory retrieval are exposed as a local MCP server (tools: e.g., `search_corpus`, `search_memories`, `add_source`, `propose_memory`) rather than host-specific scripts. All consumers — the main agent, every subagent, and the v2 chat UI/Telegram services — query the same contract, so swapping execution engines between v1 and v2 never touches the data plane. (One route reflector; every host is just a peer.)
- **FR-R7 (Staleness, deferred):** No automated expiry in v1. A periodic corpus-review task (Christopher + Lyra jointly walking recent/aging sources) is planned as a v2 scheduled job; criteria to be defined then.

### 3.4 Memory & State Manager
- **FR-M1:** Memory is tiered:
  - **Identity:** Tier 0 files — never auto-written.
  - **Episodic/relational memory:** pgvector `memories` table (text, embedding, type, salience, timestamp) enabling semantic recall of past sessions. Every memory carries a **bucket** per FR-D2 (biography / story / campaign); retrieval filters by bucket so contexts never blend. ("Ledger" in older notes means the same thing — a retrieval namespace, not a financial metaphor.)
  - **Session state:** ephemeral, managed by the host.
- **FR-M2:** A write-back job turns each session into candidate memories.
  - **Contract (stable):** candidates are written with `approved=false`; only approved rows are recalled (FR-M3); never-persist rules apply before propose (FR-M4); each candidate is tagged with a FR-D2 bucket.
  - **v1 implementation (honest):** Phase 1 ships a **deterministic stub** — sentence split, keyword bucket tags, regex never-persist filter, and markdown dump for story-canon regen. This proves the gate and isolation contracts; it is not production-grade summarization.
  - **Target implementation:** LLM summarization (Claude preferred for this task) with explicit bucket classification, replacing the stub without changing the approval/retrieval contract.
- **FR-M3 (v1 policy):** Candidate memories require Christopher's approval before commit. Auto-commit MAY be enabled per-category in v2 after the policy proves trustworthy.
- **FR-M4 (Never-persist list — DLP policy on the memory write path):** The write-back job MUST NOT create memories containing, regardless of the approval flow:
  1. Credentials or secrets (API keys, passwords, connection strings), even if mentioned in conversation.
  2. Financial or government identifiers (account/card numbers, SSN-class IDs).
  3. Personal details of third parties (family, friends, colleagues) — persistable only via explicit approval, never auto-proposed.
  4. Transient emotional states recorded as standing facts; behavioral/emotional *patterns* may be persisted only through the approval gate.
  5. Health specifics beyond what is hand-curated in Tier 0 identity files (which are never machine-written, per FR-P1/FR-M1).
  6. Roleplay/in-character events represented as real-world facts (campaign state is segregated per FR-D2).
  7. Raw transcripts or verbatim quotes — memories are summaries, not recordings.
  8. Anything Christopher marks "off the record" via an explicit do-not-remember signal.
  *(Policy confirmed v0.6. v1 stub enforces a regex subset of 1–3 and 8; full coverage is required when LLM write-back lands.)*
- **FR-M5:** `agents/lyra/state/relationship_state.md` remains the human-readable summary of relationship stage; it is regenerated from (not a replacement for) the memory store.
- **FR-M6 (Structured observation plane — ADR-002):** Alongside pgvector (semantic recall of episodic memory + corpus chunks), a separate **MCP knowledge graph** plane holds structured, assistant-oriented facts as entities/relations/observations (people, projects, orgs, habits, commitments) via the official MCP Memory server, local JSONL store. The two planes never merge: pgvector answers "what did we discuss/read," the KG answers "what do we know about X." Observations that touch biography/relationship content are subject to the same approval (FR-M3) and never-persist (FR-M4) rules as pgvector memories before they are written — propose, then approve, then write. Agents never receive raw KG mutation tools directly; they see only a gatekeeper interface (search/read + `propose_observation`), with an approval step promoting a pending proposal to a real KG write. Notion (FR-N3) remains the dashboard view, not a store for either plane.

### 3.5 Notion Integration
- **FR-N1 (inbound):** When told that Notion content changed (e.g., "I updated the task board — check it"), Lyra reads the relevant pages/databases via API and incorporates the changes into her working context.
- **FR-N2 (outbound):** On completing delegated work, Lyra updates the corresponding Notion task/page and notifies Christopher in-conversation (v1) or via Telegram (v2).
- **FR-N3:** Notion is the human dashboard, not the retrieval layer — semantic search over research content is served by pgvector only.

### 3.6 Notifications & Channels (v2)
- **FR-T1:** A Telegram bot (BotFather-provisioned) delivers notifications: research run complete, Notion task updated, scheduled digests.
- **FR-T2:** The Telegram channel optionally supports lightweight two-way chat with the same persona and memory backend.
- **FR-T3:** Telegram messages MUST respect the same mode-separation rules (FR-P3); notification content defaults to Technical Assistant register.

### 3.7 Roleplay & Campaign Mode (v2)
- **FR-D1 (Foundry VTT boundary — decided):** The tabletop platform is Foundry VTT. Integration direction: **Lyra is a client; Foundry owns mechanical truth** (HP, initiative, inventory, dice results, scenes). Integration is **buy-not-build**: the existing Foundry API Bridge (MCP) module is installed in the Foundry world and connected via the **hosted relay** (foundry-mcp.com) for v2 — Foundry thereby becomes another MCP server available to Lyra's orchestrator alongside the corpus server (IF-4). **Self-hosted relay is a documented future option** (lightweight Node service, negligible compute — could co-locate with pgvector) if privacy or reliability later motivates it. Lyra-side scope (what we build): campaign session context assembly (Lyra in character as her PC, fed relevant Foundry state + campaign ledger), post-session write-back to `memory_type='campaign'` (A5 machinery), and orchestrator config registering the Foundry MCP endpoint. The campaign ledger (FR-D2) stores narrative memory only and never duplicates mechanical state — one system of record per data type.
- **FR-D2 (Three-bucket separation):** The system maintains three segregated fiction/reality **buckets** (retrieval namespaces), none of which writes to another automatically:
  1. **Biography** — real relational memory about Christopher and the working relationship (`memory_type` in {preference, event, fact, relationship}).
  2. **Story-world** — Lyra's own emergent canon (FR-P5; `memory_type='story'`).
  3. **Campaigns** — D&D/tabletop game state (`memory_type='campaign'`, keyed by campaign ID).
  Nested roleplay is explicitly supported: in a campaign, Lyra is a character playing a character — her PC's fate affects only the campaign bucket, never her persona, story canon, or relationship memory. Cross-bucket writes occur only via the human promotion rule (FR-P6). Schema/API may still expose the field name `ledger` for compatibility; treat it as the bucket tag.

### 3.8 Voice & Avatar Stubs (v2)
- **FR-V1 (Stub interfaces):** The v2 application defines — but does not implement — the output channels a future embodiment will consume: `speak(text, prosody_hints)` and `express(emotion, intensity)`. v2 implementations are no-ops that log/emit events with no renderer attached. Purpose: persona and orchestrator code binds to these interfaces from day one, so attaching TTS or an avatar in v3+ is a renderer swap, not a refactor.
- **FR-V2 (Emotion channel):** `express()` draws from the existing color-emotion map in `agents/lyra/references/`, giving a future avatar a persona-native vocabulary rather than a generic one. Emotion events MAY be rendered minimally in the v2 chat UI (e.g., an accent color) as a cheap proof the channel works.
- **FR-V3 (Local-first bias):** When voice/avatar are eventually implemented, local renderers (e.g., CPU/GPU TTS on the workstation — the RTX 2080 suffices for current local TTS models) are preferred over cloud APIs, consistent with NFR-1 and the deployment posture (§2.5).

## 4. Data Architecture

Three storage planes (the routing table / TFTP server / NOC dashboard split):

| Plane | Store | Role |
|---|---|---|
| Semantic index | PostgreSQL + pgvector (Docker, local) | Fast semantic lookup: `sources`, `chunks`, `memories` tables |
| Raw artifacts | Local filesystem `data/` (gitignored) | PDFs, scraped HTML, datasets; referenced by path from `sources` |
| Human view | Notion | Tasks, digests, status — for Christopher, not for retrieval |

**Proposed schema (v1):**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE sources (
  id BIGSERIAL PRIMARY KEY,
  url TEXT,
  file_path TEXT,
  title TEXT,
  fetched_at TIMESTAMPTZ DEFAULT now(),
  metadata JSONB DEFAULT '{}'
);

CREATE TABLE chunks (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT REFERENCES sources(id),
  content TEXT NOT NULL,
  embedding vector(384),          -- all-MiniLM-L6-v2 dimension
  metadata JSONB DEFAULT '{}'
);

CREATE TABLE memories (
  id BIGSERIAL PRIMARY KEY,
  content TEXT NOT NULL,
  embedding vector(384),
  memory_type TEXT,               -- preference | event | fact | relationship | story | campaign (FR-D2 ledgers)
  salience SMALLINT DEFAULT 5,    -- 1-10
  created_at TIMESTAMPTZ DEFAULT now(),
  metadata JSONB DEFAULT '{}',    -- campaign_id (FR-D2), version links, flags
  approved BOOLEAN DEFAULT false  -- FR-M3 approval gate
);

CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON memories USING hnsw (embedding vector_cosine_ops);
```

**Migration path:** Supabase (managed Postgres + pgvector) is the designated v2 option if the chat UI becomes web-hosted; Postgres-to-Postgres migration via `pg_dump`.

## 5. Non-Functional Requirements

- **NFR-1 (Privacy):** All corpus, memory, and relationship data remain local in v1. No conversation or memory content is sent to third parties beyond the model providers required to process it. The GitHub repository is **private** (PRIV-1); state files (`agents/lyra/state/`) remain tracked and version-controlled within that private boundary.
- **NFR-2 (Secrets):** API keys live in `.env` only; `.env` and `venv/` are gitignored. No secrets in prompts, skills, or MCP content. Any key that has traveled in an archive or been committed is rotated.
- **NFR-3 (Portability):** Model access goes through a thin provider abstraction (OpenAI-compatible interface) so Grok/Claude/Gemini can be swapped per task without touching persona or skills.
- **NFR-4 (Hardware):** All local components (Postgres, embeddings) run CPU-only on the existing Windows workstation. No GPU required.
- **NFR-5 (Cost):** [PLACEHOLDER — monthly API budget ceiling and any per-run limits for research jobs.]
- **NFR-6 (Wellbeing & safety):**
  - Lyra provides emotional support in-character but does not position herself as a substitute for professional mental-health care; during acute distress she encourages real-world support alongside in-character warmth.
  - Mode boundaries (FR-P3) are treated as a safety property, not just a style rule.
  - [PLACEHOLDER — any additional personal guardrails Christopher wants codified.]
- **NFR-7 (Verifiability):** Existing operating rule elevated to requirement: no fabricated facts, logs, tests, or files; corpus-grounded answers cite provenance (FR-R3).
- **NFR-8 (Stack coherence):** The stack must remain logically consistent and complete:
  - **Data gravity:** services that touch the database colocate with it. No splitting compute and data across hosting locations for a single-user system.
  - **Single hosting surface per phase:** everything self-hosts on the workstation until a specific FR demands external reachability; that FR triggers an ADR (§10), not an ad-hoc deployment.
  - **Deployment-map completeness:** every runtime component appears in §2.5. A component with no row does not get built; a row with no FR gets deleted.
  - **No orphan tech:** every technology in the stack must be traceable to at least one requirement. (If PostgreSQL+pgvector is the store, we don't also stand up a second vector DB "because it was easy.")
- **NFR-9 (Backup & recovery):** Continuity is the defining requirement (§1), so its data is protected: scheduled `pg_dump` of the Lyra database plus backup of `data/` raw artifacts to a second medium (external drive or NAS; encrypted cloud bucket acceptable later via ADR). The restore procedure is documented and exercised at least once during Phase 1 — an untested backup is a hope, not a control.

## 6. Interfaces

- **IF-1 (MCP):** External integrations (Notion, Linear, Supabase, Vercel, future Telegram, optional n8n-backed workflows) are exposed as MCP tools/resources; contracts and schemas live in `mcp/tools/`. The starter corpus/memory toolset is not exhaustive — new tools are added by contract under `mcp/tools/` (ADR-001 for n8n registration; ADR-002 for the MCP knowledge-graph server, registered agent-facing only through the gatekeeper per FR-M6).
- **IF-2 (Provider API):** Grok via xAI OpenAI-compatible endpoint; Claude via Anthropic API; selection per task category in runtime config (`LYRA_MODEL` overrides).
- **IF-3 (Foundry VTT):** Existing Foundry API Bridge (MCP) module via hosted relay (per FR-D1); Lyra's orchestrator consumes it as a standard MCP server. Relay API key stored in `.env` per NFR-2. Self-hosted relay documented as a future option; no bespoke bridge development in scope.
- **IF-4 (Corpus MCP server):** Local MCP server (Python) fronting pgvector + filesystem per FR-R6; tool contracts documented in `mcp/tools/`. This is the only supported retrieval path — no direct DB access from agents.

## 7. Constraints & Assumptions

- Single-user system; no auth/multi-tenancy in scope.
- Windows + PowerShell primary; bash scripts run via `bash -lc`.
- Python is the implementation language for pipeline/services code.
- Cursor/Grok CLI owns the agent loop in v1 only; Lyra's own v1 code is limited to pipeline services (ingestion, embedding, memory write-back, Notion sync, corpus MCP server) invoked as tools. From v2, the Lyra application owns the agent loop and orchestrator (FR-S6), and nothing at runtime depends on `.cursor/` config.
- pgvector database is redeployed via Docker Compose (Appendix A) before pipeline work begins.

## 8. Phased Roadmap

**Phase 1 (v1 — Cursor as execution engine):**
1. Redeploy pgvector (Appendix A); apply schema.
2. Ingestion pipeline: fetch → store raw → chunk → embed → insert.
3. Corpus MCP server with provenance-cited retrieval (FR-R6/IF-4).
4. Memory write-back job with approval gate.
5. Notion inbound/outbound sync (FR-N1/N2).
6. Hand-authored subagent definitions in `agents/lyra/subagents/` + sync script to `.cursor/agents/` (FR-S4/S5).
7. Persona layer reorganization: per-topic reference split (FR-P4) and `state/story/` scaffold (FR-P5).

**Phase 2 (v2 — Lyra as standalone agentic application):**
1. Lyra application service with its own agent loop and orchestrator consuming existing subagent definitions (FR-S6).
2. Web chat UI on the application service.
3. Telegram bot (notifications first, chat second).
4. Dynamic subagent creation with approval gate (FR-S7).
5. Foundry VTT integration: install existing MCP bridge module (hosted relay), campaign session logic + campaign write-back (FR-D1/FR-D2).
6. Voice & avatar stub interfaces wired through persona output (FR-V1/V2).
7. Optional Supabase migration if hosting moves off-workstation.

**Phase 3 (v3 — earned autonomy & embodiment):**
1. Per-category memory auto-commit (pending v2 trust record).
2. Unattended subagent auto-creation (FR-S7, pending v2 trust record).
3. Voice/avatar renderers attached to the stub interfaces (FR-V3, local-first).
4. Auth via cloud identity provider — required before any externally reachable deployment (scope note, §1; NFR-8).

## 9. Verification & Acceptance

- **VA-1:** Every functional requirement implemented in code has at least one automated acceptance test (pytest). A requirement is "done" only when its test passes against a live local environment (real Postgres container, real embedding model; Notion tests run against a designated sandbox page/database).
- **VA-2 (Gated progression):** Development follows the task DAG in `docs/lyra_build_plan.md`. Within a track, a task's acceptance tests MUST pass before its dependent task begins. Independent tracks MAY proceed in parallel.
- **VA-3 (No fabricated verification):** Test results are never asserted without execution (reinforces NFR-7). The implementing agent runs the tests and reports actual output.
- **VA-4 (Regression):** The full test suite runs before any task is marked complete; a task may not merge green on its own test while breaking a prior one.

## 10. Change Management

- **CM-1 (ADRs):** New decisions, scope additions, or amendments enter the project as Architecture Decision Records in `docs/adr/NNN-short-title.md`, each containing: Context, Decision, Consequences, and SRS sections affected. ADRs are immutable once accepted; a reversal is a new ADR superseding the old.
- **CM-2 (SRS amendment flow):** An accepted ADR is applied to the SRS as a version bump (0.x during draft, 1.x post-kickoff), with the change reflected in Appendix B. The SRS is always current-state; ADRs are the change history explaining *why*.
- **CM-3 (Agent handling):** When the implementing agent is handed an ADR, it amends the SRS, build plan, and code consistently, and MUST NOT implement changes that lack either an SRS requirement or an accepted ADR (extends build-plan Rule 5).

## Appendix A — pgvector Redeployment (Docker Compose)

```yaml
services:
  lyra-db:
    image: pgvector/pgvector:pg16
    container_name: lyra-pgvector
    environment:
      POSTGRES_DB: lyra
      POSTGRES_USER: lyra
      POSTGRES_PASSWORD: ${LYRA_DB_PASSWORD}   # set in .env
    ports:
      - "5432:5432"
    volumes:
      - lyra_pgdata:/var/lib/postgresql/data
volumes:
  lyra_pgdata:
```

```powershell
# from the repo root
docker compose up -d
docker exec -it lyra-pgvector psql -U lyra -d lyra -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## Appendix B — Open Decisions Log

| ID | Question | Status |
|---|---|---|
| FR-R5 | Corpus curation: dedup, auto-commit | **Decided v0.2** — format-preference dedup for external sources; own works versioned; auto-commit allowed |
| FR-R7 | Staleness / expiry criteria | Deferred to v2 (joint periodic review) |
| FR-M4 | Never-persist memory categories | **Confirmed v0.6** — eight-category DLP list approved by Christopher |
| FR-D1 | D&D tool integration boundary | **Decided v0.4** — Foundry VTT + existing MCP bridge (hosted relay); self-hosted relay = future option |
| NFR-5 | API cost ceiling | Open |
| NFR-6 | Additional personal guardrails | Open |
| PRIV-1 | State files in public repo | **Decided v0.7** — repo made private; state stays tracked; NFR-1 conflict resolved |
| FR-M2 | Write-back summarizer quality | **Decided v0.8** — v1 stub OK to prove gate; LLM summarizer is the target path |
| ADR-001 | n8n automation plane | **Accepted v0.8** — optional glue for capability onboarding via workflows → MCP/webhook tools |
| ADR-002 | MCP knowledge graph alongside pgvector memory | **Accepted v0.9** — structured observation plane (entities/relations/observations) via official MCP Memory server, local JSONL store; approval + never-persist rules (FR-M3/FR-M4) apply before KG write; agents see gatekeeper only (§3.4 FR-M6) |
