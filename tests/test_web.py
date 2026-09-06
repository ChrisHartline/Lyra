from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from lyra.runtime_events import RuntimeEvent
from lyra.web import create_app, validate_bind_host


class FakeSessions:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}
        self.channels: dict[tuple[str, str], str] = {}

    def create_session(self, name):
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "name": name.strip(),
            "synopsis": None,
            "synopsis_through_sequence": 0,
            "created_at": "now",
            "updated_at": "now",
        }
        self.sessions[session_id] = session
        self.messages[session_id] = []
        return session

    def get_session(self, session_id):
        if session_id not in self.sessions:
            raise ValueError("not found")
        return self.sessions[session_id]

    def list_sessions(self):
        return list(self.sessions.values())

    def rename_session(self, session_id, name):
        session = self.get_session(session_id)
        session["name"] = name.strip()
        return session

    def delete_session(self, session_id):
        if session_id not in self.sessions:
            return False
        del self.sessions[session_id]
        del self.messages[session_id]
        return True

    def list_messages(self, session_id, after_sequence=0):
        return [
            message
            for message in self.messages[session_id]
            if message["sequence"] > after_sequence
        ]

    def append(self, session_id, role, content):
        message = {
            "message_id": len(self.messages[session_id]) + 1,
            "session_id": session_id,
            "sequence": len(self.messages[session_id]) + 1,
            "role": role,
            "content": content,
            "visible": True,
            "metadata": {},
            "created_at": "now",
        }
        self.messages[session_id].append(message)

    def bind_channel(self, session_id, channel, external_id):
        for key, value in list(self.channels.items()):
            if key == (channel, external_id) or (value == session_id and key[0] == channel):
                del self.channels[key]
        self.channels[(channel, external_id)] = session_id
        return {"session_id": session_id, "channel": channel, "external_id": external_id}

    def list_channels(self, session_id):
        return [
            {"session_id": value, "channel": key[0], "external_id": key[1]}
            for key, value in self.channels.items()
            if value == session_id
        ]


class FakeAway:
    def __init__(self):
        self.mode = "standard"
        self.policy = {
            "enabled": False,
            "quiet_start": None,
            "quiet_end": None,
            "timezone": "America/Chicago",
            "daily_notification_budget": 6,
        }

    def get_channel_preference(self, channel):
        return {"channel": channel, "presentation_mode": self.mode}

    def set_channel_preference(self, channel, mode):
        self.mode = mode
        return {"channel": channel, "presentation_mode": mode}

    def policy_dict(self):
        return dict(self.policy)

    def set_policy(self, **kwargs):
        self.policy = dict(kwargs)
        return SimpleNamespace(**kwargs)

    def list_batched(self):
        return []


class FakeControl:
    def __init__(self):
        self.proposals = [
            {
                "proposal_id": 7,
                "content": "A proposed memory",
                "status": "pending",
                "destination_plane": "semantic_memory",
                "ledger": "biography",
                "provenance": {"source_type": "session"},
                "sensitivity_flags": [],
                "proposal_reason": "Potential durable memory",
            }
        ]
        self.calls = []

    def list_proposals(self, status="pending", limit=100):
        return [item for item in self.proposals if item["status"] == status][:limit]

    def approve(self, proposal_id):
        self.calls.append(("approve", proposal_id))
        return {"proposal_id": proposal_id, "status": "approved"}

    def correct(self, proposal_id, content, reason=None):
        self.calls.append(("correct", proposal_id, content, reason))
        return {"proposal_id": proposal_id, "status": "pending", "content": content}

    def reject(self, proposal_id, reason):
        self.calls.append(("reject", proposal_id, reason))
        return {"proposal_id": proposal_id, "status": "rejected"}

    def forget(self, proposal_id, confirmed, reason=None):
        self.calls.append(("forget", proposal_id, confirmed, reason))
        return {"proposal_id": proposal_id, "status": "forgotten"}

    def list_audit(self, limit=200):
        return [{"audit_id": 1, "action": "approved"}][:limit]


class FakeLoop:
    def __init__(self, sessions: FakeSessions) -> None:
        self.sessions = sessions

    async def stream_turn(self, session_id, user_text, *, channel="web"):
        self.sessions.append(session_id, "user", user_text)
        yield RuntimeEvent.text_delta("Hello **from Lyra**.")
        self.sessions.append(session_id, "assistant", "Hello **from Lyra**.")
        yield RuntimeEvent.completion("stop")


def _client():
    sessions = FakeSessions()
    control = FakeControl()
    app = create_app(
        sessions=sessions,  # type: ignore[arg-type]
        loop_factory=lambda _session_id: FakeLoop(sessions),
        away_service=FakeAway(),  # type: ignore[arg-type]
        memory_control=control,  # type: ignore[arg-type]
    )
    return TestClient(app), sessions, control


def test_ui_assets_and_loopback_health_contract():
    client, _sessions, _control = _client()

    page = client.get("/")
    css = client.get("/app.css")
    javascript = client.get("/app.js")
    control_page = client.get("/control")
    control_js = client.get("/control.js")
    health = client.get("/api/health")

    assert page.status_code == 200
    assert "<title>Lyra</title>" in page.text
    assert "Message Lyra" in page.text
    assert css.headers["content-type"].startswith("text/css")
    assert "--accent" in css.text
    assert "parseSseBlock" in javascript.text
    assert "Memory &amp; Observation Control" in control_page.text
    assert "X-Lyra-Control-Token" in control_js.text
    assert health.json() == {"status": "ready", "network": "loopback-only"}


def test_session_crud_and_message_resume_contract():
    client, _sessions, _control = _client()

    created = client.post("/api/sessions", json={"name": "Roadmap"})
    session_id = created.json()["session_id"]
    renamed = client.patch(
        f"/api/sessions/{session_id}", json={"name": "Runtime roadmap"}
    )

    assert created.status_code == 201
    assert renamed.json()["name"] == "Runtime roadmap"
    assert client.get("/api/sessions").json()["sessions"][0]["session_id"] == session_id
    assert client.get(f"/api/sessions/{session_id}/messages").json() == {"messages": []}

    response = client.post(
        f"/api/sessions/{session_id}/turns", json={"content": "Hello"}
    )
    resumed = client.get(f"/api/sessions/{session_id}/messages").json()["messages"]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [item["content"] for item in resumed] == ["Hello", "Hello **from Lyra**."]
    assert client.delete(f"/api/sessions/{session_id}").status_code == 204
    assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_local_handoff_and_away_preferences(monkeypatch):
    monkeypatch.setenv("LYRA_TELEGRAM_ALLOWED_CHAT_IDS", "84")
    client, sessions, _control = _client()
    first = client.post("/api/sessions", json={"name": "First"}).json()["session_id"]
    target = client.post("/api/sessions", json={"name": "Target"}).json()["session_id"]
    sessions.bind_channel(first, "telegram", "84")

    handoff = client.post(f"/api/sessions/{target}/handoff/telegram")
    concise = client.patch(
        "/api/preferences/telegram", json={"presentation_mode": "concise"}
    )
    away = client.put(
        "/api/away",
        json={
            "enabled": True,
            "quiet_start": "22:00:00",
            "quiet_end": "07:00:00",
            "timezone": "America/Chicago",
            "daily_notification_budget": 4,
        },
    )

    assert handoff.json() == {
        "session_id": target,
        "channel": "telegram",
        "external_id": "84",
    }
    assert sessions.channels == {("telegram", "84"): target}
    assert client.get(f"/api/sessions/{target}/channels").json()["channels"][0][
        "channel"
    ] == "telegram"
    assert concise.json()["presentation_mode"] == "concise"
    assert away.json()["enabled"] is True
    assert client.get("/api/away").json()["daily_notification_budget"] == 4


def test_memory_control_api_is_authenticated_and_routes_local_actions(monkeypatch):
    monkeypatch.setenv("LYRA_CONTROL_TOKEN", "local-control-secret")
    client, _sessions, control = _client()
    headers = {"X-Lyra-Control-Token": "local-control-secret"}

    assert client.get("/api/control/proposals").status_code == 401
    assert client.get(
        "/api/control/proposals",
        headers={"X-Lyra-Control-Token": "wrong"},
    ).status_code == 401

    pending = client.get("/api/control/proposals", headers=headers)
    approved = client.post(
        "/api/control/proposals/7/approve", headers=headers, json={}
    )
    corrected = client.post(
        "/api/control/proposals/7/correct",
        headers=headers,
        json={"content": "Corrected", "reason": "Precision"},
    )
    rejected = client.post(
        "/api/control/proposals/7/reject",
        headers=headers,
        json={"reason": "No longer useful"},
    )
    forgotten = client.post(
        "/api/control/proposals/7/forget",
        headers=headers,
        json={"confirmed": True},
    )
    audit = client.get("/api/control/audit", headers=headers)

    assert pending.json()["proposals"][0]["proposal_id"] == 7
    assert approved.json()["status"] == "approved"
    assert corrected.json()["content"] == "Corrected"
    assert rejected.json()["status"] == "rejected"
    assert forgotten.json()["status"] == "forgotten"
    assert audit.json()["audit"][0]["action"] == "approved"
    assert [call[0] for call in control.calls] == [
        "approve",
        "correct",
        "reject",
        "forget",
    ]


def test_memory_control_fails_closed_when_token_is_unconfigured(monkeypatch):
    monkeypatch.delenv("LYRA_CONTROL_TOKEN", raising=False)
    client, _sessions, _control = _client()

    response = client.get("/api/control/proposals")

    assert response.status_code == 503
    assert response.json()["detail"] == "Memory control token is not configured"


def test_sse_stream_has_status_text_completion_and_resume_hint():
    client, _sessions, _control = _client()
    session_id = client.post("/api/sessions", json={"name": "SSE"}).json()[
        "session_id"
    ]

    with client.stream(
        "POST",
        f"/api/sessions/{session_id}/turns",
        json={"content": "Hello"},
    ) as response:
        body = "".join(response.iter_text())

    assert "event: status" in body
    assert '"status":"started"' in body
    assert "event: text" in body
    assert '"text":"Hello **from Lyra**."' in body
    assert "event: completion" in body
    assert '"resume":"messages"' in body


def test_missing_runtime_configuration_is_a_sanitized_sse_error():
    sessions = FakeSessions()

    def broken_factory(_session_id):
        raise ValueError("secret provider details")

    client = TestClient(
        create_app(sessions=sessions, loop_factory=broken_factory)  # type: ignore[arg-type]
    )
    session_id = client.post("/api/sessions", json={"name": "Broken"}).json()[
        "session_id"
    ]

    response = client.post(
        f"/api/sessions/{session_id}/turns", json={"content": "Hello"}
    )

    assert "runtime_not_configured" in response.text
    assert "secret provider details" not in response.text
    assert '"status":"failed"' in response.text


def test_default_missing_profile_persists_user_message(monkeypatch):
    import lyra.web as web

    sessions = FakeSessions()
    monkeypatch.setattr(web, "EmbeddingService", lambda: object())
    monkeypatch.setattr(web, "IngestPipeline", lambda **kwargs: object())
    monkeypatch.setattr(
        web,
        "CorpusService",
        lambda **kwargs: SimpleNamespace(search_memories=lambda *args, **kwargs: {}),
    )
    monkeypatch.setattr(web, "MCPToolRouter", lambda service: object())
    monkeypatch.setattr(web, "build_gatekeeper_router", lambda: object())
    monkeypatch.setattr(web, "build_conversation_registry", lambda **kwargs: object())
    monkeypatch.setattr(web, "ContextBuilder", lambda *args, **kwargs: object())
    monkeypatch.setattr(web, "compose_runtime_context", lambda: "system")
    monkeypatch.setattr(
        web.ModelProfiles,
        "resolve",
        lambda self, name: (_ for _ in ()).throw(
            web.ProviderConfigurationError("do not expose details")
        ),
    )

    # The real SessionService records this path; adapt the fake to its interface.
    sessions.recover_interrupted_turns = lambda session_id: 0
    sessions.append_message = lambda session_id, role, content, **kwargs: sessions.append(
        session_id, role, content
    )
    sessions.start_turn = lambda session_id, status: {"turn_id": "turn-1"}
    sessions.update_turn = lambda turn_id, status, error_code=None: None
    client = TestClient(
        create_app(
            sessions=sessions,  # type: ignore[arg-type]
            loop_factory=web.default_loop_factory(sessions),  # type: ignore[arg-type]
        )
    )
    session_id = client.post("/api/sessions", json={"name": "Offline"}).json()[
        "session_id"
    ]

    response = client.post(
        f"/api/sessions/{session_id}/turns", json={"content": "Please remember this"}
    )
    resumed = client.get(f"/api/sessions/{session_id}/messages").json()["messages"]

    assert "conversation model is not configured" in response.text
    assert "do not expose details" not in response.text
    assert [message["content"] for message in resumed] == ["Please remember this"]


def test_bind_host_rejects_lan_and_public_addresses():
    assert validate_bind_host("127.0.0.1") == "127.0.0.1"
    assert validate_bind_host("LOCALHOST") == "localhost"
    for host in ("0.0.0.0", "192.168.1.10", "lyra.example.com"):
        try:
            validate_bind_host(host)
        except ValueError as exc:
            assert "loopback" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"non-loopback host accepted: {host}")


def test_app_lifespan_starts_and_stops_optional_telegram_runner():
    client, sessions, _control = _client()
    events = []

    async def runner(received_sessions, loop_factory):
        assert received_sessions is sessions
        assert loop_factory is not None
        events.append("started")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("stopped")

    app = create_app(
        sessions=sessions,  # type: ignore[arg-type]
        loop_factory=lambda _session_id: FakeLoop(sessions),
        telegram_runner=runner,
    )
    with TestClient(app) as live_client:
        assert live_client.get("/api/health").status_code == 200
        assert events == ["started"]

    assert events == ["started", "stopped"]
