"""Opt-in ship briefs, ambient continuity, and gated story-canon proposals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Callable
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from .away import AwayModeService
from .db import connect
from .embeddings import EmbeddingService
from .memory import MemoryService, _vector_literal, sensitivity_flags, validate_persistable_text
from .memory_control import MemoryControlService
from .sessions import SessionService


logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[1]
_SHIP_STATUS = _ROOT / "ship" / "current_status.json"
_STORY_DIR = _ROOT / "state" / "story"
_INTENSITIES = frozenset({"quiet", "balanced", "vivid"})
_BRIEF_REQUEST = re.compile(
    r"\b(?:ship|silent\s+drift|cargo\s+bay|drive|power\s+core|hull|life\s+support)\b"
    r".*\b(?:status|condition|report|brief|update|how(?:'s|\s+is)|what(?:'s|\s+is))\b|"
    r"\b(?:status|condition|report|brief|update|how(?:'s|\s+is)|what(?:'s|\s+is))\b"
    r".*\b(?:ship|silent\s+drift|cargo\s+bay|drive|power\s+core|hull|life\s+support)\b",
    re.I,
)


def _instant(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Ship continuity time must be timezone-aware")
    return instant.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ShipContinuityPolicy:
    enabled: bool
    paused: bool
    briefs_enabled: bool
    ambient_enabled: bool
    intensity: str
    cadence_days: int
    local_time: time
    timezone: str
    target_session_id: str | None


@dataclass(frozen=True)
class ShipContinuityObservation:
    instruction: str | None
    source_refs: tuple[str, ...] = ()


@dataclass
class ShipContinuityService:
    away: AwayModeService
    embedding_service: EmbeddingService
    memory_control: MemoryControlService | None = None
    connection_factory: Callable[[], psycopg.Connection] = connect
    ship_status_path: Path = _SHIP_STATUS
    story_dir: Path = _STORY_DIR

    def get_policy(self) -> ShipContinuityPolicy:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT enabled,paused,briefs_enabled,ambient_enabled,intensity,
                          cadence_days,local_time,timezone,target_session_id
                   FROM ship_continuity_policy WHERE singleton=true"""
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("Ship continuity policy is not initialized")
        return ShipContinuityPolicy(
            bool(row[0]), bool(row[1]), bool(row[2]), bool(row[3]), str(row[4]),
            int(row[5]), row[6], str(row[7]), str(row[8]) if row[8] else None,
        )

    def policy_dict(self) -> dict[str, Any]:
        return asdict(self.get_policy())

    def set_policy(self, **values: Any) -> ShipContinuityPolicy:
        current = self.policy_dict()
        unknown = set(values) - set(current)
        if unknown:
            raise ValueError(f"Unknown ship continuity settings: {sorted(unknown)}")
        current.update(values)
        intensity = str(current["intensity"]).strip().lower()
        if intensity not in _INTENSITIES:
            raise ValueError("Ship continuity intensity must be quiet, balanced, or vivid")
        cadence = int(current["cadence_days"])
        if not 1 <= cadence <= 30:
            raise ValueError("Ship continuity cadence must be between 1 and 30 days")
        try:
            ZoneInfo(str(current["timezone"]))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown ship continuity timezone") from exc
        target = current["target_session_id"]
        if target is not None:
            try:
                target = str(uuid.UUID(str(target)))
            except ValueError as exc:
                raise ValueError("Ship continuity target must be a valid session ID") from exc
            if not self._story_web_session(target):
                raise ValueError("Ship continuity requires a story-scoped web session")
        if current["enabled"] and current["ambient_enabled"] and not current["paused"] and not target:
            raise ValueError("Ambient ship continuity requires a target story session")
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE ship_continuity_policy SET enabled=%s,paused=%s,
                    briefs_enabled=%s,ambient_enabled=%s,intensity=%s,
                    cadence_days=%s,local_time=%s,timezone=%s,target_session_id=%s,
                    updated_at=now() WHERE singleton=true""",
                (
                    bool(current["enabled"]), bool(current["paused"]),
                    bool(current["briefs_enabled"]), bool(current["ambient_enabled"]),
                    intensity, cadence, current["local_time"], str(current["timezone"]),
                    target,
                ),
            )
            conn.commit()
        return self.get_policy()

    def observe_message(
        self, *, session_id: str, message_id: int, text: str,
        ledger: str = "biography", channel: str = "web",
        now: datetime | None = None,
    ) -> ShipContinuityObservation:
        del message_id, ledger, now
        policy = self.get_policy()
        if (
            not policy.enabled or policy.paused or not policy.briefs_enabled
            or channel.strip().lower() != "web"
            or not self._story_web_session(session_id)
            or not _BRIEF_REQUEST.search(text)
        ):
            return ShipContinuityObservation(None)
        brief, refs = self.status_brief()
        instruction = (
            "SHIP CONTINUITY — DIRECT RESPONSE CONSTRAINT: The user asked for a ship "
            "status or continuity brief. Treat the supplied facts as sufficient: do not "
            "announce a lookup, search, record check, or uncertainty preamble. Respond in "
            "Lyra's normal in-fiction voice while preserving any technical register the "
            "user requests. Distinguish observed status from speculation and do not invent "
            "a repair, movement, discovery, or canon change. Facts: " + brief + ". "
            "Internal provenance (never mention): " + ", ".join(refs) + "."
        )
        return ShipContinuityObservation(instruction, tuple(refs))

    def status_brief(self) -> tuple[str, list[str]]:
        status = json.loads(self.ship_status_path.read_text(encoding="utf-8"))
        systems = status.get("systems") or {}
        parts = [f"overall condition is {str(status.get('overall_condition', 'unknown')).replace('_', ' ')}"]
        for name in ("quantum_drive", "power_core", "life_support", "hull"):
            item = systems.get(name)
            if not isinstance(item, dict):
                continue
            detail = f"{name.replace('_', ' ')}: {str(item.get('status', 'unknown')).replace('_', ' ')}"
            if name == "power_core" and item.get("output_percent") is not None:
                detail += f" at {item['output_percent']} percent output"
            parts.append(detail)
        living = status.get("living_conversion") or {}
        if isinstance(living, dict) and living.get("status"):
            parts.append(f"cargo-bay living conversion: {str(living['status']).replace('_', ' ')}")
        refs = [f"ship-status:{status.get('version', 'unknown')}"]
        for path in sorted(self.story_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if text and "No approved story" not in text:
                refs.append(f"state-story:{path.name}#{_hash(text)[:16]}")
        return "; ".join(parts), refs

    def preview_ambient(self) -> dict[str, Any]:
        policy = self.get_policy()
        brief, refs = self.status_brief()
        status = json.loads(self.ship_status_path.read_text(encoding="utf-8"))
        power = (status.get("systems") or {}).get("power_core") or {}
        lines = [
            "The cargo-bay light softens for half a breath as the power core shifts a load, then steadies.",
        ]
        if policy.intensity in {"balanced", "vivid"}:
            lines.append("Somewhere behind the wall plating, cooling metal answers with a small, familiar tick.")
        if policy.intensity == "vivid":
            lines.append("Lyra glances toward the engineering readout, attentive but unalarmed; the core remains stable at its reduced output.")
        if power.get("status") != "degraded":
            lines[0] = "Soft blue light holds steady through the cargo bay while the ship rests under cover."
        return {
            "body": " ".join(lines),
            "source_refs": refs,
            "canon_status": "ephemeral_noncanonical",
            "grounding_summary": brief,
        }

    def plan_due(self, *, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
        instant = _instant(now)
        policy = self.get_policy()
        if not policy.enabled or policy.paused or not policy.ambient_enabled:
            return {"disposition": "disabled" if not policy.paused else "paused"}
        if not policy.target_session_id or not self._story_web_session(policy.target_session_id):
            return {"disposition": "no_story_target"}
        local = instant.astimezone(ZoneInfo(policy.timezone))
        if not force and local.timetz().replace(tzinfo=None) < policy.local_time:
            return {"disposition": "not_due"}
        if not force and not self._ambient_due(instant, policy.cadence_days):
            return {"disposition": "not_due"}
        dedupe = f"ambient:{local.date().isoformat()}"
        if self._event_by_dedupe(dedupe):
            return {"disposition": "already_handled"}
        preview = self.preview_ambient()
        decision = self.away.plan_notification(
            channel="web", category="status",
            content=f"[ship-continuity:ambient:{_hash(preview['body'])}]", now=instant,
        )
        status = {"send": "planned", "batch": "batched", "suppress": "suppressed"}[
            decision.disposition
        ]
        event_id = str(uuid.uuid4())
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ship_continuity_events
                    (id,event_type,dedupe_key,status,target_session_id,source_refs,
                     content_sha256,canon_status,created_at)
                   VALUES (%s,'ambient',%s,%s,%s,%s::jsonb,%s,
                           'ephemeral_noncanonical',%s)""",
                (
                    event_id, dedupe, status, policy.target_session_id,
                    json.dumps(preview["source_refs"]), _hash(preview["body"]), instant,
                ),
            )
            conn.commit()
        return {
            "disposition": decision.disposition,
            "body": preview["body"],
            "event": self._event(event_id),
        }

    def propose_canon_update(
        self, *, content: str, session_id: str, source_message_id: int | None = None
    ) -> dict[str, Any]:
        if not self._story_web_session(session_id):
            raise ValueError("Canon proposals require a story-scoped web session")
        normalized = validate_persistable_text(content)
        if len(normalized) > 4000:
            raise ValueError("Canon proposal must be 4000 characters or fewer")
        stored = normalized if normalized.lower().startswith("story canon update:") else f"Story canon update: {normalized}"
        vector = self.embedding_service.embed_texts([stored])[0]
        metadata = {
            "ledger": "story",
            "source_type": "ship_continuity",
            "source_id": str(source_message_id) if source_message_id is not None else session_id,
            "source_session_id": session_id,
            "source_message_id": source_message_id,
            "destination_plane": "semantic_memory",
            "proposal_reason": "User-requested ship continuity canon change",
            "approval_mode": "review",
            "trust_lane": "story",
            "sensitivity_flags": sensitivity_flags(stored),
        }
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO memories
                    (content,embedding,memory_type,salience,metadata,approved,review_status)
                   VALUES (%s,%s::vector,'story',6,%s::jsonb,false,'pending')
                   RETURNING id,created_at""",
                (stored, _vector_literal(vector), json.dumps(metadata)),
            )
            row = cur.fetchone()
            conn.commit()
        return {
            "proposal_id": int(row[0]), "status": "pending", "created_at": row[1],
            "destination_plane": "story", "content": stored,
        }

    def approve_canon_update(self, proposal_id: int) -> dict[str, Any]:
        if self.memory_control is None:
            raise ValueError("Memory approval service is unavailable")
        proposal = next(
            (item for item in self.memory_control.list_proposals(limit=500)
             if item["proposal_id"] == proposal_id),
            None,
        )
        if not proposal or proposal["memory_type"] != "story" or proposal["provenance"]["source_type"] != "ship_continuity":
            raise ValueError("Pending ship continuity proposal not found")
        result = self.memory_control.approve(
            proposal_id, actor="local_user",
            details={"approved_via": "ship_continuity"},
        )
        regen = MemoryService(
            embedding_service=self.embedding_service,
            connection_factory=self.connection_factory,
        ).regenerate_story_canon(self.story_dir)
        return {**result, "story_canon": regen}

    def mark_delivered(self, event_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        instant = _instant(now)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE ship_continuity_events SET status='delivered',delivered_at=%s
                   WHERE id=%s AND status='planned' RETURNING id""",
                (instant, event_id),
            )
            row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Planned ship continuity event not found")
        return self._event(event_id)

    def mark_failed(self, event_id: str) -> None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ship_continuity_events SET status='failed' WHERE id=%s AND status='planned'",
                (event_id,),
            )
            conn.commit()

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,event_type,status,target_session_id,source_refs,
                          content_sha256,canon_status,created_at,delivered_at
                   FROM ship_continuity_events ORDER BY created_at DESC,id DESC LIMIT %s""",
                (min(500, max(1, limit)),),
            )
            return [self._event_view(row) for row in cur.fetchall()]

    def _story_web_session(self, session_id: str) -> bool:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM chat_sessions s
                   WHERE s.id=%s AND s.context_scope='story' AND NOT EXISTS (
                     SELECT 1 FROM session_channels c
                     WHERE c.session_id=s.id AND c.channel='telegram')""",
                (session_id,),
            )
            return cur.fetchone() is not None

    def _ambient_due(self, now: datetime, cadence_days: int) -> bool:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT max(created_at) FROM ship_continuity_events
                   WHERE event_type='ambient' AND status IN
                     ('planned','delivered','batched','suppressed')"""
            )
            last = cur.fetchone()[0]
        return last is None or now >= last + timedelta(days=cadence_days)

    def _event_by_dedupe(self, dedupe_key: str) -> dict[str, Any] | None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,event_type,status,target_session_id,source_refs,
                          content_sha256,canon_status,created_at,delivered_at
                   FROM ship_continuity_events WHERE dedupe_key=%s""",
                (dedupe_key,),
            )
            row = cur.fetchone()
        return self._event_view(row) if row else None

    def _event(self, event_id: str) -> dict[str, Any]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,event_type,status,target_session_id,source_refs,
                          content_sha256,canon_status,created_at,delivered_at
                   FROM ship_continuity_events WHERE id=%s""",
                (event_id,),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("Ship continuity event not found")
        return self._event_view(row)

    @staticmethod
    def _event_view(row: Any) -> dict[str, Any]:
        return {
            "event_id": str(row[0]), "event_type": row[1], "status": row[2],
            "target_session_id": str(row[3]) if row[3] else None,
            "source_refs": row[4] or [], "content_sha256": row[5],
            "canon_status": row[6], "created_at": row[7], "delivered_at": row[8],
        }


async def run_ship_continuity(
    sessions: SessionService,
    continuity: ShipContinuityService,
    *, interval_seconds: int = 30,
    iterations: int | None = None,
) -> None:
    """Deliver due ambient beats only to the selected story-scoped web session."""

    import asyncio

    completed = 0
    while iterations is None or completed < iterations:
        result: dict[str, Any] | None = None
        try:
            result = continuity.plan_due()
            if result.get("disposition") == "send":
                event = result["event"]
                sessions.append_message(
                    event["target_session_id"], "assistant", result["body"],
                    metadata={
                        "channel": "web", "proactive": True,
                        "ship_continuity": "ambient",
                        "ship_continuity_event_id": event["event_id"],
                        "ship_continuity_sources": event["source_refs"],
                        "canon_status": event["canon_status"],
                    },
                )
                continuity.mark_delivered(event["event_id"])
        except Exception:
            logger.exception("Ship continuity delivery failed")
            if result and result.get("event"):
                continuity.mark_failed(result["event"]["event_id"])
        completed += 1
        if iterations is None or completed < iterations:
            await asyncio.sleep(interval_seconds)
