from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
import pytest
import psycopg

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = {
    "host": "127.0.0.1",
    "port": 55432,
    "dbname": "lyra",
    "user": "lyra",
    "password": "lyra",
}


def _db_ready() -> bool:
    try:
        with psycopg.connect(
            **TEST_DB,
            connect_timeout=3,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def ensure_db():
    subprocess.run(["docker", "compose", "up", "-d"], cwd=ROOT, check=True)
    deadline = time.time() + 120
    while time.time() < deadline:
        if _db_ready():
            break
        time.sleep(2)
    if not _db_ready():
        pytest.fail("Postgres did not become ready in time")
    yield
