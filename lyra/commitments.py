"""Confirmation-gated commitment detection, lifecycle, and reminders."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import psycopg

from lyra.away import AwayModeService
from lyra.db import connect
from lyra.memory import validate_persistable_text


KINDS = frozenset({"promise", "deadline", "follow_up", "unresolved_decision", "task"})
STATES = frozenset({"active", "done", "snoozed", "dropped"})
OFFER_STATES = frozenset({"offered", "confirmed", "dismissed", "expired"})
VISIBILITY_SCOPES = frozenset({"general", "professional", "private_shared"})

_INTENT = re.compile(
    r"\b(?:i['’]?ll|i\s+will|i\s+need\s+to|i\s+have\s+to|i\s+should|"
    r"remind\s+me\s+to|i\s+promised\s+to|i\s+must)\b",
    re.IGNORECASE,
)
_NON_BIOGRAPHY = re.compile(
    r"\b(?:in\s+the\s+campaign|my\s+character|roll\s+initiative|d20|"
    r"the\s+silentdrift|aboard\s+silentdrift|phase\s+regulator|"
    r"entanglement\s+coil|(?:repair|fix)\s+the\s+ship|story\s+canon|"
    r"campaign\s+combat)\b",
    re.IGNORECASE,
)
_ISO_DUE = re.compile(r"\b(?:by|on)\s+(20\d{2}-\d{2}-\d{2})\b", re.IGNORECASE)
_WEEKDAY_DUE = re.compile(
    r"\b(?:by|on)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_CONFIRM_WORDS = frozenset(
    {"yes", "yes please", "track it", "add it", "please do", "do that", "confirm it"}
)
_REJECT_WORDS = frozenset(
    {"no", "no thanks", "do not track it", "don't track it", "skip it", "dismiss it"}
)


def _normalized_reply(text: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()


def _explicit_confirmation(text: str) -> bool:
    reply = _normalized_reply(text)
    if reply in _CONFIRM_WORDS:
        return True
    return reply.startswith("yes ") and any(
        word in reply for word in ("track", "add", "remind", "please", "do")
    )


def _explicit_rejection(text: str) -> bool:
    return _normalized_reply(text) in _REJECT_WORDS


def _kind(text: str, due_at: datetime | None) -> str:
    lowered = text.lower()
    if due_at is not None or any(word in lowered for word in ("deadline", "due ")):
        return "deadline"
    if any(phrase in lowered for phrase in ("follow up", "check back", "email ", "call ", "send ")):
        return "follow_up"
    if any(phrase in lowered for phrase in ("decide", "choose", "figure out")):
        return "unresolved_decision"
    if re.search(r"\b(?:i['’]?ll|i\s+will|i\s+promised\s+to)\b", lowered):
        return "promise"
    return "task"


def _due_at(text: str, *, now: datetime, timezone: str) -> datetime | None:
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    iso = _ISO_DUE.search(text)
    if iso:
        due_date = datetime.strptime(iso.group(1), "%Y-%m-%d").date()
        return datetime.combine(due_date, time(17, 0), tzinfo=zone).astimezone(UTC)
    if re.search(r"\b(?:by\s+)?tomorrow\b", text, re.IGNORECASE):
        return datetime.combine(
            local.date() + timedelta(days=1), time(9, 0), tzinfo=zone
        ).astimezone(UTC)
    weekday = _WEEKDAY_DUE.search(text)
    if weekday:
        target = (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ).index(weekday.group(1).lower())
        days = (target - local.weekday()) % 7 or 7
        return datetime.combine(
            local.date() + timedelta(days=days), time(17, 0), tzinfo=zone
        ).astimezone(UTC)
    return None


def _offer(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "offer_id": str(row[0]),
        "summary": row[1],
        "kind": row[2],
        "due_at": row[3],
        "visibility_scope": row[4],
        "source": {
            "type": row[5],
            "session_id": str(row[6]) if row[6] else None,
            "message_id": int(row[7]) if row[7] is not None else None,
            "url": row[8],
            "approved": bool(row[9]),
        },
        "detection_reason": row[10],
        "status": row[11],
        "created_at": row[12],
        "resolved_at": row[13],
    }


def _commitment(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "commitment_id": str(row[0]),
        "offer_id": str(row[1]),
        "summary": row[2],
        "kind": row[3],
        "status": row[4],
        "due_at": row[5],
        "snoozed_until": row[6],
        "last_reminded_at": row[7],
        "confirmed_at": row[8],
        "updated_at": row[9],
        "visibility_scope": row[10],
        "source": {
            "type": row[11],
            "session_id": str(row[12]) if row[12] else None,
            "message_id": int(row[13]) if row[13] is not None else None,
            "url": row[14],
        },
    }


@dataclass(frozen=True)
class RadarObservation:
    action: str
    instruction: str | None = None
    offer: dict[str, Any] | None = None
    commitment: dict[str, Any] | None = None


@dataclass
class CommitmentService:
    connection_factory: Callable[[], psycopg.Connection] = connect
    timezone: str = "America/Chicago"
    max_offer_age: timedelta = timedelta(days=7)

    def _candidate_summary(
        self, text: str, *, ledger: str, now: datetime
    ) -> tuple[str, str, datetime | None, str] | None:
        if ledger != "biography" or _NON_BIOGRAPHY.search(text):
            return None
        try:
            summary = validate_persistable_text(text)
        except ValueError:
            return None
        if not _INTENT.search(summary):
            return None
        summary = summary[:500].rstrip()
        due = _due_at(summary, now=now, timezone=self.timezone)
        kind = _kind(summary, due)
        reason = {
            "deadline": "First-person intent with a possible deadline",
            "follow_up": "First-person follow-up intent",
            "unresolved_decision": "First-person unresolved decision",
            "promise": "First-person promise or stated intention",
            "task": "First-person task intention",
        }[kind]
        return summary, kind, due, reason

    def list_offers(
        self, *, status: str = "offered", session_id: str | None = None
    ) -> list[dict[str, Any]]:
        if status not in OFFER_STATES:
            raise ValueError("Unknown commitment offer status")
        session_filter = (
            "AND source_session_id = %s"
            if session_id
            else "AND visibility_scope <> 'private_shared'"
        )
        params: tuple[Any, ...] = (status, session_id) if session_id else (status,)
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, summary, kind, due_at, visibility_scope, source_type,
                           source_session_id, source_message_id, source_url,
                           source_approved, detection_reason, status, created_at,
                           resolved_at
                    FROM commitment_candidates
                    WHERE status = %s {session_filter}
                    ORDER BY created_at DESC, id DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [_offer(row) for row in rows]

    def offer_session_message(
        self,
        *,
        session_id: str,
        message_id: int,
        text: str,
        ledger: str = "biography",
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("Observation time must be timezone-aware")
        candidate = self._candidate_summary(text, ledger=ledger, now=instant)
        if candidate is None:
            return None
        visibility = self._session_visibility(session_id)
        if visibility is None:
            return None
        summary, kind, due, reason = candidate
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, summary, kind, due_at, visibility_scope, source_type,
                           source_session_id, source_message_id, source_url,
                           source_approved, detection_reason, status, created_at,
                           resolved_at
                    FROM commitment_candidates
                    WHERE source_session_id = %s AND status = 'offered'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (session_id,),
                )
                existing = cur.fetchone()
                if existing:
                    return _offer(existing)
                candidate_id = uuid.uuid4()
                cur.execute(
                    """
                    INSERT INTO commitment_candidates (
                        id, summary, kind, due_at, visibility_scope, source_type,
                        source_session_id, source_message_id, source_approved,
                        detection_reason, status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, 'session', %s, %s, false,
                              %s, 'offered', %s)
                    RETURNING id, summary, kind, due_at, visibility_scope, source_type,
                              source_session_id, source_message_id, source_url,
                              source_approved, detection_reason, status,
                              created_at, resolved_at
                    """,
                    (
                        candidate_id,
                        summary,
                        kind,
                        due,
                        visibility,
                        session_id,
                        message_id,
                        reason,
                        instant,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return _offer(row)

    def offer_dashboard_item(
        self,
        *,
        text: str,
        source_url: str,
        approved: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not approved:
            raise ValueError("Dashboard commitment source must be approved")
        url = source_url.strip()
        if not url:
            raise ValueError("Dashboard commitment source URL is required")
        instant = now or datetime.now(UTC)
        candidate = self._candidate_summary(text, ledger="biography", now=instant)
        if candidate is None:
            raise ValueError("Dashboard item is not a safe first-person commitment")
        summary, kind, due, reason = candidate
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO commitment_candidates (
                        id, summary, kind, due_at, visibility_scope, source_type, source_url,
                        source_approved, detection_reason, status, created_at
                    ) VALUES (%s, %s, %s, %s, 'professional', 'dashboard', %s, true, %s,
                              'offered', %s)
                    RETURNING id, summary, kind, due_at, visibility_scope, source_type,
                              source_session_id, source_message_id, source_url,
                              source_approved, detection_reason, status,
                              created_at, resolved_at
                    """,
                    (uuid.uuid4(), summary, kind, due, url, reason, instant),
                )
                row = cur.fetchone()
            conn.commit()
        return _offer(row)

    def confirm_offer(
        self, offer_id: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        instant = now or datetime.now(UTC)
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, summary, kind, due_at, status, visibility_scope
                    FROM commitment_candidates WHERE id = %s FOR UPDATE
                    """,
                    (offer_id,),
                )
                candidate = cur.fetchone()
                if not candidate:
                    raise ValueError("Commitment offer not found")
                if candidate[4] != "offered":
                    raise ValueError("Commitment offer is no longer pending")
                commitment_id = uuid.uuid4()
                cur.execute(
                    """
                    INSERT INTO commitments (
                        id, candidate_id, summary, kind, status, due_at, visibility_scope,
                        confirmed_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s)
                    """,
                    (
                        commitment_id,
                        candidate[0],
                        candidate[1],
                        candidate[2],
                        candidate[3],
                        candidate[5],
                        instant,
                        instant,
                    ),
                )
                cur.execute(
                    """
                    UPDATE commitment_candidates
                    SET status = 'confirmed', resolved_at = %s WHERE id = %s
                    """,
                    (instant, candidate[0]),
                )
            conn.commit()
        return self.get_commitment(str(commitment_id), include_private=True)

    def dismiss_offer(self, offer_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        instant = now or datetime.now(UTC)
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE commitment_candidates
                    SET status = 'dismissed', resolved_at = %s
                    WHERE id = %s AND status = 'offered'
                    RETURNING id, summary, kind, due_at, visibility_scope, source_type,
                              source_session_id, source_message_id, source_url,
                              source_approved, detection_reason, status,
                              created_at, resolved_at
                    """,
                    (instant, offer_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Pending commitment offer not found")
        return _offer(row)

    def expire_stale_offers(self, *, now: datetime | None = None) -> int:
        instant = now or datetime.now(UTC)
        cutoff = instant - self.max_offer_age
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE commitment_candidates
                    SET status = 'expired', resolved_at = %s
                    WHERE status = 'offered' AND created_at < %s
                    """,
                    (instant, cutoff),
                )
                changed = cur.rowcount
            conn.commit()
        return changed

    def get_commitment(
        self, commitment_id: str, *, include_private: bool = False
    ) -> dict[str, Any]:
        privacy = "" if include_private else " AND c.visibility_scope <> 'private_shared'"
        rows = self._commitment_rows(f"WHERE c.id = %s{privacy}", (commitment_id,))
        if not rows:
            raise ValueError("Commitment not found")
        return _commitment(rows[0])

    def list_commitments(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in STATES:
            raise ValueError("Unknown commitment status")
        where = (
            "WHERE c.status = %s AND c.visibility_scope <> 'private_shared'"
            if status
            else "WHERE c.visibility_scope <> 'private_shared'"
        )
        params: tuple[Any, ...] = (status,) if status else ()
        return [_commitment(row) for row in self._commitment_rows(where, params)]

    def _commitment_rows(
        self, where: str, params: tuple[Any, ...]
    ) -> list[tuple[Any, ...]]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT c.id, c.candidate_id, c.summary, c.kind, c.status,
                           c.due_at, c.snoozed_until, c.last_reminded_at,
                           c.confirmed_at, c.updated_at, c.visibility_scope, o.source_type,
                           o.source_session_id, o.source_message_id, o.source_url
                    FROM commitments c
                    JOIN commitment_candidates o ON o.id = c.candidate_id
                    {where}
                    ORDER BY c.updated_at DESC, c.id DESC
                    """,
                    params,
                )
                return cur.fetchall()

    def transition(
        self,
        commitment_id: str,
        status: str,
        *,
        snoozed_until: datetime | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = status.strip().lower()
        if normalized not in STATES:
            raise ValueError("Unknown commitment status")
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("Transition time must be timezone-aware")
        if normalized == "snoozed":
            if snoozed_until is None or snoozed_until.tzinfo is None:
                raise ValueError("Snoozed commitments require a timezone-aware wake time")
            if snoozed_until <= instant:
                raise ValueError("Snooze wake time must be in the future")
        elif snoozed_until is not None:
            raise ValueError("Wake time is valid only for snoozed commitments")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE commitments
                    SET status = %s, snoozed_until = %s, updated_at = %s
                    WHERE id = %s RETURNING id
                    """,
                    (normalized, snoozed_until, instant, commitment_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Commitment not found")
        return self.get_commitment(commitment_id, include_private=True)

    def observe_message(
        self,
        *,
        session_id: str,
        message_id: int,
        text: str,
        ledger: str = "biography",
        now: datetime | None = None,
    ) -> RadarObservation:
        instant = now or datetime.now(UTC)
        self.expire_stale_offers(now=instant)
        pending = self.list_offers(status="offered", session_id=session_id)
        if pending and _explicit_confirmation(text):
            commitment = self.confirm_offer(pending[0]["offer_id"], now=instant)
            return RadarObservation(
                "confirmed",
                "Commitment Radar: Christopher explicitly confirmed the offered "
                f"commitment. It is now active: {commitment['summary']}",
                commitment=commitment,
            )
        if pending and _explicit_rejection(text):
            offer = self.dismiss_offer(pending[0]["offer_id"], now=instant)
            return RadarObservation(
                "dismissed",
                "Commitment Radar: Christopher declined the offered commitment. "
                "Acknowledge briefly and do not remind him about it.",
                offer=offer,
            )
        if pending:
            return RadarObservation("none")
        offer = self.offer_session_message(
            session_id=session_id,
            message_id=message_id,
            text=text,
            ledger=ledger,
            now=instant,
        )
        if offer is None:
            return RadarObservation("none")
        return RadarObservation(
            "offered",
            "Commitment Radar detected a possible "
            f"{offer['kind'].replace('_', ' ')}: {offer['summary']}\n"
            "Ask Christopher one concise conversational question about whether he "
            "wants Lyra to track it. Do not claim it is saved or active until he "
            "explicitly confirms.",
            offer=offer,
        )

    def plan_due_reminders(
        self,
        *,
        away: AwayModeService,
        channel: str,
        now: datetime | None = None,
        horizon: timedelta = timedelta(days=1),
    ) -> list[dict[str, Any]]:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("Reminder time must be timezone-aware")
        cutoff = instant + horizon
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, summary FROM commitments
                    WHERE status = 'active' AND due_at IS NOT NULL
                      AND visibility_scope <> 'private_shared'
                      AND due_at <= %s AND last_reminded_at IS NULL
                    ORDER BY due_at, id
                    """,
                    (cutoff,),
                )
                rows = cur.fetchall()
        planned: list[dict[str, Any]] = []
        for commitment_id, summary in rows:
            content = f"Commitment reminder: {summary}"
            decision = away.plan_notification(
                channel=channel,
                category="commitment",
                content=content,
                now=instant,
            )
            with self.connection_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE commitments SET last_reminded_at = %s WHERE id = %s",
                        (instant, commitment_id),
                    )
                conn.commit()
            planned.append(
                {
                    "commitment_id": str(commitment_id),
                    "content": content,
                    "disposition": decision.disposition,
                    "reason": decision.reason,
                }
            )
        return planned

    def set_visibility(self, commitment_id: str, visibility_scope: str) -> dict[str, Any]:
        scope = visibility_scope.strip().lower()
        if scope not in VISIBILITY_SCOPES:
            raise ValueError("Unknown commitment visibility scope")
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE commitments SET visibility_scope=%s,updated_at=now()
                   WHERE id=%s RETURNING id,candidate_id""",
                (scope, commitment_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE commitment_candidates SET visibility_scope=%s WHERE id=%s",
                    (scope, row[1]),
                )
            conn.commit()
        if not row:
            raise ValueError("Commitment not found")
        return self.get_commitment(commitment_id, include_private=True)

    def _session_visibility(self, session_id: str) -> str | None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT s.context_scope,
                          EXISTS (SELECT 1 FROM shared_journal_private_sessions p
                                  WHERE p.session_id=s.id)
                   FROM chat_sessions s WHERE s.id=%s""",
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("Commitment source session was not found")
        if row[1]:
            return "private_shared"
        if row[0] in {"story", "campaign"}:
            return None
        return "professional" if row[0] == "professional" else "general"
