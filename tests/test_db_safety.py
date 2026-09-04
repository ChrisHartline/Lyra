from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests import db_support


def test_database_guard_requires_test_suffix(monkeypatch):
    monkeypatch.setitem(db_support.TEST_DB, "dbname", "lyra_scratch")

    with pytest.raises(RuntimeError, match=r"\*_test"):
        db_support.assert_safe_test_database()


def test_database_guard_rejects_runtime_database(monkeypatch):
    monkeypatch.setattr(db_support, "settings", SimpleNamespace(db_name="lyra_test"))

    with pytest.raises(RuntimeError, match="runtime database"):
        db_support.assert_safe_test_database()
