from __future__ import annotations

import subprocess
import time
from pathlib import Path
import pytest

from tests.db_support import (
    assert_safe_test_database,
    connect_test_db,
    ensure_test_database,
)

ROOT = Path(__file__).resolve().parents[1]


def pytest_sessionstart(session):
    del session
    assert_safe_test_database()


def _db_ready() -> bool:
    try:
        with connect_test_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def ensure_db():
    subprocess.run(["docker", "compose", "up", "-d"], cwd=ROOT, check=True)
    ensure_test_database()
    deadline = time.time() + 120
    while time.time() < deadline:
        if _db_ready():
            break
        time.sleep(2)
    if not _db_ready():
        pytest.fail("Postgres did not become ready in time")
    yield
