from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import db_backup


ROOT = Path(__file__).resolve().parents[1]


def test_full_database_backup_covers_sessions_without_password_in_command(monkeypatch):
    calls = []
    monkeypatch.setattr(
        db_backup,
        "settings",
        SimpleNamespace(
            db_host="127.0.0.1",
            db_port=55432,
            db_user="lyra",
            db_name="lyra",
            db_password="not-in-command",
        ),
    )

    def runner(command, **kwargs):
        calls.append((command, kwargs))

    output = db_backup.create_backup(
        ROOT / "data" / "test_tmp" / "service" / "backups",
        runner=runner,
        pg_dump_path="pg_dump",
    )
    command, kwargs = calls[0]

    assert output.name.startswith("lyra_") and output.suffix == ".sql"
    assert command[0] == "pg_dump"
    assert "--no-password" in command
    assert "not-in-command" not in command
    assert kwargs["env"]["PGPASSWORD"] == "not-in-command"
    assert set(db_backup.SESSION_TABLES) == {
        "chat_sessions",
        "session_messages",
        "session_turns",
        "session_channels",
    }


def test_backup_falls_back_to_the_existing_database_container(monkeypatch):
    calls = []
    monkeypatch.setattr(db_backup.shutil, "which", lambda _name: None)

    def runner(command, **kwargs):
        calls.append((command, kwargs))

    output = db_backup.create_backup(
        ROOT / "data" / "test_tmp" / "service" / "container-backups",
        runner=runner,
    )
    command, kwargs = calls[0]

    assert command[:4] == ["docker", "exec", "lyra-pgvector", "pg_dump"]
    assert kwargs["stdout"].name == str(output)


def test_backup_verification_requires_nonempty_complete_dump():
    target = ROOT / "data" / "test_tmp" / "service" / "verified" / "backup.sql"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(
            f"COPY public.{table} (id) FROM stdin;\n\\.\n"
            for table in db_backup.REQUIRED_BACKUP_TABLES
        ),
        encoding="utf-8",
    )

    size, digest = db_backup.verify_backup_file(target)

    assert size > 0
    assert len(digest) == 64

    target.write_text("COPY public.chat_sessions (id) FROM stdin;\n\\.\n")
    with pytest.raises(RuntimeError, match="incomplete"):
        db_backup.verify_backup_file(target)

    target.write_text("")
    with pytest.raises(RuntimeError, match="empty"):
        db_backup.verify_backup_file(target)
