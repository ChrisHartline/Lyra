"""Configurable morning orientation and evening reflection rituals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import json
import uuid
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from .away import AwayModeService
from .briefings import BriefingService
from .db import connect


RITUAL_TYPES = frozenset({"morning", "evening"})


@dataclass(frozen=True)
class RitualPolicy:
    morning_enabled: bool
    evening_enabled: bool
    morning_time: time
    evening_time: time
    timezone: str
    channel: str
    notion_publish: bool
    vacation_until: date | None
    morning_snoozed_until: datetime | None
    evening_snoozed_until: datetime | None


@dataclass
class RitualService:
    briefing: BriefingService
    away: AwayModeService
    connection_factory: Callable[[], psycopg.Connection] = connect

    def get_policy(self) -> RitualPolicy:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT morning_enabled,evening_enabled,morning_time,
                evening_time,timezone,channel,notion_publish,vacation_until,
                morning_snoozed_until,evening_snoozed_until
                FROM ritual_policy WHERE singleton=true""")
            row = cur.fetchone()
        if not row:
            raise ValueError("Ritual policy is not initialized")
        return RitualPolicy(*row)

    def policy_dict(self) -> dict[str, Any]:
        return asdict(self.get_policy())

    def set_policy(self, **values: Any) -> RitualPolicy:
        current = self.policy_dict()
        unknown = set(values) - set(current)
        if unknown:
            raise ValueError(f"Unknown ritual settings: {sorted(unknown)}")
        current.update(values)
        try:
            ZoneInfo(str(current["timezone"]))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown ritual timezone") from exc
        if current["channel"] not in {"web", "telegram"}:
            raise ValueError("Ritual channel must be web or telegram")
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ritual_policy SET morning_enabled=%s,
                evening_enabled=%s,morning_time=%s,evening_time=%s,timezone=%s,
                channel=%s,notion_publish=%s,vacation_until=%s,
                morning_snoozed_until=%s,evening_snoozed_until=%s,updated_at=now()
                WHERE singleton=true""", tuple(current[key] for key in current))
            conn.commit()
        return self.get_policy()

    def snooze(self, ritual_type: str, until: datetime) -> RitualPolicy:
        kind = self._kind(ritual_type)
        if until.tzinfo is None or until <= datetime.now(UTC):
            raise ValueError("Ritual snooze must be a future timezone-aware time")
        return self.set_policy(**{f"{kind}_snoozed_until": until})

    def skip(self, ritual_type: str, *, now: datetime | None = None) -> dict[str, Any]:
        kind = self._kind(ritual_type)
        instant = now or datetime.now(UTC)
        policy = self.get_policy()
        local_date = instant.astimezone(ZoneInfo(policy.timezone)).date()
        return self._record(kind, local_date, "skipped", policy.channel, [], None)

    def build(self, ritual_type: str, *, now: datetime | None = None) -> dict[str, Any]:
        kind = self._kind(ritual_type)
        instant = now or datetime.now(UTC)
        policy = self.get_policy()
        local = instant.astimezone(ZoneInfo(policy.timezone))
        briefing = self.briefing.assemble("morning", as_of=local.date(), gather=True, for_notion=False)
        commitments = self._commitments()
        sessions = self._recent_sessions()
        source_items = [
            *(f"[commitment] {item}" for item in commitments),
            *(f"[session] {item}" for item in sessions),
            *(f"[{item['plane']}] {item['text']}" for item in briefing["bullets"]),
        ]
        if kind == "morning":
            opening = "Good morning. Here’s a calm orientation—not a demand list."
            closing = "What would make today feel well used?"
        else:
            opening = "Evening check-in. Here’s what may be worth carrying forward."
            closing = "What should we close, carry, or release tonight?"
        body = "\n".join([opening, "", *(source_items or ["[status] Nothing needs your attention."]), "", closing])
        return {"ritual_type": kind, "local_date": local.date(), "body": body,
                "source_planes": sorted({item.split("]", 1)[0][1:] for item in source_items})}

    def plan_due(self, ritual_type: str, *, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
        kind = self._kind(ritual_type)
        instant = now or datetime.now(UTC)
        policy = self.get_policy()
        local = instant.astimezone(ZoneInfo(policy.timezone))
        enabled = getattr(policy, f"{kind}_enabled")
        if not force and not enabled:
            return {"disposition": "disabled"}
        if policy.vacation_until and local.date() <= policy.vacation_until:
            return {"disposition": "vacation"}
        snoozed = getattr(policy, f"{kind}_snoozed_until")
        if snoozed and instant < snoozed:
            return {"disposition": "snoozed"}
        scheduled = getattr(policy, f"{kind}_time")
        if not force and local.timetz().replace(tzinfo=None) < scheduled:
            return {"disposition": "not_due"}
        existing = self._existing(kind, local.date())
        if existing:
            return {"disposition": "already_handled", "run": existing}
        draft = self.build(kind, now=instant)
        decision = self.away.plan_notification(
            channel=policy.channel, category="digest", content=draft["body"], now=instant
        )
        status = {"send": "planned", "batch": "batched", "suppress": "suppressed"}[decision.disposition]
        run = self._record(kind, local.date(), status, policy.channel,
                           draft["source_planes"], draft["body"])
        return {"disposition": decision.disposition, "draft": draft, "run": run,
                "notion_publish": policy.notion_publish}

    def mark_delivered(self, run_id: str, *, session_id: str | None = None) -> dict[str, Any]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ritual_runs SET status='delivered',session_id=%s,
                           delivered_at=now() WHERE id=%s AND status='planned'
                           RETURNING id,status,ritual_type,local_date,channel,source_planes""",
                        (session_id, run_id))
            row = cur.fetchone(); conn.commit()
        if not row:
            raise ValueError("Planned ritual run not found")
        return self._run_view(row)

    def mark_failed(self, run_id: str) -> None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ritual_runs SET status='failed' WHERE id=%s AND status='planned'",
                (run_id,),
            )
            conn.commit()

    def _commitments(self) -> list[str]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT summary FROM commitments WHERE status='active'
                           ORDER BY due_at NULLS LAST,updated_at DESC LIMIT 5""")
            return [str(row[0]) for row in cur.fetchall()]

    def _recent_sessions(self) -> list[str]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT name FROM chat_sessions s
                           WHERE updated_at >= now()-interval '2 days'
                             AND NOT EXISTS (
                               SELECT 1 FROM shared_journal_private_sessions p
                               WHERE p.session_id=s.id
                             )
                           ORDER BY updated_at DESC LIMIT 3""")
            return [str(row[0]) for row in cur.fetchall()]

    def _existing(self, kind: str, local_date: date) -> dict[str, Any] | None:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id,status,ritual_type,local_date,channel,source_planes
                           FROM ritual_runs WHERE ritual_type=%s AND local_date=%s""",
                        (kind, local_date)); row = cur.fetchone()
        return self._run_view(row) if row else None

    def _record(self, kind: str, local_date: date, status: str, channel: str,
                planes: list[str], content: str | None) -> dict[str, Any]:
        digest = hashlib.sha256(content.encode()).hexdigest() if content else None
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO ritual_runs
                (id,ritual_type,local_date,status,channel,source_planes,content_sha256)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (ritual_type,local_date) DO UPDATE SET status=EXCLUDED.status
                RETURNING id,status,ritual_type,local_date,channel,source_planes""",
                (uuid.uuid4(), kind, local_date, status, channel, json.dumps(planes), digest))
            row = cur.fetchone(); conn.commit()
        return self._run_view(row)

    @staticmethod
    def _run_view(row: Any) -> dict[str, Any]:
        return {"run_id": str(row[0]), "status": row[1], "ritual_type": row[2],
                "local_date": row[3], "channel": row[4], "source_planes": row[5] or []}

    @staticmethod
    def _kind(value: str) -> str:
        kind = value.strip().lower()
        if kind not in RITUAL_TYPES:
            raise ValueError("Ritual must be morning or evening")
        return kind
