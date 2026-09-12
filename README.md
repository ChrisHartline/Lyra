# Lyra

Lyra is a local-first personal and professional assistant with a stable
relational persona, shared web/Telegram conversations, approval-gated memory,
and explicit privacy boundaries between biography, story, and campaign state.

## Current build status

Wave 5 is closed. W6.1 through W6.3 are complete: memory/observation
control, Commitment Radar, and Stuck Mode are implemented and live. W6.4
(local runtime resilience) is next.

The authoritative status and acceptance evidence live in the
[build plan](docs/lyra_build_plan.md). Product behavior is defined by the
[system requirements](docs/lyra_system_requirements.md), currently SRS v0.18.

## Run and check Lyra

From the repository root:

```powershell
.\venv\Scripts\python.exe -m lyra.web --host 127.0.0.1 --port 8765
.\venv\Scripts\python.exe scripts\lyra_doctor.py
```

Lyra intentionally binds only to loopback. Private remote web access is
provided by Tailscale Serve, not by exposing the application port.

## Operating guides

| Capability | Guide |
|---|---|
| Workstation process, logs, backups, NSSM | [Workstation service](docs/workstation_service.md) |
| Private Tailscale HTTPS | [Tailscale access](docs/tailscale_access.md) |
| Telegram bot and allowlists | [Telegram setup](docs/telegram_setup.md) |
| Device handoff and Away Mode | [Away Mode](docs/away_mode.md) |
| Memory and observation review | [Memory control](docs/memory_control.md) |
| Commitment offers and reminders | [Commitment Radar](docs/commitment_radar.md) |
| Stuck Mode support and privacy | [Stuck Mode](docs/stuck_mode.md) |
| Database recovery | [Database restore](docs/db_restore.md) |

Additional implementation helpers are cataloged in
[scripts/README.md](scripts/README.md); MCP servers and contracts are described
in [mcp/README.md](mcp/README.md).

Run the documentation freshness check after changing requirements, gates,
schema, scripts, MCP surfaces, or Markdown links:

```powershell
.\venv\Scripts\python.exe scripts\validate_docs.py
```

## Source-of-truth boundaries

- `personality/`, `ship/`, and `state/` hold Lyra's canonical persona, ship,
  relationship, and story packs.
- `agents/lyra/` is the Agent Skills host and contains operational references,
  skills, and subagent definitions—not a second persona store.
- PostgreSQL + pgvector holds corpus, session, operational, and gated episodic
  memory data.
- The local MCP knowledge graph holds approved structured observations.
- Notion is a human dashboard, not Lyra's memory store.

Secrets belong only in `.env`. Telegram and Tailscale conversation access do
not expand authority to local-only memory, commitment, filesystem, shell, Git,
or publication controls.
