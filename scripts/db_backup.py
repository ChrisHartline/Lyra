from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import psycopg

from lyra.config import settings
from lyra.service import SESSION_TABLES


REQUIRED_BACKUP_TABLES = (
    "sources",
    "chunks",
    "memories",
    "memory_review_audit",
    "memory_policy",
    *SESSION_TABLES,
    "memory_control_intents",
    "channel_preferences",
    "away_policy",
    "notification_events",
    "ritual_policy",
    "ritual_runs",
    "research_garden_policy",
    "research_garden_topic_mutes",
    "research_garden_suggestions",
    "shared_journal_entries",
    "shared_journal_private_sessions",
    "shared_journal_audit",
    "commitment_candidates",
    "commitments",
    "stuck_interactions",
    "telegram_updates",
    "telegram_inbox",
)


def verify_required_tables() -> None:
    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        connect_timeout=5,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename = ANY(%s)",
                (list(REQUIRED_BACKUP_TABLES),),
            )
            found = {row[0] for row in cursor.fetchall()}
    missing = set(REQUIRED_BACKUP_TABLES) - found
    if missing:
        raise RuntimeError(
            "Database backup coverage is incomplete; missing tables: "
            + ", ".join(sorted(missing))
        )


def verify_backup_file(path: Path) -> tuple[int, str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("Database backup is missing or empty")
    digest = hashlib.sha256()
    markers = {
        table: f"COPY public.{table} ".encode() for table in REQUIRED_BACKUP_TABLES
    }
    found: set[str] = set()
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            for table, marker in markers.items():
                if line.startswith(marker):
                    found.add(table)
    missing = set(REQUIRED_BACKUP_TABLES) - found
    if missing:
        raise RuntimeError(
            "Backup dump is incomplete; missing table data sections: "
            + ", ".join(sorted(missing))
        )
    return path.stat().st_size, digest.hexdigest()


def create_backup(
    backup_dir: Path,
    *,
    runner=subprocess.run,
    pg_dump_path: str | None = None,
) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = backup_dir / f"lyra_{ts}.sql"
    environment = dict(os.environ)
    environment["PGPASSWORD"] = settings.db_password
    executable = pg_dump_path or shutil.which("pg_dump") or shutil.which("pg_dump.exe")
    if executable:
        runner(
            [
                executable,
                "-h",
                settings.db_host,
                "-p",
                str(settings.db_port),
                "-U",
                settings.db_user,
                "-d",
                settings.db_name,
                "--no-password",
                "-f",
                str(out),
            ],
            env=environment,
            check=True,
        )
    else:
        command = [
            "docker",
            "exec",
            "lyra-pgvector",
            "pg_dump",
            "-U",
            settings.db_user,
            "-d",
            settings.db_name,
            "--no-password",
        ]
        with out.open("wb") as stream:
            runner(command, stdout=stream, check=True)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the complete Lyra database")
    parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    args = parser.parse_args(argv)
    verify_required_tables()
    out = create_backup(args.output_dir)
    size, sha256 = verify_backup_file(out)
    print(f"Backup written: {out}")
    print(f"Verified bytes: {size}")
    print(f"SHA-256: {sha256}")
    print("Tables covered: " + ", ".join(REQUIRED_BACKUP_TABLES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
