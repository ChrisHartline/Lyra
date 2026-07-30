"""D5 — assistant briefing assembly across digest / observation / memory planes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import psycopg

from .db import connect
from .digests import DigestPublisher, _task_title
from .notion_sync import NotionClient
from .safety import is_notion_safe, safe_lines

BriefingPeriod = Literal["morning", "weekly"]

_STORY_CAMPAIGN_MARKERS = (
    "story canon",
    "campaign log",
    "phase regulator",
    "entanglement coil",
    "d20",
    "orc patrol",
    "initiative",
)


def _is_story_or_campaign(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _STORY_CAMPAIGN_MARKERS)


@dataclass
class BriefingBullet:
    plane: Literal["digest", "observation", "memory"]
    text: str

    def render(self) -> str:
        return f"- [{self.plane}] {self.text}"


@dataclass
class BriefingService:
    digests_database_id: str
    title_property: str = "Name"
    kg_memory_file: str | Path | None = None
    connection_factory: Callable[[], psycopg.Connection] = connect
    publisher: DigestPublisher | None = None

    def assemble(
        self,
        period: BriefingPeriod = "morning",
        *,
        as_of: date | None = None,
        digest_items: list[str] | None = None,
        observation_items: list[str] | None = None,
        memory_items: list[str] | None = None,
        gather: bool = True,
        for_notion: bool = False,
    ) -> dict[str, Any]:
        day = as_of or datetime.now(timezone.utc).date()
        digests = list(digest_items or [])
        observations = list(observation_items or [])
        memories = list(memory_items or [])

        if gather:
            if not digests:
                digests = self._gather_recent_digest_titles()
            if not observations:
                observations = self._gather_observations()
            if not memories:
                memories = self._gather_biography_memories()

        bullets: list[BriefingBullet] = []
        for text in digests:
            cleaned = self._sanitize(text, for_notion=for_notion)
            if cleaned:
                bullets.append(BriefingBullet(plane="digest", text=cleaned))
        for text in observations:
            cleaned = self._sanitize(text, for_notion=for_notion, block_story=True)
            if cleaned:
                bullets.append(BriefingBullet(plane="observation", text=cleaned))
        for text in memories:
            cleaned = self._sanitize(text, for_notion=for_notion, block_story=True)
            if cleaned:
                bullets.append(BriefingBullet(plane="memory", text=cleaned))

        title = f"Lyra {period} briefing — {day.isoformat()}"
        lines = [
            f"# {title}",
            "",
            "Each bullet cites its plane: digest / observation / memory.",
            "",
        ]
        if bullets:
            lines.extend(bullet.render() for bullet in bullets)
        else:
            lines.append("- (no briefing items)")

        body = "\n".join(lines)
        return {
            "period": period,
            "as_of": day.isoformat(),
            "title": title,
            "body": body,
            "bullets": [
                {"plane": bullet.plane, "text": bullet.text} for bullet in bullets
            ],
        }

    def publish_to_notion(
        self,
        period: BriefingPeriod = "morning",
        *,
        as_of: date | None = None,
        digest_type: str = "daily",
        digest_items: list[str] | None = None,
        observation_items: list[str] | None = None,
        memory_items: list[str] | None = None,
        gather: bool = True,
    ) -> dict[str, Any]:
        if self.publisher is None:
            raise ValueError("publisher is required to publish a briefing to Notion")
        briefing = self.assemble(
            period,
            as_of=as_of,
            digest_items=digest_items,
            observation_items=observation_items,
            memory_items=memory_items,
            gather=gather,
            for_notion=True,
        )
        created = self.publisher.create_digest_page(
            database_id=self.digests_database_id,
            title=briefing["title"],
            body=briefing["body"],
            source_links=[],
            title_property=self.title_property,
            digest_type=digest_type,
        )
        return {
            **briefing,
            "digest_id": created.get("id"),
            "digest_type": digest_type,
            "created": created,
        }

    def _sanitize(
        self,
        text: str,
        *,
        for_notion: bool,
        block_story: bool = False,
    ) -> str | None:
        cleaned_list = safe_lines([text], for_notion=for_notion)
        if not cleaned_list:
            return None
        cleaned = cleaned_list[0]
        if block_story and _is_story_or_campaign(cleaned):
            return None
        if for_notion and not is_notion_safe(cleaned):
            return None
        return cleaned

    def _gather_recent_digest_titles(self) -> list[str]:
        if not isinstance(self.publisher, NotionClient):
            return []
        result = self.publisher.query_database(self.digests_database_id, page_size=10)
        titles: list[str] = []
        for page in result.get("results", []):
            title = _task_title(page, self.title_property)
            if not title or not safe_lines([title], for_notion=True):
                continue
            if "briefing" in title.lower():
                continue
            titles.append(title)
        return titles[:5]

    def _gather_observations(self) -> list[str]:
        if not self.kg_memory_file:
            return []
        path = Path(self.kg_memory_file)
        if not path.exists():
            return []
        items: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "entity":
                continue
            name = row.get("name") or "entity"
            for observation in row.get("observations") or []:
                items.append(f"{name}: {observation}")
        return items

    def _gather_biography_memories(self) -> list[str]:
        items: list[str] = []
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT content
                    FROM memories
                    WHERE approved = true
                      AND COALESCE(metadata->>'ledger', 'biography') = 'biography'
                      AND COALESCE(memory_type, 'fact') NOT IN ('story', 'campaign', 'observation')
                    ORDER BY created_at DESC, id DESC
                    LIMIT 8
                    """
                )
                for (content,) in cur.fetchall():
                    items.append(str(content))
        return items
