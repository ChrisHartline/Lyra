"""Loopback-only FastAPI surface for Lyra's standalone chat runtime."""

from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from lyra.corpus_mcp import CorpusService, MCPToolRouter
from lyra.embeddings import EmbeddingService
from lyra.ingest import IngestPipeline
from lyra.kg_gatekeeper import build_gatekeeper_router
from lyra.packs import compose_runtime_context
from lyra.providers import ModelProfiles, ProviderConfigurationError, adapter_for
from lyra.runtime import AgentLoop, ModelToolRunner
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.runtime_tools import build_conversation_registry
from lyra.service import configure_rotating_logging
from lyra.sessions import ContextBuilder, SessionService


STATIC_DIR = Path(__file__).resolve().parent / "web_static"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class TurnLoop(Protocol):
    def stream_turn(
        self, session_id: str, user_text: str
    ) -> AsyncIterator[RuntimeEvent]: ...


LoopFactory = Callable[[str], TurnLoop]


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SessionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TurnCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


def validate_bind_host(host: str) -> str:
    if host.strip().lower() not in LOOPBACK_HOSTS:
        raise ValueError("Lyra web chat may bind only to a loopback address")
    return host.strip().lower()


def _event_payload(event: RuntimeEvent) -> dict[str, Any]:
    return {
        "kind": event.kind.value,
        "text": event.text,
        "name": event.name,
        "call_id": event.call_id,
        "arguments": dict(event.arguments) if event.arguments is not None else None,
        "data": dict(event.data),
    }


def _sse(event: str, data: dict[str, Any], event_id: int) -> str:
    payload = json.dumps(data, default=str, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


def default_loop_factory(sessions: SessionService) -> LoopFactory:
    embedding = EmbeddingService()
    corpus = CorpusService(
        embedding_service=embedding,
        ingest_pipeline=IngestPipeline(embedding_service=embedding),
    )
    corpus_router = MCPToolRouter(corpus)
    memory_router = build_gatekeeper_router()
    registry = build_conversation_registry(
        corpus_router=corpus_router, memory_router=memory_router
    )
    context = ContextBuilder(sessions, memory_search=corpus.search_memories)
    system_prompt = compose_runtime_context()

    class UnavailableLoop:
        def __init__(self, message: str) -> None:
            self.message = message

        async def stream_turn(
            self, session_id: str, user_text: str
        ) -> AsyncIterator[RuntimeEvent]:
            sessions.recover_interrupted_turns(session_id)
            sessions.append_message(session_id, "user", user_text)
            turn = sessions.start_turn(session_id, "running")
            sessions.update_turn(
                turn["turn_id"], "failed", error_code="runtime_not_configured"
            )
            yield RuntimeEvent.error("runtime_not_configured", self.message)

    def factory(_session_id: str) -> AgentLoop | UnavailableLoop:
        try:
            profile = ModelProfiles().resolve("conversation")
        except ProviderConfigurationError:
            return UnavailableLoop("Lyra's conversation model is not configured")
        provider = adapter_for(profile)
        return AgentLoop(
            sessions=sessions,
            context=context,
            runner=ModelToolRunner(provider, profile, registry),
            system_prompt=system_prompt,
        )

    return factory


def create_app(
    sessions: SessionService | None = None,
    loop_factory: LoopFactory | None = None,
) -> FastAPI:
    session_service = sessions or SessionService()
    factory = loop_factory or default_loop_factory(session_service)
    app = FastAPI(title="Lyra", version="0.2.0")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/app.css", include_in_schema=False)
    async def css():
        return FileResponse(STATIC_DIR / "app.css", media_type="text/css")

    @app.get("/app.js", include_in_schema=False)
    async def javascript():
        return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript")

    @app.get("/api/health")
    async def health():
        return {"status": "ready", "network": "loopback-only"}

    @app.get("/api/sessions")
    async def list_sessions():
        return {"sessions": session_service.list_sessions()}

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: SessionCreate):
        try:
            return session_service.create_session(request.name)
        except Exception as exc:
            raise HTTPException(status_code=409, detail="Session name is unavailable") from exc

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        try:
            return session_service.get_session(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(session_id: str, request: SessionUpdate):
        try:
            return session_service.rename_session(session_id, request.name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        if not session_service.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")

    @app.get("/api/sessions/{session_id}/messages")
    async def list_messages(session_id: str, after_sequence: int = 0):
        try:
            session_service.get_session(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return {
            "messages": session_service.list_messages(
                session_id, after_sequence=max(0, after_sequence)
            )
        }

    @app.post("/api/sessions/{session_id}/turns")
    async def create_turn(session_id: str, turn: TurnCreate, request: Request):
        try:
            session_service.get_session(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        async def stream() -> AsyncIterator[str]:
            event_id = 1
            yield _sse("status", {"status": "started"}, event_id)
            event_id += 1
            failed = False
            try:
                loop = factory(session_id)
                async for event in loop.stream_turn(session_id, turn.content):
                    if await request.is_disconnected():
                        break
                    if event.kind is EventKind.ERROR:
                        failed = True
                    yield _sse(event.kind.value, _event_payload(event), event_id)
                    event_id += 1
            except Exception:
                failed = True
                error = RuntimeEvent.error(
                    "runtime_not_configured", "Lyra runtime is not configured"
                )
                yield _sse("error", _event_payload(error), event_id)
                event_id += 1
            yield _sse(
                "status",
                {"status": "failed" if failed else "completed", "resume": "messages"},
                event_id,
            )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Lyra's local web chat")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    host = validate_bind_host(args.host)
    configure_rotating_logging(Path("logs"))
    import uvicorn

    uvicorn.run("lyra.web:app", host=host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
