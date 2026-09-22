from __future__ import annotations

from pathlib import Path

from lyra.sessions import ContextBuilder, SessionService, estimate_tokens
from tests.db_support import connect_test_db


def _conn():
    return connect_test_db()


def _reset() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(Path("db/schema.sql").read_text(encoding="utf-8"))
            cur.execute(
                "TRUNCATE session_turns, session_channels, session_messages, "
                "chat_sessions RESTART IDENTITY CASCADE"
            )
        conn.commit()


def test_named_session_resumes_after_service_restart_and_channel_binding(ensure_db):
    _reset()
    first = SessionService(connection_factory=_conn)
    session = first.create_session("Lyra runtime design")
    first.append_message(session["session_id"], "user", "Remember this turn.")
    first.bind_channel(session["session_id"], "telegram", "chat-42")

    restarted = SessionService(connection_factory=_conn)

    assert restarted.get_session(session["session_id"])["name"] == "Lyra runtime design"
    assert restarted.list_messages(session["session_id"])[0]["content"] == "Remember this turn."
    assert restarted.resolve_channel("telegram", "chat-42") == session["session_id"]


def test_session_context_scope_defaults_and_requires_explicit_supported_value(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    general = service.create_session("Command Deck")
    professional = service.create_session(
        "Professional project", context_scope="professional"
    )

    assert general["context_scope"] == "general"
    assert professional["context_scope"] == "professional"
    assert service.set_context_scope(
        professional["session_id"], "story"
    )["context_scope"] == "story"

    import pytest
    with pytest.raises(ValueError, match="Session scope"):
        service.set_context_scope(general["session_id"], "private")


def test_channel_rebind_moves_handoff_without_copying_history(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    first = service.create_session("First device session")
    second = service.create_session("Handoff target")
    service.append_message(first["session_id"], "user", "First-only history")
    service.append_message(second["session_id"], "user", "Target history")
    service.bind_channel(first["session_id"], "telegram", "chat-42")

    service.bind_channel(second["session_id"], "telegram", "chat-42")

    assert service.resolve_channel("telegram", "chat-42") == second["session_id"]
    assert service.list_channels(first["session_id"]) == []
    assert service.list_channels(second["session_id"])[0]["channel"] == "telegram"
    assert [item["content"] for item in service.list_messages(first["session_id"])] == [
        "First-only history"
    ]
    assert [item["content"] for item in service.list_messages(second["session_id"])] == [
        "Target history"
    ]


def test_session_delete_cascades_but_does_not_touch_knowledge_planes(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    session = service.create_session("Disposable")
    service.append_message(session["session_id"], "user", "Raw private chat history")
    service.bind_channel(session["session_id"], "web", "browser-1")
    service.start_turn(session["session_id"], "running")

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sources")
            sources_before = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memories")
            memories_before = cur.fetchone()[0]

    assert service.delete_session(session["session_id"]) is True

    with _conn() as conn:
        with conn.cursor() as cur:
            for table in ("session_messages", "session_channels", "session_turns"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM sources")
            assert cur.fetchone()[0] == sources_before
            cur.execute("SELECT COUNT(*) FROM memories")
            assert cur.fetchone()[0] == memories_before


def test_turn_status_and_visible_message_contract(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    session = service.create_session("Turn state")
    visible = service.append_message(session["session_id"], "user", "Visible")
    service.append_message(
        session["session_id"], "tool", "Internal tool payload", visible=False
    )
    turn = service.start_turn(session["session_id"], "pending")

    running = service.update_turn(turn["turn_id"], "running")
    completed = service.update_turn(turn["turn_id"], "completed")

    assert running["finished_at"] is None
    assert completed["finished_at"] is not None
    assert service.list_messages(session["session_id"]) == [visible]
    assert len(service.list_messages(session["session_id"], visible_only=False)) == 2


def test_restart_recovery_marks_unfinished_turns_disconnected(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    session = service.create_session("Recovery")
    pending = service.start_turn(session["session_id"], "pending")
    running = service.start_turn(session["session_id"], "running")
    completed = service.start_turn(session["session_id"], "running")
    service.update_turn(completed["turn_id"], "completed")

    recovered = SessionService(connection_factory=_conn).recover_interrupted_turns(
        session["session_id"]
    )

    assert recovered == 2
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, error_code FROM session_turns ORDER BY id"
            )
            statuses = {str(row[0]): (row[1], row[2]) for row in cur.fetchall()}
    assert statuses[pending["turn_id"]] == ("disconnected", "runtime_interrupted")
    assert statuses[running["turn_id"]] == ("disconnected", "runtime_interrupted")
    assert statuses[completed["turn_id"]] == ("completed", None)


def test_synopsis_replaces_only_summarized_prefix(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    session = service.create_session("Synopsis")
    service.append_message(session["session_id"], "user", "Old question")
    second = service.append_message(session["session_id"], "assistant", "Old answer")
    service.append_message(session["session_id"], "user", "New question")
    service.set_synopsis(
        session["session_id"], "We previously resolved the old question.", second["sequence"]
    )

    context = ContextBuilder(service).build(
        session["session_id"], system_prompt="You are Lyra.", response_reserve=20, max_tokens=200
    )
    content = "\n".join(item["content"] for item in context)

    assert "resolved the old question" in content
    assert "Old question" not in content
    assert "Old answer" not in content
    assert "New question" in content


def test_context_accepts_only_approved_requested_memory_buckets(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    session = service.create_session("Memory filtering")
    service.append_message(session["session_id"], "user", "What do you remember?")
    calls: list[dict] = []

    def search(query, **kwargs):
        calls.append({"query": query, **kwargs})
        bucket = kwargs["ledger"]
        return {
            "results": [
                {
                    "content": "Approved biography fact",
                    "approved": True,
                    "metadata": {"ledger": bucket},
                },
                {
                    "content": "Unapproved planted secret",
                    "approved": False,
                    "metadata": {"ledger": bucket},
                },
                {
                    "content": "Wrong-bucket campaign secret",
                    "approved": True,
                    "metadata": {"ledger": "campaign"},
                },
            ]
        }

    context = ContextBuilder(service, memory_search=search).build(
        session["session_id"],
        system_prompt="You are Lyra.",
        memory_query="Christopher",
        memory_buckets=("biography",),
        max_tokens=300,
        response_reserve=40,
    )
    content = "\n".join(item["content"] for item in context)

    assert calls == [
        {
            "query": "Christopher",
            "limit": 3,
            "approved_only": True,
            "ledger": "biography",
        }
    ]
    assert "Approved biography fact" in content
    assert "planted secret" not in content
    assert "campaign secret" not in content


def test_context_budget_keeps_newest_complete_messages(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    session = service.create_session("Budget")
    service.append_message(session["session_id"], "user", "old-" + "a" * 80)
    service.append_message(session["session_id"], "assistant", "new-" + "b" * 40)

    context = ContextBuilder(service).build(
        session["session_id"],
        system_prompt="system",
        max_tokens=30,
        response_reserve=10,
    )
    total = sum(estimate_tokens(item["content"]) for item in context)
    content = "\n".join(item["content"] for item in context)

    assert total <= 20
    assert "new-" in content
    assert "old-" not in content


def test_context_labels_channel_provenance_without_mutating_stored_text(ensure_db):
    _reset()
    service = SessionService(connection_factory=_conn)
    session = service.create_session("Channel provenance")
    service.append_message(
        session["session_id"],
        "user",
        "From the phone",
        metadata={"channel": "telegram"},
    )
    service.append_message(
        session["session_id"],
        "assistant",
        "Phone reply",
        metadata={"channel": "telegram"},
    )

    context = ContextBuilder(service).build(
        session["session_id"],
        system_prompt="You are Lyra.",
        presentation_instruction="Keep this response concise.",
    )

    assert context[1] == {"role": "system", "content": "Keep this response concise."}
    assert context[2]["content"] == "[Channel: telegram]\nFrom the phone"
    assert context[3]["content"] == "[Channel: telegram]\nPhone reply"
    assert service.list_messages(session["session_id"])[0]["content"] == "From the phone"
