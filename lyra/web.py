"""Loopback-only FastAPI surface for Lyra's standalone chat runtime."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from lyra.away import AwayModeService
from lyra.commitments import CommitmentService
from lyra.config import settings
from lyra.corpus_mcp import CorpusService, MCPToolRouter
from lyra.embeddings import EmbeddingService
from lyra.ingest import IngestPipeline
from lyra.kg_gatekeeper import build_gatekeeper_router
from lyra.knowledge_graph import MCPKnowledgeGraphWriter
from lyra.memory_control import MemoryControlService
from lyra.packs import compose_runtime_context
from lyra.providers import ModelProfiles, ProviderConfigurationError, adapter_for
from lyra.runtime import AgentLoop, ModelToolRunner
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.runtime_tools import build_conversation_registry
from lyra.service import configure_rotating_logging
from lyra.sessions import ContextBuilder, SessionService
from lyra.stuck import StuckModeService
from lyra.telegram import run_configured_bot


STATIC_DIR = Path(__file__).resolve().parent / "web_static"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class TurnLoop(Protocol):
    def stream_turn(
        self, session_id: str, user_text: str, *, channel: str = "web"
    ) -> AsyncIterator[RuntimeEvent]: ...


LoopFactory = Callable[[str], TurnLoop]


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SessionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TurnCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class PresentationUpdate(BaseModel):
    presentation_mode: str = Field(pattern="^(standard|concise)$")


class AwayUpdate(BaseModel):
    enabled: bool
    quiet_start: time | None = None
    quiet_end: time | None = None
    timezone: str = Field(min_length=1, max_length=100)
    daily_notification_budget: int = Field(ge=0, le=1000)


class ControlCorrection(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    reason: str | None = Field(default=None, max_length=500)


class ControlRejection(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ControlForget(BaseModel):
    confirmed: bool
    reason: str | None = Field(default=None, max_length=500)


class CommitmentTransition(BaseModel):
    status: str = Field(pattern="^(active|done|snoozed|dropped)$")
    snoozed_until: datetime | None = None


class ReminderPlan(BaseModel):
    channel: str = Field(default="telegram", pattern="^(web|telegram)$")
    horizon_hours: int = Field(default=24, ge=1, le=720)


def validate_bind_host(host: str) -> str:
    if host.strip().lower() not in LOOPBACK_HOSTS:
        raise ValueError("Lyra web chat may bind only to a loopback address")
    return host.strip().lower()


def is_loopback_client(host: str | None) -> bool:
    """Return true only for a client address originating on this workstation."""

    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.strip().lower() == "localhost"


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
    presentation = AwayModeService(
        getattr(sessions, "connection_factory", SessionService().connection_factory)
    )
    commitment_radar = CommitmentService(
        getattr(sessions, "connection_factory", SessionService().connection_factory)
    )
    stuck_mode = StuckModeService(
        getattr(sessions, "connection_factory", SessionService().connection_factory)
    )
    system_prompt = compose_runtime_context()

    class UnavailableLoop:
        def __init__(self, message: str) -> None:
            self.message = message

        async def stream_turn(
            self, session_id: str, user_text: str, *, channel: str = "web"
        ) -> AsyncIterator[RuntimeEvent]:
            sessions.recover_interrupted_turns(session_id)
            sessions.append_message(
                session_id, "user", user_text, metadata={"channel": channel}
            )
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
            presentation=presentation,
            commitment_radar=commitment_radar,
            stuck_mode=stuck_mode,
        )

    return factory


def create_app(
    sessions: SessionService | None = None,
    loop_factory: LoopFactory | None = None,
    telegram_runner: Callable[[SessionService, LoopFactory], Any] | None = run_configured_bot,
    away_service: AwayModeService | None = None,
    memory_control: MemoryControlService | None = None,
    commitment_service: CommitmentService | None = None,
    stuck_service: StuckModeService | None = None,
) -> FastAPI:
    session_service = sessions or SessionService()
    factory = loop_factory or default_loop_factory(session_service)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = (
            asyncio.create_task(telegram_runner(session_service, factory))
            if telegram_runner is not None
            else None
        )
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Lyra", version="0.4.0", lifespan=lifespan)
    away = away_service or AwayModeService(
        getattr(
            session_service,
            "connection_factory",
            SessionService().connection_factory,
        )
    )
    control = memory_control or MemoryControlService(
        embedding_service=EmbeddingService(),
        graph_writer=MCPKnowledgeGraphWriter(settings.kg_memory_file_path),
        connection_factory=getattr(
            session_service,
            "connection_factory",
            SessionService().connection_factory,
        ),
    )
    commitments = commitment_service or CommitmentService(
        getattr(
            session_service,
            "connection_factory",
            SessionService().connection_factory,
        )
    )
    stuck = stuck_service or StuckModeService(
        getattr(
            session_service,
            "connection_factory",
            SessionService().connection_factory,
        )
    )

    def require_local_control_client(request: Request) -> None:
        # Tailscale Serve and other reverse proxies must not extend mutation
        # authority beyond the workstation, even when the caller has a token.
        forwarded = request.headers.get("X-Forwarded-For", "").strip()
        tailscale_identity = request.headers.get("Tailscale-User-Login", "").strip()
        client_host = request.client.host if request.client is not None else None
        if forwarded or tailscale_identity or not is_loopback_client(client_host):
            raise HTTPException(
                status_code=403,
                detail="Memory control is available only on this workstation",
            )

    def require_control_access(request: Request) -> None:
        require_local_control_client(request)
        expected = os.getenv("LYRA_CONTROL_TOKEN", "").strip()
        supplied = request.headers.get("X-Lyra-Control-Token", "")
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="Memory control token is not configured",
            )
        if not supplied or not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Control access denied")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/app.css", include_in_schema=False)
    async def css():
        return FileResponse(STATIC_DIR / "app.css", media_type="text/css")

    @app.get("/app.js", include_in_schema=False)
    async def javascript():
        return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript")

    @app.get("/control", include_in_schema=False)
    async def control_center(request: Request):
        require_local_control_client(request)
        return FileResponse(STATIC_DIR / "control.html", media_type="text/html")

    @app.get("/control.js", include_in_schema=False)
    async def control_javascript():
        return FileResponse(STATIC_DIR / "control.js", media_type="text/javascript")

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

    @app.get("/api/sessions/{session_id}/channels")
    async def list_channels(session_id: str):
        try:
            session_service.get_session(session_id)
            return {"channels": session_service.list_channels(session_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.post("/api/sessions/{session_id}/handoff/telegram")
    async def handoff_to_telegram(session_id: str):
        try:
            session_service.get_session(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        chat_ids = [
            item.strip()
            for item in os.getenv("LYRA_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
            if item.strip()
        ]
        if len(chat_ids) != 1:
            raise HTTPException(
                status_code=409,
                detail="Exactly one Telegram private chat must be configured",
            )
        return session_service.bind_channel(session_id, "telegram", chat_ids[0])

    @app.get("/api/preferences/{channel}")
    async def get_channel_preference(channel: str):
        try:
            return away.get_channel_preference(channel)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/api/preferences/{channel}")
    async def set_channel_preference(channel: str, request: PresentationUpdate):
        try:
            return away.set_channel_preference(channel, request.presentation_mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/away")
    async def get_away_policy():
        return away.policy_dict()

    @app.get("/api/away/batched")
    async def list_batched_notifications():
        return {"notifications": away.list_batched()}

    @app.get("/api/commitment-offers")
    async def list_commitment_offers(
        status: str = "offered", session_id: str | None = None
    ):
        try:
            return {
                "offers": commitments.list_offers(
                    status=status, session_id=session_id
                )
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/commitment-offers/{offer_id}/confirm")
    async def confirm_commitment_offer(offer_id: str, request: Request):
        require_local_control_client(request)
        try:
            return commitments.confirm_offer(offer_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/commitment-offers/{offer_id}/dismiss")
    async def dismiss_commitment_offer(offer_id: str, request: Request):
        require_local_control_client(request)
        try:
            return commitments.dismiss_offer(offer_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/commitments")
    async def list_commitments(status: str | None = None):
        try:
            return {"commitments": commitments.list_commitments(status=status)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/commitments/{commitment_id}")
    async def get_commitment(commitment_id: str):
        try:
            return commitments.get_commitment(commitment_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/commitments/{commitment_id}")
    async def transition_commitment(
        commitment_id: str, transition: CommitmentTransition, request: Request
    ):
        require_local_control_client(request)
        try:
            return commitments.transition(
                commitment_id,
                transition.status,
                snoozed_until=transition.snoozed_until,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/commitment-reminders/plan")
    async def plan_commitment_reminders(plan: ReminderPlan, request: Request):
        require_local_control_client(request)
        return {
            "reminders": commitments.plan_due_reminders(
                away=away,
                channel=plan.channel,
                horizon=timedelta(hours=plan.horizon_hours),
            )
        }

    @app.get("/api/stuck-mode/{session_id}")
    async def get_stuck_mode(session_id: str):
        return {"interaction": stuck.get_state(session_id)}

    @app.put("/api/away")
    async def set_away_policy(request: AwayUpdate):
        try:
            policy = away.set_policy(
                enabled=request.enabled,
                quiet_start=request.quiet_start,
                quiet_end=request.quiet_end,
                timezone=request.timezone,
                daily_notification_budget=request.daily_notification_budget,
            )
            return {
                "enabled": policy.enabled,
                "quiet_start": policy.quiet_start,
                "quiet_end": policy.quiet_end,
                "timezone": policy.timezone,
                "daily_notification_budget": policy.daily_notification_budget,
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/proposals")
    async def list_memory_proposals(
        request: Request,
        status: str = "pending",
        limit: int = 100,
    ):
        require_control_access(request)
        try:
            return {"proposals": control.list_proposals(status=status, limit=limit)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/proposals/{proposal_id}/approve")
    async def approve_memory_proposal(proposal_id: int, request: Request):
        require_control_access(request)
        try:
            return control.approve(proposal_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/proposals/{proposal_id}/correct")
    async def correct_memory_proposal(
        proposal_id: int,
        correction: ControlCorrection,
        request: Request,
    ):
        require_control_access(request)
        try:
            return control.correct(
                proposal_id,
                correction.content,
                reason=correction.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/proposals/{proposal_id}/reject")
    async def reject_memory_proposal(
        proposal_id: int,
        rejection: ControlRejection,
        request: Request,
    ):
        require_control_access(request)
        try:
            return control.reject(proposal_id, reason=rejection.reason)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/proposals/{proposal_id}/forget")
    async def forget_memory_proposal(
        proposal_id: int,
        forget: ControlForget,
        request: Request,
    ):
        require_control_access(request)
        try:
            return control.forget(
                proposal_id,
                confirmed=forget.confirmed,
                reason=forget.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/audit")
    async def list_memory_audit(request: Request, limit: int = 200):
        require_control_access(request)
        return {"audit": control.list_audit(limit=limit)}

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
                async for event in loop.stream_turn(
                    session_id, turn.content, channel="web"
                ):
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
