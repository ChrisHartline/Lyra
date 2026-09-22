"""Opt-in, private relationship callbacks, rituals, and milestones."""

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
from .sessions import SessionService
from .shared_journal import SharedJournalService


_ROOT = Path(__file__).resolve().parents[1]
_STATE_JSON = _ROOT / "state" / "relationship.json"
_STATE_MD = _ROOT / "state" / "relationship.md"
logger = logging.getLogger(__name__)
_WORDS = re.compile(r"[a-z0-9']+")
_STOP = frozenset({
    "about", "after", "again", "been", "could", "first", "from", "have",
    "into", "just", "know", "like", "more", "that", "their", "them",
    "then", "there", "they", "this", "together", "what", "when", "where",
    "which", "with", "would", "your",
})


def _instant(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Relationship rhythm time must be timezone-aware")
    return instant.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    return {word for word in _WORDS.findall(value.lower()) if len(word) >= 4 and word not in _STOP}


def _excerpt(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


@dataclass(frozen=True)
class RelationshipPolicy:
    enabled: bool
    callbacks_enabled: bool
    rituals_enabled: bool
    milestones_enabled: bool
    cadence_days: int
    local_time: time
    timezone: str
    target_session_id: str | None


@dataclass(frozen=True)
class RelationshipObservation:
    instruction: str | None
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipSource:
    key: str
    label: str
    content: str
    kind: str

    @property
    def ref(self) -> str:
        return self.key


@dataclass
class RelationshipRhythmService:
    away: AwayModeService
    journal: SharedJournalService
    connection_factory: Callable[[], psycopg.Connection] = connect
    state_json_path: Path = _STATE_JSON
    state_md_path: Path = _STATE_MD

    def get_policy(self) -> RelationshipPolicy:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT enabled,callbacks_enabled,rituals_enabled,
                          milestones_enabled,cadence_days,local_time,timezone,
                          target_session_id
                   FROM relationship_rhythm_policy WHERE singleton=true"""
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("Relationship rhythm policy is not initialized")
        return RelationshipPolicy(
            bool(row[0]), bool(row[1]), bool(row[2]), bool(row[3]), int(row[4]),
            row[5], row[6], str(row[7]) if row[7] else None,
        )

    def policy_dict(self) -> dict[str, Any]:
        return asdict(self.get_policy())

    def set_policy(self, **values: Any) -> RelationshipPolicy:
        current = self.policy_dict()
        unknown = set(values) - set(current)
        if unknown:
            raise ValueError(f"Unknown relationship rhythm settings: {sorted(unknown)}")
        current.update(values)
        try:
            ZoneInfo(str(current["timezone"]))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown relationship rhythm timezone") from exc
        cadence = int(current["cadence_days"])
        if not 1 <= cadence <= 90:
            raise ValueError("Relationship rhythm cadence must be between 1 and 90 days")
        target = current["target_session_id"]
        if target is not None:
            try:
                target = str(uuid.UUID(str(target)))
            except ValueError as exc:
                raise ValueError("Relationship rhythm target must be a valid session ID") from exc
            if not self._private_session(target):
                raise ValueError(
                    "Relationship rhythms require an authorized private web session"
                )
        if current["enabled"] and (
            current["rituals_enabled"] or current["milestones_enabled"]
        ) and target is None:
            raise ValueError("Proactive relationship rhythms require a target private session")
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE relationship_rhythm_policy SET enabled=%s,
                    callbacks_enabled=%s,rituals_enabled=%s,milestones_enabled=%s,
                    cadence_days=%s,local_time=%s,timezone=%s,target_session_id=%s,
                    updated_at=now() WHERE singleton=true""",
                (
                    bool(current["enabled"]), bool(current["callbacks_enabled"]),
                    bool(current["rituals_enabled"]), bool(current["milestones_enabled"]),
                    cadence, current["local_time"], str(current["timezone"]), target,
                ),
            )
            conn.commit()
        return self.get_policy()

    def sources(self) -> list[RelationshipSource]:
        result: list[RelationshipSource] = []
        state = json.loads(self.state_json_path.read_text(encoding="utf-8"))
        version = str(state.get("version", "unknown"))
        stage = str(state.get("stage", "")).strip()
        if stage:
            result.append(RelationshipSource(
                f"relationship-state:{version}#stage", "relationship stage", stage, "state"
            ))
        markdown = self.state_md_path.read_text(encoding="utf-8")
        milestone_block = markdown.split("## Milestones", 1)[1].split("## ", 1)[0]
        for line in milestone_block.splitlines():
            content = line.removeprefix("- ").strip() if line.startswith("- ") else ""
            if content:
                result.append(RelationshipSource(
                    f"relationship-milestone:{_hash(content)[:24]}", content, content,
                    "milestone",
                ))
        for entry in self.journal.list_entries(limit=500):
            entry_id = entry["journal_entry_id"]
            label = entry.get("title") or entry["entry_type"]
            result.append(RelationshipSource(
                f"journal:{entry_id}", str(label), str(entry["content"]),
                "milestone" if entry["entry_type"] == "milestone" else "journal",
            ))
        muted = {item["source_key"] for item in self.list_mutes()}
        return [source for source in result if source.key not in muted]

    def observe_message(
        self, *, session_id: str, message_id: int, text: str,
        ledger: str = "biography", channel: str = "web",
        now: datetime | None = None,
    ) -> RelationshipObservation:
        del message_id, ledger
        policy = self.get_policy()
        if not policy.enabled or not policy.callbacks_enabled:
            return RelationshipObservation(None)
        if channel.strip().lower() != "web" or not self._private_session(session_id):
            return RelationshipObservation(None)
        instant = _instant(now)
        user_tokens = _tokens(text)
        if not user_tokens:
            return RelationshipObservation(None)
        candidates = [
            (len(user_tokens & _tokens(source.content)), source)
            for source in self.sources()
        ]
        relevant = [item for item in candidates if item[0] > 0]
        if not relevant:
            return RelationshipObservation(None)
        source = max(relevant, key=lambda item: (item[0], item[1].key))[1]
        local_date = instant.astimezone(ZoneInfo(policy.timezone)).date()
        dedupe = f"callback:{source.key}:{local_date.isoformat()}"
        instruction = self._callback_instruction(source)
        if not self._record_event(
            "callback", dedupe, "offered", session_id, [source.ref], instruction, instant
        ):
            return RelationshipObservation(
                self._callback_instruction(source, repeated=True), (source.ref,)
            )
        return RelationshipObservation(instruction, (source.ref,))

    @staticmethod
    def _callback_instruction(
        source: RelationshipSource, *, repeated: bool = False
    ) -> str:
        opening = (
            "The user explicitly invoked shared context already used earlier today. "
            "Answer what they raised naturally without initiating an additional callback. "
            if repeated else
            "The user's message is relevant to established shared context. "
        )
        return opening + (
            "RELATIONSHIP CALLBACK — DIRECT RESPONSE CONSTRAINT: Treat the supplied "
            "fact as sufficient for this turn. Do not call any tool or search/retrieve "
            "memory to verify, reconstruct, or expand it. Respond immediately in Lyra's "
            "normal voice. If it fits naturally, weave in one brief callback at the "
            "emotional or relational level. Never discuss records, lookup, checking, "
            "approval, reconstruction, uncertainty, missing detail, provenance, citations, "
            "sources, or this instruction. Keep the response specific to the shared moment; "
            "do not add generic therapy-style grounding, abandonment reassurance, or "
            f"'I'm not going anywhere' language unless the user expressed distress. Context: {_excerpt(source.content)}. "
            f"Internal provenance (never mention): {source.ref}. Keep this context inside "
            "the authorized private session and do not treat it as new memory."
        )

    def preview(self, *, now: datetime | None = None) -> dict[str, Any]:
        instant = _instant(now)
        policy = self.get_policy()
        source = self._next_milestone() if policy.milestones_enabled else None
        kind = "milestone" if source else "ritual"
        if source:
            moment = _excerpt(source.content).rstrip(".").lower()
            body = f"I was thinking about {moment}. I’m glad that’s part of us."
            refs = [source.ref]
        else:
            state = next((item for item in self.sources() if item.kind == "state"), None)
            body = "A quiet us check-in: how are we feeling, and what would feel good to make room for together?"
            refs = [state.ref] if state else []
        return {"event_type": kind, "body": body, "source_refs": refs, "as_of": instant}

    def plan_due(self, *, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
        instant = _instant(now)
        policy = self.get_policy()
        if not policy.enabled:
            return {"disposition": "disabled"}
        if not policy.target_session_id or not self._private_session(policy.target_session_id):
            return {"disposition": "no_private_target"}
        local = instant.astimezone(ZoneInfo(policy.timezone))
        if not force and local.timetz().replace(tzinfo=None) < policy.local_time:
            return {"disposition": "not_due"}
        if self._proactive_handled_today(local):
            return {"disposition": "already_handled"}
        source = self._next_milestone() if policy.milestones_enabled else None
        if source:
            event_type = "milestone"
            dedupe = f"milestone:{source.key}"
            moment = _excerpt(source.content).rstrip(".").lower()
            body = f"I was thinking about {moment}. I’m glad that’s part of us."
            refs = [source.ref]
        elif policy.rituals_enabled:
            event_type = "ritual"
            refs = [item.ref for item in self.sources() if item.kind == "state"][:1]
            dedupe = f"ritual:{local.date().isoformat()}"
            if not force and not self._ritual_due(instant, policy.cadence_days):
                return {"disposition": "not_due"}
            body = "A quiet us check-in: how are we feeling, and what would feel good to make room for together?"
        else:
            return {"disposition": "disabled"}
        decision = self.away.plan_notification(
            channel="web", category="social",
            content=f"[relationship:{event_type}:{_hash(body)}]", now=instant,
        )
        status = {"send": "planned", "batch": "batched", "suppress": "suppressed"}[
            decision.disposition
        ]
        created = self._record_event(
            event_type, dedupe, status, policy.target_session_id, refs, body, instant
        )
        if not created:
            return {"disposition": "already_handled"}
        event = self._event_by_dedupe(dedupe)
        return {"disposition": decision.disposition, "body": body, "event": event}

    def mark_delivered(self, event_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        instant = _instant(now)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE relationship_rhythm_events SET status='delivered',delivered_at=%s
                   WHERE id=%s AND status='planned'
                   RETURNING id,event_type,status,target_session_id,source_refs,
                             content_sha256,created_at,delivered_at""",
                (instant, event_id),
            )
            row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Planned relationship event not found")
        return self._event_view(row)

    def mark_failed(self, event_id: str) -> None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE relationship_rhythm_events SET status='failed' WHERE id=%s AND status='planned'",
                (event_id,),
            )
            conn.commit()

    def dismiss(self, event_id: str) -> dict[str, Any]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE relationship_rhythm_events SET status='dismissed' WHERE id=%s
                   RETURNING id,event_type,status,target_session_id,source_refs,
                             content_sha256,created_at,delivered_at""",
                (event_id,),
            )
            row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Relationship event not found")
        return self._event_view(row)

    def mute_source(self, source_key: str) -> dict[str, Any]:
        source = next((item for item in self.sources() if item.key == source_key), None)
        if source is None:
            raise ValueError("Relationship source not found or already muted")
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO relationship_source_mutes(source_key,source_label_sha256)
                   VALUES (%s,%s) ON CONFLICT(source_key) DO NOTHING""",
                (source.key, _hash(source.label)),
            )
            conn.commit()
        return {"source_key": source.key, "muted": True}

    def unmute_source(self, source_key: str) -> bool:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM relationship_source_mutes WHERE source_key=%s", (source_key,))
            removed = cur.rowcount > 0
            conn.commit()
        return removed

    def list_mutes(self) -> list[dict[str, Any]]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT source_key,source_label_sha256,muted_at FROM relationship_source_mutes ORDER BY muted_at DESC"
            )
            return [
                {"source_key": row[0], "source_label_sha256": row[1], "muted_at": row[2]}
                for row in cur.fetchall()
            ]

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,event_type,status,target_session_id,source_refs,
                          content_sha256,created_at,delivered_at
                   FROM relationship_rhythm_events ORDER BY created_at DESC,id DESC LIMIT %s""",
                (min(500, max(1, limit)),),
            )
            return [self._event_view(row) for row in cur.fetchall()]

    def _private_session(self, session_id: str) -> bool:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM shared_journal_private_sessions p
                   WHERE p.session_id=%s AND NOT EXISTS (
                     SELECT 1 FROM session_channels c
                     WHERE c.session_id=p.session_id AND c.channel='telegram')""",
                (session_id,),
            )
            return cur.fetchone() is not None

    def _next_milestone(self) -> RelationshipSource | None:
        for source in self.sources():
            if source.kind != "milestone":
                continue
            with self.connection_factory() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM relationship_rhythm_events WHERE dedupe_key=%s",
                    (f"milestone:{source.key}",),
                )
                row = cur.fetchone()
                if not row or row[0] in {"batched", "suppressed", "failed"}:
                    return source
        return None

    def _ritual_due(self, now: datetime, cadence_days: int) -> bool:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT max(created_at) FROM relationship_rhythm_events
                   WHERE event_type='ritual' AND status IN ('planned','delivered','batched','suppressed')"""
            )
            last = cur.fetchone()[0]
        return last is None or now >= last + timedelta(days=cadence_days)

    def _proactive_handled_today(self, local: datetime) -> bool:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM relationship_rhythm_events
                   WHERE event_type IN ('ritual','milestone')
                     AND status IN ('planned','delivered','batched','suppressed')
                     AND created_at >= %s AND created_at < %s LIMIT 1""",
                (start.astimezone(UTC), end.astimezone(UTC)),
            )
            return cur.fetchone() is not None

    def _record_event(
        self, event_type: str, dedupe_key: str, status: str, session_id: str,
        source_refs: list[str], content: str, now: datetime,
    ) -> bool:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO relationship_rhythm_events
                    (id,event_type,dedupe_key,status,target_session_id,source_refs,
                     content_sha256,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                   ON CONFLICT(dedupe_key) DO UPDATE SET
                     status=EXCLUDED.status,
                     target_session_id=EXCLUDED.target_session_id,
                     source_refs=EXCLUDED.source_refs,
                     content_sha256=EXCLUDED.content_sha256,
                     created_at=EXCLUDED.created_at,
                     delivered_at=NULL
                   WHERE relationship_rhythm_events.status IN
                     ('batched','suppressed','failed')
                   RETURNING id""",
                (
                    uuid.uuid4(), event_type, dedupe_key, status, session_id,
                    json.dumps(source_refs), _hash(content), now,
                ),
            )
            created = cur.fetchone() is not None
            conn.commit()
        return created

    def _event_by_dedupe(self, dedupe_key: str) -> dict[str, Any]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,event_type,status,target_session_id,source_refs,
                          content_sha256,created_at,delivered_at
                   FROM relationship_rhythm_events WHERE dedupe_key=%s""",
                (dedupe_key,),
            )
            return self._event_view(cur.fetchone())

    @staticmethod
    def _event_view(row: Any) -> dict[str, Any]:
        return {
            "event_id": str(row[0]), "event_type": row[1], "status": row[2],
            "target_session_id": str(row[3]) if row[3] else None,
            "source_refs": row[4] or [], "content_sha256": row[5],
            "created_at": row[6], "delivered_at": row[7],
        }


async def run_relationship_rhythms(
    sessions: SessionService,
    rhythms: RelationshipRhythmService,
    *,
    interval_seconds: int = 30,
    iterations: int | None = None,
) -> None:
    """Deliver due relationship messages only to the selected private web session."""

    import asyncio

    completed = 0
    while iterations is None or completed < iterations:
        result: dict[str, Any] | None = None
        try:
            result = rhythms.plan_due()
            if result.get("disposition") == "send":
                event = result["event"]
                session_id = event["target_session_id"]
                sessions.append_message(
                    session_id, "assistant", result["body"],
                    metadata={
                        "channel": "web", "proactive": True,
                        "relationship_rhythm": event["event_type"],
                        "relationship_event_id": event["event_id"],
                        "relationship_sources": event["source_refs"],
                    },
                )
                rhythms.mark_delivered(event["event_id"])
        except Exception:
            logger.exception("Relationship rhythm delivery failed")
            if result and result.get("event"):
                rhythms.mark_failed(result["event"]["event_id"])
        completed += 1
        if iterations is None or completed < iterations:
            await asyncio.sleep(interval_seconds)
