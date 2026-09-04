# Database Backup and Restore

## Backup
Run:

```powershell
.\venv\Scripts\python.exe scripts\db_backup.py
```

This verifies the complete runtime schema, writes a timestamped full-database
dump to the gitignored `backups/` directory, then refuses success unless the
dump is nonempty and contains data sections for every corpus, memory, session,
Away Mode, and Telegram table. It prints the byte count and SHA-256 checksum.
If `pg_dump` is not installed on the Windows host, the helper runs the matching
client inside the existing `lyra-pgvector` container.

After W5.1 validation, run the command once and retain its reported path and
checksum as the new production checkpoint. Keep durable copies outside
`data/test_tmp/`, which is disposable test output.

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

Confirm that the runtime tables are present and open the checkpointed named
conversation after restarting the Lyra service. A restore is not considered
verified until both schema inspection and session recovery succeed.
