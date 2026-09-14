# Scripts

Run Python helpers from the repository root with
`.\venv\Scripts\python.exe scripts\<name>.py`.

## Runtime and database

- `lyra_doctor.py` reports secret-safe readiness for the runtime, database,
  model providers, Telegram, Notion, knowledge graph, logging, and service.
- `db_init.py` starts PostgreSQL/pgvector when needed and applies the idempotent
  schema.
- `db_backup.py` creates a verified full dump covering every required runtime
  table and prints its size and SHA-256 hash. See
  [database restore](../docs/db_restore.md) before recovery.
- `manage_service.py` previews or applies idempotent NSSM install/status/remove
  commands. NSSM is optional until explicitly configured.
- `watchdog.py` performs one conservative health/recovery tick or runs the
  bounded after-logon monitor.
- `register_watchdog.py` previews or manages the per-user hidden Startup-folder
  watchdog launcher; registration requires explicit opt-in.
- `doctor.ps1` is the PowerShell entry point for environment checks.

## Access and approval

- `telegram_discover.py` discovers Telegram user/chat IDs after BotFather setup.
- `configure_control_token.py` generates the local memory-control token directly
  into `.env` without printing it.
- `approve_memory.py` and `approve_observation.py` perform explicit gated
  promotions; agents do not receive those mutation capabilities.

## Digests, briefings, and Notion

- `generate_digest.py` and `generate_briefing.py` build the current local
  artifacts using their plane/bucket filters.
- `notion_ensure_digests_db.py` creates or verifies the configured Notion
  Digests database.
- `d1_verify_live_digest.py` performs the D1 live digest verification path.

## Models, demos, and agent definitions

- `check_model_providers.py` checks configured provider profiles without
  exposing credentials.
- `phase1_e2e_demo.py` runs the Phase 1 end-to-end demonstration.
- `sync_subagents.py` syncs canonical definitions from `agents/lyra/subagents/`
  into `.cursor/agents/`.
- `validate_build_plan.py` validates roadmap structure and dependency ordering.
- `validate_docs.py` checks local Markdown links plus SRS, roadmap, schema,
  script, and MCP documentation alignment.

## Grok CLI helpers

Use these helpers to avoid PowerShell line-ending issues when installing
bash-based tools:

```powershell
.\scripts\install-grok.ps1
.\scripts\install-grok.ps1 -VerifyOnly
.\scripts\verify-grok.ps1
```

From Bash on Windows:

```bash
bash ./scripts/install-grok.sh
```
