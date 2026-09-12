from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from lyra.sessions import SessionService
from lyra.stuck import StuckModeService
from tests.db_support import connect_test_db


NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)


def _conn():
    return connect_test_db()


def _reset() -> tuple[StuckModeService, SessionService]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cur.execute(
                "TRUNCATE stuck_interactions, session_messages, session_turns, "
                "session_channels, chat_sessions RESTART IDENTITY CASCADE"
            )
        conn.commit()
    return StuckModeService(_conn), SessionService(_conn)


def _message(
    service: StuckModeService,
    sessions: SessionService,
    session_id: str,
    text: str,
    *,
    ledger: str = "biography",
    now: datetime = NOW,
):
    message = sessions.append_message(session_id, "user", text)
    return service.observe_message(
        session_id=session_id,
        message_id=message["message_id"],
        text=text,
        ledger=ledger,
        now=now,
    )


def test_explicit_entry_selection_active_guidance_and_resolution(ensure_db):
    stuck, sessions = _reset()
    session = sessions.create_session("Explicit stuck")
    session_id = session["session_id"]

    offered = _message(stuck, sessions, session_id, "I'm stuck.")
    activated = _message(
        stuck,
        sessions,
        session_id,
        "Technical diagnosis, deep please.",
        now=NOW + timedelta(minutes=1),
    )
    active = _message(
        stuck,
        sessions,
        session_id,
        "Here is the failure sequence.",
        now=NOW + timedelta(minutes=2),
    )
    resolved = _message(
        stuck,
        sessions,
        session_id,
        "Got it.",
        now=NOW + timedelta(minutes=3),
    )

    assert offered.action == "offered"
    assert offered.interaction["trigger_kind"] == "explicit"
    assert "choose technical diagnosis" in offered.instruction
    assert activated.action == "activated"
    assert activated.interaction["selected_mode"] == "technical_diagnosis"
    assert activated.interaction["depth"] == "deep"
    assert active.action == "active"
    assert "methodically" in active.instruction
    assert resolved.action == "resolved"
    assert stuck.get_state(session_id)["status"] == "resolved"


def test_observational_dismissal_cooldown_and_explicit_override(ensure_db):
    stuck, sessions = _reset()
    session_id = sessions.create_session("Cooldown")["session_id"]

    offered = _message(
        stuck, sessions, session_id, "This still isn't working.", now=NOW
    )
    dismissed = _message(
        stuck, sessions, session_id, "Not now.", now=NOW + timedelta(minutes=1)
    )
    suppressed = _message(
        stuck,
        sessions,
        session_id,
        "I can't figure this out.",
        now=NOW + timedelta(hours=2),
    )
    explicit = _message(
        stuck,
        sessions,
        session_id,
        "I’m stuck.",
        now=NOW + timedelta(hours=3),
    )

    assert offered.interaction["trigger_kind"] == "observational"
    assert dismissed.action == "dismissed"
    assert dismissed.interaction["cooldown_until"] == NOW + timedelta(
        minutes=1, hours=24
    )
    assert suppressed.action == "suppressed"
    assert suppressed.instruction is None
    assert explicit.action == "offered"
    assert explicit.interaction["trigger_kind"] == "explicit"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), array_agg(status ORDER BY created_at) "
                "FROM stuck_interactions WHERE session_id = %s",
                (session_id,),
            )
            count, statuses = cur.fetchone()
    assert count == 2
    assert statuses == ["dismissed", "offered"]


def test_story_technical_shift_preserves_register_but_story_stress_is_ignored(ensure_db):
    stuck, sessions = _reset()
    technical_id = sessions.create_session("Story technical")["session_id"]
    stress_id = sessions.create_session("Story stress")["session_id"]

    technical = _message(
        stuck,
        sessions,
        technical_id,
        "I'm stuck debugging the phase regulator. Go deep.",
        ledger="story",
    )
    stress = _message(
        stuck,
        sessions,
        stress_id,
        "I'm overwhelmed by the captain's orders.",
        ledger="campaign",
    )

    assert technical.action == "activated"
    assert technical.interaction["selected_mode"] == "technical_diagnosis"
    assert "Preserve the current fictional scene" in technical.instruction
    assert stress.action == "none"
    assert stuck.get_state(stress_id) is None


def test_stress_offer_does_not_diagnose_or_store_trigger_text(ensure_db):
    stuck, sessions = _reset()
    session_id = sessions.create_session("Stress privacy")["session_id"]

    result = _message(stuck, sessions, session_id, "I'm overwhelmed.")
    third_party = _message(
        stuck,
        sessions,
        sessions.create_session("Third party")["session_id"],
        "She is overwhelmed and cannot decide what to do.",
    )

    assert result.action == "offered"
    assert result.interaction["suggested_mode"] == "stress_check_in"
    assert "Do not diagnose" in result.instruction
    assert third_party.action == "none"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'stuck_interactions'"
            )
            columns = {row[0] for row in cur.fetchall()}
    assert not columns.intersection({"text", "content", "summary", "inference"})


def test_companionship_depth_change_and_immediate_dismiss(ensure_db):
    stuck, sessions = _reset()
    session_id = sessions.create_session("Companionship")["session_id"]

    _message(stuck, sessions, session_id, "I'm stuck.")
    activated = _message(
        stuck,
        sessions,
        session_id,
        "Just stay with me, light please.",
        now=NOW + timedelta(minutes=1),
    )
    deepened = _message(
        stuck,
        sessions,
        session_id,
        "Let's go deep.",
        now=NOW + timedelta(minutes=2),
    )
    dismissed = _message(
        stuck,
        sessions,
        session_id,
        "No thanks.",
        now=NOW + timedelta(minutes=3),
    )

    assert activated.interaction["selected_mode"] == "companionship"
    assert activated.interaction["depth"] == "light"
    assert deepened.interaction["depth"] == "deep"
    assert dismissed.action == "dismissed"
    assert dismissed.interaction["status"] == "dismissed"
