# Database Backup and Restore

## Backup
Run:

```powershell
.\venv\Scripts\python.exe scripts\db_backup.py
```

This verifies the session schema, then writes a timestamped full-database dump
to `backups/`. The dump includes `chat_sessions`, `session_messages`,
`session_turns`, and `session_channels`. If `pg_dump` is not installed on the
Windows host, the helper runs the matching client inside the existing
`lyra-pgvector` container.

## Restore
1. Ensure database container is running:

```powershell
docker compose up -d
```

2. Restore from a dump file:

```powershell
$env:PGPASSWORD = $env:LYRA_DB_PASSWORD
psql -h 127.0.0.1 -p 55432 -U lyra -d lyra -f backups/lyra_<timestamp>.sql
```

3. Validate schema objects:

```powershell
psql -h 127.0.0.1 -p 55432 -U lyra -d lyra -c "\dt"
```

Confirm that the four session tables listed above are present and open a named
conversation after restarting the Lyra service. A restore is not considered
verified until both schema inspection and session recovery succeed.
