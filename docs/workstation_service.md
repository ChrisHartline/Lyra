# Lyra Workstation Service

Lyra's application service remains bound to `127.0.0.1:8765`. When NSSM is
explicitly installed and configured, it can keep the process running across
logoff/restart without exposing it to the LAN or public internet. Until then,
Lyra can be launched manually or by NSSM. W6.4 adds a conservative user-level
watchdog that can start an existing process when health repeatedly fails.

## Readiness

Run the secret-safe capability report from the repository root:

```powershell
.\venv\Scripts\python.exe scripts\lyra_doctor.py
```

The report uses four states: `READY`, `DEGRADED`, `UNCONFIGURED`, and
`UNAVAILABLE`. It reports only presence and health, never credential values.
It also reports Docker Desktop auto-start and per-user watchdog registration.

## NSSM management

Supply an explicit NSSM executable or put `nssm.exe` on `PATH`. Preview every
mutation first. An install dry-run may use the intended future NSSM path before
the executable is present:

```powershell
.\venv\Scripts\python.exe scripts\manage_service.py install --nssm C:\path\to\nssm.exe --dry-run
.\venv\Scripts\python.exe scripts\manage_service.py status --nssm C:\path\to\nssm.exe
.\venv\Scripts\python.exe scripts\manage_service.py uninstall --nssm C:\path\to\nssm.exe --dry-run
```

Remove `--dry-run` to apply an install or uninstall. Re-running install updates
the existing service rather than creating a duplicate; uninstalling an absent
service succeeds without mutation. The service starts in the repository root,
loads configuration from `.env`, and listens only on loopback.

## Logs

Application logs are written to `logs/lyra.log` with five 10 MiB rotations.
NSSM stdout/stderr use `logs/lyra-service.log` with online rotation. The entire
directory is gitignored.

## Backup and restart recovery

`scripts/db_backup.py` verifies the complete runtime table set before running a
full `pg_dump`, then validates that the resulting file is nonempty and contains
every required table data section. It reports the dump's size and SHA-256
checksum. Because sessions share Lyra's PostgreSQL database, the full dump
currently covers all 31 required tables: corpus and memory data, policy/control
intent state, review audit,
named sessions/messages/turns/channel bindings, channel/Away and notification
state, Commitment Radar, Stuck Mode, Research Garden policy/mutes/suggestions,
private shared journal entries/access/audit, relationship rhythm policy/mutes/
events, and Telegram state. Follow
`docs/db_restore.md` to restore and verify a dump.

Commitment and Stuck Mode behavior is documented in
`docs/commitment_radar.md` and `docs/stuck_mode.md`.

See `docs/runtime_resilience.md` for watchdog operation, startup registration,
failure diagnostics, and the local-versus-deployed readiness boundary.
