from __future__ import annotations

from datetime import datetime, timezone
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


def test_compose_has_restart_policy_and_bounded_healthcheck():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "restart: unless-stopped" in compose
    assert "pg_isready" in compose
    assert "timeout: 3s" in compose
    assert "retries: 20" in compose
    assert "start_period: 10s" in compose
