# Lyra Workstation Service

Lyra's application service remains bound to `127.0.0.1:8765`. NSSM keeps the
process running across logoff/restart without exposing it to the LAN or public
internet.

## Readiness

Run the secret-safe capability report from the repository root:

```powershell
.\venv\Scripts\python.exe scripts\lyra_doctor.py
```

The report uses four states: `READY`, `DEGRADED`, `UNCONFIGURED`, and
`UNAVAILABLE`. It reports only presence and health, never credential values.

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

`scripts/db_backup.py` verifies that all four session tables exist before
running a full `pg_dump`. Because sessions share Lyra's PostgreSQL database,
the full dump covers named sessions, messages, channel bindings, and turn
state together with corpus and memory data. Follow `docs/db_restore.md` to
restore and verify a dump.
