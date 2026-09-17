"""Explicitly approved, local-only private shared journal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any, Callable
import uuid

import psycopg

from .db import connect
from .memory import validate_persistable_text


ENTRY_TYPES = frozenset({"moment", "reflection", "milestone"})
_FICTION = re.compile(
    r"\b(?:campaign|story canon|silentdrift|phase regulator|entanglement coil|"
    r"initiative|d20|orc patrol)\b",
    re.IGNORECASE,
)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _instant(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Journal time must be timezone-aware")
    return instant.astimezone(UTC)


def _journal_text(value: str, label: str) -> str:
    normalized = validate_persistable_text(value)
    if _FICTION.search(normalized):
        raise ValueError(f"{label} belongs in story or campaign continuity")
    return normalized


def _reason(value: str | None) -> str | None:
    if value is None:
        return None
    return _journal_text(value, "Journal audit reason")[:500]


def _entry(row: Any) -> dict[str, Any]:
    return {
        "journal_entry_id": str(row[0]),
        "entry_type": row[1],
        "title": row[2],
        "content": row[3],
        "source": {
            "session_id": str(row[4]) if row[4] else None,
            "message_id": int(row[5]) if row[5] is not None else None,
            "channel": row[6],
        },
        "created_by": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


@dataclass
class SharedJournalService:
    connection_factory: Callable[[], psycopg.Connection] = connect

    def create_entry(
        self,
        *,
        content: str,
        entry_type: str,
        approved: bool,
        title: str | None = None,
        source_session_id: str | None = None,
        source_message_id: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if approved is not True:
            raise ValueError("Shared journal creation requires explicit approval")
        normalized_type = entry_type.strip().lower()
        if normalized_type not in ENTRY_TYPES:
            raise ValueError("Journal type must be moment, reflection, or milestone")
        normalized_content = _journal_text(content, "Journal entry")
        normalized_title = _journal_text(title, "Journal title") if title else None
        if (source_session_id is None) != (source_message_id is None):
            raise ValueError("Journal source requires both session and message IDs")
        instant = _instant(now)
        entry_id = uuid.uuid4()
        source_channel: str | None = None
        has_source = source_session_id is not None
        with self.connection_factory() as conn, conn.cursor() as cur:
            if source_session_id is not None:
                cur.execute(
                    """SELECT m.metadata->>'channel'
                       FROM session_messages m
                       WHERE m.id=%s AND m.session_id=%s AND m.visible=true""",
                    (source_message_id, source_session_id),
                )
                source = cur.fetchone()
                if not source:
                    raise ValueError("Journal source message was not found in that session")
                source_channel = source[0]
            cur.execute(
                """INSERT INTO shared_journal_entries
                    (id,entry_type,title,content,source_session_id,source_message_id,
                     source_channel,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id,entry_type,title,content,source_session_id,
                              source_message_id,source_channel,created_by,
                              created_at,updated_at""",
                (
                    entry_id, normalized_type, normalized_title, normalized_content,
                    source_session_id, source_message_id, source_channel, instant, instant,
                ),
            )
            row = cur.fetchone()
            self._audit(
                cur, entry_id, "created", new_hash=_hash(normalized_content),
                details={"entry_type": normalized_type, "has_source": has_source},
                now=instant,
            )
            conn.commit()
        return _entry(row)

    def list_entries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,entry_type,title,content,source_session_id,
                          source_message_id,source_channel,created_by,created_at,updated_at
                   FROM shared_journal_entries
                   ORDER BY created_at DESC,id DESC LIMIT %s""",
                (min(500, max(1, limit)),),
            )
            return [_entry(row) for row in cur.fetchall()]

    def edit_entry(
        self,
        entry_id: str,
        *,
        content: str,
        title: str | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_content = _journal_text(content, "Journal entry")
        normalized_title = _journal_text(title, "Journal title") if title else None
        instant = _instant(now)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT content,title FROM shared_journal_entries WHERE id=%s FOR UPDATE",
                (entry_id,),
            )
            existing = cur.fetchone()
            if not existing:
                raise ValueError("Shared journal entry not found")
            cur.execute(
                """UPDATE shared_journal_entries SET content=%s,title=%s,updated_at=%s
                   WHERE id=%s
                   RETURNING id,entry_type,title,content,source_session_id,
                             source_message_id,source_channel,created_by,
                             created_at,updated_at""",
                (normalized_content, normalized_title, instant, entry_id),
            )
            row = cur.fetchone()
            self._audit(
                cur, uuid.UUID(entry_id), "edited", reason=_reason(reason),
                old_hash=_hash(existing[0]), new_hash=_hash(normalized_content), now=instant,
                details={
                    "old_title_sha256": _hash(existing[1]) if existing[1] else None,
                    "new_title_sha256": _hash(normalized_title) if normalized_title else None,
                },
            )
            conn.commit()
        return _entry(row)

    def forget_entry(
        self,
        entry_id: str,
        *,
        confirmed: bool,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise ValueError("Forgetting a journal entry requires confirmation")
        instant = _instant(now)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM shared_journal_entries WHERE id=%s FOR UPDATE",
                (entry_id,),
            )
            existing = cur.fetchone()
            if not existing:
                raise ValueError("Shared journal entry not found")
            self._audit(
                cur, uuid.UUID(entry_id), "forgotten", reason=_reason(reason),
                old_hash=_hash(existing[0]), now=instant,
            )
            cur.execute("DELETE FROM shared_journal_entries WHERE id=%s", (entry_id,))
            conn.commit()
        return {"journal_entry_id": str(entry_id), "status": "forgotten"}

    def authorize_session(
        self, session_id: str, *, enabled: bool, now: datetime | None = None
    ) -> dict[str, Any]:
        instant = _instant(now)
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM chat_sessions WHERE id=%s FOR UPDATE", (session_id,)
            )
            if not cur.fetchone():
                raise ValueError("Session not found")
            if enabled:
                cur.execute(
                    """SELECT 1 FROM session_channels
                       WHERE session_id=%s AND channel='telegram'""",
                    (session_id,),
                )
                if cur.fetchone():
                    raise ValueError("Telegram-bound sessions cannot access the shared journal")
                cur.execute(
                    """INSERT INTO shared_journal_private_sessions
                        (session_id,authorized_at) VALUES (%s,%s)
                       ON CONFLICT(session_id) DO UPDATE
                       SET authorized_at=EXCLUDED.authorized_at""",
                    (session_id, instant),
                )
            else:
                cur.execute(
                    "DELETE FROM shared_journal_private_sessions WHERE session_id=%s",
                    (session_id,),
                )
            conn.commit()
        return {"session_id": str(session_id), "private_shared": bool(enabled)}

    def session_access(self, session_id: str) -> dict[str, Any]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT s.id,p.authorized_at
                   FROM chat_sessions s LEFT JOIN shared_journal_private_sessions p
                     ON p.session_id=s.id WHERE s.id=%s""",
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("Session not found")
        return {"session_id": str(row[0]), "private_shared": row[1] is not None,
                "authorized_at": row[1]}

    def context_entries(self, session_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM shared_journal_private_sessions WHERE session_id=%s",
                (session_id,),
            )
            if not cur.fetchone():
                return []
            cur.execute(
                """SELECT id,entry_type,title,left(content,1200),
                          length(content)>1200,created_at
                   FROM shared_journal_entries ORDER BY created_at DESC,id DESC LIMIT %s""",
                (min(20, max(1, limit)),),
            )
            return [
                {"journal_entry_id": str(row[0]), "entry_type": row[1],
                 "title": row[2], "content": row[3], "content_truncated": row[4],
                 "created_at": row[5]}
                for row in cur.fetchall()
            ]

    def list_audit(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,journal_entry_id,action,actor,reason,
                          old_content_sha256,new_content_sha256,details,created_at
                   FROM shared_journal_audit ORDER BY created_at DESC,id DESC LIMIT %s""",
                (min(500, max(1, limit)),),
            )
            return [
                {"audit_id": int(row[0]), "journal_entry_id": str(row[1]),
                 "action": row[2], "actor": row[3], "reason": row[4],
                 "old_content_sha256": row[5], "new_content_sha256": row[6],
                 "details": row[7] or {}, "created_at": row[8]}
                for row in cur.fetchall()
            ]

    @staticmethod
    def _audit(
        cur: psycopg.Cursor,
        entry_id: uuid.UUID,
        action: str,
        *,
        reason: str | None = None,
        old_hash: str | None = None,
        new_hash: str | None = None,
        details: dict[str, Any] | None = None,
        now: datetime,
    ) -> None:
        cur.execute(
            """INSERT INTO shared_journal_audit
                (journal_entry_id,action,reason,old_content_sha256,
                 new_content_sha256,details,created_at)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)""",
            (entry_id, action, reason, old_hash, new_hash,
             json.dumps(details or {}, sort_keys=True), now),
        )
