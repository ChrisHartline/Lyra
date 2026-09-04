"""Fail-closed PostgreSQL configuration for destructive integration tests."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql

from lyra.config import settings


TEST_DATABASE_NAME = "lyra_test"
TEST_DB: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 55432,
    "dbname": TEST_DATABASE_NAME,
    "user": "lyra",
    "password": "lyra",
}


def assert_safe_test_database() -> None:
    database = str(TEST_DB["dbname"]).strip().lower()
    runtime_database = settings.db_name.strip().lower()
    if not database.endswith("_test"):
        raise RuntimeError("Destructive integration tests require a *_test database")
    if database == runtime_database:
        raise RuntimeError("Integration tests refuse to target Lyra's runtime database")


def ensure_test_database() -> None:
    assert_safe_test_database()
    admin = dict(TEST_DB)
    admin["dbname"] = settings.db_name
    with psycopg.connect(**admin, connect_timeout=3, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (TEST_DATABASE_NAME,),
            )
            if not cur.fetchone():
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(TEST_DATABASE_NAME)
                    )
                )


def connect_test_db() -> psycopg.Connection:
    assert_safe_test_database()
    return psycopg.connect(**TEST_DB, connect_timeout=3)
