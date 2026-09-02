"""Bounded standalone conversation and read-only specialist loops."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from lyra.providers import ModelProfile
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.runtime_tools import ToolDeniedError, ToolRegistry
from lyra.sessions import ContextBuilder, SessionService


class ProviderAdapter(Protocol):
    def stream(
        self,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] = (),
        *,
        environ: Mapping[str, str] | None = None,
    ) -> AsyncIterator[RuntimeEvent]: ...


class VoiceOutput(Protocol):
    async def emit(self, text: str) -> None: ...


class EmotionOutput(Protocol):
    async def emit(self, name: str, data: Mapping[str, Any]) -> None: ...


class NoOpVoiceOutput:
    async def emit(self, text: str) -> None:
        return None


class NoOpEmotionOutput:
    async def emit(self, name: str, data: Mapping[str, Any]) -> None:
        return None


def _tool_message(event: RuntimeEvent) -> dict[str, Any]:
    return {
        "id": event.call_id,
        "type": "function",
        "function": {
            "name": event.name,
            "arguments": json.dumps(dict(event.arguments or {}), sort_keys=True),
        },
    }


@dataclass
class ModelToolRunner:
    provider: ProviderAdapter
    profile: ModelProfile
    tools: ToolRegistry
    max_iterations: int = 6
    event_timeout: float = 120.0
    max_tool_result_chars: int = 32_000

    async def stream(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> AsyncIterator[RuntimeEvent]:
        working = [dict(message) for message in messages]
        for _iteration in range(self.max_iterations):
            tool_calls: list[RuntimeEvent] = []
            text_parts: list[str] = []
            completion: RuntimeEvent | None = None
            iterator = self.provider.stream(
                self.profile, working, self.tools.definitions()
            ).__aiter__()
            while True:
                try:
                    event = await asyncio.wait_for(
                        iterator.__anext__(), timeout=self.event_timeout
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    yield RuntimeEvent.error(
                        "provider_timeout", "Provider stream timed out"
                    )
                    return
                if event.kind is EventKind.ERROR:
                    yield event
                    return
                if event.kind is EventKind.TEXT:
                    text_parts.append(event.text or "")
                    yield event
                elif event.kind is EventKind.TOOL:
                    tool_calls.append(event)
                    yield event
                elif event.kind is EventKind.EMOTION:
                    yield event
                elif event.kind is EventKind.COMPLETION:
                    completion = event

            if not tool_calls:
                yield completion or RuntimeEvent.completion("stop")
                return

            working.append(
                {
                    "role": "assistant",
                    "content": "".join(text_parts) or None,
                    "tool_calls": [_tool_message(event) for event in tool_calls],
                }
            )
            for event in tool_calls:
                try:
                    result = await self.tools.invoke(
                        event.name or "", event.arguments or {}
                    )
                except ToolDeniedError as exc:
                    yield RuntimeEvent.error("tool_denied", str(exc))
                    return
                except Exception:
                    yield RuntimeEvent.error(
                        "tool_execution_failed",
                        f"Tool '{event.name or 'unknown'}' failed",
                    )
                    return
                serialized = json.dumps(result, default=str, sort_keys=True)
                if len(serialized) > self.max_tool_result_chars:
                    serialized = serialized[: self.max_tool_result_chars] + "…"
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": event.call_id,
                        "name": event.name,
                        "content": serialized,
                    }
                )
        yield RuntimeEvent.error(
            "iteration_limit", "Agent loop reached its tool iteration limit"
        )


@dataclass
class AgentLoop:
    sessions: SessionService
    context: ContextBuilder
    runner: ModelToolRunner
    system_prompt: str
    voice: VoiceOutput = field(default_factory=NoOpVoiceOutput)
    emotion: EmotionOutput = field(default_factory=NoOpEmotionOutput)

    async def stream_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        memory_buckets: tuple[str, ...] = ("biography",),
    ) -> AsyncIterator[RuntimeEvent]:
        self.sessions.recover_interrupted_turns(session_id)
        self.sessions.append_message(session_id, "user", user_text)
        turn = self.sessions.start_turn(session_id, "running")
        assistant_parts: list[str] = []
        persisted = False

        def persist_assistant(partial: bool) -> None:
            nonlocal persisted
            text = "".join(assistant_parts).strip()
            if text and not persisted:
                self.sessions.append_message(
                    session_id,
                    "assistant",
                    text,
                    metadata={"partial": partial, "turn_id": turn["turn_id"]},
                )
                persisted = True

        try:
            messages = self.context.build(
                session_id,
                system_prompt=self.system_prompt,
                memory_query=user_text,
                memory_buckets=memory_buckets,
            )
            async for event in self.runner.stream(messages):
                if event.kind is EventKind.TEXT:
                    assistant_parts.append(event.text or "")
                elif event.kind is EventKind.EMOTION and event.name:
                    await self.emotion.emit(event.name, event.data)
                elif event.kind is EventKind.ERROR:
                    persist_assistant(partial=True)
                    self.sessions.update_turn(
                        turn["turn_id"],
                        "failed",
                        error_code=str(event.data.get("code", "runtime_error")),
                    )
                    yield event
                    return
                elif event.kind is EventKind.COMPLETION:
                    persist_assistant(partial=False)
                    self.sessions.update_turn(turn["turn_id"], "completed")
                    await self.voice.emit("".join(assistant_parts))
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            persist_assistant(partial=True)
            self.sessions.update_turn(
                turn["turn_id"], "disconnected", error_code="client_disconnected"
            )
            raise
        except Exception:
            persist_assistant(partial=True)
            self.sessions.update_turn(
                turn["turn_id"], "failed", error_code="runtime_error"
            )
            yield RuntimeEvent.error("runtime_error", "Conversation turn failed")


@dataclass
class ResearcherOrchestrator:
    provider: ProviderAdapter
    profile: ModelProfile
    conversation_tools: ToolRegistry
    max_iterations: int = 4
    event_timeout: float = 120.0

    async def stream(self, task_packet: str) -> AsyncIterator[RuntimeEvent]:
        yield RuntimeEvent.subagent("researcher", status="started")
        runner = ModelToolRunner(
            provider=self.provider,
            profile=self.profile,
            tools=self.conversation_tools.read_only(),
            max_iterations=self.max_iterations,
            event_timeout=self.event_timeout,
        )
        failed = False
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Lyra's read-only researcher. Use only supplied search "
                    "tools. Do not write, approve, publish, or alter files."
                ),
            },
            {"role": "user", "content": task_packet},
        ]
        async for event in runner.stream(messages):
            if event.kind is EventKind.ERROR:
                failed = True
            yield event
        yield RuntimeEvent.subagent(
            "researcher", status="failed" if failed else "completed"
        )
