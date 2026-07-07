from __future__ import annotations

from pathlib import Path
import psycopg
from .config import settings


def dsn() -> str:
    return (
        f"host={settings.db_host} port={settings.db_port} dbname={settings.db_name} "
        f"user={settings.db_user} password={settings.db_password}"
    )


def connect():
    return psycopg.connect(dsn())


def apply_schema(schema_path: str | Path = "db/schema.sql") -> None:
    sql = Path(schema_path).read_text(encoding="utf-8")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
