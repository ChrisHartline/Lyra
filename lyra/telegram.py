"""Single-user Telegram channel and local inbox adapter."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import psycopg

from lyra.db import connect
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.sessions import SessionService
from lyra.rituals import RitualService


logger = logging.getLogger(__name__)
URL_ONLY = re.compile(r"^https?://\S+$", re.IGNORECASE)
SUPPORTED_DOCUMENT_SUFFIXES = frozenset({".pdf", ".docx", ".md", ".txt", ".html", ".htm"})
REMOTE_DENIED_COMMANDS = frozenset(
    {"/approve", "/reject", "/forget", "/code", "/publish", "/shell", "/git", "/allowlist"}
)


class TelegramError(RuntimeError):
    """Safe-to-log Telegram transport or payload failure."""


class TurnLoop(Protocol):
    def stream_turn(
        self, session_id: str, user_text: str, *, channel: str = "web"
    ) -> AsyncIterator[RuntimeEvent]: ...


class TelegramClient(Protocol):
    async def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]: ...
    async def send_text(self, chat_id: str, text: str) -> None: ...
    async def download(self, file_id: str) -> bytes: ...


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    allowed_user_ids: frozenset[str]
    allowed_chat_ids: frozenset[str]
    artifact_root: Path = Path("data/telegram")
    poll_timeout: int = 30
    max_artifact_bytes: int = 20 * 1024 * 1024

    @staticmethod
    def _ids(value: str) -> frozenset[str]:
        return frozenset(part.strip() for part in value.split(",") if part.strip())

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> TelegramConfig | None:
        env = os.environ if environ is None else environ
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return None
        users = cls._ids(env.get("LYRA_TELEGRAM_ALLOWED_USER_IDS", ""))
        chats = cls._ids(env.get("LYRA_TELEGRAM_ALLOWED_CHAT_IDS", ""))
        if not users or not chats:
            raise TelegramError(
                "Telegram is configured without both user and chat allowlists"
            )
        return cls(
            token=token,
            allowed_user_ids=users,
            allowed_chat_ids=chats,
            artifact_root=Path(env.get("LYRA_TELEGRAM_ARTIFACT_ROOT", "data/telegram")),
        )


class BotAPI:
    """Minimal Telegram Bot API client with sanitized failures."""

    def __init__(self, token: str, client: httpx.AsyncClient) -> None:
        self._token = token
        self._client = client
        self._base = f"https://api.telegram.org/bot{token}"
        self._files = f"https://api.telegram.org/file/bot{token}"

    async def _call(self, method: str, payload: Mapping[str, Any]) -> Any:
        try:
            response = await self._client.post(f"{self._base}/{method}", json=dict(payload))
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(f"Telegram {method} request failed") from None
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramError(f"Telegram {method} request was rejected")
        return body.get("result")

    async def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload)
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    async def send_text(self, chat_id: str, text: str) -> None:
        content = text.strip() or "I couldn't produce a visible reply."
        for start in range(0, len(content), 4000):
            await self._call(
                "sendMessage",
                {"chat_id": chat_id, "text": content[start : start + 4000]},
            )

    async def download(self, file_id: str) -> bytes:
        result = await self._call("getFile", {"file_id": file_id})
        if not isinstance(result, dict) or not result.get("file_path"):
            raise TelegramError("Telegram file metadata was incomplete")
        try:
            response = await self._client.get(f"{self._files}/{result['file_path']}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError("Telegram file download failed") from None
        return response.content


@dataclass(frozen=True)
class InboxItem:
    update_id: int
    message_id: int
    sender_id: str
    chat_id: str
    media_type: str
    original_filename: str | None
    file_id: str | None
    source_url: str | None
    route: str
    metadata: Mapping[str, Any]


def _safe_filename(value: str | None, fallback: str) -> str:
    name = Path(value or fallback).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned[:180] or fallback


def parse_inbox_item(update: Mapping[str, Any]) -> InboxItem | None:
    message = update.get("message")
    if not isinstance(message, Mapping):
        return None
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(sender, Mapping) or not isinstance(chat, Mapping):
        return None
    base = {
        "update_id": int(update["update_id"]),
        "message_id": int(message["message_id"]),
        "sender_id": str(sender["id"]),
        "chat_id": str(chat["id"]),
    }
    text = str(message.get("text") or message.get("caption") or "").strip()
    if URL_ONLY.fullmatch(text):
        return InboxItem(
            **base,
            media_type="url",
            original_filename=None,
            file_id=None,
            source_url=text,
            route="corpus_candidate",
            metadata={},
        )

    document = message.get("document")
    if isinstance(document, Mapping) and document.get("file_id"):
        filename = str(document.get("file_name") or f"document-{base['message_id']}")
        route = (
            "corpus_candidate"
            if Path(filename).suffix.lower() in SUPPORTED_DOCUMENT_SUFFIXES
            else "unsupported"
        )
        return InboxItem(
            **base,
            media_type="document",
            original_filename=filename,
            file_id=str(document["file_id"]),
            source_url=None,
            route=route,
            metadata={"mime_type": document.get("mime_type"), "caption": text},
        )

    photos = message.get("photo")
    if isinstance(photos, Sequence) and photos:
        photo = photos[-1]
        if isinstance(photo, Mapping) and photo.get("file_id"):
            return InboxItem(
                **base,
                media_type="photo",
                original_filename=f"photo-{base['message_id']}.jpg",
                file_id=str(photo["file_id"]),
                source_url=None,
                route="pending_review",
                metadata={"caption": text},
            )

    voice = message.get("voice")
    if isinstance(voice, Mapping) and voice.get("file_id"):
        return InboxItem(
            **base,
            media_type="voice",
            original_filename=f"voice-{base['message_id']}.ogg",
            file_id=str(voice["file_id"]),
            source_url=None,
            route="pending_review",
            metadata={"duration": voice.get("duration"), "caption": text},
        )
    for media_type in ("audio", "video", "video_note", "animation", "sticker"):
        media = message.get(media_type)
        if isinstance(media, Mapping) and media.get("file_id"):
            extension = Path(str(media.get("file_name") or "")).suffix or ".bin"
            return InboxItem(
                **base,
                media_type=media_type,
                original_filename=str(
                    media.get("file_name")
                    or f"{media_type}-{base['message_id']}{extension}"
                ),
                file_id=str(media["file_id"]),
                source_url=None,
                route="unsupported",
                metadata={"caption": text},
            )
    return None


@dataclass
class TelegramStore:
    connection_factory: Callable[[], psycopg.Connection] = connect

    def claim_update(self, update_id: int) -> bool:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO telegram_updates (update_id, status)
                    VALUES (%s, 'processing')
                    ON CONFLICT (update_id) DO NOTHING
                    RETURNING update_id
                    """,
                    (update_id,),
                )
                claimed = cursor.fetchone() is not None
            connection.commit()
        return claimed

    def finish_update(self, update_id: int, status: str, error_code: str | None = None) -> None:
        if status not in {"completed", "failed", "ignored"}:
            raise ValueError("Invalid final Telegram update status")
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_updates
                    SET status = %s, error_code = %s, finished_at = now()
                    WHERE update_id = %s
                    """,
                    (status, error_code, update_id),
                )
            connection.commit()

    def add_inbox_item(self, item: InboxItem, local_path: Path | None) -> str:
        item_id = uuid.uuid4()
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO telegram_inbox
                        (id, update_id, message_id, sender_id, chat_id, media_type,
                         original_filename, local_path, source_url, route, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        item_id,
                        item.update_id,
                        item.message_id,
                        item.sender_id,
                        item.chat_id,
                        item.media_type,
                        item.original_filename,
                        str(local_path.resolve()) if local_path else None,
                        item.source_url,
                        item.route,
                        json.dumps(dict(item.metadata)),
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        return str(row[0])


class TelegramBot:
    def __init__(
        self,
        config: TelegramConfig,
        client: TelegramClient,
        sessions: SessionService,
        loop_factory: Callable[[str], TurnLoop],
        store: TelegramStore | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.sessions = sessions
        self.loop_factory = loop_factory
        self.store = store or TelegramStore()
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        self._stopped.set()

    def _authorized(self, message: Mapping[str, Any]) -> bool:
        sender = message.get("from")
        chat = message.get("chat")
        return (
            isinstance(sender, Mapping)
            and isinstance(chat, Mapping)
            and str(sender.get("id")) in self.config.allowed_user_ids
            and str(chat.get("id")) in self.config.allowed_chat_ids
        )

    def _session(self, chat_id: str) -> str:
        existing = self.sessions.resolve_channel("telegram", chat_id)
        if existing:
            return existing
        session = self.sessions.create_session(f"Telegram {chat_id}")
        self.sessions.bind_channel(session["session_id"], "telegram", chat_id)
        return str(session["session_id"])

    async def _save_inbox(self, item: InboxItem) -> str:
        local_path = None
        if item.file_id:
            content = await self.client.download(item.file_id)
            if len(content) > self.config.max_artifact_bytes:
                raise TelegramError("Telegram artifact exceeds the configured size limit")
            directory = self.config.artifact_root / str(item.update_id)
            directory.mkdir(parents=True, exist_ok=True)
            filename = _safe_filename(
                item.original_filename,
                f"artifact-{item.message_id}.bin",
            )
            local_path = directory / filename
            local_path.write_bytes(content)
        self.store.add_inbox_item(item, local_path)
        if item.route == "corpus_candidate":
            return "Saved to Lyra's inbox as a corpus candidate."
        if item.route == "pending_review":
            return "Saved locally for review. I won't infer or remember its contents automatically."
        return "Saved locally, but that file type needs manual review before routing."

    async def _chat(self, session_id: str, text: str) -> str:
        parts: list[str] = []
        async for event in self.loop_factory(session_id).stream_turn(
            session_id, text, channel="telegram"
        ):
            if event.kind is EventKind.TEXT and event.text:
                parts.append(event.text)
            elif event.kind is EventKind.ERROR:
                raise TelegramError("Lyra could not complete the Telegram turn")
        return "".join(parts).strip() or "I couldn't produce a visible reply."

    async def handle_update(self, update: Mapping[str, Any]) -> str:
        update_id = int(update.get("update_id", -1))
        message = update.get("message")
        if update_id < 0 or not isinstance(message, Mapping) or not self._authorized(message):
            return "ignored"
        if not self.store.claim_update(update_id):
            return "duplicate"
        chat_id = str(message["chat"]["id"])
        try:
            inbox = parse_inbox_item(update)
            if inbox:
                reply = await self._save_inbox(inbox)
            else:
                text = str(message.get("text") or "").strip()
                if text == "/status":
                    session_id = self.sessions.resolve_channel("telegram", chat_id)
                    reply = (
                        f"Current session: {self.sessions.get_session(session_id)['name']}"
                        if session_id
                        else "No Telegram session is bound yet."
                    )
                elif text == "/sessions":
                    names = [session["name"] for session in self.sessions.list_sessions()]
                    reply = "Sessions: " + (", ".join(names) if names else "none")
                elif text.split(maxsplit=1)[0].lower() in REMOTE_DENIED_COMMANDS:
                    reply = "That action is deliberately unavailable on Telegram."
                elif not text:
                    reply = "That message type isn't supported yet."
                else:
                    reply = await self._chat(self._session(chat_id), text)
            await self.client.send_text(chat_id, reply)
            self.store.finish_update(update_id, "completed")
            return "completed"
        except TelegramError:
            logger.exception("Telegram update failed safely", extra={"update_id": update_id})
            self.store.finish_update(update_id, "failed", "telegram_error")
            try:
                await self.client.send_text(chat_id, "I couldn't process that safely. Please try again later.")
            except TelegramError:
                pass
            return "failed"

    async def run(self) -> None:
        offset = None
        delay = 1.0
        while not self._stopped.is_set():
            try:
                updates = await self.client.get_updates(offset, self.config.poll_timeout)
                delay = 1.0
                for update in updates:
                    if "update_id" in update:
                        offset = max(offset or 0, int(update["update_id"]) + 1)
                    await self.handle_update(update)
            except TelegramError:
                logger.warning("Telegram polling failed; retrying with backoff")
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 30.0)


async def run_configured_bot(
    sessions: SessionService,
    loop_factory: Callable[[str], TurnLoop],
) -> None:
    config = TelegramConfig.from_environ()
    if config is None:
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
        bot = TelegramBot(config, BotAPI(config.token, client), sessions, loop_factory)
        await bot.run()


async def run_configured_rituals(
    sessions: SessionService,
    rituals: RitualService,
    *,
    interval_seconds: int = 30,
    iterations: int | None = None,
) -> None:
    """Deliver due rituals without granting the model proactive authority."""

    config = TelegramConfig.from_environ()
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
        bot_api = BotAPI(config.token, client) if config else None
        completed_iterations = 0
        while iterations is None or completed_iterations < iterations:
            for kind in ("morning", "evening"):
                result: dict[str, Any] | None = None
                try:
                    result = rituals.plan_due(kind)
                    if result.get("disposition") != "send":
                        continue
                    policy = rituals.get_policy()
                    draft = result["draft"]
                    session_id: str | None = None
                    if policy.channel == "telegram":
                        if bot_api is None or config is None:
                            raise TelegramError(
                                "Ritual Telegram delivery is not configured"
                            )
                        chat_id = sorted(config.allowed_chat_ids)[0]
                        session_id = sessions.resolve_channel("telegram", chat_id)
                        if not session_id:
                            created = sessions.create_session("Daily rituals")
                            session_id = str(created["session_id"])
                            sessions.bind_channel(session_id, "telegram", chat_id)
                        await bot_api.send_text(chat_id, draft["body"])
                    else:
                        existing = sessions.list_sessions()
                        session_id = (
                            str(existing[0]["session_id"])
                            if existing
                            else str(sessions.create_session("Daily rituals")["session_id"])
                        )
                    sessions.append_message(
                        session_id,
                        "assistant",
                        draft["body"],
                        metadata={
                            "channel": policy.channel,
                            "ritual_type": kind,
                            "proactive": True,
                        },
                    )
                    rituals.mark_delivered(
                        result["run"]["run_id"], session_id=session_id
                    )
                    if (
                        result.get("notion_publish")
                        and rituals.briefing.publisher is not None
                    ):
                        rituals.briefing.publish_to_notion(kind)
                except Exception:
                    logger.exception(
                        "Ritual delivery failed safely", extra={"ritual_type": kind}
                    )
                    if result and result.get("run"):
                        rituals.mark_failed(result["run"]["run_id"])
            completed_iterations += 1
            if iterations is None or completed_iterations < iterations:
                await asyncio.sleep(max(10, min(interval_seconds, 300)))
