"""Read-only, time-bounded re-engagement synthesis for W7.2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

import psycopg

from .db import connect
from .digests import _task_title
from .notion_sync import NotionClient


_REQUEST = re.compile(r"^\s*(?:/catchup|catch\s+me\s+up)\b(?P<rest>.*)$", re.IGNORECASE)
_LAST = re.compile(r"^(?:the\s+)?last\s+(\d+)\s+(hour|day|week)s?$", re.IGNORECASE)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


@dataclass(frozen=True)
class CatchUpRequest:
    since: datetime
    until: datetime
    mode: str
    boundary_text: str


@dataclass(frozen=True)
class CatchUpItem:
    text: str
    occurred_at: datetime
    citations: tuple[str, ...]


class ChangeReader(Protocol):
    def changes(self, since: datetime, until: datetime) -> tuple[list[CatchUpItem], list[str]]: ...


@dataclass
class NotionChangeReader:
    client: NotionClient
    projects_database_id: str | None
    digests_database_id: str | None
    project_title_property: str = "Project name"
    digest_title_property: str = "Name"

    def changes(self, since: datetime, until: datetime) -> tuple[list[CatchUpItem], list[str]]:
        items: list[CatchUpItem] = []
        statuses: list[str] = []
        configurations = (
            ("project", self.projects_database_id, self.project_title_property),
            ("digest", self.digests_database_id, self.digest_title_property),
        )
        for plane, database_id, title_property in configurations:
            if not database_id:
                statuses.append(f"[integration:{plane}] unavailable: database is not configured")
                continue
            try:
                result = self.client.query_database(database_id, page_size=100)
            except Exception as exc:
                statuses.append(
                    f"[integration:{plane}] inaccessible: {type(exc).__name__}; no changes inferred"
                )
                continue
            newest: datetime | None = None
            for page in result.get("results", []):
                changed = _aware(page.get("last_edited_time") or page.get("created_time"))
                if changed is None:
                    continue
                newest = max(newest, changed) if newest else changed
                if not since <= changed <= until:
                    continue
                title = _task_title(page, title_property)
                if not title:
                    continue
                page_id = str(page.get("id") or "unknown")
                url = str(page.get("url") or "").strip()
                reference = url or f"notion:{page_id}"
                items.append(CatchUpItem(
                    text=f"{plane.title()} updated: {title}",
                    occurred_at=changed,
                    citations=(f"{plane}:{reference}@{changed.isoformat()}",),
                ))
            if newest and newest < until - timedelta(days=30):
                statuses.append(
                    f"[integration:{plane}] stale: newest visible change is {newest.date().isoformat()}"
                )
        return items, statuses


@dataclass
class CatchUpService:
    connection_factory: Callable[[], psycopg.Connection] = connect
    change_reader: ChangeReader | None = None
    timezone: str = "America/Chicago"

    def respond(
        self,
        text: str,
        *,
        memory_buckets: Sequence[str] = ("biography",),
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        match = _REQUEST.match(text)
        if not match:
            return None
        try:
            request = self._parse(match.group("rest"), instant)
        except ValueError as exc:
            return {
                "mode": "concise",
                "since": None,
                "until": instant,
                "body": (
                    f"I couldn't determine the time boundary: {exc}. "
                    "Try “catch me up since yesterday,” “catch me up for the last 3 days,” "
                    "or “catch me up since 2026-09-10.”"
                ),
                "items": [],
                "integration_status": [],
            }
        return self.synthesize(request, memory_buckets=memory_buckets)

    def synthesize(
        self,
        request: CatchUpRequest,
        *,
        memory_buckets: Sequence[str] = ("biography",),
    ) -> dict[str, Any]:
        items = self._local_changes(request.since, request.until, memory_buckets)
        statuses: list[str] = []
        if self.change_reader is None:
            statuses.extend([
                "[integration:project] unavailable: external project reader is not configured",
                "[integration:digest] unavailable: external digest reader is not configured",
            ])
        else:
            external, statuses = self.change_reader.changes(request.since, request.until)
            items.extend(external)
        merged = _merge(items)
        limit = 8 if request.mode == "concise" else 30
        visible = merged[:limit]
        lines = [
            f"Here’s what changed since {request.boundary_text} "
            f"({request.since.isoformat()} through {request.until.isoformat()}):",
            "",
        ]
        if visible:
            for item in visible:
                citations = " ".join(f"[{citation}]" for citation in item.citations)
                timestamp = f" {item.occurred_at.isoformat()} —" if request.mode == "deep" else ""
                lines.append(f"-{timestamp} {item.text} {citations}")
            if len(merged) > limit:
                lines.append(f"- [status] {len(merged) - limit} additional changes omitted in concise mode")
        else:
            lines.append("- [status] No qualifying changes were recorded in that window.")
        if statuses:
            lines.extend(["", "Integration notes:", *(f"- {status}" for status in statuses)])
        return {
            "mode": request.mode,
            "since": request.since,
            "until": request.until,
            "body": "\n".join(lines),
            "items": [
                {"text": item.text, "occurred_at": item.occurred_at,
                 "citations": list(item.citations)} for item in visible
            ],
            "integration_status": statuses,
        }

    def _parse(self, rest: str, now: datetime) -> CatchUpRequest:
        value = rest.strip()
        mode = "deep" if re.search(r"\b(deep|detailed|in detail)\b", value, re.I) else "concise"
        value = re.sub(r"\b(deep|detailed|in detail|concise|briefly)\b", "", value, flags=re.I)
        value = re.sub(r"(?:,?\s+please)\s*[.!?]*$", "", value, flags=re.I)
        value = re.sub(r"^(?:since|from|for)\s+", "", value.strip(), flags=re.I).strip(" .,?")
        boundary = value or "the last 24 hours"
        since = self._boundary(boundary, now)
        if since >= now:
            raise ValueError("the boundary must be earlier than now")
        return CatchUpRequest(since=since, until=now, mode=mode, boundary_text=boundary)

    def _boundary(self, value: str, now: datetime) -> datetime:
        local_now = now.astimezone(ZoneInfo(self.timezone))
        lowered = value.lower()
        if lowered in {"the last 24 hours", "last 24 hours"}:
            return now - timedelta(hours=24)
        if lowered == "today":
            return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        if lowered == "yesterday":
            return (local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=1)).astimezone(UTC)
        match = _LAST.match(lowered)
        if match:
            count = int(match.group(1))
            if count < 1 or count > 365:
                raise ValueError("relative windows must be between 1 and 365 units")
            unit = match.group(2).lower()
            return now - timedelta(**{f"{unit}s": count})
        weekday_text = lowered.removeprefix("last ")
        if weekday_text in _WEEKDAYS:
            days = (local_now.weekday() - _WEEKDAYS[weekday_text]) % 7
            if lowered.startswith("last ") and days == 0:
                days = 7
            return (local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=days)).astimezone(UTC)
        parsed = _aware(value)
        if parsed is None:
            raise ValueError(f'“{value}” is not a supported date or relative window')
        if parsed.tzinfo == UTC and "T" not in value and "+" not in value and not value.endswith("Z"):
            parsed = parsed.replace(tzinfo=ZoneInfo(self.timezone)).astimezone(UTC)
        return parsed.astimezone(UTC)

    def _local_changes(
        self, since: datetime, until: datetime, memory_buckets: Sequence[str]
    ) -> list[CatchUpItem]:
        items: list[CatchUpItem] = []
        buckets = tuple(dict.fromkeys(str(bucket) for bucket in memory_buckets)) or ("biography",)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id,name,synopsis,updated_at FROM chat_sessions
                WHERE updated_at >= %s AND updated_at <= %s ORDER BY updated_at DESC""",
                        (since, until))
            for session_id, name, synopsis, changed in cur.fetchall():
                detail = str(synopsis).strip() if synopsis else "activity recorded"
                items.append(CatchUpItem(
                    f"Session “{name}”: {detail}", changed,
                    (f"session:{session_id}@{changed.isoformat()}",),
                ))
            cur.execute("""SELECT id,summary,status,due_at,updated_at FROM commitments
                WHERE updated_at >= %s AND updated_at <= %s ORDER BY updated_at DESC""",
                        (since, until))
            for item_id, summary, status, due_at, changed in cur.fetchall():
                due = f"; due {due_at.isoformat()}" if due_at else ""
                items.append(CatchUpItem(
                    f"Commitment {status}: {summary}{due}", changed,
                    (f"commitment:{item_id}@{changed.isoformat()}",),
                ))
            cur.execute("""SELECT id,content,created_at FROM memories
                WHERE approved=true AND review_status='approved'
                  AND created_at >= %s AND created_at <= %s
                  AND COALESCE(metadata->>'ledger','biography') = ANY(%s)
                ORDER BY created_at DESC""", (since, until, list(buckets)))
            for memory_id, content, changed in cur.fetchall():
                items.append(CatchUpItem(
                    f"Approved memory: {content}", changed,
                    (f"memory:{memory_id}@{changed.isoformat()}",),
                ))
        return items


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.strip() + "T00:00:00")
            except ValueError:
                return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _merge(items: Iterable[CatchUpItem]) -> list[CatchUpItem]:
    merged: dict[str, CatchUpItem] = {}
    for item in sorted(items, key=lambda candidate: candidate.occurred_at, reverse=True):
        comparable = re.sub(
            r"^(?:session\s+.*?|commitment\s+\w+|approved\s+memory|"
            r"project\s+updated|digest\s+updated)\s*:\s*",
            "",
            item.text,
            flags=re.IGNORECASE,
        )
        key = re.sub(r"[^a-z0-9]+", " ", comparable.lower()).strip()
        previous = merged.get(key)
        if previous is None:
            merged[key] = item
            continue
        citations = tuple(dict.fromkeys((*previous.citations, *item.citations)))
        merged[key] = CatchUpItem(previous.text, max(previous.occurred_at, item.occurred_at), citations)
    return sorted(merged.values(), key=lambda candidate: candidate.occurred_at, reverse=True)
