# Database Backup and Restore

## Backup
Run:

```powershell
venv\Scripts\python scripts/db_backup.py
```

This writes a timestamped dump to `backups/`.

## Restore
1. Ensure database container is running:

```powershell
docker compose up -d
```

2. Restore from a dump file:

```powershell
$env:PGPASSWORD = $env:LYRA_DB_PASSWORD
psql -h localhost -p 5432 -U lyra -d lyra -f backups/lyra_<timestamp>.sql
```

3. Validate schema objects:

```powershell
psql -h localhost -p 5432 -U lyra -d lyra -c "\dt"
```
