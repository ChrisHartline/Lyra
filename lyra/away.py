"""Persistent channel presentation and Away Mode delivery policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from lyra.db import connect


PRESENTATION_MODES = frozenset({"standard", "concise"})
URGENT_CATEGORIES = frozenset(
    {"security", "safety", "service_failure", "user_requested"}
)
NON_URGENT_CATEGORIES = frozenset(
    {"digest", "commitment", "research", "social", "status"}
)
NOTIFICATION_CATEGORIES = URGENT_CATEGORIES | NON_URGENT_CATEGORIES


@dataclass(frozen=True)
class AwayPolicy:
    enabled: bool
    quiet_start: time | None
    quiet_end: time | None
    timezone: str
    daily_notification_budget: int


@dataclass(frozen=True)
class NotificationDecision:
    disposition: str
    reason: str
    category: str


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {name}") from exc


def _in_quiet_hours(value: time, start: time | None, end: time | None) -> bool:
    if start is None and end is None:
        return False
    if start is None or end is None:
        raise ValueError("Quiet hours require both a start and end")
    if start == end:
        return True
    if start < end:
        return start <= value < end
    return value >= start or value < end


@dataclass
class AwayModeService:
    connection_factory: Callable[[], psycopg.Connection] = connect

    def get_policy(self) -> AwayPolicy:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO away_policy (singleton)
                    VALUES (true)
                    ON CONFLICT (singleton) DO NOTHING
                    """
                )
                cur.execute(
                    """
                    SELECT enabled, quiet_start, quiet_end, timezone,
                           daily_notification_budget
                    FROM away_policy WHERE singleton = true
                    """
                )
                row = cur.fetchone()
            conn.commit()
        return AwayPolicy(bool(row[0]), row[1], row[2], row[3], int(row[4]))

    def set_policy(
        self,
        *,
        enabled: bool,
        quiet_start: time | None,
        quiet_end: time | None,
        timezone: str,
        daily_notification_budget: int,
    ) -> AwayPolicy:
        if (quiet_start is None) != (quiet_end is None):
            raise ValueError("Quiet hours require both a start and end")
        normalized_zone = timezone.strip()
        _zone(normalized_zone)
        if daily_notification_budget < 0:
            raise ValueError("Daily notification budget must not be negative")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO away_policy
                        (singleton, enabled, quiet_start, quiet_end, timezone,
                         daily_notification_budget, updated_at)
                    VALUES (true, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (singleton) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        quiet_start = EXCLUDED.quiet_start,
                        quiet_end = EXCLUDED.quiet_end,
                        timezone = EXCLUDED.timezone,
                        daily_notification_budget = EXCLUDED.daily_notification_budget,
                        updated_at = now()
                    """,
                    (
                        enabled,
                        quiet_start,
                        quiet_end,
                        normalized_zone,
                        daily_notification_budget,
                    ),
                )
            conn.commit()
        return self.get_policy()

    def get_channel_preference(self, channel: str) -> dict[str, str]:
        normalized = channel.strip().lower()
        if not normalized:
            raise ValueError("Channel must not be empty")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT presentation_mode FROM channel_preferences WHERE channel = %s",
                    (normalized,),
                )
                row = cur.fetchone()
        return {
            "channel": normalized,
            "presentation_mode": row[0] if row else "standard",
        }

    def set_channel_preference(self, channel: str, mode: str) -> dict[str, str]:
        normalized_channel = channel.strip().lower()
        normalized_mode = mode.strip().lower()
        if not normalized_channel:
            raise ValueError("Channel must not be empty")
        if normalized_mode not in PRESENTATION_MODES:
            raise ValueError("Presentation mode must be standard or concise")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO channel_preferences
                        (channel, presentation_mode, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (channel) DO UPDATE SET
                        presentation_mode = EXCLUDED.presentation_mode,
                        updated_at = now()
                    """,
                    (normalized_channel, normalized_mode),
                )
            conn.commit()
        return self.get_channel_preference(normalized_channel)

    def presentation_instruction(self, channel: str) -> str | None:
        mode = self.get_channel_preference(channel)["presentation_mode"]
        if self.get_policy().enabled or mode == "concise":
            return (
                "Channel presentation mode is concise. Keep the reply brief and "
                "easy to scan while preserving Lyra's identity, warmth, safety, "
                "memory rules, and the full stored meaning of the conversation."
            )
        return None

    def plan_notification(
        self,
        *,
        channel: str,
        category: str,
        content: str,
        now: datetime | None = None,
    ) -> NotificationDecision:
        normalized_category = category.strip().lower()
        if normalized_category not in NOTIFICATION_CATEGORIES:
            raise ValueError(f"Unknown notification category: {category}")
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Notification content must not be empty")
        policy = self.get_policy()
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("Notification time must be timezone-aware")
        local = instant.astimezone(_zone(policy.timezone))

        if normalized_category in URGENT_CATEGORIES:
            decision = NotificationDecision("send", "urgent_category", normalized_category)
        elif not policy.enabled:
            decision = NotificationDecision("send", "away_mode_disabled", normalized_category)
        elif _in_quiet_hours(
            local.timetz().replace(tzinfo=None),
            policy.quiet_start,
            policy.quiet_end,
        ):
            decision = NotificationDecision("batch", "quiet_hours", normalized_category)
        elif self._sent_today(local) >= policy.daily_notification_budget:
            decision = NotificationDecision(
                "suppress", "daily_budget_exhausted", normalized_category
            )
        else:
            decision = NotificationDecision("send", "within_budget", normalized_category)

        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notification_events
                        (channel, category, disposition, reason, content, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        channel.strip().lower(),
                        decision.category,
                        decision.disposition,
                        decision.reason,
                        normalized_content,
                        instant,
                    ),
                )
            conn.commit()
        return decision

    def _sent_today(self, local: datetime) -> int:
        start_local = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
        end_local = datetime.combine(
            local.date() + timedelta(days=1), time.min, tzinfo=local.tzinfo
        )
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM notification_events
                    WHERE disposition = 'send'
                      AND NOT (category = ANY(%s))
                      AND created_at >= %s AND created_at < %s
                    """,
                    (list(URGENT_CATEGORIES), start_local, end_local),
                )
                return int(cur.fetchone()[0])

    def list_batched(self) -> list[dict[str, Any]]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, channel, category, reason, content, created_at
                    FROM notification_events
                    WHERE disposition = 'batch'
                    ORDER BY created_at, id
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "id": int(row[0]),
                "channel": row[1],
                "category": row[2],
                "reason": row[3],
                "content": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    def policy_dict(self) -> dict[str, Any]:
        return asdict(self.get_policy())
