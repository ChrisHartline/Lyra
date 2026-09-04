from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path

from lyra.away import AwayModeService
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


def _reset() -> AwayModeService:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cur.execute(
                "TRUNCATE notification_events, channel_preferences, away_policy "
                "RESTART IDENTITY"
            )
        conn.commit()
    return AwayModeService(_conn)


def test_channel_presentation_is_independent_of_persona_and_history(ensure_db):
    service = _reset()

    assert service.get_channel_preference("telegram") == {
        "channel": "telegram",
        "presentation_mode": "standard",
    }
    assert service.presentation_instruction("telegram") is None

    service.set_channel_preference("telegram", "concise")
    instruction = service.presentation_instruction("telegram")

    assert instruction is not None
    assert "concise" in instruction
    assert "identity" in instruction
    assert service.get_channel_preference("web")["presentation_mode"] == "standard"


def test_quiet_hours_batch_budget_suppresses_and_urgent_bypasses(ensure_db):
    service = _reset()
    service.set_policy(
        enabled=True,
        quiet_start=time(22, 0),
        quiet_end=time(7, 0),
        timezone="America/Chicago",
        daily_notification_budget=1,
    )

    quiet = service.plan_notification(
        channel="telegram",
        category="digest",
        content="Evening digest",
        now=datetime(2026, 9, 5, 4, 0, tzinfo=UTC),
    )
    urgent = service.plan_notification(
        channel="telegram",
        category="security",
        content="Credential warning",
        now=datetime(2026, 9, 5, 4, 1, tzinfo=UTC),
    )
    first = service.plan_notification(
        channel="telegram",
        category="commitment",
        content="First reminder",
        now=datetime(2026, 9, 4, 17, 0, tzinfo=UTC),
    )
    exhausted = service.plan_notification(
        channel="telegram",
        category="research",
        content="Second reminder",
        now=datetime(2026, 9, 4, 18, 0, tzinfo=UTC),
    )

    assert (quiet.disposition, quiet.reason) == ("batch", "quiet_hours")
    assert (urgent.disposition, urgent.reason) == ("send", "urgent_category")
    assert (first.disposition, first.reason) == ("send", "within_budget")
    assert (exhausted.disposition, exhausted.reason) == (
        "suppress",
        "daily_budget_exhausted",
    )
    assert [item["content"] for item in service.list_batched()] == ["Evening digest"]


def test_policy_validation_and_away_mode_concise_override(ensure_db):
    service = _reset()
    policy = service.set_policy(
        enabled=True,
        quiet_start=None,
        quiet_end=None,
        timezone="America/Chicago",
        daily_notification_budget=0,
    )

    assert policy.enabled is True
    assert service.presentation_instruction("web") is not None

    for kwargs in (
        {
            "enabled": True,
            "quiet_start": time(22),
            "quiet_end": None,
            "timezone": "America/Chicago",
            "daily_notification_budget": 1,
        },
        {
            "enabled": True,
            "quiet_start": None,
            "quiet_end": None,
            "timezone": "Not/A_Real_Zone",
            "daily_notification_budget": 1,
        },
    ):
        try:
            service.set_policy(**kwargs)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("Invalid Away Mode policy was accepted")
