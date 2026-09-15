"""Conservative workstation watchdog for Docker, PostgreSQL, and Lyra."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Sequence
from urllib.request import urlopen

from .service import LOOPBACK_URL, SERVICE_NAME


@dataclass(frozen=True)
class HealthSnapshot:
    docker: bool
    database: bool
    lyra: bool
    diagnostics: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return self.docker and self.database and self.lyra


@dataclass(frozen=True)
class WatchdogOutcome:
    disposition: str
    consecutive_failures: int
    action: str | None = None
    recovered: bool | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass
class WatchdogState:
    consecutive_failures: int = 0
    last_attempt_at: str | None = None
    last_action: str | None = None


class WorkstationWatchdog:
    """Observe first; perform at most one bounded recovery after a threshold."""

    def __init__(
        self,
        repo_root: Path,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: int = 300,
        verify_attempts: int = 5,
        verify_interval_seconds: float = 2.0,
        state_path: Path | None = None,
        log_path: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        process_starter: Callable[..., Any] = subprocess.Popen,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = repo_root.resolve()
        self.failure_threshold = max(2, failure_threshold)
        self.cooldown = timedelta(seconds=max(30, cooldown_seconds))
        self.verify_attempts = max(1, min(verify_attempts, 10))
        self.verify_interval_seconds = max(0.0, min(verify_interval_seconds, 30.0))
        self.state_path = state_path or self.root / "data" / "runtime" / "watchdog_state.json"
        self.log_path = log_path or self.root / "logs" / "watchdog.log"
        self.runner = runner
        self.process_starter = process_starter
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def check(self) -> HealthSnapshot:
        diagnostics: list[str] = []
        docker = self._command_ok(["docker", "info", "--format", "{{.ServerVersion}}"])
        if not docker:
            diagnostics.append("Docker Engine is unavailable; open Docker Desktop and inspect its diagnostics.")
        database = False
        if docker:
            result = self._run(
                ["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", "lyra-pgvector"]
            )
            database = result.returncode == 0 and result.stdout.strip().lower() == "healthy"
            if not database:
                diagnostics.append("PostgreSQL container is absent or unhealthy; run docker compose ps.")
        lyra = self._url_ok(LOOPBACK_URL)
        if not lyra:
            diagnostics.append("Lyra health endpoint is unavailable; inspect logs/lyra.log and logs/lyra-service.log.")
        return HealthSnapshot(docker, database, lyra, tuple(diagnostics))

    def tick(self) -> WatchdogOutcome:
        state = self._load_state()
        snapshot = self.check()
        if snapshot.healthy:
            state.consecutive_failures = 0
            self._save_state(state)
            return WatchdogOutcome("healthy", 0)

        state.consecutive_failures += 1
        if state.consecutive_failures < self.failure_threshold:
            self._save_state(state)
            self._log("observed_failure", None, snapshot.diagnostics)
            return WatchdogOutcome(
                "observing", state.consecutive_failures, diagnostics=snapshot.diagnostics
            )

        now = self.clock()
        last_attempt = self._parse_time(state.last_attempt_at)
        if last_attempt and now - last_attempt < self.cooldown:
            self._save_state(state)
            return WatchdogOutcome(
                "cooldown", state.consecutive_failures,
                action=state.last_action, diagnostics=snapshot.diagnostics,
            )

        action = "start_docker" if not snapshot.docker else (
            "start_database" if not snapshot.database else "start_lyra"
        )
        state.last_attempt_at = now.isoformat()
        state.last_action = action
        self._save_state(state)
        attempted, action_detail = self._recover(action)
        recovered = attempted and self._verify(action)
        details = snapshot.diagnostics + ((
            f"Recovery action {action} succeeded."
            if recovered else f"Recovery action {action} did not restore health: {action_detail}"
        ),)
        self._log("recovery_succeeded" if recovered else "recovery_failed", action, details)
        return WatchdogOutcome(
            "recovered" if recovered else "failed",
            state.consecutive_failures,
            action=action,
            recovered=recovered,
            diagnostics=details,
        )

    def _recover(self, action: str) -> tuple[bool, str]:
        try:
            if action == "start_docker":
                executable = self._docker_desktop_path()
                if executable is None:
                    return False, "Docker Desktop executable was not found."
                self.process_starter([str(executable)], **self._detached_options())
                return True, "Docker Desktop start requested."
            if action == "start_database":
                result = self._run(["docker", "compose", "up", "-d", "lyra-db"], timeout=45)
                return result.returncode == 0, self._safe_process_detail(result)
            nssm = shutil.which("nssm") or shutil.which("nssm.exe")
            if nssm and self._command_ok([nssm, "status", SERVICE_NAME]):
                result = self._run([nssm, "restart", SERVICE_NAME], timeout=30)
                return result.returncode == 0, self._safe_process_detail(result)
            python = self.root / "venv" / "Scripts" / "pythonw.exe"
            if not python.is_file():
                return False, f"Runtime executable is missing: {python}"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            service_log = (self.root / "logs" / "lyra-service.log").open("a", encoding="utf-8")
            self.process_starter(
                [str(python), "-m", "lyra.web", "--host", "127.0.0.1", "--port", "8765"],
                cwd=str(self.root), stdout=service_log, stderr=service_log,
                **self._detached_options(),
            )
            service_log.close()
            return True, "Lyra loopback process start requested."
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _verify(self, action: str) -> bool:
        for attempt in range(self.verify_attempts):
            if action == "start_docker":
                healthy = self._command_ok(["docker", "info", "--format", "{{.ServerVersion}}"])
            elif action == "start_database":
                result = self._run(["docker", "inspect", "--format", "{{.State.Health.Status}}", "lyra-pgvector"])
                healthy = result.returncode == 0 and result.stdout.strip().lower() == "healthy"
            else:
                healthy = self._url_ok(LOOPBACK_URL)
            if healthy:
                return True
            if attempt + 1 < self.verify_attempts:
                self.sleeper(self.verify_interval_seconds)
        return False

    def _run(self, command: Sequence[str], *, timeout: int = 8) -> subprocess.CompletedProcess:
        try:
            return self.runner(
                list(command), cwd=self.root, capture_output=True, text=True,
                check=False, timeout=timeout, **self._hidden_run_options(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(command, 1, "", f"{type(exc).__name__}: {exc}")

    def _command_ok(self, command: Sequence[str]) -> bool:
        return self._run(command).returncode == 0

    @staticmethod
    def _url_ok(url: str) -> bool:
        try:
            with urlopen(url, timeout=4) as response:
                return response.status == 200
        except Exception:
            return False

    def _docker_desktop_path(self) -> Path | None:
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "Docker Desktop.exe",
        ]
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def _detached_options() -> dict[str, Any]:
        if os.name != "nt":
            return {}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return {"creationflags": subprocess.CREATE_NO_WINDOW,
                "startupinfo": startupinfo, "close_fds": True}

    @staticmethod
    def _hidden_run_options() -> dict[str, Any]:
        """Keep recurring CLI health checks invisible on Windows."""
        if os.name != "nt":
            return {}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return {"creationflags": subprocess.CREATE_NO_WINDOW,
                "startupinfo": startupinfo}

    @staticmethod
    def _safe_process_detail(result: subprocess.CompletedProcess) -> str:
        detail = (result.stderr or result.stdout or "no process output").strip()
        return detail[-500:]

    def _load_state(self) -> WatchdogState:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return WatchdogState(**payload)
        except (OSError, ValueError, TypeError):
            return WatchdogState()

    def _save_state(self, state: WatchdogState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(state), sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

    def _log(self, event: str, action: str | None, diagnostics: Sequence[str]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path.is_file() and self.log_path.stat().st_size >= 2 * 1024 * 1024:
            rotated = self.log_path.with_suffix(self.log_path.suffix + ".1")
            rotated.unlink(missing_ok=True)
            self.log_path.replace(rotated)
        payload = {
            "timestamp": self.clock().isoformat(),
            "event": event,
            "action": action,
            "diagnostics": list(diagnostics),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        try:
            return datetime.fromisoformat(value) if value else None
        except ValueError:
            return None
