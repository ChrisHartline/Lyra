# Lyra Directory Guide

Use this guide as the source of truth for where to place new files.
Persona **data** lives in repo-root packs (ADR-003). `agents/lyra/` is the
Agent Skills **host** (routing, skills, subagents, operational docs).

## Data packs (single source of truth)

Stable identity, ship lore, and living state are not duplicated under
`agents/lyra/` except as thin pointers.

- `personality/system_prompt.md` - stable behavior and mode contract (hand-edited)
- `personality/character_bible.md` - stable identity constants and index (hand-edited)
- `personality/appearance.md` - visual / physiological reference
- `personality/emotional_color_map.md` - bioluminescence vocabulary
- `personality/speech_and_idioms.md` - voice, idioms, quirks
- `locations/locations.md` - approved stable place canon, atmosphere,
  constraints, and narrative use. Ship rooms link to `ship/` rather than
  duplicating it.
- `ship/ship_reference.md` - class, interior, repair context
- `ship/systems.md` - system-by-system notes
- `ship/cargo_and_layout.md` - rooms and living conversion
- `ship/current_status.json` - machine-live ship status
- `state/relationship.md` - human-readable relationship stage (FR-M5)
- `state/relationship.json` - machine relationship fields
- `state/active_arcs.md` - open story/life arcs
- `state/user_knowledge.md` - approved facts about Christopher
- `state/story/` - machine-writable canon regen from approved story memories

## Agent Skills host (`agents/lyra/`)

- `agents/lyra/SKILL.md` - load packs first, then route to skills/subagents
- `agents/lyra/architecture.md`
- `agents/lyra/model-config.md`
- `agents/lyra/references/` - operational docs (e.g. observation etiquette) and
  durable lore not yet packed (per-topic backstory). Do not add a second
  appearance, idiom, color-map, or ship SoT here.
- `agents/lyra/state/knowledge_graph/` - KG JSONL store (not persona data)
- `agents/lyra/skills/` - domain skills (one folder per skill)
- `agents/lyra/subagents/` - canonical isolated-worker definitions; sync to
  `.cursor/agents/` with `scripts/sync_subagents.py`
- `agents/lyra/subagents/references/` - task packets, language playbooks, and
  eval prompts (not synced; workers read from the repo)
- `agents/lyra/tools/` - optional local tool wrappers/docs

`agents/lyra/resources/` is legacy compatibility only. Do not add new content there.

## Tier 2 (Assets and Generated Artifacts)

- `assets/visual_references/lyra/` - canonical/candidate character visual refs
- `assets/visual_references/wardrobe/` - clothing and appearance references
- `assets/visual_references/locations/` - place images and visual presets linked
  to `locations/` by stable `location_id`
- `assets/visual_references/ship/` - ship exterior/interior images linked to
  canonical `ship/` definitions
- `assets/visual_references/props/` - object and continuity references
- `agents/lyra/assets/` - only implementation assets intrinsically owned by a
  skill; never a mirrored canonical visual library

The former `agents/lyra/assets/visual_references/` staging tree was migrated and
removed on 2026-09-20. Do not recreate it or maintain synchronized copies.

## Search Order

When looking for information, search in this order:

1. `personality/` (Tier 0 prompt + bible, then appearance / color / speech)
2. `locations/`
3. `ship/`
4. `state/`
5. `agents/lyra/skills/*/SKILL.md`
6. `agents/lyra/references/` (etiquette, unpacked backstory)
7. `assets/visual_references/`

## Naming Conventions

- Use lowercase with underscores for folder names in `agents/lyra/skills/`
- Use descriptive snake_case file names for markdown docs
- Keep one concern per file whenever possible
- Pack markdown uses YAML frontmatter: `pack`, `file`, `version`, `last_updated`
- JSON is only for machine-live status (`ship/current_status.json`,
  `state/relationship.json`)
- Use lowercase hyphenated filenames matching each subagent's frontmatter
  `name`; never hand-edit generated `.cursor/agents/` copies
