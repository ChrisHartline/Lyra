from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable
from typing import Any

import httpx

from lyra.providers import (
    AnthropicAdapter,
    ModelProfile,
    ModelProfiles,
    OpenAICompatibleAdapter,
    ProviderConfigurationError,
    normalize_anthropic_stream,
    normalize_openai_stream,
)
from lyra.runtime_events import EventKind, RuntimeEvent


async def _events(items: list[dict[str, Any]]) -> AsyncIterable[dict[str, Any]]:
    for item in items:
        yield item


async def _collect(stream) -> list[RuntimeEvent]:
    return [event async for event in stream]


def test_openai_and_anthropic_streams_share_normalized_contract():
    openai_chunks = [
        {"choices": [{"delta": {"content": "Hello "}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {
                                    "name": "search_corpus",
                                    "arguments": '{"query":',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '"stars"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"total_tokens": 12},
        },
    ]
    anthropic_events = [
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello "},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "call-1",
                "name": "search_corpus",
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"query":"stars"}',
            },
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 12},
        },
        {"type": "message_stop"},
    ]

    openai = asyncio.run(_collect(normalize_openai_stream(_events(openai_chunks))))
    anthropic = asyncio.run(
        _collect(normalize_anthropic_stream(_events(anthropic_events)))
    )

    assert [event.kind for event in openai] == [
        EventKind.TEXT,
        EventKind.TOOL,
        EventKind.COMPLETION,
    ]
    assert [event.kind for event in anthropic] == [
        EventKind.TEXT,
        EventKind.TOOL,
        EventKind.COMPLETION,
    ]
    for result in (openai, anthropic):
        assert result[0].text == "Hello "
        assert result[1].name == "search_corpus"
        assert result[1].call_id == "call-1"
        assert result[1].arguments == {"query": "stars"}


def test_runtime_event_contract_includes_subagent_emotion_and_safe_errors():
    subagent = RuntimeEvent.subagent("researcher", status="started")
    emotion = RuntimeEvent.emotion("curious", intensity=0.4)
    error = RuntimeEvent.error("provider_error", "Provider stream reported an error")

    assert subagent.kind is EventKind.SUBAGENT
    assert emotion.kind is EventKind.EMOTION
    assert error.kind is EventKind.ERROR
    assert error.data == {"code": "provider_error"}


def test_logical_profiles_resolve_at_runtime_and_fail_without_models():
    profiles = ModelProfiles(
        {
            "LYRA_MODEL": "grok-test",
            "GROK_BASE_URL": "https://example.test/v1/",
            "ANTHROPIC_MODEL": "claude-test",
        }
    )

    conversation = profiles.resolve("conversation")
    specialist = profiles.resolve("specialist")

    assert conversation.provider == "openai-compatible"
    assert conversation.model == "grok-test"
    assert conversation.base_url == "https://example.test/v1"
    assert specialist.provider == "anthropic"
    assert specialist.model == "claude-test"

    try:
        ModelProfiles({}).resolve("conversation")
    except ProviderConfigurationError as exc:
        assert str(exc) == "Model profile 'conversation' has no configured model"
    else:  # pragma: no cover
        raise AssertionError("missing profile model should fail")


def test_adapters_parse_mocked_sse_and_do_not_leak_credentials():
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if request.url.path.endswith("chat/completions"):
            body = (
                'data: {"choices":[{"delta":{"content":"Grok"},'
                '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
        else:
            body = (
                'event: content_block_delta\n'
                'data: {"type":"content_block_delta","index":0,'
                '"delta":{"type":"text_delta","text":"Claude"}}\n\n'
                'event: message_delta\n'
                'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
                'event: message_stop\n'
                'data: {"type":"message_stop"}\n\n'
            )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://example.test"
        ) as client:
            grok = ModelProfile(
                "conversation",
                "openai-compatible",
                "grok-test",
                "GROK_API_KEY",
                "https://example.test/v1",
            )
            claude = ModelProfile(
                "specialist",
                "anthropic",
                "claude-test",
                "ANTHROPIC_API_KEY",
                "https://example.test/v1",
            )
            grok_events = await _collect(
                OpenAICompatibleAdapter(client).stream(
                    grok, [{"role": "user", "content": "hi"}], environ={"GROK_API_KEY": "secret-g"}
                )
            )
            claude_events = await _collect(
                AnthropicAdapter(client).stream(
                    claude,
                    [
                        {"role": "system", "content": "be precise"},
                        {"role": "user", "content": "hi"},
                    ],
                    environ={"ANTHROPIC_API_KEY": "secret-a"},
                )
            )
            missing = await _collect(
                OpenAICompatibleAdapter(client).stream(grok, [], environ={})
            )
        return grok_events, claude_events, missing

    grok_events, claude_events, missing = asyncio.run(run())

    assert grok_events[0].text == "Grok"
    assert claude_events[0].text == "Claude"
    assert requests[1]["system"] == "be precise"
    assert requests[1]["messages"] == [{"role": "user", "content": "hi"}]
    assert missing[0].kind is EventKind.ERROR
    assert missing[0].data["code"] == "provider_not_configured"
    assert "secret" not in (missing[0].text or "").lower()


def test_invalid_tool_json_becomes_error_without_raw_payload():
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "bad",
                                "function": {
                                    "name": "search_corpus",
                                    "arguments": "not-a-secret-json-value",
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    ]

    events = asyncio.run(_collect(normalize_openai_stream(_events(chunks))))

    assert events[0].kind is EventKind.ERROR
    assert "not-a-secret" not in (events[0].text or "")


def test_anthropic_adapter_translates_generic_tool_history():
    payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=(
                'event: message_delta\n'
                'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
                'event: message_stop\n'
                'data: {"type":"message_stop"}\n\n'
            ),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            profile = ModelProfile(
                "specialist",
                "anthropic",
                "claude-test",
                "ANTHROPIC_API_KEY",
                "https://example.test/v1",
            )
            return await _collect(
                AnthropicAdapter(client).stream(
                    profile,
                    [
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_corpus",
                                        "arguments": '{"query":"stars"}',
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "call-1",
                            "content": '{"hits":[]}',
                        },
                    ],
                    environ={"ANTHROPIC_API_KEY": "secret"},
                )
            )

    events = asyncio.run(run())

    assert events[-1].kind is EventKind.COMPLETION
    assert payloads[0]["messages"][0]["content"][0] == {
        "type": "tool_use",
        "id": "call-1",
        "name": "search_corpus",
        "input": {"query": "stars"},
    }
    assert payloads[0]["messages"][1]["content"][0]["type"] == "tool_result"
