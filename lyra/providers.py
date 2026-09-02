"""Async model adapters and stream normalization for the Lyra runtime."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from lyra.runtime_events import RuntimeEvent


class ProviderConfigurationError(ValueError):
    """A safe-to-display provider configuration error."""


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider: str
    model: str
    api_key_env: str
    base_url: str
    max_tokens: int = 4096

    def api_key(self, environ: Mapping[str, str] | None = None) -> str:
        source = os.environ if environ is None else environ
        value = source.get(self.api_key_env)
        if not value:
            raise ProviderConfigurationError(
                f"Model profile '{self.name}' requires {self.api_key_env}"
            )
        return value


class ModelProfiles:
    """Resolve logical model names without leaking credentials into profiles."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def resolve(self, name: str) -> ModelProfile:
        normalized = name.strip().lower()
        if normalized not in {"conversation", "specialist"}:
            raise ProviderConfigurationError(f"Unknown model profile '{name}'")

        prefix = f"LYRA_{normalized.upper()}"
        provider_default = (
            "openai-compatible" if normalized == "conversation" else "anthropic"
        )
        provider = self._environ.get(
            f"{prefix}_PROVIDER",
            self._environ.get("LYRA_PROVIDER", provider_default),
        ).strip().lower()
        model = self._environ.get(f"{prefix}_MODEL")
        if normalized == "conversation":
            model = model or self._environ.get("LYRA_MODEL")
        else:
            model = model or self._environ.get("ANTHROPIC_MODEL")
        if not model:
            raise ProviderConfigurationError(
                f"Model profile '{normalized}' has no configured model"
            )

        if provider == "openai-compatible":
            return ModelProfile(
                name=normalized,
                provider=provider,
                model=model,
                api_key_env=self._environ.get(
                    f"{prefix}_API_KEY_ENV", "GROK_API_KEY"
                ),
                base_url=self._environ.get(
                    f"{prefix}_BASE_URL",
                    self._environ.get("GROK_BASE_URL", "https://api.x.ai/v1"),
                ).rstrip("/"),
                max_tokens=int(
                    self._environ.get(f"{prefix}_MAX_TOKENS", "4096")
                ),
            )
        if provider == "anthropic":
            return ModelProfile(
                name=normalized,
                provider=provider,
                model=model,
                api_key_env=self._environ.get(
                    f"{prefix}_API_KEY_ENV", "ANTHROPIC_API_KEY"
                ),
                base_url=self._environ.get(
                    f"{prefix}_BASE_URL", "https://api.anthropic.com/v1"
                ).rstrip("/"),
                max_tokens=int(
                    self._environ.get(f"{prefix}_MAX_TOKENS", "4096")
                ),
            )
        raise ProviderConfigurationError(
            f"Model profile '{normalized}' uses unsupported provider '{provider}'"
        )


async def _sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            yield {"type": "error", "error": {"type": "invalid_stream_event"}}
            continue
        if isinstance(value, dict):
            yield value


def _json_object(value: str) -> tuple[dict[str, Any] | None, RuntimeEvent | None]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return None, RuntimeEvent.error(
            "invalid_tool_arguments", "Provider returned invalid tool arguments"
        )
    if not isinstance(parsed, dict):
        return None, RuntimeEvent.error(
            "invalid_tool_arguments", "Provider returned non-object tool arguments"
        )
    return parsed, None


async def normalize_openai_stream(
    chunks: AsyncIterable[Mapping[str, Any]],
) -> AsyncIterator[RuntimeEvent]:
    tools: dict[int, dict[str, str]] = {}
    emitted_tools = False
    last_usage: Mapping[str, Any] | None = None
    last_reason: str | None = None

    async for chunk in chunks:
        if chunk.get("type") == "error" or chunk.get("error"):
            error = chunk.get("error")
            code = error.get("type", "provider_error") if isinstance(error, Mapping) else "provider_error"
            yield RuntimeEvent.error(str(code), "Provider stream reported an error")
            continue
        usage = chunk.get("usage")
        if isinstance(usage, Mapping):
            last_usage = usage
        choices = chunk.get("choices")
        if not isinstance(choices, Sequence) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, Mapping):
            continue
        reason = choice.get("finish_reason")
        if reason is not None:
            last_reason = str(reason)
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield RuntimeEvent.text_delta(content)
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, Sequence):
            for call in tool_calls:
                if not isinstance(call, Mapping):
                    continue
                index = int(call.get("index", 0))
                current = tools.setdefault(
                    index, {"id": "", "name": "", "arguments": ""}
                )
                if call.get("id"):
                    current["id"] = str(call["id"])
                function = call.get("function")
                if isinstance(function, Mapping):
                    if function.get("name"):
                        current["name"] = str(function["name"])
                    if function.get("arguments"):
                        current["arguments"] += str(function["arguments"])

        if last_reason == "tool_calls" and not emitted_tools:
            for index in sorted(tools):
                call = tools[index]
                arguments, error = _json_object(call["arguments"])
                if error:
                    yield error
                    continue
                yield RuntimeEvent.tool_call(
                    name=call["name"],
                    call_id=call["id"] or f"tool-{index}",
                    arguments=arguments or {},
                )
            emitted_tools = True

    if tools and not emitted_tools:
        for index in sorted(tools):
            call = tools[index]
            arguments, error = _json_object(call["arguments"])
            if error:
                yield error
                continue
            yield RuntimeEvent.tool_call(
                name=call["name"],
                call_id=call["id"] or f"tool-{index}",
                arguments=arguments or {},
            )
    yield RuntimeEvent.completion(last_reason, usage=dict(last_usage or {}))


async def normalize_anthropic_stream(
    events: AsyncIterable[Mapping[str, Any]],
) -> AsyncIterator[RuntimeEvent]:
    tools: dict[int, dict[str, str]] = {}
    stop_reason: str | None = None
    usage: Mapping[str, Any] | None = None

    async for event in events:
        event_type = event.get("type")
        if event_type == "error":
            error = event.get("error")
            code = error.get("type", "provider_error") if isinstance(error, Mapping) else "provider_error"
            yield RuntimeEvent.error(str(code), "Provider stream reported an error")
        elif event_type == "content_block_start":
            block = event.get("content_block")
            if isinstance(block, Mapping) and block.get("type") == "tool_use":
                index = int(event.get("index", 0))
                tools[index] = {
                    "id": str(block.get("id", f"tool-{index}")),
                    "name": str(block.get("name", "")),
                    "arguments": "",
                }
        elif event_type == "content_block_delta":
            delta = event.get("delta")
            if not isinstance(delta, Mapping):
                continue
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                yield RuntimeEvent.text_delta(str(delta["text"]))
            elif delta.get("type") == "input_json_delta":
                index = int(event.get("index", 0))
                if index in tools:
                    tools[index]["arguments"] += str(delta.get("partial_json", ""))
        elif event_type == "content_block_stop":
            index = int(event.get("index", 0))
            call = tools.pop(index, None)
            if call:
                arguments, error = _json_object(call["arguments"])
                if error:
                    yield error
                else:
                    yield RuntimeEvent.tool_call(
                        name=call["name"],
                        call_id=call["id"],
                        arguments=arguments or {},
                    )
        elif event_type == "message_delta":
            delta = event.get("delta")
            if isinstance(delta, Mapping) and delta.get("stop_reason") is not None:
                stop_reason = str(delta["stop_reason"])
            if isinstance(event.get("usage"), Mapping):
                usage = event["usage"]

    yield RuntimeEvent.completion(stop_reason, usage=dict(usage or {}))


class OpenAICompatibleAdapter:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def stream(
        self,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] = (),
        *,
        environ: Mapping[str, str] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        try:
            api_key = profile.api_key(environ)
        except ProviderConfigurationError as exc:
            yield RuntimeEvent.error("provider_not_configured", str(exc))
            return
        payload: dict[str, Any] = {
            "model": profile.model,
            "messages": list(messages),
            "max_tokens": profile.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = list(tools)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=3600)
        try:
            async with client.stream(
                "POST",
                f"{profile.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            ) as response:
                response.raise_for_status()
                async for event in normalize_openai_stream(_sse_json(response)):
                    yield event
        except httpx.HTTPStatusError as exc:
            yield RuntimeEvent.error(
                "provider_http_error",
                f"Provider request failed with status {exc.response.status_code}",
            )
        except httpx.HTTPError:
            yield RuntimeEvent.error("provider_connection_error", "Provider connection failed")
        finally:
            if owns_client:
                await client.aclose()


class AnthropicAdapter:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def stream(
        self,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] = (),
        *,
        environ: Mapping[str, str] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        try:
            api_key = profile.api_key(environ)
        except ProviderConfigurationError as exc:
            yield RuntimeEvent.error("provider_not_configured", str(exc))
            return
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "system":
                content = message.get("content")
                if isinstance(content, str):
                    system_parts.append(content)
            elif message.get("role") == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.get("tool_call_id"),
                                "content": str(message.get("content", "")),
                            }
                        ],
                    }
                )
            elif message.get("role") == "assistant" and message.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                content = message.get("content")
                if isinstance(content, str) and content:
                    blocks.append({"type": "text", "text": content})
                calls = message.get("tool_calls")
                if isinstance(calls, Sequence):
                    for call in calls:
                        if not isinstance(call, Mapping):
                            continue
                        function = call.get("function")
                        if not isinstance(function, Mapping):
                            continue
                        arguments = function.get("arguments", "{}")
                        if isinstance(arguments, str):
                            parsed, error = _json_object(arguments)
                            if error:
                                parsed = {}
                        elif isinstance(arguments, Mapping):
                            parsed = dict(arguments)
                        else:
                            parsed = {}
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": call.get("id"),
                                "name": function.get("name"),
                                "input": parsed or {},
                            }
                        )
                anthropic_messages.append({"role": "assistant", "content": blocks})
            else:
                anthropic_messages.append(dict(message))
        payload: dict[str, Any] = {
            "model": profile.model,
            "messages": anthropic_messages,
            "max_tokens": profile.max_tokens,
            "stream": True,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [
                {
                    "name": tool.get("function", {}).get("name"),
                    "description": tool.get("function", {}).get("description", ""),
                    "input_schema": tool.get("function", {}).get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
                if tool.get("type") == "function"
                and isinstance(tool.get("function"), Mapping)
                else tool
                for tool in tools
            ]
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=3600)
        try:
            async with client.stream(
                "POST",
                f"{profile.base_url}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
            ) as response:
                response.raise_for_status()
                async for event in normalize_anthropic_stream(_sse_json(response)):
                    yield event
        except httpx.HTTPStatusError as exc:
            yield RuntimeEvent.error(
                "provider_http_error",
                f"Provider request failed with status {exc.response.status_code}",
            )
        except httpx.HTTPError:
            yield RuntimeEvent.error("provider_connection_error", "Provider connection failed")
        finally:
            if owns_client:
                await client.aclose()


def adapter_for(profile: ModelProfile) -> OpenAICompatibleAdapter | AnthropicAdapter:
    if profile.provider == "openai-compatible":
        return OpenAICompatibleAdapter()
    if profile.provider == "anthropic":
        return AnthropicAdapter()
    raise ProviderConfigurationError(
        f"Model profile '{profile.name}' uses unsupported provider '{profile.provider}'"
    )
