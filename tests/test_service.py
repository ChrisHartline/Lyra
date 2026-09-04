from __future__ import annotations

import importlib.util
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from lyra.config import Settings
from lyra.service import (
    Capability,
    capability_report,
    configure_rotating_logging,
    nssm_install_commands,
    render_capability_report,
    resolve_nssm,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "manage_service", ROOT / "scripts" / "manage_service.py"
)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manager
SPEC.loader.exec_module(manager)


def test_capability_report_uses_explicit_states_without_secret_values():
    case = ROOT / "data" / "test_tmp" / "service" / "doctor"
    settings = Settings(kg_memory_file_path=str(case / "missing" / "kg.jsonl"))
    environment = {
        "GROK_API_KEY": "super-secret-value",
        "LYRA_CONVERSATION_MODEL": "grok-test",
    }

    result = capability_report(
        settings=settings,
        environ=environment,
        repo_root=case,
        database_check=lambda _settings: Capability(
            "database", "unavailable", "PostgreSQL connection failed"
        ),
    )
    rendered = render_capability_report(result)
    states = {item.state for item in result}

    assert states == {"ready", "degraded", "unconfigured", "unavailable"}
    assert "super-secret-value" not in rendered
    assert "[READY] conversation-model" in rendered
    assert "[UNAVAILABLE] database" in rendered


def test_telegram_capability_requires_token_and_both_allowlists():
    ready = capability_report(
        environ={
            "TELEGRAM_BOT_TOKEN": "not-printed",
            "LYRA_TELEGRAM_ALLOWED_USER_IDS": "42",
            "LYRA_TELEGRAM_ALLOWED_CHAT_IDS": "84",
        },
        database_check=lambda _settings: Capability(
            "database", "ready", "PostgreSQL is reachable"
        ),
    )
    partial = capability_report(
        environ={"TELEGRAM_BOT_TOKEN": "not-printed"},
        database_check=lambda _settings: Capability(
            "database", "ready", "PostgreSQL is reachable"
        ),
    )

    assert next(item for item in ready if item.name == "telegram").state == "ready"
    assert next(item for item in partial if item.name == "telegram").state == "degraded"
    assert "not-printed" not in render_capability_report(ready)


def test_rotating_logging_creates_gitignored_bounded_files():
    case = ROOT / "data" / "test_tmp" / "service" / "logging"
    path = configure_rotating_logging(case, max_bytes=80, backup_count=1)
    logger = logging.getLogger("lyra.service.rotation-test")
    for index in range(20):
        logger.info("bounded-log-line-%s", index)
    for handler in logging.getLogger("lyra").handlers:
        handler.flush()

    assert path.exists()
    assert path.with_name("lyra.log.1").exists()
    assert len(list(case.glob("lyra.log*"))) == 2

    root_logger = logging.getLogger("lyra")
    for handler in list(root_logger.handlers):
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == path:
            root_logger.removeHandler(handler)
            handler.close()


def test_nssm_resolution_and_install_plan_are_loopback_only():
    case = ROOT / "data" / "test_tmp" / "service" / "nssm"
    case.mkdir(parents=True, exist_ok=True)
    executable = case / "nssm.exe"
    executable.touch()

    resolved = resolve_nssm(str(executable))
    commands = nssm_install_commands(resolved, ROOT)
    flattened = " ".join(part for command in commands for part in command)

    assert resolved == executable.resolve()
    assert "127.0.0.1" in flattened
    assert "0.0.0.0" not in flattened
    assert "AppRotateBytes" in flattened
    assert str((ROOT / "logs" / "lyra-service.log").resolve()) in flattened


def test_service_install_and_uninstall_are_idempotent(monkeypatch, capsys):
    fake_nssm = ROOT / "data" / "test_tmp" / "service" / "fake-nssm.exe"
    fake_nssm.parent.mkdir(parents=True, exist_ok=True)
    fake_nssm.touch()
    monkeypatch.setattr(
        manager,
        "resolve_nssm",
        lambda _value, **_kwargs: fake_nssm,
    )
    monkeypatch.setattr(manager, "_installed", lambda *_args: True)

    assert manager.main(["install", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert " install Lyra " not in output
    assert " set Lyra AppDirectory " in output

    monkeypatch.setattr(manager, "_installed", lambda *_args: False)
    assert manager.main(["uninstall", "--dry-run"]) == 0
    assert "already absent" in capsys.readouterr().out


def test_install_dry_run_accepts_a_future_explicit_nssm_path(capsys):
    future = ROOT / "data" / "test_tmp" / "service" / "future" / "nssm.exe"

    assert manager.main(["install", "--nssm", str(future), "--dry-run"]) == 0
    output = capsys.readouterr().out

    assert "DRY-RUN:" in output
    assert " install Lyra " in output
    assert "127.0.0.1" in output
