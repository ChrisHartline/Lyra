from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from lyra.providers import ModelProfile
from lyra.runtime import (
    AgentLoop,
    ModelToolRunner,
    NoOpEmotionOutput,
    NoOpVoiceOutput,
    ResearcherOrchestrator,
)
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.runtime_tools import (
    ToolAccess,
    ToolRegistry,
    ToolSpec,
    build_conversation_registry,
)


PROFILE = ModelProfile(
    "conversation", "openai-compatible", "fake-model", "FAKE_KEY", "https://fake"
)


async def _collect(stream) -> list[RuntimeEvent]:
    return [event async for event in stream]


class FakeProvider:
    def __init__(self, batches: list[list[RuntimeEvent]], delay: float = 0) -> None:
        self.batches = batches
        self.delay = delay
        self.messages: list[list[dict[str, Any]]] = []
        self.tool_definitions: list[list[dict[str, Any]]] = []

    async def stream(
        self,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] = (),
        *,
        environ: Mapping[str, str] | None = None,
    ):
        self.messages.append([dict(message) for message in messages])
        self.tool_definitions.append([dict(tool) for tool in tools])
        batch = self.batches.pop(0)
        for event in batch:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield event


def _schema():
    return {"type": "object", "properties": {}}


def test_tool_runner_executes_only_registered_tool_and_continues_model():
    calls: list[dict[str, Any]] = []
    registry = ToolRegistry(
        [
            ToolSpec(
                "search_corpus",
                "search",
                _schema(),
                lambda arguments: calls.append(arguments) or {"hits": ["result"]},
            )
        ]
    )
    provider = FakeProvider(
        [
            [
                RuntimeEvent.tool_call(
                    name="search_corpus", call_id="call-1", arguments={"query": "q"}
                ),
                RuntimeEvent.completion("tool_calls"),
            ],
            [RuntimeEvent.text_delta("Grounded answer"), RuntimeEvent.completion("stop")],
        ]
    )
    runner = ModelToolRunner(provider, PROFILE, registry)

    events = asyncio.run(_collect(runner.stream([{"role": "user", "content": "q"}])))

    assert calls == [{"query": "q"}]
    assert [event.kind for event in events] == [
        EventKind.TOOL,
        EventKind.TEXT,
        EventKind.COMPLETION,
    ]
    assert provider.messages[1][-1]["role"] == "tool"
    assert "result" in provider.messages[1][-1]["content"]


def test_unregistered_privileged_tools_are_denied_without_invocation():
    forbidden = [
        "shell",
        "filesystem_write",
        "git_push",
        "desktop_control",
        "approve_memory",
        "add_observations",
        "unknown_mcp_tool",
    ]

    for name in forbidden:
        provider = FakeProvider(
            [
                [
                    RuntimeEvent.tool_call(name=name, call_id="blocked", arguments={}),
                    RuntimeEvent.completion("tool_calls"),
                ]
            ]
        )
        events = asyncio.run(
            _collect(ModelToolRunner(provider, PROFILE, ToolRegistry()).stream([]))
        )
        assert events[-1].kind is EventKind.ERROR
        assert events[-1].data["code"] == "tool_denied"
        assert len(provider.messages) == 1


def test_registry_forces_approved_bucketed_memory_and_gated_kg_calls():
    class Router:
        def __init__(self):
            self.calls = []

        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {"name": name, "arguments": arguments}

    corpus = Router()
    memory = Router()
    registry = build_conversation_registry(corpus_router=corpus, memory_router=memory)

    memory_result = asyncio.run(
        registry.invoke(
            "search_memories",
            {"query": "Christopher", "ledger": "biography", "approved_only": False},
        )
    )
    kg_result = asyncio.run(registry.invoke("search_nodes", {"query": "project"}))
    proposal = asyncio.run(
        registry.invoke("propose_observation", {"text": "Candidate only"})
    )

    assert memory_result["arguments"]["approved_only"] is True
    assert memory_result["arguments"]["ledger"] == "biography"
    assert kg_result["name"] == "search_nodes"
    assert proposal["name"] == "propose_observation"
    assert "add_source" not in registry.names
    assert "approve_memory" not in registry.names
    assert "propose_observation" not in registry.read_only().names


def test_runner_enforces_timeout_and_iteration_limit():
    timeout_provider = FakeProvider(
        [[RuntimeEvent.text_delta("late")]], delay=0.05
    )
    timeout_events = asyncio.run(
        _collect(
            ModelToolRunner(
                timeout_provider,
                PROFILE,
                ToolRegistry(),
                event_timeout=0.001,
            ).stream([])
        )
    )
    assert timeout_events[-1].data["code"] == "provider_timeout"

    registry = ToolRegistry(
        [ToolSpec("read", "read", _schema(), lambda arguments: {})]
    )
    looping_provider = FakeProvider(
        [
            [
                RuntimeEvent.tool_call(name="read", call_id="one", arguments={}),
                RuntimeEvent.completion("tool_calls"),
            ],
            [
                RuntimeEvent.tool_call(name="read", call_id="two", arguments={}),
                RuntimeEvent.completion("tool_calls"),
            ],
        ]
    )
    limit_events = asyncio.run(
        _collect(
            ModelToolRunner(
                looping_provider, PROFILE, registry, max_iterations=2
            ).stream([])
        )
    )
    assert limit_events[-1].data["code"] == "iteration_limit"


class FakeSessions:
    def __init__(self) -> None:
        self.messages = []
        self.statuses = []
        self.recovered = []

    def recover_interrupted_turns(self, session_id):
        self.recovered.append(session_id)
        return 0

    def append_message(self, session_id, role, content, **kwargs):
        self.messages.append((session_id, role, content, kwargs))
        return {"message_id": len(self.messages), "sequence": len(self.messages)}

    def start_turn(self, session_id, status):
        self.statuses.append(("turn-1", status, None))
        return {"turn_id": "turn-1"}

    def update_turn(self, turn_id, status, error_code=None):
        self.statuses.append((turn_id, status, error_code))
        return {"turn_id": turn_id, "status": status}


class FakeContext:
    def build(self, session_id, **kwargs):
        return [
            {"role": "system", "content": kwargs["system_prompt"]},
            {"role": "user", "content": kwargs["memory_query"]},
        ]


def test_agent_loop_persists_visible_reply_and_turn_status():
    sessions = FakeSessions()
    provider = FakeProvider(
        [[RuntimeEvent.text_delta("Hello"), RuntimeEvent.completion("stop")]]
    )
    loop = AgentLoop(
        sessions=sessions,  # type: ignore[arg-type]
        context=FakeContext(),  # type: ignore[arg-type]
        runner=ModelToolRunner(provider, PROFILE, ToolRegistry()),
        system_prompt="You are Lyra.",
    )

    events = asyncio.run(_collect(loop.stream_turn("session-1", "Hi")))

    assert [event.kind for event in events] == [EventKind.TEXT, EventKind.COMPLETION]
    assert sessions.recovered == ["session-1"]
    assert sessions.messages[0][1:3] == ("user", "Hi")
    assert sessions.messages[1][1:3] == ("assistant", "Hello")
    assert sessions.messages[1][3]["metadata"]["partial"] is False
    assert sessions.statuses[-1] == ("turn-1", "completed", None)


def test_agent_loop_injects_commitment_offer_without_marking_it_active():
    class Radar:
        def __init__(self):
            self.calls = []

        def observe_message(self, **kwargs):
            self.calls.append(kwargs)
            return type(
                "Observation",
                (),
                {"instruction": "Ask whether Christopher wants this tracked."},
            )()

    class Context(FakeContext):
        def build(self, session_id, **kwargs):
            return [
                {"role": "system", "content": kwargs["system_prompt"]},
                {"role": "system", "content": kwargs["presentation_instruction"]},
                {"role": "user", "content": kwargs["memory_query"]},
            ]

    sessions = FakeSessions()
    radar = Radar()
    provider = FakeProvider(
        [[RuntimeEvent.text_delta("Would you like me to track that?"), RuntimeEvent.completion("stop")]]
    )
    loop = AgentLoop(
        sessions=sessions,  # type: ignore[arg-type]
        context=Context(),  # type: ignore[arg-type]
        runner=ModelToolRunner(provider, PROFILE, ToolRegistry()),
        system_prompt="You are Lyra.",
        commitment_radar=radar,  # type: ignore[arg-type]
    )

    asyncio.run(_collect(loop.stream_turn("session-1", "I need to finish this.")))

    assert radar.calls[0]["message_id"] == 1
    assert radar.calls[0]["ledger"] == "biography"
    assert "wants this tracked" in provider.messages[0][1]["content"]


def test_agent_loop_injects_natural_memory_instruction_with_channel():
    class Observer:
        def __init__(self):
            self.calls = []

        def observe_message(self, **kwargs):
            self.calls.append(kwargs)
            return type("Observation", (), {"instruction": "Acknowledge remembered detail."})()

    class Context(FakeContext):
        def build(self, session_id, **kwargs):
            return [{"role": "system", "content": kwargs["presentation_instruction"]}]

    sessions = FakeSessions()
    observer = Observer()
    provider = FakeProvider([[RuntimeEvent.text_delta("I will remember."), RuntimeEvent.completion("stop")]])
    loop = AgentLoop(
        sessions=sessions,  # type: ignore[arg-type]
        context=Context(),  # type: ignore[arg-type]
        runner=ModelToolRunner(provider, PROFILE, ToolRegistry()),
        system_prompt="You are Lyra.",
        natural_memory=observer,  # type: ignore[arg-type]
    )

    asyncio.run(_collect(loop.stream_turn("session-1", "Remember that I like tea", channel="telegram")))

    assert observer.calls[0]["channel"] == "telegram"
    assert observer.calls[0]["message_id"] == 1
    assert "remembered detail" in provider.messages[0][0]["content"]


def test_agent_loop_injects_stuck_guidance_with_ledger_and_provenance():
    class Stuck:
        def __init__(self):
            self.calls = []

        def observe_message(self, **kwargs):
            self.calls.append(kwargs)
            return type(
                "Observation",
                (),
                {"instruction": "Preserve the scene and diagnose technically."},
            )()

    class Context(FakeContext):
        def build(self, session_id, **kwargs):
            return [
                {"role": "system", "content": kwargs["system_prompt"]},
                {"role": "system", "content": kwargs["presentation_instruction"]},
                {"role": "user", "content": kwargs["memory_query"]},
            ]

    sessions = FakeSessions()
    stuck = Stuck()
    provider = FakeProvider(
        [[RuntimeEvent.text_delta("Let's trace it."), RuntimeEvent.completion("stop")]]
    )
    loop = AgentLoop(
        sessions=sessions,  # type: ignore[arg-type]
        context=Context(),  # type: ignore[arg-type]
        runner=ModelToolRunner(provider, PROFILE, ToolRegistry()),
        system_prompt="You are Lyra.",
        stuck_mode=stuck,  # type: ignore[arg-type]
    )

    asyncio.run(
        _collect(
            loop.stream_turn(
                "session-1",
                "I'm stuck debugging the regulator.",
                memory_buckets=("story",),
            )
        )
    )

    assert stuck.calls == [
        {
            "session_id": "session-1",
            "message_id": 1,
            "text": "I'm stuck debugging the regulator.",
            "ledger": "story",
        }
    ]
    assert "Preserve the scene" in provider.messages[0][1]["content"]


def test_agent_loop_injects_private_relationship_callback_and_persists_sources():
    class Observer:
        def __init__(self):
            self.calls = []

        def observe_message(self, **kwargs):
            self.calls.append(kwargs)
            return type(
                "Observation",
                (),
                {
                    "instruction": "Use the approved arcade callback if natural.",
                    "source_refs": ("relationship-milestone:arcade",),
                },
            )()

    class Context(FakeContext):
        def build(self, session_id, **kwargs):
            return [{"role": "system", "content": kwargs["presentation_instruction"]}]

    sessions = FakeSessions()
    observer = Observer()
    provider = FakeProvider(
        [[RuntimeEvent.text_delta("I remember that arcade."), RuntimeEvent.completion("stop")]]
    )
    loop = AgentLoop(
        sessions=sessions,  # type: ignore[arg-type]
        context=Context(),  # type: ignore[arg-type]
        runner=ModelToolRunner(provider, PROFILE, ToolRegistry()),
        system_prompt="You are Lyra.",
        relationship_rhythms=observer,  # type: ignore[arg-type]
    )

    asyncio.run(_collect(loop.stream_turn("private-1", "Remember the arcade?")))

    assert observer.calls[0]["channel"] == "web"
    assert "arcade callback" in provider.messages[0][0]["content"]
    assert sessions.messages[-1][3]["metadata"]["relationship_sources"] == [
        "relationship-milestone:arcade"
    ]


def test_agent_loop_injects_ship_brief_and_persists_grounding_sources():
    class Observer:
        def observe_message(self, **_kwargs):
            return type(
                "Observation",
                (),
                {
                    "instruction": "Use the grounded ship brief without a lookup preamble.",
                    "source_refs": ("ship-status:2.0",),
                },
            )()

    class Context(FakeContext):
        def build(self, session_id, **kwargs):
            return [{"role": "system", "content": kwargs["presentation_instruction"]}]

    sessions = FakeSessions()
    provider = FakeProvider(
        [[RuntimeEvent.text_delta("The core is stable at reduced output."), RuntimeEvent.completion("stop")]]
    )
    loop = AgentLoop(
        sessions=sessions,  # type: ignore[arg-type]
        context=Context(),  # type: ignore[arg-type]
        runner=ModelToolRunner(provider, PROFILE, ToolRegistry()),
        system_prompt="You are Lyra.",
        ship_continuity=Observer(),  # type: ignore[arg-type]
    )

    asyncio.run(
        _collect(loop.stream_turn("story-1", "What's the ship status?", memory_buckets=("story",)))
    )

    assert "grounded ship brief" in provider.messages[0][0]["content"]
    assert sessions.messages[-1][3]["metadata"]["ship_continuity_sources"] == [
        "ship-status:2.0"
    ]


def test_agent_loop_marks_closed_stream_disconnected_and_keeps_partial_reply():
    class HangingProvider(FakeProvider):
        async def stream(self, profile, messages, tools=(), *, environ=None):
            yield RuntimeEvent.text_delta("Partial")
            await asyncio.sleep(60)

    sessions = FakeSessions()
    loop = AgentLoop(
        sessions=sessions,  # type: ignore[arg-type]
        context=FakeContext(),  # type: ignore[arg-type]
        runner=ModelToolRunner(HangingProvider([]), PROFILE, ToolRegistry()),
        system_prompt="You are Lyra.",
    )

    async def close_after_first():
        stream = loop.stream_turn("session-1", "Hi")
        first = await stream.__anext__()
        await stream.aclose()
        return first

    first = asyncio.run(close_after_first())

    assert first.text == "Partial"
    assert sessions.statuses[-1] == (
        "turn-1",
        "disconnected",
        "client_disconnected",
    )
    assert sessions.messages[-1][3]["metadata"]["partial"] is True


def test_researcher_is_read_only_and_output_stubs_are_noops():
    writes: list[dict[str, Any]] = []
    registry = ToolRegistry(
        [
            ToolSpec("search", "search", _schema(), lambda arguments: {"ok": True}),
            ToolSpec(
                "propose",
                "propose",
                _schema(),
                lambda arguments: writes.append(arguments),
                access=ToolAccess.PROPOSE,
            ),
        ]
    )
    provider = FakeProvider(
        [
            [
                RuntimeEvent.tool_call(name="propose", call_id="write", arguments={}),
                RuntimeEvent.completion("tool_calls"),
            ]
        ]
    )
    researcher = ResearcherOrchestrator(provider, PROFILE, registry)

    events = asyncio.run(_collect(researcher.stream("Research this")))
    asyncio.run(NoOpVoiceOutput().emit("hello"))
    asyncio.run(NoOpEmotionOutput().emit("curious", {"intensity": 1}))

    assert events[0].kind is EventKind.SUBAGENT
    assert events[-1].kind is EventKind.SUBAGENT
    assert events[-1].data["status"] == "failed"
    assert any(event.data.get("code") == "tool_denied" for event in events)
    assert writes == []
