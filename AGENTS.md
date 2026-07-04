## Learned User Preferences
- Keep Lyra personality and roleplay behavior in `agents/lyra/system_prompt.md`, while placing specialized technical depth in skills and MCP content.
- Use MCP for tools, resources, and reusable prompts; treat skills as the main mechanism for domain-specific technical workflows.
- Keep the Lyra directory aligned to the Agent Skills standard, centered on `agents/lyra/SKILL.md` with skill folders containing `SKILL.md`.
- Prefer helper automation scripts for recurring setup and troubleshooting tasks instead of repeating manual terminal steps.

## Learned Workspace Facts
- Primary workspace is `V:/ProjectsGit/lyra` on Windows with PowerShell as the default shell.
- Bash-based installers on this machine should run via `bash -lc "<command>"` to avoid PowerShell alias/CRLF pipeline issues.
- Grok tooling is part of the workspace setup, with helper scripts under `scripts/` for install, verify, and doctor checks.
- The Lyra agent scaffold lives under `agents/lyra` with core files (`SKILL.md`, `system_prompt.md`, `character_file.md`), domain skills, canonical `references/`, state, tools, and visual assets under `assets/visual_references/`.
