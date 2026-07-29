# ADR-002 — MCP knowledge graph alongside pgvector memory

**Status:** Accepted; D3 (server registration + round-trip proof) implemented 2026-07-29  
**Date:** 2026-07-26  
**SRS sections affected:** §3.4 (Memory), IF-1; related FR-N* (Notion digests), personal-assistant digests

## Context

Phase 1 ships episodic/relational memory in pgvector (`memories` with approval gate + FR-D2 buckets). Christopher also wants Lyra as a daily/weekly personal + professional assistant, with richer structured recall (people, projects, habits, commitments) and is evaluating the official MCP Knowledge Graph / Memory server (entities, relations, **observations**) from [`modelcontextprotocol/servers` memory](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md).

Risk: two “memories” that drift or bypass Lyra’s approval/DLP rules.

## Decision

1. **Keep pgvector as the semantic recall plane** for approved episodic memories and corpus chunks (FR-R6 / FR-M*).
2. **Add the MCP knowledge graph as a structured observation plane** for assistant-oriented facts: entities (Christopher, projects, orgs), relations, and atomic observations — local JSONL (or equivalent), registered as an MCP server.
3. **Notion remains the human dashboard** (tasks + digests). Digests are *views* of work done; they are not the knowledge graph and not the corpus.
4. **Write policy:** KG observations that touch biography/relationship content MUST respect FR-M3/FR-M4 (approval + never-persist). Prefer: propose → approve → then mirror/select into KG, or dual-write only after approval.
5. **n8n (ADR-001)** may trigger digest generation or notifications; it must not own the KG or pgvector stores.

## Consequences

- Clear split: **corpus** (documents) / **episodic memory** (approved summaries) / **KG** (structured observations) / **Notion** (human-readable board + digests).
- Phase 2 work: register `@modelcontextprotocol/server-memory` (or pinned equivalent), define entity taxonomy, wire digests → optional KG observation extraction, daily/weekly assistant jobs.
- SRS follow-up required before implementation gates (new FRs for personal-assistant digests + KG boundary).

## Alternatives considered

- **KG replaces pgvector memory** — rejected; loses vector search and existing A5 approval path.
- **Notion as graph** — rejected; Notion is the dashboard (FR-N3), not retrieval.
- **Only n8n workflows for digests** — useful for delivery, insufficient as structured memory.
