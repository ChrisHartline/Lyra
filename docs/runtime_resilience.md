# Local Runtime Resilience (W6.4)

Lyra remains a workstation-hosted, loopback-bound system. Recovery automation
may start an existing component; it is not an updater, repair utility, backup
restorer, or deployment system.

## Recovery order and limits

The watchdog checks, in dependency order:

1. Docker Engine (`docker info`).
2. The `lyra-pgvector` container's Docker health status.
3. Lyra's loopback `/api/health` endpoint.

One failed check is observation, not an incident. The default policy requires
three consecutive failed checks before one recovery attempt and then waits five
minutes before another attempt. Recovery starts only the first failed dependency:
Docker Desktop, `docker compose up -d lyra-db`, or the existing Lyra runtime.
Each attempt is bounded and written to `logs/watchdog.log`; counters/timestamps
live in gitignored `data/runtime/watchdog_state.json`.

The watchdog never installs updates, resets Docker or WSL, deletes/recreates a
volume, restores a backup, edits `.env`, changes Tailscale Serve, enables Funnel,
or changes Lyra's `127.0.0.1:8765` binding. Failed recovery logs point to Docker
diagnostics, `docker compose ps`, and Lyra's local logs rather than escalating to
destructive repair.

## Operator commands

Run a single non-destructive check:

```powershell
.\venv\Scripts\python.exe scripts\watchdog.py
```

Preview per-user after-logon registration:

```powershell
.\venv\Scripts\python.exe scripts\register_watchdog.py install --start-now --dry-run
```

After explicit opt-in, remove `--dry-run`. Inspect or remove it with:

```powershell
.\venv\Scripts\python.exe scripts\register_watchdog.py status
.\venv\Scripts\python.exe scripts\register_watchdog.py uninstall
```

Registration creates a hidden `LyraWatchdog.vbs` launcher in Christopher's
per-user Startup folder; it requires no administrator privileges. Docker Desktop's own
“Start Docker Desktop when you sign in” setting is separately enabled in Docker
Desktop under Settings → General; the watchdog does not modify it.

## Deployment-readiness boundary

This gate improves recovery while the workstation is powered on and Christopher
is signed in. It does not make the workstation an always-on service: Windows
sleep, logout, power/network loss, Docker Desktop account state, and workstation
maintenance remain availability boundaries.

A later always-on or hybrid deployment should begin with an ADR and explicit
privacy/cost/authentication decisions. The minimum readiness package is a
containerized Lyra application, managed PostgreSQL or a colocated protected
database, encrypted backup/restore drills, authenticated private ingress,
secret management, monitoring/alerting, and a tested rollback. Until then,
Tailscale Serve plus this watchdog is local recovery—not cloud production.
