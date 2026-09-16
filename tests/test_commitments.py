from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from lyra.away import AwayModeService
from lyra.commitments import CommitmentService
from lyra.sessions import SessionService
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


def _reset() -> tuple[CommitmentService, SessionService, AwayModeService]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cur.execute(
                "TRUNCATE commitments, commitment_candidates, notification_events, "
                "channel_preferences, away_policy, session_messages, session_turns, "
                "session_channels, chat_sessions RESTART IDENTITY CASCADE"
            )
        conn.commit()
    return CommitmentService(_conn), SessionService(_conn), AwayModeService(_conn)


def _offer(
    radar: CommitmentService,
    sessions: SessionService,
    text: str,
    *,
    name: str = "Commitment test",
    now: datetime | None = None,
):
    session = sessions.create_session(name)
    message = sessions.append_message(session["session_id"], "user", text)
    result = radar.observe_message(
        session_id=session["session_id"],
        message_id=message["message_id"],
        text=text,
        now=now or datetime.now(UTC),
    )
    return session, result


def test_offer_requires_conversational_confirmation_before_commitment(ensure_db):
    radar, sessions, _away = _reset()
    session, result = _offer(
        radar,
        sessions,
        "I need to decide which model to use by Friday.",
        now=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
    )

    assert result.action == "offered"
    assert result.offer["kind"] == "deadline"
    assert result.offer["source"]["session_id"] == session["session_id"]
    assert "Ask Christopher" in result.instruction
    assert radar.list_commitments() == []

    confirmation = sessions.append_message(session["session_id"], "user", "Yes, track it.")
    confirmed = radar.observe_message(
        session_id=session["session_id"],
        message_id=confirmation["message_id"],
        text="Yes, track it.",
        now=datetime(2026, 9, 9, 15, 1, tzinfo=UTC),
    )

    assert confirmed.action == "confirmed"
    assert confirmed.commitment["status"] == "active"
    assert confirmed.commitment["source"]["message_id"] == result.offer["source"]["message_id"]
    assert radar.list_offers(status="confirmed")[0]["offer_id"] == result.offer["offer_id"]


def test_decline_story_campaign_and_sensitive_third_party_never_create_commitments(ensure_db):
    radar, sessions, _away = _reset()
    session, offered = _offer(radar, sessions, "I'll finish the report tomorrow.")
    rejection = sessions.append_message(session["session_id"], "user", "No thanks.")
    declined = radar.observe_message(
        session_id=session["session_id"],
        message_id=rejection["message_id"],
        text="No thanks.",
    )

    assert offered.action == "offered"
    assert declined.action == "dismissed"
    assert radar.list_commitments() == []

    for index, (text, ledger) in enumerate(
        (
            ("I'll repair the SilentDrift by Friday.", "story"),
            ("I will roll initiative in the campaign.", "biography"),
            ("I need to call my colleague at 555-123-4567.", "biography"),
        )
    ):
        other = sessions.create_session(f"Excluded {index}")
        message = sessions.append_message(other["session_id"], "user", text)
        result = radar.observe_message(
            session_id=other["session_id"],
            message_id=message["message_id"],
            text=text,
            ledger=ledger,
        )
        assert result.action == "none"
    assert radar.list_offers(status="offered") == []


def test_states_and_reminders_obey_away_mode(ensure_db):
    radar, sessions, away = _reset()
    session, offer = _offer(
        radar,
        sessions,
        "I will submit the draft by 2026-09-10.",
        now=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
    )
    commitment = radar.confirm_offer(offer.offer["offer_id"])

    away.set_policy(
        enabled=True,
        quiet_start=time(22, 0),
        quiet_end=time(7, 0),
        timezone="America/Chicago",
        daily_notification_budget=5,
    )
    planned = radar.plan_due_reminders(
        away=away,
        channel="telegram",
        now=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
    )
    assert planned[0]["disposition"] == "batch"
    assert planned[0]["reason"] == "quiet_hours"
    assert radar.plan_due_reminders(
        away=away,
        channel="telegram",
        now=datetime(2026, 9, 10, 4, 1, tzinfo=UTC),
    ) == []

    snoozed = radar.transition(
        commitment["commitment_id"],
        "snoozed",
        snoozed_until=datetime.now(UTC) + timedelta(days=2),
    )
    assert snoozed["status"] == "snoozed"
    assert radar.plan_due_reminders(away=away, channel="telegram") == []
    assert radar.transition(commitment["commitment_id"], "active")["status"] == "active"
    assert radar.transition(commitment["commitment_id"], "done")["status"] == "done"
    assert radar.transition(commitment["commitment_id"], "dropped")["status"] == "dropped"

    with pytest.raises(ValueError, match="wake time"):
        radar.transition(commitment["commitment_id"], "snoozed")


def test_dashboard_sources_must_be_approved_and_retain_url(ensure_db):
    radar, _sessions, _away = _reset()
    with pytest.raises(ValueError, match="approved"):
        radar.offer_dashboard_item(
            text="I need to review the architecture tomorrow.",
            source_url="https://notion.example/item",
            approved=False,
        )

    offer = radar.offer_dashboard_item(
        text="I need to review the architecture tomorrow.",
        source_url="https://notion.example/item",
        approved=True,
    )
    commitment = radar.confirm_offer(offer["offer_id"])

    assert commitment["source"] == {
        "type": "dashboard",
        "session_id": None,
        "message_id": None,
        "url": "https://notion.example/item",
    }


def test_stale_offer_expires_instead_of_accepting_late_confirmation(ensure_db):
    radar, sessions, _away = _reset()
    session, old = _offer(
        radar,
        sessions,
        "I need to review the deployment plan.",
        now=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    reply = sessions.append_message(session["session_id"], "user", "Yes, track it.")
    result = radar.observe_message(
        session_id=session["session_id"],
        message_id=reply["message_id"],
        text="Yes, track it.",
        now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )

    assert result.action == "none"
    assert radar.list_offers(status="expired")[0]["offer_id"] == old.offer["offer_id"]
    assert radar.list_commitments() == []
