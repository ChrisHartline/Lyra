from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys

import httpx

from lyra.runtime_events import RuntimeEvent


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_model_providers", ROOT / "scripts" / "check_model_providers.py"
)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


class FakeAdapter:
    async def stream(self, profile, messages):
        assert profile.max_tokens == 64
        assert messages == [{"role": "user", "content": "Reply with exactly OK"}]
        yield RuntimeEvent.text_delta("OK")
        yield RuntimeEvent.completion("stop")


class HangingAdapter:
    async def stream(self, profile, messages):
        await asyncio.sleep(60)
        yield RuntimeEvent.text_delta("too late")


def test_check_profile_authenticates_resolves_and_generates(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "not-printed")
    monkeypatch.setenv("LYRA_CONVERSATION_MODEL", "grok-test")
    monkeypatch.setenv("LYRA_CONVERSATION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LYRA_CONVERSATION_BASE_URL", "https://xai.test/v1")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models/grok-test"
        assert request.headers["authorization"] == "Bearer not-printed"
        return httpx.Response(200, json={"id": "grok-test-2026"})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await checker.check_profile(
                "conversation",
                client=client,
                adapter_factory=lambda profile: FakeAdapter(),
            )

    result = asyncio.run(run())

    assert result.configured_model == "grok-test"
    assert result.resolved_model == "grok-test-2026"
    assert result.generated is True


def test_check_profile_reports_safe_http_failure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sensitive-value")
    monkeypatch.setenv("LYRA_SPECIALIST_MODEL", "missing-model")
    monkeypatch.setenv("LYRA_SPECIALIST_PROVIDER", "anthropic")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"message": "sensitive-value must never print"}},
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await checker.check_profile("specialist", client=client)

    try:
        asyncio.run(run())
    except checker.ProviderCheckError as exc:
        message = str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid model should fail")

    assert message == "specialist model lookup failed with status 404"
    assert "sensitive-value" not in message


def test_check_profile_bounds_generation_time(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "not-printed")
    monkeypatch.setenv("LYRA_CONVERSATION_MODEL", "grok-test")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "grok-test"})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await checker.check_profile(
                "conversation",
                client=client,
                generation_timeout=0.01,
                adapter_factory=lambda profile: HangingAdapter(),
            )

    try:
        asyncio.run(run())
    except checker.ProviderCheckError as exc:
        message = str(exc)
    else:  # pragma: no cover
        raise AssertionError("hanging generation should time out")

    assert message == "conversation generation timed out after 0.01s"


def test_openai_adapter_sends_profile_token_cap():
    from lyra.providers import ModelProfile, OpenAICompatibleAdapter

    payloads = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"OK"},'
                '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            ),
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            profile = ModelProfile(
                "conversation",
                "openai-compatible",
                "grok-test",
                "GROK_API_KEY",
                "https://xai.test/v1",
                max_tokens=64,
            )
            return [
                event
                async for event in OpenAICompatibleAdapter(client).stream(
                    profile,
                    [{"role": "user", "content": "OK"}],
                    environ={"GROK_API_KEY": "key"},
                )
            ]

    asyncio.run(run())

    assert payloads[0]["max_tokens"] == 64
