"""Persistent chat sessions and bounded runtime-context assembly."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from lyra.db import connect


TURN_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "disconnected",
}
FINAL_TURN_STATUSES = {"completed", "failed", "cancelled"}
MESSAGE_ROLES = {"system", "user", "assistant", "tool"}


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _session(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "session_id": str(row[0]),
        "name": row[1],
        "synopsis": row[2],
        "synopsis_through_sequence": int(row[3]),
        "created_at": row[4],
        "updated_at": row[5],
    }


def _message(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "message_id": int(row[0]),
        "session_id": str(row[1]),
        "sequence": int(row[2]),
        "role": row[3],
        "content": row[4],
        "visible": bool(row[5]),
        "metadata": row[6] or {},
        "created_at": row[7],
    }


@dataclass
class SessionService:
    connection_factory: Callable[[], psycopg.Connection] = connect

    def create_session(self, name: str) -> dict[str, Any]:
        session_id = uuid.uuid4()
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_sessions (id, name)
                    VALUES (%s, %s)
                    RETURNING id, name, synopsis, synopsis_through_sequence,
                              created_at, updated_at
                    """,
                    (session_id, _required_text(name, "Session name")),
                )
                row = cur.fetchone()
            conn.commit()
        return _session(row)

    def get_session(self, session_id: str | uuid.UUID) -> dict[str, Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, synopsis, synopsis_through_sequence,
                           created_at, updated_at
                    FROM chat_sessions
                    WHERE id = %s
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError(f"Session not found: {session_id}")
        return _session(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, synopsis, synopsis_through_sequence,
                           created_at, updated_at
                    FROM chat_sessions
                    ORDER BY updated_at DESC, created_at DESC
                    """
                )
                rows = cur.fetchall()
        return [_session(row) for row in rows]

    def rename_session(
        self, session_id: str | uuid.UUID, name: str
    ) -> dict[str, Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE chat_sessions
                    SET name = %s, updated_at = now()
                    WHERE id = %s
                    RETURNING id, name, synopsis, synopsis_through_sequence,
                              created_at, updated_at
                    """,
                    (_required_text(name, "Session name"), session_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError(f"Session not found: {session_id}")
        return _session(row)

    def delete_session(self, session_id: str | uuid.UUID) -> bool:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
                deleted = cur.rowcount == 1
            conn.commit()
        return deleted

    def append_message(
        self,
        session_id: str | uuid.UUID,
        role: str,
        content: str,
        *,
        visible: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in MESSAGE_ROLES:
            raise ValueError(f"Unsupported message role: {role}")
        normalized = _required_text(content, "Message content")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM chat_sessions WHERE id = %s FOR UPDATE",
                    (session_id,),
                )
                if not cur.fetchone():
                    raise ValueError(f"Session not found: {session_id}")
                cur.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1
                    FROM session_messages
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                sequence = int(cur.fetchone()[0])
                cur.execute(
                    """
                    INSERT INTO session_messages
                        (session_id, sequence, role, content, visible, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id, session_id, sequence, role, content, visible,
                              metadata, created_at
                    """,
                    (
                        session_id,
                        sequence,
                        role,
                        normalized,
                        visible,
                        json.dumps(dict(metadata or {})),
                    ),
                )
                row = cur.fetchone()
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = now() WHERE id = %s",
                    (session_id,),
                )
            conn.commit()
        return _message(row)

    def list_messages(
        self,
        session_id: str | uuid.UUID,
        *,
        visible_only: bool = True,
        after_sequence: int = 0,
    ) -> list[dict[str, Any]]:
        visible_filter = "AND visible = true" if visible_only else ""
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, session_id, sequence, role, content, visible,
                           metadata, created_at
                    FROM session_messages
                    WHERE session_id = %s
                      AND sequence > %s
                      {visible_filter}
                    ORDER BY sequence
                    """,
                    (session_id, after_sequence),
                )
                rows = cur.fetchall()
        return [_message(row) for row in rows]

    def set_synopsis(
        self,
        session_id: str | uuid.UUID,
        synopsis: str | None,
        through_sequence: int,
    ) -> dict[str, Any]:
        normalized = synopsis.strip() if synopsis else None
        if through_sequence < 0:
            raise ValueError("Synopsis sequence must not be negative")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0)
                    FROM session_messages
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                maximum = int(cur.fetchone()[0])
                if through_sequence > maximum:
                    raise ValueError("Synopsis sequence exceeds session history")
                cur.execute(
                    """
                    UPDATE chat_sessions
                    SET synopsis = %s,
                        synopsis_through_sequence = %s,
                        updated_at = now()
                    WHERE id = %s
                    RETURNING id, name, synopsis, synopsis_through_sequence,
                              created_at, updated_at
                    """,
                    (normalized, through_sequence, session_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError(f"Session not found: {session_id}")
        return _session(row)

    def bind_channel(
        self,
        session_id: str | uuid.UUID,
        channel: str,
        external_id: str,
    ) -> dict[str, str]:
        channel = _required_text(channel, "Channel").lower()
        external_id = _required_text(external_id, "External channel id")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM chat_sessions WHERE id=%s FOR UPDATE",
                    (session_id,),
                )
                if not cur.fetchone():
                    raise ValueError(f"Session not found: {session_id}")
                if channel == "telegram":
                    cur.execute(
                        """SELECT 1 FROM shared_journal_private_sessions
                           WHERE session_id=%s""",
                        (session_id,),
                    )
                    if cur.fetchone():
                        raise ValueError(
                            "Private shared journal sessions cannot bind to Telegram"
                        )
                cur.execute(
                    """
                    DELETE FROM session_channels
                    WHERE channel = %s AND external_id = %s AND session_id <> %s
                    """,
                    (channel, external_id, session_id),
                )
                cur.execute(
                    """
                    INSERT INTO session_channels (session_id, channel, external_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id, channel)
                    DO UPDATE SET external_id = EXCLUDED.external_id
                    RETURNING session_id, channel, external_id
                    """,
                    (session_id, channel, external_id),
                )
                row = cur.fetchone()
            conn.commit()
        return {
            "session_id": str(row[0]),
            "channel": row[1],
            "external_id": row[2],
        }

    def list_channels(self, session_id: str | uuid.UUID) -> list[dict[str, str]]:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, channel, external_id
                    FROM session_channels
                    WHERE session_id = %s
                    ORDER BY channel
                    """,
                    (session_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "session_id": str(row[0]),
                "channel": row[1],
                "external_id": row[2],
            }
            for row in rows
        ]

    def resolve_channel(self, channel: str, external_id: str) -> str | None:
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id
                    FROM session_channels
                    WHERE channel = %s AND external_id = %s
                    """,
                    (channel.strip().lower(), external_id.strip()),
                )
                row = cur.fetchone()
        return str(row[0]) if row else None

    def start_turn(
        self, session_id: str | uuid.UUID, status: str = "pending"
    ) -> dict[str, Any]:
        if status not in {"pending", "running"}:
            raise ValueError(f"Invalid initial turn status: {status}")
        turn_id = uuid.uuid4()
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO session_turns (id, session_id, status)
                    VALUES (%s, %s, %s)
                    RETURNING id, session_id, status, error_code,
                              started_at, finished_at
                    """,
                    (turn_id, session_id, status),
                )
                row = cur.fetchone()
            conn.commit()
        return self._turn(row)

    def recover_interrupted_turns(
        self, session_id: str | uuid.UUID | None = None
    ) -> int:
        session_filter = "AND session_id = %s" if session_id is not None else ""
        params: tuple[Any, ...] = (session_id,) if session_id is not None else ()
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE session_turns
                    SET status = 'disconnected', error_code = 'runtime_interrupted'
                    WHERE status IN ('pending', 'running')
                    {session_filter}
                    """,
                    params,
                )
                recovered = cur.rowcount
            conn.commit()
        return recovered

    def update_turn(
        self,
        turn_id: str | uuid.UUID,
        status: str,
        *,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        if status not in TURN_STATUSES:
            raise ValueError(f"Invalid turn status: {status}")
        with self.connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE session_turns
                    SET status = %s,
                        error_code = %s,
                        finished_at = CASE
                            WHEN %s = ANY(%s) THEN now()
                            ELSE NULL
                        END
                    WHERE id = %s
                    RETURNING id, session_id, status, error_code,
                              started_at, finished_at
                    """,
                    (status, error_code, status, list(FINAL_TURN_STATUSES), turn_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError(f"Turn not found: {turn_id}")
        return self._turn(row)

    @staticmethod
    def _turn(row: Sequence[Any]) -> dict[str, Any]:
        return {
            "turn_id": str(row[0]),
            "session_id": str(row[1]),
            "status": row[2],
            "error_code": row[3],
            "started_at": row[4],
            "finished_at": row[5],
        }


def estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate used only for context budgeting."""
    return max(1, math.ceil(len(text) / 4))


MemorySearch = Callable[..., Mapping[str, Any]]
JournalReader = Callable[..., Sequence[Mapping[str, Any]]]


@dataclass
class ContextBuilder:
    sessions: SessionService
    memory_search: MemorySearch | None = None
    journal_reader: JournalReader | None = None

    def build(
        self,
        session_id: str | uuid.UUID,
        *,
        system_prompt: str,
        memory_query: str | None = None,
        memory_buckets: Iterable[str] = ("biography",),
        max_tokens: int = 8192,
        response_reserve: int = 2048,
        memory_limit_per_bucket: int = 3,
        presentation_instruction: str | None = None,
    ) -> list[dict[str, str]]:
        available = max_tokens - response_reserve
        if available <= 0:
            raise ValueError("Context budget must exceed response reserve")
        session = self.sessions.get_session(session_id)
        prefix: list[dict[str, str]] = []
        if system_prompt.strip():
            prefix.append({"role": "system", "content": system_prompt.strip()})
        if session["synopsis"]:
            prefix.append(
                {
                    "role": "system",
                    "content": "Session synopsis:\n" + session["synopsis"],
                }
            )
        if presentation_instruction:
            prefix.append(
                {"role": "system", "content": presentation_instruction.strip()}
            )

        approved_memory_lines: list[str] = []
        allowed_buckets = tuple(dict.fromkeys(memory_buckets))
        if self.memory_search and memory_query and allowed_buckets:
            for bucket in allowed_buckets:
                response = self.memory_search(
                    memory_query,
                    limit=memory_limit_per_bucket,
                    approved_only=True,
                    ledger=bucket,
                )
                results = response.get("results", [])
                if not isinstance(results, Sequence):
                    continue
                for item in results:
                    if not isinstance(item, Mapping) or item.get("approved") is not True:
                        continue
                    metadata = item.get("metadata")
                    if not isinstance(metadata, Mapping) or metadata.get("ledger") != bucket:
                        continue
                    content = item.get("content")
                    if isinstance(content, str) and content.strip():
                        approved_memory_lines.append(f"[{bucket}] {content.strip()}")
        if approved_memory_lines:
            prefix.append(
                {
                    "role": "system",
                    "content": "Approved memories:\n" + "\n".join(approved_memory_lines),
                }
            )

        if self.journal_reader is not None:
            journal_entries = self.journal_reader(str(session_id), limit=5)
            journal_lines = []
            for item in journal_entries:
                content = item.get("content")
                entry_id = item.get("journal_entry_id")
                entry_type = item.get("entry_type")
                if not isinstance(content, str) or not content.strip() or not entry_id:
                    continue
                title = item.get("title")
                label = f"{entry_type}: {title}" if title else str(entry_type)
                suffix = "… [excerpt]" if item.get("content_truncated") else ""
                journal_lines.append(
                    f"[journal:{entry_id}] {label} — {content.strip()}{suffix}"
                )
            if journal_lines:
                prefix.append(
                    {
                        "role": "system",
                        "content": (
                            "Approved private shared journal. Use only in this "
                            "authorized private session:\n" + "\n".join(journal_lines)
                        ),
                    }
                )

        used = sum(estimate_tokens(item["content"]) for item in prefix)
        if used > available:
            raise ValueError("System context exceeds the available token budget")
        history = self.sessions.list_messages(
            session_id,
            visible_only=True,
            after_sequence=session["synopsis_through_sequence"],
        )
        selected: list[dict[str, str]] = []
        for item in reversed(history):
            content = item["content"]
            channel = item["metadata"].get("channel")
            if channel in {"web", "telegram"}:
                content = f"[Channel: {channel}]\n{content}"
            cost = estimate_tokens(content)
            if used + cost > available:
                break
            selected.append({"role": item["role"], "content": content})
            used += cost
        selected.reverse()
        return prefix + selected
