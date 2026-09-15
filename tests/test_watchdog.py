from __future__ import annotations

from datetime import datetime, timezone
import subprocess
from pathlib import Path

from lyra.watchdog import HealthSnapshot, WorkstationWatchdog
from scripts import register_watchdog


ROOT = Path(__file__).resolve().parents[1]


class InjectedWatchdog(WorkstationWatchdog):
    def __init__(self, case, snapshots, clock):
        super().__init__(
            ROOT,
            failure_threshold=3,
            cooldown_seconds=300,
            state_path=case / "state.json",
            log_path=case / "watchdog.log",
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        self.snapshots = iter(snapshots)
        self.recoveries = []
        self.verify_result = True

    def check(self):
        return next(self.snapshots)

    def _recover(self, action):
        self.recoveries.append(action)
        return True, "injected action"

    def _verify(self, action):
        return self.verify_result


def _case(name):
    case = ROOT / "data" / "test_tmp" / "watchdog" / name
    case.mkdir(parents=True, exist_ok=True)
    for path in case.iterdir():
        if path.is_file():
            path.unlink()
    return case


def test_transient_failures_do_not_recover_and_threshold_attempts_once():
    case = _case("threshold")
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    failed = HealthSnapshot(True, False, False, ("database unavailable",))
    watchdog = InjectedWatchdog(case, [failed, failed, failed, failed], lambda: now)

    assert watchdog.tick().disposition == "observing"
    assert watchdog.tick().disposition == "observing"
    third = watchdog.tick()
    fourth = watchdog.tick()

    assert third.disposition == "recovered"
    assert third.action == "start_database"
    assert watchdog.recoveries == ["start_database"]
    assert fourth.disposition == "cooldown"
    assert "observed_failure" in (case / "watchdog.log").read_text(encoding="utf-8")


def test_unsuccessful_recovery_has_actionable_diagnostics():
    case = _case("failed")
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    failed = HealthSnapshot(True, True, False, ("health endpoint unavailable",))
    watchdog = InjectedWatchdog(case, [failed, failed, failed], lambda: now)
    watchdog.verify_result = False

    watchdog.tick()
    watchdog.tick()
    outcome = watchdog.tick()

    assert outcome.disposition == "failed"
    assert outcome.action == "start_lyra"
    assert any("did not restore health" in detail for detail in outcome.diagnostics)
    log = (case / "watchdog.log").read_text(encoding="utf-8")
    assert "recovery_failed" in log
    assert "health endpoint unavailable" in log


def test_healthy_check_resets_failure_counter():
    case = _case("reset")
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    failed = HealthSnapshot(False, False, False)
    healthy = HealthSnapshot(True, True, True)
    watchdog = InjectedWatchdog(case, [failed, healthy, failed], lambda: now)

    assert watchdog.tick().consecutive_failures == 1
    assert watchdog.tick().consecutive_failures == 0
    assert watchdog.tick().consecutive_failures == 1
    assert watchdog.recoveries == []


def test_startup_registration_is_user_level_hidden_watchdog_only():
    environment = {"APPDATA": str(ROOT / "data" / "test_tmp" / "watchdog" / "appdata")}
    target = register_watchdog.launcher_path(environment)
    content = register_watchdog.launcher_content(ROOT)

    assert target.name == "LyraWatchdog.vbs"
    assert "Start Menu" in str(target)
    assert "pythonw.exe" in content
    assert "watchdog.py" in content
    assert "--monitor" in content
    assert 'shell.Run """' in content
    assert ", 0, False" in content
    assert not any(term in content.lower() for term in ("funnel", "volume rm", "wsl --unregister", "update"))


def test_startup_registration_writes_only_the_user_startup_launcher():
    environment = {"APPDATA": str(_case("registration") / "appdata")}

    target = register_watchdog.install(ROOT, environ=environment)

    assert target == register_watchdog.launcher_path(environment)
    assert target.read_text(encoding="utf-8").splitlines() == register_watchdog.launcher_content(ROOT).splitlines()


def test_start_now_registration_uses_non_conflicting_hidden_flags():
    options = register_watchdog._hidden_popen_options()
    if __import__("os").name == "nt":
        assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
        assert not options["creationflags"] & subprocess.DETACHED_PROCESS
        assert options["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_start_now_registration_disconnects_monitor_standard_handles(monkeypatch):
    calls = []
    monkeypatch.setattr(register_watchdog.subprocess, "Popen",
                        lambda command, **options: calls.append((command, options)))
    root = ROOT
    environment = {"APPDATA": str(_case("registration_handles") / "appdata")}

    register_watchdog.install(root, environ=environment, start_now=True)

    options = calls[0][1]
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stdout"] is subprocess.DEVNULL
    assert options["stderr"] is subprocess.DEVNULL


def test_compose_has_restart_policy_and_bounded_healthcheck():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "restart: unless-stopped" in compose
    assert "pg_isready" in compose
    assert "timeout: 3s" in compose
    assert "retries: 20" in compose
    assert "start_period: 10s" in compose


def test_watchdog_has_no_browser_process_control():
    source = (ROOT / "lyra" / "watchdog.py").read_text(encoding="utf-8").lower()

    assert "chrome.exe" not in source
    assert "msedge.exe" not in source
    assert "taskkill" not in source


def test_watchdog_health_commands_are_hidden_on_windows():
    case = _case("hidden_commands")
    calls = []

    def runner(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, "ok", "")

    watchdog = WorkstationWatchdog(
        ROOT,
        runner=runner,
        state_path=case / "state.json",
        log_path=case / "watchdog.log",
    )
    watchdog._run(["docker", "info"])

    expected = subprocess.CREATE_NO_WINDOW if __import__("os").name == "nt" else None
    assert calls[0][1].get("creationflags") == expected
    if expected is not None:
        assert calls[0][1]["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_lyra_recovery_uses_pythonw_and_non_conflicting_hidden_flags():
    case = _case("hidden_recovery")
    calls = []

    def starter(command, **options):
        calls.append((command, options))
        return object()

    watchdog = WorkstationWatchdog(
        ROOT,
        process_starter=starter,
        state_path=case / "state.json",
        log_path=case / "watchdog.log",
    )
    recovered, _detail = watchdog._recover("start_lyra")

    assert recovered is True
    assert calls[0][0][0].endswith("pythonw.exe")
    if __import__("os").name == "nt":
        flags = calls[0][1]["creationflags"]
        assert flags == subprocess.CREATE_NO_WINDOW
        assert not flags & subprocess.DETACHED_PROCESS
        assert calls[0][1]["startupinfo"].wShowWindow == subprocess.SW_HIDE
