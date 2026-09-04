from __future__ import annotations

import asyncio
from pathlib import Path
import traceback

import httpx
from lyra.runtime_events import RuntimeEvent
from lyra.telegram import (
    BotAPI,
    InboxItem,
    TelegramBot,
    TelegramConfig,
    TelegramError,
    TelegramStore,
    parse_inbox_item,
)
from tests.db_support import connect_test_db


ROOT = Path(__file__).resolve().parents[1]
def _conn():
    return connect_test_db()


class FakeStore:
    def __init__(self):
        self.claimed = set()
        self.finished = []
        self.inbox = []

    def claim_update(self, update_id):
        if update_id in self.claimed:
            return False
        self.claimed.add(update_id)
        return True

    def finish_update(self, update_id, status, error_code=None):
        self.finished.append((update_id, status, error_code))

    def add_inbox_item(self, item, local_path):
        self.inbox.append((item, local_path))
        return "inbox-1"


class FakeClient:
    def __init__(self):
        self.sent = []
        self.downloads = []

    async def get_updates(self, offset, timeout):
        return []

    async def send_text(self, chat_id, text):
        self.sent.append((chat_id, text))

    async def download(self, file_id):
        self.downloads.append(file_id)
        return b"local artifact"


class FakeSessions:
    def __init__(self):
        self.sessions = {}
        self.channels = {}

    def resolve_channel(self, channel, external_id):
        return self.channels.get((channel, external_id))

    def create_session(self, name):
        session_id = f"session-{len(self.sessions) + 1}"
        self.sessions[session_id] = {"session_id": session_id, "name": name}
        return self.sessions[session_id]

    def bind_channel(self, session_id, channel, external_id):
        self.channels[(channel, external_id)] = session_id

    def get_session(self, session_id):
        return self.sessions[session_id]

    def list_sessions(self):
        return list(self.sessions.values())


class FakeLoop:
    def __init__(self, calls, session_id):
        self.calls = calls
        self.session_id = session_id

    async def stream_turn(self, session_id, user_text, *, channel="web"):
        self.calls.append((session_id, user_text, channel))
        yield RuntimeEvent.text_delta("Hello from the shared session.")
        yield RuntimeEvent.completion("stop")


def _config(case: str = "default"):
    return TelegramConfig(
        token="never-printed",
        allowed_user_ids=frozenset({"42"}),
        allowed_chat_ids=frozenset({"84"}),
        artifact_root=ROOT / "data" / "test_tmp" / "telegram" / case,
    )


def _message(update_id=100, text="Hello", **extra):
    message = {
        "message_id": update_id + 10,
        "from": {"id": 42},
        "chat": {"id": 84},
        "text": text,
    }
    message.update(extra)
    return {"update_id": update_id, "message": message}


def test_config_is_disabled_without_token_and_fails_closed_without_allowlists():
    assert TelegramConfig.from_environ({}) is None
    try:
        TelegramConfig.from_environ({"TELEGRAM_BOT_TOKEN": "secret"})
    except TelegramError as exc:
        assert "allowlists" in str(exc)
        assert "secret" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("partial Telegram configuration must fail closed")


def test_unauthorized_update_is_silent_and_authorized_retry_is_deduplicated():
    client = FakeClient()
    sessions = FakeSessions()
    store = FakeStore()
    calls = []
    bot = TelegramBot(
        _config(),
        client,
        sessions,  # type: ignore[arg-type]
        lambda session_id: FakeLoop(calls, session_id),
        store=store,  # type: ignore[arg-type]
    )
    unauthorized = _message(update_id=1)
    unauthorized["message"]["from"]["id"] = 999

    assert asyncio.run(bot.handle_update(unauthorized)) == "ignored"
    assert client.sent == []
    assert store.claimed == set()

    update = _message(update_id=2, text="Continue our conversation")
    assert asyncio.run(bot.handle_update(update)) == "completed"
    assert asyncio.run(bot.handle_update(update)) == "duplicate"

    assert calls == [("session-1", "Continue our conversation", "telegram")]
    assert sessions.channels[("telegram", "84")] == "session-1"
    assert client.sent == [("84", "Hello from the shared session.")]


def test_remote_approval_and_execution_commands_never_reach_the_model_loop():
    client = FakeClient()
    calls = []
    bot = TelegramBot(
        _config(),
        client,
        FakeSessions(),  # type: ignore[arg-type]
        lambda session_id: FakeLoop(calls, session_id),
        store=FakeStore(),  # type: ignore[arg-type]
    )

    for index, command in enumerate(("/approve memory-1", "/code fix it", "/publish"), start=10):
        assert asyncio.run(bot.handle_update(_message(update_id=index, text=command))) == "completed"

    assert calls == []
    assert all("deliberately unavailable" in text for _chat, text in client.sent)


def test_url_document_photo_and_voice_route_without_memory_writes():
    assert parse_inbox_item(_message(text="https://example.com/paper")) == InboxItem(
        update_id=100,
        message_id=110,
        sender_id="42",
        chat_id="84",
        media_type="url",
        original_filename=None,
        file_id=None,
        source_url="https://example.com/paper",
        route="corpus_candidate",
        metadata={},
    )
    document = parse_inbox_item(
        _message(
            update_id=101,
            text="",
            document={
                "file_id": "doc-1",
                "file_name": "paper.pdf",
                "mime_type": "application/pdf",
            },
        )
    )
    photo = parse_inbox_item(
        _message(update_id=102, text="", photo=[{"file_id": "small"}, {"file_id": "large"}])
    )
    voice = parse_inbox_item(
        _message(update_id=103, text="", voice={"file_id": "voice-1", "duration": 7})
    )

    assert document and document.route == "corpus_candidate"
    assert photo and photo.file_id == "large" and photo.route == "pending_review"
    assert voice and voice.route == "pending_review"
    sticker = parse_inbox_item(
        _message(update_id=104, text="", sticker={"file_id": "sticker-1"})
    )
    assert sticker and sticker.media_type == "sticker" and sticker.route == "unsupported"


def test_attachment_download_is_local_sanitized_and_pending_review():
    client = FakeClient()
    store = FakeStore()
    bot = TelegramBot(
        _config("artifact"),
        client,
        FakeSessions(),  # type: ignore[arg-type]
        lambda session_id: FakeLoop([], session_id),
        store=store,  # type: ignore[arg-type]
    )
    update = _message(
        update_id=200,
        text="",
        document={"file_id": "file-200", "file_name": "../../unsafe.exe"},
    )

    assert asyncio.run(bot.handle_update(update)) == "completed"
    item, local_path = store.inbox[0]

    assert client.downloads == ["file-200"]
    assert item.route == "unsupported"
    assert local_path.parent == _config("artifact").artifact_root / "200"
    assert local_path.name == "unsafe.exe"
    assert local_path.read_bytes() == b"local artifact"
    assert "manual review" in client.sent[0][1]


def test_bot_api_failure_never_exposes_token_or_remote_error_body():
    token = "sensitive-bot-token"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"ok": False, "description": f"bad {token}"},
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await BotAPI(token, client).get_updates(None, 1)

    try:
        asyncio.run(run())
    except TelegramError as exc:
        rendered_traceback = traceback.format_exc()
        assert token not in str(exc)
        assert token not in rendered_traceback
        assert str(exc) == "Telegram getUpdates request failed"
    else:  # pragma: no cover
        raise AssertionError("Telegram HTTP failure should be sanitized")


def test_telegram_store_persists_provenance_and_deduplicates(ensure_db):
    update_id = 9_003_001
    with _conn() as connection:
        with connection.cursor() as cursor:
            cursor.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cursor.execute("DELETE FROM telegram_inbox WHERE update_id = %s", (update_id,))
            cursor.execute("DELETE FROM telegram_updates WHERE update_id = %s", (update_id,))
        connection.commit()

    store = TelegramStore(connection_factory=_conn)
    item = InboxItem(
        update_id=update_id,
        message_id=77,
        sender_id="42",
        chat_id="84",
        media_type="url",
        original_filename=None,
        file_id=None,
        source_url="https://example.com/source",
        route="corpus_candidate",
        metadata={"test": True},
    )
    assert store.claim_update(update_id) is True
    assert store.claim_update(update_id) is False
    store.add_inbox_item(item, None)
    store.finish_update(update_id, "completed")

    with _conn() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sender_id, chat_id, source_url, route FROM telegram_inbox WHERE update_id = %s",
                (update_id,),
            )
            assert cursor.fetchone() == (
                "42",
                "84",
                "https://example.com/source",
                "corpus_candidate",
            )
            cursor.execute("DELETE FROM telegram_inbox WHERE update_id = %s", (update_id,))
            cursor.execute("DELETE FROM telegram_updates WHERE update_id = %s", (update_id,))
        connection.commit()
