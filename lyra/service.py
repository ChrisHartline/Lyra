"""Workstation-service readiness, logging, and NSSM command planning."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psycopg

from lyra.config import Settings


SERVICE_NAME = "Lyra"
LOOPBACK_URL = "http://127.0.0.1:8765/api/health"
SESSION_TABLES = (
    "chat_sessions",
    "session_messages",
    "session_turns",
    "session_channels",
)
CAPABILITY_STATES = frozenset({"ready", "degraded", "unconfigured", "unavailable"})


@dataclass(frozen=True)
class Capability:
    name: str
    state: str
    detail: str

    def __post_init__(self) -> None:
        if self.state not in CAPABILITY_STATES:
            raise ValueError(f"Unsupported capability state: {self.state}")


def _configured(environ: Mapping[str, str], *names: str) -> bool:
    return any(bool(environ.get(name, "").strip()) for name in names)


def _database_capability(settings: Settings) -> Capability:
    try:
        with psycopg.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            connect_timeout=3,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception:
        return Capability("database", "unavailable", "PostgreSQL connection failed")
    return Capability("database", "ready", "PostgreSQL is reachable")


def capability_report(
    *,
    settings: Settings | None = None,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    database_check: Callable[[Settings], Capability] = _database_capability,
) -> list[Capability]:
    """Return a secret-safe snapshot of Lyra's operational capabilities."""

    active_settings = settings or Settings()
    env = os.environ if environ is None else environ
    root = (repo_root or Path.cwd()).resolve()
    capabilities = [
        Capability(
            "runtime",
            "ready" if sys.version_info >= (3, 10) else "unavailable",
            f"Python {sys.version_info.major}.{sys.version_info.minor}",
        ),
        database_check(active_settings),
    ]

    conversation_ready = _configured(
        env, "LYRA_CONVERSATION_MODEL", "LYRA_MODEL"
    ) and _configured(env, "GROK_API_KEY")
    capabilities.append(
        Capability(
            "conversation-model",
            "ready" if conversation_ready else "unconfigured",
            "model profile and credential are set"
            if conversation_ready
            else "configure the conversation model profile",
        )
    )

    specialist_ready = _configured(
        env, "LYRA_SPECIALIST_MODEL", "ANTHROPIC_MODEL"
    ) and _configured(env, "ANTHROPIC_API_KEY")
    capabilities.append(
        Capability(
            "specialist-model",
            "ready" if specialist_ready else "unconfigured",
            "model profile and credential are set"
            if specialist_ready
            else "configure the specialist model profile",
        )
    )

    notion_ready = _configured(env, "NOTION_TOKEN", "NOTION_API_TOKEN", "NOTION_API_KEY")
    notion_targets = _configured(env, "LYRA_NOTION_TASKS_DATABASE_ID") and _configured(
        env, "LYRA_NOTION_DIGESTS_DATABASE_ID"
    )
    notion_state = "ready" if notion_ready and notion_targets else "unconfigured"
    capabilities.append(
        Capability(
            "notion",
            notion_state,
            "credential and both database targets are set"
            if notion_state == "ready"
            else "Notion is optional or incompletely configured",
        )
    )

    kg_path = Path(active_settings.kg_memory_file_path)
    capabilities.append(
        Capability(
            "knowledge-graph",
            "ready" if kg_path.parent.exists() else "degraded",
            "local store directory is ready"
            if kg_path.parent.exists()
            else "local store directory is missing",
        )
    )

    log_dir = root / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        writable = log_dir.is_dir()
    except OSError:
        writable = False
    capabilities.append(
        Capability(
            "logging",
            "ready" if writable else "unavailable",
            "rotating local log directory is writable"
            if writable
            else "local log directory is not writable",
        )
    )

    nssm = shutil.which("nssm") or shutil.which("nssm.exe")
    capabilities.append(
        Capability(
            "nssm-service",
            "ready" if nssm else "unconfigured",
            "NSSM is discoverable on PATH"
            if nssm
            else "provide --nssm or add NSSM to PATH",
        )
    )
    return capabilities


def render_capability_report(capabilities: Sequence[Capability]) -> str:
    lines = ["Lyra workstation readiness"]
    lines.extend(
        f"[{capability.state.upper()}] {capability.name}: {capability.detail}"
        for capability in capabilities
    )
    return "\n".join(lines)


def configure_rotating_logging(
    log_dir: Path,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    """Attach one rotating UTF-8 file handler to Lyra's root logger."""

    log_dir.mkdir(parents=True, exist_ok=True)
    path = (log_dir / "lyra.log").resolve()
    target = logging.getLogger("lyra")
    for handler in target.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == path:
            return path
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    target.addHandler(handler)
    target.setLevel(logging.INFO)
    return path


def resolve_nssm(explicit: str | None = None, *, require_exists: bool = True) -> Path:
    candidate = explicit or shutil.which("nssm") or shutil.which("nssm.exe")
    if not candidate:
        raise FileNotFoundError("NSSM was not found; pass --nssm or add it to PATH")
    path = Path(candidate).expanduser().resolve()
    if require_exists and not path.is_file():
        raise FileNotFoundError(f"NSSM executable not found: {path}")
    return path


def nssm_install_commands(
    nssm: Path,
    repo_root: Path,
    *,
    service_name: str = SERVICE_NAME,
) -> list[list[str]]:
    root = repo_root.resolve()
    python = root / "venv" / "Scripts" / "python.exe"
    logs = root / "logs"
    service_log = logs / "lyra-service.log"
    return [
        [str(nssm), "install", service_name, str(python), "-m", "lyra.web", "--host", "127.0.0.1", "--port", "8765"],
        [str(nssm), "set", service_name, "AppDirectory", str(root)],
        [str(nssm), "set", service_name, "AppStdout", str(service_log)],
        [str(nssm), "set", service_name, "AppStderr", str(service_log)],
        [str(nssm), "set", service_name, "AppRotateFiles", "1"],
        [str(nssm), "set", service_name, "AppRotateOnline", "1"],
        [str(nssm), "set", service_name, "AppRotateBytes", str(10 * 1024 * 1024)],
        [str(nssm), "set", service_name, "Start", "SERVICE_AUTO_START"],
    ]


def run_commands(commands: Sequence[Sequence[str]]) -> None:
    for command in commands:
        subprocess.run(list(command), check=True)
