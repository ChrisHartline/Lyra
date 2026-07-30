"""D2 — daily / weekly digest generation for Notion Digests DB."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Literal, Protocol

import psycopg

from .db import connect
from .memory import _contains_sensitive
from .notion_sync import NotionClient

DigestPeriod = Literal["daily", "weekly"]


class DigestPublisher(Protocol):
    def create_digest_page(
        self,
        database_id: str,
        title: str,
        body: str,
        source_links: list[str],
        title_property: str = "Name",
        digest_type: str | None = None,
        related_task_page_id: str | None = None,
    ) -> dict: ...


def _safe_lines(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        text = " ".join(str(item).split()).strip()
        if not text or _contains_sensitive(text):
            continue
        out.append(text)
    return out


def _task_title(page: dict[str, Any], title_property: str = "Project name") -> str | None:
    props = page.get("properties") or {}
    title_prop = props.get(title_property) or props.get("Name") or props.get("title")
    if not isinstance(title_prop, dict):
        return None
    bits = title_prop.get("title") or []
    if not bits:
        return None
    text = bits[0].get("plain_text")
    return text.strip() if text else None


@dataclass
class DigestDraft:
    period: DigestPeriod
    as_of: date
    title: str
    body: str
    source_links: list[str] = field(default_factory=list)
    digest_type: DigestPeriod = "daily"


@dataclass
class DigestService:
    publisher: DigestPublisher
    digests_database_id: str
    title_property: str = "Name"
    tasks_database_id: str | None = None
    task_title_property: str = "Project name"
    connection_factory: Callable[[], psycopg.Connection] = connect
    corpus_query: str = "recent research progress"

    def build_body(
        self,
        period: DigestPeriod,
        as_of: date,
        *,
        personal_items: list[str] | None = None,
        professional_items: list[str] | None = None,
        corpus_items: list[str] | None = None,
        memory_items: list[str] | None = None,
        task_items: list[str] | None = None,
    ) -> str:
        window = self._window_label(period, as_of)
        sections = [
            f"# Lyra {period.capitalize()} Digest — {as_of.isoformat()}",
            f"Window: {window}",
            "",
            "## Personal",
        ]
        personal = _safe_lines(personal_items or [])
        if personal:
            sections.extend(f"- {line}" for line in personal)
        else:
            sections.append("- (none)")

        sections.extend(["", "## Professional"])
        professional = _safe_lines((professional_items or []) + (task_items or []))
        if professional:
            sections.extend(f"- {line}" for line in professional)
        else:
            sections.append("- (none)")

        sections.extend(["", "## Corpus"])
        corpus = _safe_lines(corpus_items or [])
        if corpus:
            sections.extend(f"- {line}" for line in corpus)
        else:
            sections.append("- (none)")

        sections.extend(["", "## Approved memories"])
        memories = _safe_lines(memory_items or [])
        if memories:
            sections.extend(f"- {line}" for line in memories)
        else:
            sections.append("- (none)")

        body = "\n".join(sections)
        if _contains_sensitive(body):
            raise ValueError("Digest body still contains never-persist material after filtering")
        return body

    def draft(
        self,
        period: DigestPeriod,
        *,
        as_of: date | None = None,
        personal_items: list[str] | None = None,
        professional_items: list[str] | None = None,
        gather: bool = True,
    ) -> DigestDraft:
        day = as_of or datetime.now(timezone.utc).date()
        task_items: list[str] = []
        corpus_items: list[str] = []
        memory_items: list[str] = []
        source_links: list[str] = []

        if gather:
            task_items = self._gather_tasks()
            corpus_items, source_links = self._gather_corpus()
            memory_items = self._gather_memories()

        body = self.build_body(
            period,
            day,
            personal_items=personal_items,
            professional_items=professional_items,
            corpus_items=corpus_items,
            memory_items=memory_items,
            task_items=task_items,
        )
        title = f"Lyra {period} digest — {day.isoformat()}"
        return DigestDraft(
            period=period,
            as_of=day,
            title=title,
            body=body,
            source_links=source_links,
            digest_type=period,
        )

    def publish(
        self,
        period: DigestPeriod,
        *,
        as_of: date | None = None,
        personal_items: list[str] | None = None,
        professional_items: list[str] | None = None,
        gather: bool = True,
    ) -> dict[str, Any]:
        draft = self.draft(
            period,
            as_of=as_of,
            personal_items=personal_items,
            professional_items=professional_items,
            gather=gather,
        )
        created = self.publisher.create_digest_page(
            database_id=self.digests_database_id,
            title=draft.title,
            body=draft.body,
            source_links=draft.source_links,
            title_property=self.title_property,
            digest_type=draft.digest_type,
        )
        return {
            "digest_id": created.get("id"),
            "period": period,
            "digest_type": draft.digest_type,
            "title": draft.title,
            "body": draft.body,
            "parent": created.get("parent"),
            "created": created,
        }

    def _window_label(self, period: DigestPeriod, as_of: date) -> str:
        if period == "daily":
            return as_of.isoformat()
        start = as_of - timedelta(days=6)
        return f"{start.isoformat()} → {as_of.isoformat()}"

    def _gather_tasks(self) -> list[str]:
        if not self.tasks_database_id or not isinstance(self.publisher, NotionClient):
            return []
        result = self.publisher.query_database(self.tasks_database_id, page_size=20)
        titles: list[str] = []
        for page in result.get("results", []):
            title = _task_title(page, self.task_title_property)
            if title and not _contains_sensitive(title):
                titles.append(title)
        return titles

    def _gather_corpus(self) -> tuple[list[str], list[str]]:
        items: list[str] = []
        links: list[str] = []
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(title, url, file_path, 'untitled'), url
                    FROM sources
                    WHERE superseded_by IS NULL
                    ORDER BY fetched_at DESC NULLS LAST, id DESC
                    LIMIT 5
                    """
                )
                for title, url in cur.fetchall():
                    text = str(title)
                    if _contains_sensitive(text):
                        continue
                    items.append(text)
                    if url and not _contains_sensitive(url):
                        links.append(url)
        return items, links

    def _gather_memories(self) -> list[str]:
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
                    text = str(content)
                    if _contains_sensitive(text):
                        continue
                    items.append(text)
        return items
