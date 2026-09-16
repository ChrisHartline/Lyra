from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from lyra.runtime_events import RuntimeEvent
from lyra.web import create_app, is_loopback_client, validate_bind_host


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

    def correct_approved(self, proposal_id, content, reason=None):
        self.calls.append(("correct-approved", proposal_id, content, reason))
        return {"proposal_id": proposal_id, "status": "approved", "content": content}

    def reject(self, proposal_id, reason):
        self.calls.append(("reject", proposal_id, reason))
        return {"proposal_id": proposal_id, "status": "rejected"}

    def forget(self, proposal_id, confirmed, reason=None):
        self.calls.append(("forget", proposal_id, confirmed, reason))
        return {"proposal_id": proposal_id, "status": "forgotten"}

    def list_audit(self, limit=200):
        return [{"audit_id": 1, "action": "approved"}][:limit]

    def list_recent_natural(self, limit=20):
        return [{"proposal_id": 8, "approval_mode": "auto"}][:limit]


class FakePolicy:
    def __init__(self):
        self.policy = {"private_shared": "auto", "professional": "review", "story": "auto", "campaign": "auto"}

    def get_policy(self):
        return dict(self.policy)

    def set_policy(self, **modes):
        self.policy.update(modes)
        return dict(self.policy)


class FakeRituals:
    def __init__(self):
        self.policy = {
            "morning_enabled": False, "evening_enabled": False,
            "morning_time": "08:00:00", "evening_time": "21:00:00",
            "timezone": "America/Chicago", "channel": "telegram",
            "notion_publish": False, "vacation_until": None,
            "morning_snoozed_until": None, "evening_snoozed_until": None,
        }

    def policy_dict(self):
        return dict(self.policy)

    def set_policy(self, **values):
        self.policy.update(values)
        return SimpleNamespace(**self.policy)

    def build(self, ritual_type):
        return {"ritual_type": ritual_type, "body": "[digest] Preview"}

    def skip(self, ritual_type):
        return {"ritual_type": ritual_type, "status": "skipped"}

    def snooze(self, ritual_type, until):
        self.policy[f"{ritual_type}_snoozed_until"] = until
        return SimpleNamespace(**self.policy)

class FakeCommitments:
    def __init__(self):
        self.calls = []

    def list_offers(self, status="offered", session_id=None):
        self.calls.append(("list_offers", status, session_id))
        return [{"offer_id": "offer-1", "status": status}]

    def confirm_offer(self, offer_id):
        self.calls.append(("confirm", offer_id))
        return {"commitment_id": "commitment-1", "status": "active"}

    def dismiss_offer(self, offer_id):
        self.calls.append(("dismiss", offer_id))
        return {"offer_id": offer_id, "status": "dismissed"}

    def list_commitments(self, status=None):
        self.calls.append(("list", status))
        return [{"commitment_id": "commitment-1", "status": status or "active"}]

    def get_commitment(self, commitment_id):
        self.calls.append(("get", commitment_id))
        return {"commitment_id": commitment_id, "status": "active"}

    def transition(self, commitment_id, status, snoozed_until=None):
        self.calls.append(("transition", commitment_id, status, snoozed_until))
        return {"commitment_id": commitment_id, "status": status}

    def plan_due_reminders(self, *, away, channel, horizon):
        self.calls.append(("reminders", away, channel, horizon))
        return [{"commitment_id": "commitment-1", "disposition": "send"}]


class FakeStuck:
    def __init__(self):
        self.calls = []

    def get_state(self, session_id):
        self.calls.append(("get", session_id))
        return {
            "interaction_id": "stuck-1",
            "session_id": session_id,
            "status": "active",
            "selected_mode": "task_decomposition",
            "depth": "standard",
        }


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
        memory_policy=FakePolicy(),  # type: ignore[arg-type]
        ritual_service=FakeRituals(),  # type: ignore[arg-type]
    )
    return TestClient(app, client=("127.0.0.1", 50000)), sessions, control


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
    corrected_approved = client.post(
        "/api/control/proposals/7/correct-approved",
        headers=headers,
        json={"content": "Approved correction"},
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
    recent = client.get("/api/control/recent", headers=headers)
    policy = client.get("/api/control/memory-policy", headers=headers)
    updated_policy = client.put(
        "/api/control/memory-policy",
        headers=headers,
        json={"private_shared": "review", "professional": "review", "story": "auto", "campaign": "auto"},
    )
    rituals = client.get("/api/control/rituals", headers=headers)
    preview = client.get("/api/control/rituals/morning/preview", headers=headers)
    skipped = client.post("/api/control/rituals/evening/skip", headers=headers)

    assert pending.json()["proposals"][0]["proposal_id"] == 7
    assert approved.json()["status"] == "approved"
    assert corrected.json()["content"] == "Corrected"
    assert corrected_approved.json()["content"] == "Approved correction"
    assert rejected.json()["status"] == "rejected"
    assert forgotten.json()["status"] == "forgotten"
    assert audit.json()["audit"][0]["action"] == "approved"
    assert recent.json()["proposals"][0]["approval_mode"] == "auto"
    assert policy.json()["policy"]["private_shared"] == "auto"
    assert updated_policy.json()["policy"]["private_shared"] == "review"
    assert rituals.json()["policy"]["morning_enabled"] is False
    assert preview.json()["body"] == "[digest] Preview"
    assert skipped.json()["status"] == "skipped"
    assert [call[0] for call in control.calls] == [
        "approve",
        "correct",
        "correct-approved",
        "reject",
        "forget",
    ]


def test_memory_control_fails_closed_when_token_is_unconfigured(monkeypatch):
    monkeypatch.delenv("LYRA_CONTROL_TOKEN", raising=False)
    client, _sessions, _control = _client()

    response = client.get("/api/control/proposals")

    assert response.status_code == 503
    assert response.json()["detail"] == "Memory control token is not configured"


def test_memory_control_rejects_tailnet_and_forwarded_clients(monkeypatch):
    monkeypatch.setenv("LYRA_CONTROL_TOKEN", "local-control-secret")
    sessions = FakeSessions()
    control = FakeControl()
    app = create_app(
        sessions=sessions,  # type: ignore[arg-type]
        loop_factory=lambda _session_id: FakeLoop(sessions),
        away_service=FakeAway(),  # type: ignore[arg-type]
        memory_control=control,  # type: ignore[arg-type]
    )
    token = {"X-Lyra-Control-Token": "local-control-secret"}
    remote = TestClient(app, client=("100.119.187.40", 50000))
    local = TestClient(app, client=("127.0.0.1", 50000))

    assert remote.get("/").status_code == 200
    assert remote.get("/control").status_code == 403
    assert remote.get("/api/control/proposals", headers=token).status_code == 403
    assert local.get(
        "/api/control/proposals",
        headers={**token, "Tailscale-User-Login": "owner@example.invalid"},
    ).status_code == 403
    assert local.get(
        "/api/control/proposals",
        headers={**token, "X-Forwarded-For": "100.119.187.40"},
    ).status_code == 403
    assert control.calls == []


def test_commitment_offer_lifecycle_and_reminder_api():
    sessions = FakeSessions()
    commitments = FakeCommitments()
    away = FakeAway()
    app = create_app(
        sessions=sessions,  # type: ignore[arg-type]
        loop_factory=lambda _session_id: FakeLoop(sessions),
        away_service=away,  # type: ignore[arg-type]
        memory_control=FakeControl(),  # type: ignore[arg-type]
        commitment_service=commitments,  # type: ignore[arg-type]
    )
    client = TestClient(app, client=("127.0.0.1", 50000))

    offers = client.get("/api/commitment-offers?status=offered&session_id=s-1")
    confirmed = client.post("/api/commitment-offers/offer-1/confirm")
    dismissed = client.post("/api/commitment-offers/offer-2/dismiss")
    listed = client.get("/api/commitments?status=active")
    fetched = client.get("/api/commitments/commitment-1")
    transitioned = client.patch(
        "/api/commitments/commitment-1", json={"status": "done"}
    )
    reminders = client.post(
        "/api/commitment-reminders/plan",
        json={"channel": "telegram", "horizon_hours": 48},
    )

    assert offers.json()["offers"][0]["offer_id"] == "offer-1"
    assert confirmed.json()["status"] == "active"
    assert dismissed.json()["status"] == "dismissed"
    assert listed.json()["commitments"][0]["status"] == "active"
    assert fetched.json()["commitment_id"] == "commitment-1"
    assert transitioned.json()["status"] == "done"
    assert reminders.json()["reminders"][0]["disposition"] == "send"
    assert [call[0] for call in commitments.calls] == [
        "list_offers",
        "confirm",
        "dismiss",
        "list",
        "get",
        "transition",
        "reminders",
    ]


def test_commitment_mutations_reject_tailnet_and_forwarded_clients():
    sessions = FakeSessions()
    commitments = FakeCommitments()
    app = create_app(
        sessions=sessions,  # type: ignore[arg-type]
        loop_factory=lambda _session_id: FakeLoop(sessions),
        away_service=FakeAway(),  # type: ignore[arg-type]
        memory_control=FakeControl(),  # type: ignore[arg-type]
        commitment_service=commitments,  # type: ignore[arg-type]
    )
    remote = TestClient(app, client=("100.119.187.40", 50000))
    proxied = TestClient(app, client=("127.0.0.1", 50000))

    assert remote.get("/api/commitments").status_code == 200
    assert remote.post("/api/commitment-offers/offer-1/confirm").status_code == 403
    assert remote.post("/api/commitment-offers/offer-1/dismiss").status_code == 403
    assert remote.patch(
        "/api/commitments/commitment-1", json={"status": "done"}
    ).status_code == 403
    assert proxied.post(
        "/api/commitment-reminders/plan",
        headers={"Tailscale-User-Login": "owner@example.invalid"},
        json={"channel": "telegram", "horizon_hours": 24},
    ).status_code == 403
    assert commitments.calls == [("list", None)]


def test_stuck_mode_status_api_is_channel_neutral_and_read_only():
    sessions = FakeSessions()
    stuck = FakeStuck()
    app = create_app(
        sessions=sessions,  # type: ignore[arg-type]
        loop_factory=lambda _session_id: FakeLoop(sessions),
        away_service=FakeAway(),  # type: ignore[arg-type]
        memory_control=FakeControl(),  # type: ignore[arg-type]
        commitment_service=FakeCommitments(),  # type: ignore[arg-type]
        stuck_service=stuck,  # type: ignore[arg-type]
    )
    remote = TestClient(app, client=("100.119.187.40", 50000))

    response = remote.get("/api/stuck-mode/session-1")

    assert response.status_code == 200
    assert response.json()["interaction"]["selected_mode"] == "task_decomposition"
    assert stuck.calls == [("get", "session-1")]


def test_loopback_client_classification():
    assert is_loopback_client("127.0.0.1") is True
    assert is_loopback_client("::1") is True
    assert is_loopback_client("localhost") is True
    assert is_loopback_client("100.119.187.40") is False
    assert is_loopback_client(None) is False


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
