# Lyra Directory Guide

Use this guide as the source of truth for where to place new files.

## Tier 0 (Core Foundation)

These files define Lyra's identity and operating model:

- `agents/lyra/SKILL.md`
- `agents/lyra/system_prompt.md`
- `agents/lyra/character_file.md`
- `agents/lyra/architecture.md`
- `agents/lyra/model-config.md`

## Tier 1 (Durable Agent Context)

- `agents/lyra/references/` - canonical world/context references
- `agents/lyra/state/` - ongoing relationship/session state
- `agents/lyra/skills/` - domain skills (one folder per skill)
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
