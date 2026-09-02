# ADR-003 — Repo-root data packs as the persona source of truth

**Status:** Accepted  
**Date:** 2026-09-01  
**SRS sections affected:** §3.1 FR-P1 / FR-P4 / FR-P5, §3.4 FR-M5, §3.8 FR-V2, NFR-1; related DIRECTORY_GUIDE and Track E

## Context

Phase 1 and Track D gated green with persona files under `agents/lyra/` (Tier 0 `system_prompt.md` / `character_file.md`, `references/`, `state/`). Phase 3 Track E introduces portable **data packs** at the repo root (`personality/`, `ship/`, `state/`) so stable identity, ship lore, and living state can travel independently of the Agent Skills host.

A WIP pack tree already existed beside the live `agents/lyra/` tree. The two copies disagreed (relationship stage, height, ship layout) and nothing loaded the packs. Continuing with two sources of truth would drift identity and break FR-P1 / FR-P6.

## Decision

1. **Repo-root packs are the single data source of truth.**
   - `personality/` — stable identity: `personality/system_prompt.md` and `personality/character_bible.md` (hand-edited), plus appearance, color map, speech/idioms
   - `ship/` — ship reference, systems, cargo/layout, and live `ship/current_status.json`
   - `state/` — `state/relationship.md` plus `relationship.json`, active arcs, user knowledge; machine-writable story-canon regen lands here
2. **`agents/lyra/` remains the Agent Skills host**, not a second identity store: `SKILL.md`, domain skills, subagents, architecture, and operational docs (e.g. observation etiquette). Former Tier 0 / lore / living-state files under `agents/lyra/` become thin pointers or are deleted.
3. **FR-P1 is unchanged in spirit:** `personality/system_prompt.md` and `personality/character_bible.md` are hand-edited and never machine-written. The pack loader reads them; it does not regenerate them. Promotion from state or story canon into personality remains Christopher-only (FR-P6).
4. **Pack conventions:** markdown files carry YAML frontmatter (`pack`, `file`, `version`, `last_updated`). JSON is reserved for machine-live status (`ship/current_status.json`, `state/relationship.json`).
5. **Knowledge-graph store path is unchanged:** `agents/lyra/state/knowledge_graph/` stays with the host (operational store, not persona data).

## Consequences

- Cursor skills, C4 contract tests, and `MemoryService.regenerate_story_canon` must point at pack paths (Track E gates E2–E5).
- Backstory topic files may remain under `agents/lyra/references/` until separately packed; they are durable lore, not a second system prompt.
- SRS path strings in FR-P4, FR-P5, FR-M5, FR-V2, and NFR-1 are amended to the pack tree.

## Alternatives considered

- **Nested packs under `agents/lyra/`** — less path churn, weaker portability; rejected because Track E’s purpose is a host-neutral data drop.
- **Keep both trees and sync** — rejected; the WIP already drifted.
