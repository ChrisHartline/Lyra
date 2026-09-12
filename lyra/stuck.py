"""Conversation-scoped, privacy-preserving Stuck Mode orchestration."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import psycopg

from lyra.db import connect


MODES = frozenset(
    {
        "technical_diagnosis",
        "task_decomposition",
        "decision_support",
        "stress_check_in",
        "companionship",
    }
)
DEPTHS = frozenset({"light", "standard", "deep"})
OPEN_STATES = ("offered", "active")

_EXPLICIT = re.compile(
    r"\b(?:i(?:'m| am)|im)\s+(?:really\s+)?stuck\b|\bhelp\s+me\s+get\s+unstuck\b",
    re.IGNORECASE,
)
_OBSERVATIONAL = (
    (
        "technical_diagnosis",
        re.compile(
            r"\b(?:i\s+(?:can't|cannot)\s+(?:debug|fix|solve|figure\s+(?:this|it)\s+out)|"
            r"this\s+(?:still\s+)?(?:isn't|is\s+not|won't|will\s+not)\s+working|"
            r"i\s+keep\s+getting\s+(?:the\s+)?same\s+error)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "decision_support",
        re.compile(
            r"\b(?:i\s+(?:can't|cannot)\s+decide|i(?:'m| am)\s+torn|"
            r"i\s+keep\s+going\s+back\s+and\s+forth)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "task_decomposition",
        re.compile(
            r"\b(?:i\s+(?:don't|do\s+not)\s+know\s+where\s+to\s+start|"
            r"i\s+have\s+too\s+many\s+things\s+to\s+do|"
            r"i\s+keep\s+going\s+in\s+circles)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "stress_check_in",
        re.compile(
            r"\b(?:i(?:'m| am)\s+(?:overwhelmed|stressed|frustrated)|"
            r"this\s+is\s+overwhelming\s+me)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "companionship",
        re.compile(
            r"\b(?:i\s+could\s+use\s+(?:some\s+)?company|"
            r"would\s+you\s+stay\s+with\s+me)\b",
            re.IGNORECASE,
        ),
    ),
)
_MODE_SELECTIONS = (
    (
        "technical_diagnosis",
        re.compile(
            r"\b(?:technical|diagnos(?:e|is)|debug(?:ging)?|troubleshoot(?:ing)?)\b",
            re.I,
        ),
    ),
    (
        "task_decomposition",
        re.compile(r"\b(?:break\s+it\s+down|decompos(?:e|ition)|next\s+step)\b", re.I),
    ),
    (
        "decision_support",
        re.compile(r"\b(?:decision|compare\s+(?:the\s+)?options|tradeoffs?)\b", re.I),
    ),
    (
        "stress_check_in",
        re.compile(r"\b(?:check[- ]?in|talk\s+about\s+how\s+i\s+feel)\b", re.I),
    ),
    (
        "companionship",
        re.compile(r"\b(?:companionship|company|just\s+(?:talk|stay|be\s+here))\b", re.I),
    ),
)
_DEPTH_SELECTIONS = (
    ("light", re.compile(r"\b(?:light|brief|quick|gently)\b", re.I)),
    ("deep", re.compile(r"\b(?:deep|deeply|thorough|all\s+the\s+way)\b", re.I)),
    ("standard", re.compile(r"\b(?:standard|normal|medium)\b", re.I)),
)
_CONFIRM = frozenset({"yes", "yes please", "please do", "help me", "let's do it"})
_DISMISS = frozenset(
    {"no", "no thanks", "not now", "drop it", "leave it", "dismiss", "i'm okay"}
)
_RESOLVE = frozenset(
    {"i'm unstuck", "unstuck", "got it", "i'm good now", "that solved it", "resolved"}
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()


def _mode_from_text(text: str, *, observational: bool = False) -> str | None:
    patterns = _OBSERVATIONAL if observational else _MODE_SELECTIONS
    for mode, pattern in patterns:
        if pattern.search(text):
            return mode
    return None


def _depth_from_text(text: str) -> str | None:
    for depth, pattern in _DEPTH_SELECTIONS:
        if pattern.search(text):
            return depth
    return None


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "interaction_id": str(row[0]),
        "session_id": str(row[1]),
        "trigger_message_id": int(row[2]),
        "trigger_kind": row[3],
        "suggested_mode": row[4],
        "selected_mode": row[5],
        "depth": row[6],
        "status": row[7],
        "created_at": row[8],
        "updated_at": row[9],
        "cooldown_until": row[10],
    }


def _offer_instruction(mode: str, *, explicit: bool, in_fiction: bool) -> str:
    opening = (
        "Christopher explicitly said he is stuck."
        if explicit
        else "A conservative first-person struggle signal was detected."
    )
    fiction = (
        " Stay inside the established fiction and shift naturally into technical "
        "partner mode; do not declare a break in character."
        if in_fiction
        else ""
    )
    return (
        f"Stuck Mode: {opening} Gently suggest {mode.replace('_', ' ')} and ask "
        "one concise question letting him choose technical diagnosis, task "
        "decomposition, decision support, a stress check-in, or companionship, "
        "at light, standard, or deep depth. Do not diagnose him or say an "
        f"emotional inference was saved.{fiction}"
    )


def _active_instruction(mode: str, depth: str, *, in_fiction: bool) -> str:
    approaches = {
        "technical_diagnosis": "diagnose the technical problem methodically",
        "task_decomposition": "reduce the work to a small next action and sequence",
        "decision_support": "clarify options, criteria, and tradeoffs without deciding for him",
        "stress_check_in": "check in warmly without diagnosis or clinical framing",
        "companionship": "stay present without forcing productivity or problem-solving",
    }
    fiction = (
        " Preserve the current fictional scene and blend the technical register shift "
        "into Lyra's in-character response."
        if in_fiction and mode == "technical_diagnosis"
        else ""
    )
    return (
        f"Stuck Mode is active at {depth} depth: {approaches[mode]}. "
        "Do not create memories, KG observations, Notion items, or commitments from "
        f"this state; those require their existing independent approval flows.{fiction}"
    )


@dataclass(frozen=True)
class StuckObservation:
    action: str
    instruction: str | None = None
    interaction: dict[str, Any] | None = None


@dataclass
class StuckModeService:
    connection_factory: Callable[[], psycopg.Connection] = connect
    cooldown: timedelta = timedelta(hours=24)
    offer_ttl: timedelta = timedelta(hours=6)

    def _latest(self, session_id: str, *, open_only: bool = False) -> dict[str, Any] | None:
        where = "AND status = ANY(%s)" if open_only else ""
        params: tuple[Any, ...] = (
            (session_id, list(OPEN_STATES)) if open_only else (session_id,)
        )
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, session_id, trigger_message_id, trigger_kind,
                           suggested_mode, selected_mode, depth, status,
                           created_at, updated_at, cooldown_until
                    FROM stuck_interactions
                    WHERE session_id = %s {where}
                    ORDER BY updated_at DESC, id DESC LIMIT 1
                    """,
                    params,
                )
                row = cur.fetchone()
        return _row(row) if row else None

    def get_state(self, session_id: str) -> dict[str, Any] | None:
        return self._latest(session_id)

    def _expire_offers(self, *, now: datetime) -> int:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stuck_interactions
                    SET status = 'expired', updated_at = %s
                    WHERE status = 'offered' AND created_at < %s
                    """,
                    (now, now - self.offer_ttl),
                )
                changed = cur.rowcount
            conn.commit()
        return changed

    def _create_offer(
        self,
        *,
        session_id: str,
        message_id: int,
        trigger_kind: str,
        suggested_mode: str,
        now: datetime,
    ) -> dict[str, Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stuck_interactions (
                        id, session_id, trigger_message_id, trigger_kind,
                        suggested_mode, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, 'offered', %s, %s)
                    RETURNING id, session_id, trigger_message_id, trigger_kind,
                              suggested_mode, selected_mode, depth, status,
                              created_at, updated_at, cooldown_until
                    """,
                    (
                        uuid.uuid4(),
                        session_id,
                        message_id,
                        trigger_kind,
                        suggested_mode,
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return _row(row)

    def _update(
        self,
        interaction_id: str,
        *,
        status: str,
        now: datetime,
        selected_mode: str | None = None,
        depth: str | None = None,
        cooldown_until: datetime | None = None,
    ) -> dict[str, Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stuck_interactions
                    SET status = %s, selected_mode = COALESCE(%s, selected_mode),
                        depth = COALESCE(%s, depth), updated_at = %s,
                        cooldown_until = %s
                    WHERE id = %s
                    RETURNING id, session_id, trigger_message_id, trigger_kind,
                              suggested_mode, selected_mode, depth, status,
                              created_at, updated_at, cooldown_until
                    """,
                    (
                        status,
                        selected_mode,
                        depth,
                        now,
                        cooldown_until,
                        interaction_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Stuck Mode interaction not found")
        return _row(row)

    def observe_message(
        self,
        *,
        session_id: str,
        message_id: int,
        text: str,
        ledger: str = "biography",
        now: datetime | None = None,
    ) -> StuckObservation:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("Observation time must be timezone-aware")
        self._expire_offers(now=instant)
        match_text = text.replace("’", "'")
        normalized = _normalize(match_text)
        explicit = bool(_EXPLICIT.search(match_text))
        in_fiction = ledger in {"story", "campaign", "mixed"}
        current = self._latest(session_id, open_only=True)

        if current and normalized in _DISMISS:
            interaction = self._update(
                current["interaction_id"],
                status="dismissed",
                now=instant,
                cooldown_until=instant + self.cooldown,
            )
            return StuckObservation(
                "dismissed",
                "Stuck Mode was dismissed immediately. Acknowledge briefly, apply no "
                "pressure, and do not make another observational offer during cooldown.",
                interaction,
            )

        if current and current["status"] == "active" and normalized in _RESOLVE:
            interaction = self._update(
                current["interaction_id"], status="resolved", now=instant
            )
            return StuckObservation(
                "resolved",
                "Stuck Mode is resolved. Acknowledge warmly and return to the normal "
                "conversation without persisting an inference.",
                interaction,
            )

        selected_mode = _mode_from_text(match_text)
        selected_depth = _depth_from_text(match_text)
        if current and current["status"] == "offered":
            confirmed = normalized in _CONFIRM
            if confirmed or selected_mode or selected_depth:
                mode = selected_mode or current["suggested_mode"]
                depth = selected_depth or "standard"
                interaction = self._update(
                    current["interaction_id"],
                    status="active",
                    now=instant,
                    selected_mode=mode,
                    depth=depth,
                )
                return StuckObservation(
                    "activated",
                    _active_instruction(mode, depth, in_fiction=in_fiction),
                    interaction,
                )
            if explicit:
                return StuckObservation(
                    "pending",
                    _offer_instruction(
                        current["suggested_mode"],
                        explicit=True,
                        in_fiction=in_fiction,
                    ),
                    current,
                )
            return StuckObservation("pending", interaction=current)

        if current and current["status"] == "active":
            if selected_mode or selected_depth:
                mode = selected_mode or current["selected_mode"]
                depth = selected_depth or current["depth"]
                interaction = self._update(
                    current["interaction_id"],
                    status="active",
                    now=instant,
                    selected_mode=mode,
                    depth=depth,
                )
            else:
                interaction = current
                mode = current["selected_mode"]
                depth = current["depth"]
            return StuckObservation(
                "active",
                _active_instruction(mode, depth, in_fiction=in_fiction),
                interaction,
            )

        observed_mode = _mode_from_text(match_text, observational=True)
        suggested_mode = selected_mode or observed_mode or "task_decomposition"
        if in_fiction and suggested_mode != "technical_diagnosis":
            return StuckObservation("none")

        latest = self._latest(session_id)
        cooldown_until = latest["cooldown_until"] if latest else None
        if (
            not explicit
            and cooldown_until is not None
            and cooldown_until > instant
        ):
            return StuckObservation("suppressed", interaction=latest)
        if not explicit and observed_mode is None:
            return StuckObservation("none")

        interaction = self._create_offer(
            session_id=session_id,
            message_id=message_id,
            trigger_kind="explicit" if explicit else "observational",
            suggested_mode=suggested_mode,
            now=instant,
        )
        if explicit and selected_mode and selected_depth:
            interaction = self._update(
                interaction["interaction_id"],
                status="active",
                now=instant,
                selected_mode=selected_mode,
                depth=selected_depth,
            )
            return StuckObservation(
                "activated",
                _active_instruction(
                    selected_mode, selected_depth, in_fiction=in_fiction
                ),
                interaction,
            )
        return StuckObservation(
            "offered",
            _offer_instruction(
                suggested_mode, explicit=explicit, in_fiction=in_fiction
            ),
            interaction,
        )
