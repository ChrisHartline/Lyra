# Lyra Context Architecture

## Separation Of Concerns
- `system_prompt.md`: identity, personality, behavior contract
- `character_file.md`: detailed persona and backstory reference
- `skills/**`: specialized technical playbooks
- `references/**`: canonical durable context for Lyra
- `state/**`: evolving session/relationship context
- `assets/**`: visual references and static artifacts
- `mcp/**`: prompts, resources, tool definitions and integration context

## Why This Split
- Keeps persona stable while technical knowledge evolves quickly.
- Prevents system prompt bloat.
- Makes MCP and skills independently versionable.

## Deployment Strategy
1. Local-first development in this repository.
2. Validate tool/resource usefulness through real usage.
3. Publish stable MCP content to GitHub when ready.
4. Add third-party MCP servers incrementally (for example Vercel) with explicit ownership and secrets policy.
