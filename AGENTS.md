## Learned User Preferences
- Keep Lyra personality and roleplay behavior in `agents/lyra/system_prompt.md`, while placing specialized technical depth in skills and MCP content.
- Use MCP for tools, resources, and reusable prompts; treat skills as the main mechanism for domain-specific technical workflows. Keep the MCP tool surface open and incremental—add contracts under `mcp/tools/` rather than freezing the starter set.
- Keep the Lyra directory aligned to the Agent Skills standard, centered on `agents/lyra/SKILL.md` with skill folders containing `SKILL.md`.
- Prefer helper automation scripts for recurring setup and troubleshooting tasks instead of repeating manual terminal steps.
- Follow the Rules of Engagement in `docs/lyra_build_plan.md` when implementing (gated progression, real pytest output, one commit per gate, secrets from `.env` only).
- Use `agents/lyra/DIRECTORY_GUIDE.md` for file placement; put new durable context in `references/` (not legacy `resources/`); put character/ship visuals under `assets/visual_references/`.
- Use Telegram and n8n as communication and tooling channels; treat n8n as optional workflow glue for capability onboarding, not a second memory/corpus store (`docs/adr/001-n8n-automation-plane.md`).
- Lyra is intended as a daily/weekly personal and professional assistant with digests, not only a research/corpus agent.

## Learned Workspace Facts
- Primary workspace is `V:/ProjectsGit/lyra` on Windows with PowerShell as the default shell.
- Bash-based installers on this machine should run via `bash -lc "<command>"` to avoid PowerShell alias/CRLF pipeline issues.
- Grok is the primary agent LLM, with helper scripts under `scripts/` for install, verify, and doctor checks.
- The Lyra agent scaffold lives under `agents/lyra` with core files (`SKILL.md`, `system_prompt.md`, `character_file.md`), domain skills, canonical `references/` (legacy `resources/` for compatibility only), `state/` including `state/story/`, tools, visual assets under `assets/visual_references/`, and placement guidance in `DIRECTORY_GUIDE.md`.
- Product requirements live in `docs/lyra_system_requirements.md` (SRS); build sequencing and acceptance gates live in `docs/lyra_build_plan.md`.
- The GitHub remote for this repo is `https://github.com/ChrisHartline/Lyra`.
- Automated tests live under `tests/` with pytest configured in `pyproject.toml`.
- PostgreSQL + pgvector runs locally via Docker for corpus and memory storage.
- Notion is the human-dashboard integration; configure via `NOTION_TOKEN` and `LYRA_NOTION_*` in `.env`.
