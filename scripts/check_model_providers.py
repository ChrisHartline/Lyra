"""Safely verify Lyra's configured provider credentials and model access."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

from lyra.providers import (
    ModelProfile,
    ModelProfiles,
    ProviderConfigurationError,
    adapter_for,
)
from lyra.runtime_events import EventKind


ROOT = Path(__file__).resolve().parents[1]


class ProviderCheckError(RuntimeError):
    """Safe-to-print smoke-check failure."""


@dataclass(frozen=True)
class ProviderCheck:
    profile: str
    provider: str
    configured_model: str
    resolved_model: str
    generated: bool


def _model_headers(profile: ModelProfile, api_key: str) -> dict[str, str]:
    if profile.provider == "openai-compatible":
        return {"Authorization": f"Bearer {api_key}"}
    if profile.provider == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    raise ProviderCheckError(f"Unsupported provider '{profile.provider}'")


async def check_profile(
    profile_name: str,
    *,
    client: httpx.AsyncClient,
    generate: bool = True,
    generation_timeout: float = 30.0,
    adapter_factory: Callable[[ModelProfile], Any] = adapter_for,
) -> ProviderCheck:
    try:
        profile = ModelProfiles().resolve(profile_name)
        api_key = profile.api_key()
    except ProviderConfigurationError as exc:
        raise ProviderCheckError(str(exc)) from exc

    model_url = f"{profile.base_url}/models/{quote(profile.model, safe='')}"
    try:
        response = await client.get(
            model_url, headers=_model_headers(profile, api_key)
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProviderCheckError(
            f"{profile_name} model lookup failed with status "
            f"{exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderCheckError(
            f"{profile_name} provider connection failed"
        ) from exc

    try:
        model_data = response.json()
    except ValueError as exc:
        raise ProviderCheckError(
            f"{profile_name} model lookup returned invalid JSON"
        ) from exc
    resolved_model = (
        str(model_data.get("id"))
        if isinstance(model_data, dict) and model_data.get("id")
        else profile.model
    )

    generated = False
    if generate:
        smoke_profile = replace(profile, max_tokens=min(profile.max_tokens, 64))
        adapter = adapter_factory(smoke_profile)
        async def collect_text() -> list[str]:
            text_parts: list[str] = []
            async for event in adapter.stream(
                smoke_profile,
                [{"role": "user", "content": "Reply with exactly OK"}],
            ):
                if event.kind is EventKind.TEXT and event.text:
                    text_parts.append(event.text)
                elif event.kind is EventKind.ERROR:
                    raise ProviderCheckError(
                        f"{profile_name} generation failed: "
                        f"{event.data.get('code', 'provider_error')}"
                    )
            return text_parts

        try:
            text_parts = await asyncio.wait_for(
                collect_text(), timeout=generation_timeout
            )
        except asyncio.TimeoutError as exc:
            raise ProviderCheckError(
                f"{profile_name} generation timed out after "
                f"{generation_timeout:g}s"
            ) from exc
        if not "".join(text_parts).strip():
            raise ProviderCheckError(
                f"{profile_name} generation returned no visible text"
            )
        generated = True

    return ProviderCheck(
        profile=profile_name,
        provider=profile.provider,
        configured_model=profile.model,
        resolved_model=resolved_model,
        generated=generated,
    )


async def run_checks(
    generate: bool = True, *, timeout_seconds: float = 30.0
) -> list[ProviderCheck]:
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = []
        for name in ("conversation", "specialist"):
            results.append(
                await check_profile(
                    name,
                    client=client,
                    generate=generate,
                    generation_timeout=timeout_seconds,
                )
            )
        return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Lyra provider keys, model names, and minimal generation"
    )
    parser.add_argument(
        "--lookup-only",
        action="store_true",
        help="Authenticate and resolve models without generating text",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Maximum seconds for each lookup or generation (default: 30)",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    load_dotenv(ROOT / ".env", override=False)
    try:
        results = asyncio.run(
            run_checks(
                generate=not args.lookup_only,
                timeout_seconds=args.timeout,
            )
        )
    except ProviderCheckError as exc:
        print(f"FAIL: {exc}")
        return 1
    for result in results:
        generation = "generation=ok" if result.generated else "generation=skipped"
        print(
            f"PASS: {result.profile} provider={result.provider} "
            f"configured={result.configured_model} "
            f"resolved={result.resolved_model} {generation}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
