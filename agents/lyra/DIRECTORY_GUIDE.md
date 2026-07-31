# Lyra Directory Guide

Use this guide as the source of truth for where to place new files.

## Tier 0 (Core Foundation)

These files define Lyra's identity and operating model:

- `agents/lyra/SKILL.md`
- `agents/lyra/system_prompt.md` - stable behavior and mode contract
- `agents/lyra/character_file.md` - stable identity constants and index
- `agents/lyra/architecture.md`
- `agents/lyra/model-config.md`

## Tier 1 (Durable Agent Context)

- `agents/lyra/references/` - canonical lore, appearance, idioms, and quirks
- `agents/lyra/state/` - evolving approved relationship/session/story state
- `agents/lyra/skills/` - domain skills (one folder per skill)
- `agents/lyra/subagents/` - canonical isolated-worker definitions; sync to
  `.cursor/agents/` with `scripts/sync_subagents.py`
- `agents/lyra/subagents/references/` - task packets, language playbooks, and
  eval prompts (not synced; workers read from the repo)
- `agents/lyra/tools/` - optional local tool wrappers/docs

`agents/lyra/resources/` is legacy compatibility only. Do not add new content there.

## Tier 2 (Assets and Generated Artifacts)

- `agents/lyra/assets/visual_references/lyra/` - character visual refs (images, concept sheets)
- `agents/lyra/assets/visual_references/spaceship/` - ship visual refs, diagrams, paint/color studies
- `agents/lyra/assets/` (other subfolders) - templates or static artifacts shared by skills

## Search Order

When looking for information, search in this order:

1. Tier 0 foundation files
2. `agents/lyra/references/`
3. `agents/lyra/state/`
4. `agents/lyra/skills/*/references/`
5. `agents/lyra/assets/`

## Naming Conventions

- Use lowercase with underscores for folder names in `agents/lyra/skills/`
- Use descriptive snake_case file names for markdown docs
- Keep one concern per file whenever possible
- Use lowercase hyphenated filenames matching each subagent's frontmatter
  `name`; never hand-edit generated `.cursor/agents/` copies
