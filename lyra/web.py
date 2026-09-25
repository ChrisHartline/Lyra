"""Loopback-only FastAPI surface for Lyra's standalone chat runtime."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import secrets
from dataclasses import asdict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from lyra.away import AwayModeService
from lyra.catch_up import CatchUpService, NotionChangeReader
from lyra.commitments import CommitmentService
from lyra.config import settings
from lyra.corpus_mcp import CorpusService, MCPToolRouter
from lyra.embeddings import EmbeddingService
from lyra.ingest import IngestPipeline
from lyra.kg_gatekeeper import build_gatekeeper_router
from lyra.knowledge_routing import routing_prompt
from lyra.knowledge_graph import MCPKnowledgeGraphWriter
from lyra.notion_sync import NotionClient
from lyra.memory_control import MemoryControlService
from lyra.natural_memory import MemoryPolicyService, NaturalMemoryService
from lyra.packs import compose_runtime_context
from lyra.providers import ModelProfiles, ProviderConfigurationError, adapter_for
from lyra.research_garden import ResearchGardenService
from lyra.relationship_rhythms import (
    RelationshipRhythmService,
    run_relationship_rhythms,
)
from lyra.ship_continuity import ShipContinuityService, run_ship_continuity
from lyra.runtime import AgentLoop, ModelToolRunner
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.runtime_tools import build_conversation_registry
from lyra.scene_media import SceneDirector, SceneMediaError
from lyra.rituals import RitualService
from lyra.briefings import BriefingService
from lyra.service import configure_rotating_logging
from lyra.sessions import ContextBuilder, SessionService
from lyra.shared_journal import SharedJournalService
from lyra.stuck import StuckModeService
from lyra.telegram import (
    run_configured_bot,
    run_configured_research_garden,
    run_configured_rituals,
)
from lyra.wiki import WikiService, WikiToolRouter


STATIC_DIR = Path(__file__).resolve().parent / "web_static"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class TurnLoop(Protocol):
    def stream_turn(
        self, session_id: str, user_text: str, *, channel: str = "web"
    ) -> AsyncIterator[RuntimeEvent]: ...


LoopFactory = Callable[[str], TurnLoop]


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    context_scope: str = Field(
        default="general", pattern="^(general|professional|story|campaign)$"
    )


class SessionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SessionScopeUpdate(BaseModel):
    context_scope: str = Field(pattern="^(general|professional|story|campaign)$")


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


class ScenePolicyUpdate(BaseModel):
    enabled: bool
    automatic_enabled: bool
    allowed_channels: list[str]
    max_per_day: int = Field(ge=1, le=20)
    cooldown_minutes: int = Field(ge=1, le=1440)
    max_storyboard_frames: int = Field(ge=2, le=4)


class MemoryPolicyUpdate(BaseModel):
    private_shared: str = Field(pattern="^(auto|review|off)$")
    professional: str = Field(pattern="^(auto|review|off)$")
    story: str = Field(pattern="^(auto|review|off)$")
    campaign: str = Field(pattern="^(auto|review|off)$")


class CommitmentTransition(BaseModel):
    status: str = Field(pattern="^(active|done|snoozed|dropped)$")
    snoozed_until: datetime | None = None


class CommitmentVisibilityUpdate(BaseModel):
    visibility_scope: str = Field(pattern="^(general|professional|private_shared)$")


class ReminderPlan(BaseModel):
    channel: str = Field(default="telegram", pattern="^(web|telegram)$")
    horizon_hours: int = Field(default=24, ge=1, le=720)


class RitualPolicyUpdate(BaseModel):
    morning_enabled: bool
    evening_enabled: bool
    morning_time: time
    evening_time: time
    timezone: str = Field(min_length=1, max_length=100)
    channel: str = Field(pattern="^(web|telegram)$")
    target_session_id: str | None = None
    notion_publish: bool = False
    vacation_until: date | None = None


class RitualSnooze(BaseModel):
    until: datetime


class GardenPolicyUpdate(BaseModel):
    enabled: bool
    channel: str = Field(pattern="^(web|telegram)$")
    interval_hours: int = Field(ge=1, le=720)
    min_dormant_days: int = Field(ge=1, le=365)
    max_suggestions: int = Field(ge=1, le=10)


class GardenTopicMute(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    expires_at: datetime | None = None


class JournalEntryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    entry_type: str = Field(pattern="^(moment|reflection|milestone)$")
    approved: bool
    title: str | None = Field(default=None, max_length=240)
    source_session_id: str | None = None
    source_message_id: int | None = None


class JournalEntryEdit(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    title: str | None = Field(default=None, max_length=240)
    reason: str | None = Field(default=None, max_length=500)


class JournalEntryForget(BaseModel):
    confirmed: bool
    reason: str | None = Field(default=None, max_length=500)


class JournalSessionAccess(BaseModel):
    enabled: bool


class RelationshipRhythmUpdate(BaseModel):
    enabled: bool
    callbacks_enabled: bool
    rituals_enabled: bool
    milestones_enabled: bool
    cadence_days: int = Field(ge=1, le=90)
    local_time: time
    timezone: str = Field(min_length=1, max_length=100)
    target_session_id: str | None = None


class RelationshipSourceMute(BaseModel):
    source_key: str = Field(min_length=1, max_length=300)


class ShipContinuityUpdate(BaseModel):
    enabled: bool
    paused: bool
    briefs_enabled: bool
    ambient_enabled: bool
    intensity: str = Field(pattern="^(quiet|balanced|vivid)$")
    cadence_days: int = Field(ge=1, le=30)
    local_time: time
    timezone: str = Field(min_length=1, max_length=100)
    target_session_id: str | None = None


class ShipCanonProposalCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    session_id: str
    source_message_id: int | None = None


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
    data = dict(event.data)
    if event.kind is EventKind.MEDIA:
        data["frames"] = [
            {key: value for key, value in dict(frame).items() if key != "local_path"}
            for frame in data.get("frames", [])
        ]
    return {
        "kind": event.kind.value,
        "text": event.text,
        "name": event.name,
        "call_id": event.call_id,
        "arguments": dict(event.arguments) if event.arguments is not None else None,
        "data": data,
    }


def _sse(event: str, data: dict[str, Any], event_id: int) -> str:
    payload = json.dumps(data, default=str, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


def default_loop_factory(
    sessions: SessionService, *, scene_director: SceneDirector | None = None
) -> LoopFactory:
    embedding = EmbeddingService()
    corpus = CorpusService(
        embedding_service=embedding,
        ingest_pipeline=IngestPipeline(embedding_service=embedding),
    )
    corpus_router = MCPToolRouter(corpus)
    memory_router = build_gatekeeper_router()
    wiki_router = WikiToolRouter(WikiService())
    registry = build_conversation_registry(
        corpus_router=corpus_router,
        memory_router=memory_router,
        wiki_router=wiki_router,
    )
    shared_journal = SharedJournalService(
        getattr(sessions, "connection_factory", SessionService().connection_factory)
    )
    context = ContextBuilder(
        sessions,
        memory_search=corpus.search_memories,
        journal_reader=shared_journal.context_entries,
    )
    presentation = AwayModeService(
        getattr(sessions, "connection_factory", SessionService().connection_factory)
    )
    relationship_rhythms = RelationshipRhythmService(
        away=presentation,
        journal=shared_journal,
        connection_factory=getattr(
            sessions, "connection_factory", SessionService().connection_factory
        ),
    )
    commitment_radar = CommitmentService(
        getattr(sessions, "connection_factory", SessionService().connection_factory)
    )
    stuck_mode = StuckModeService(
        getattr(sessions, "connection_factory", SessionService().connection_factory)
    )
    connection_factory = getattr(
        sessions, "connection_factory", SessionService().connection_factory
    )
    memory_control = MemoryControlService(
        embedding_service=embedding,
        graph_writer=MCPKnowledgeGraphWriter(settings.kg_memory_file_path),
        connection_factory=connection_factory,
    )
    natural_memory = NaturalMemoryService(
        corpus=corpus,
        control=memory_control,
        connection_factory=connection_factory,
    )
    ship_continuity = ShipContinuityService(
        away=presentation,
        embedding_service=embedding,
        memory_control=memory_control,
        connection_factory=connection_factory,
    )
    notion = NotionClient(token=settings.notion_token) if settings.notion_token else None
    catch_up = CatchUpService(
        connection_factory=connection_factory,
        change_reader=(
            NotionChangeReader(
                client=notion,
                projects_database_id=settings.notion_tasks_database_id,
                digests_database_id=settings.notion_digests_database_id,
                project_title_property=settings.notion_task_title_property,
                digest_title_property=settings.notion_digest_title_property,
            )
            if notion else None
        ),
    )
    system_prompt = compose_runtime_context() + "\n\n---\n\n" + routing_prompt() + "\n"

    class UnavailableLoop:
        def __init__(self, message: str) -> None:
            self.message = message

        async def stream_turn(
            self, session_id: str, user_text: str, *, channel: str = "web"
        ) -> AsyncIterator[RuntimeEvent]:
            response = catch_up.respond(user_text)
            if response is not None:
                sessions.recover_interrupted_turns(session_id)
                sessions.append_message(
                    session_id, "user", user_text, metadata={"channel": channel}
                )
                turn = sessions.start_turn(session_id, "running")
                sessions.append_message(
                    session_id, "assistant", response["body"],
                    metadata={"channel": channel, "catch_up": True,
                              "turn_id": turn["turn_id"]},
                )
                sessions.update_turn(turn["turn_id"], "completed")
                yield RuntimeEvent.text_delta(response["body"])
                yield RuntimeEvent.completion("catch_up", source_planes=True)
                return
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
            natural_memory=natural_memory,
            catch_up=catch_up,
            relationship_rhythms=relationship_rhythms,
            ship_continuity=ship_continuity,
            scene_director=scene_director,
        )

    return factory


def create_app(
    sessions: SessionService | None = None,
    loop_factory: LoopFactory | None = None,
    telegram_runner: Callable[[SessionService, LoopFactory], Any] | None = run_configured_bot,
    ritual_runner: Callable[[SessionService, RitualService], Any] | None = run_configured_rituals,
    garden_runner: Callable[[SessionService, ResearchGardenService], Any] | None = run_configured_research_garden,
    relationship_runner: Callable[[SessionService, RelationshipRhythmService], Any] | None = run_relationship_rhythms,
    ship_runner: Callable[[SessionService, ShipContinuityService], Any] | None = run_ship_continuity,
    away_service: AwayModeService | None = None,
    memory_control: MemoryControlService | None = None,
    memory_policy: MemoryPolicyService | None = None,
    commitment_service: CommitmentService | None = None,
    stuck_service: StuckModeService | None = None,
    ritual_service: RitualService | None = None,
    garden_service: ResearchGardenService | None = None,
    journal_service: SharedJournalService | None = None,
    relationship_service: RelationshipRhythmService | None = None,
    ship_service: ShipContinuityService | None = None,
    scene_service: SceneDirector | None = None,
) -> FastAPI:
    session_service = sessions or SessionService()
    scene_media = scene_service or SceneDirector()
    factory = loop_factory or default_loop_factory(
        session_service, scene_director=scene_media
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        tasks = []
        if telegram_runner is not None:
            tasks.append(asyncio.create_task(telegram_runner(session_service, factory)))
        if ritual_runner is not None:
            tasks.append(asyncio.create_task(ritual_runner(session_service, rituals)))
        if garden_runner is not None:
            tasks.append(asyncio.create_task(garden_runner(session_service, garden)))
        if relationship_runner is not None:
            tasks.append(asyncio.create_task(
                relationship_runner(session_service, relationship)
            ))
        if ship_runner is not None:
            tasks.append(asyncio.create_task(
                ship_runner(session_service, ship_continuity)
            ))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
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
    policy = memory_policy or MemoryPolicyService(
        getattr(
            session_service,
            "connection_factory",
            SessionService().connection_factory,
        )
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
    rituals = ritual_service or RitualService(
        briefing=BriefingService(
            digests_database_id=settings.notion_digests_database_id or "unset",
            title_property=settings.notion_digest_title_property,
            kg_memory_file=settings.kg_memory_file_path,
            connection_factory=getattr(
                session_service, "connection_factory", SessionService().connection_factory
            ),
            publisher=(
                NotionClient(token=settings.notion_token)
                if settings.notion_token and settings.notion_digests_database_id
                else None
            ),
        ),
        away=away,
        connection_factory=getattr(
            session_service, "connection_factory", SessionService().connection_factory
        ),
    )
    garden = garden_service or ResearchGardenService(
        away=away,
        connection_factory=getattr(
            session_service, "connection_factory", SessionService().connection_factory
        ),
    )
    journal = journal_service or SharedJournalService(
        getattr(
            session_service, "connection_factory", SessionService().connection_factory
        )
    )
    relationship = relationship_service or RelationshipRhythmService(
        away=away,
        journal=journal,
        connection_factory=getattr(
            session_service, "connection_factory", SessionService().connection_factory
        ),
    )
    ship_continuity = ship_service or ShipContinuityService(
        away=away,
        embedding_service=EmbeddingService(),
        memory_control=control,
        connection_factory=getattr(
            session_service, "connection_factory", SessionService().connection_factory
        ),
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

    @app.get("/api/scene-media/{request_id}/{filename}")
    async def scene_media_artifact(request_id: str, filename: str, request: Request):
        require_local_control_client(request)
        try:
            return FileResponse(scene_media.artifact_path(request_id, filename))
        except SceneMediaError as exc:
            raise HTTPException(status_code=404, detail="Scene artifact not found") from exc

    @app.get("/api/control/scene-media")
    async def get_scene_media_policy(request: Request):
        require_control_access(request)
        return {"policy": asdict(scene_media.get_policy())}

    @app.put("/api/control/scene-media")
    async def update_scene_media_policy(update: ScenePolicyUpdate, request: Request):
        require_control_access(request)
        try:
            return {"policy": asdict(scene_media.set_policy(**update.model_dump()))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/control/scene-media/{request_id}")
    async def delete_scene_media(request_id: str, request: Request):
        require_control_access(request)
        try:
            if not scene_media.delete(request_id):
                raise HTTPException(status_code=404, detail="Scene media not found")
        except SceneMediaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted": True, "conversation_changed": False}

    @app.get("/api/sessions")
    async def list_sessions():
        return {"sessions": session_service.list_sessions()}

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: SessionCreate):
        try:
            if request.context_scope == "general":
                return session_service.create_session(request.name)
            return session_service.create_session(
                request.name, context_scope=request.context_scope
            )
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

    @app.put("/api/control/sessions/{session_id}/context-scope")
    async def set_session_context_scope(
        session_id: str, update: SessionScopeUpdate, request: Request
    ):
        require_control_access(request)
        try:
            return session_service.set_context_scope(
                session_id, update.context_scope
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
        try:
            return session_service.bind_channel(session_id, "telegram", chat_ids[0])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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

    @app.put("/api/control/commitments/{commitment_id}/visibility")
    async def set_commitment_visibility(
        commitment_id: str,
        update: CommitmentVisibilityUpdate,
        request: Request,
    ):
        require_control_access(request)
        try:
            return commitments.set_visibility(
                commitment_id, update.visibility_scope
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

    @app.post("/api/control/proposals/{proposal_id}/correct-approved")
    async def correct_approved_memory(
        proposal_id: int,
        correction: ControlCorrection,
        request: Request,
    ):
        require_control_access(request)
        try:
            return control.correct_approved(
                proposal_id, correction.content, reason=correction.reason
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

    @app.get("/api/control/recent")
    async def recent_memories(request: Request, limit: int = 20):
        require_control_access(request)
        return {"proposals": control.list_recent_natural(limit=limit)}

    @app.get("/api/control/rituals")
    async def get_ritual_policy(request: Request):
        require_control_access(request)
        return {"policy": rituals.policy_dict()}

    @app.put("/api/control/rituals")
    async def update_ritual_policy(update: RitualPolicyUpdate, request: Request):
        require_control_access(request)
        try:
            return {"policy": asdict(rituals.set_policy(**update.model_dump()))}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/rituals/{ritual_type}/preview")
    async def preview_ritual(ritual_type: str, request: Request):
        require_control_access(request)
        try:
            return rituals.build(ritual_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/rituals/{ritual_type}/skip")
    async def skip_ritual(ritual_type: str, request: Request):
        require_control_access(request)
        try:
            return rituals.skip(ritual_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/rituals/{ritual_type}/snooze")
    async def snooze_ritual(ritual_type: str, snooze: RitualSnooze, request: Request):
        require_control_access(request)
        try:
            return {"policy": asdict(rituals.snooze(ritual_type, snooze.until))}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/research-garden")
    async def get_research_garden(request: Request):
        require_control_access(request)
        return {
            "policy": garden.policy_dict(),
            "suggestions": garden.list_suggestions(),
            "mutes": garden.list_mutes(),
        }

    @app.put("/api/control/research-garden")
    async def update_research_garden(
        update: GardenPolicyUpdate, request: Request
    ):
        require_control_access(request)
        try:
            return {"policy": asdict(garden.set_policy(**update.model_dump()))}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/research-garden/preview")
    async def preview_research_garden(request: Request):
        require_control_access(request)
        return {"suggestions": [asdict(item) for item in garden.discover()]}

    @app.get("/api/control/research-garden/mutes")
    async def list_research_garden_mutes(request: Request):
        require_control_access(request)
        return {"mutes": garden.list_mutes()}

    @app.post("/api/control/research-garden/mutes")
    async def mute_research_garden_topic(
        mute: GardenTopicMute, request: Request
    ):
        require_control_access(request)
        try:
            return garden.mute_topic(mute.topic, expires_at=mute.expires_at)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/control/research-garden/mutes/{topic}")
    async def unmute_research_garden_topic(topic: str, request: Request):
        require_control_access(request)
        return {"removed": garden.unmute_topic(topic)}

    @app.post("/api/control/research-garden/{suggestion_id}/dismiss")
    async def dismiss_research_garden_suggestion(
        suggestion_id: str, request: Request
    ):
        require_control_access(request)
        try:
            return garden.dismiss(suggestion_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/control/research-garden/{suggestion_id}/draft")
    async def draft_research_garden_digest(
        suggestion_id: str, request: Request
    ):
        require_control_access(request)
        try:
            return garden.draft_digest(suggestion_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/control/shared-journal")
    async def list_shared_journal(request: Request, limit: int = 100):
        require_control_access(request)
        return {"entries": journal.list_entries(limit=limit)}

    @app.post("/api/control/shared-journal", status_code=201)
    async def create_shared_journal_entry(
        entry: JournalEntryCreate, request: Request
    ):
        require_control_access(request)
        try:
            return journal.create_entry(**entry.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/shared-journal/audit")
    async def list_shared_journal_audit(request: Request, limit: int = 200):
        require_control_access(request)
        return {"audit": journal.list_audit(limit=limit)}

    @app.get("/api/control/shared-journal/sessions/{session_id}")
    async def get_shared_journal_session(session_id: str, request: Request):
        require_control_access(request)
        try:
            return journal.session_access(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/control/shared-journal/sessions/{session_id}")
    async def update_shared_journal_session(
        session_id: str, access: JournalSessionAccess, request: Request
    ):
        require_control_access(request)
        try:
            return journal.authorize_session(session_id, enabled=access.enabled)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/control/shared-journal/{entry_id}")
    async def edit_shared_journal_entry(
        entry_id: str, edit: JournalEntryEdit, request: Request
    ):
        require_control_access(request)
        try:
            return journal.edit_entry(entry_id, **edit.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/shared-journal/{entry_id}/forget")
    async def forget_shared_journal_entry(
        entry_id: str, forget: JournalEntryForget, request: Request
    ):
        require_control_access(request)
        try:
            return journal.forget_entry(entry_id, **forget.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/relationship-rhythms")
    async def get_relationship_rhythms(request: Request, limit: int = 100):
        require_control_access(request)
        return {
            "policy": relationship.policy_dict(),
            "events": relationship.list_events(limit=limit),
            "mutes": relationship.list_mutes(),
        }

    @app.put("/api/control/relationship-rhythms")
    async def update_relationship_rhythms(
        update: RelationshipRhythmUpdate, request: Request
    ):
        require_control_access(request)
        try:
            relationship.set_policy(**update.model_dump())
            return {"policy": relationship.policy_dict()}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/relationship-rhythms/preview")
    async def preview_relationship_rhythms(request: Request):
        require_control_access(request)
        return relationship.preview()

    @app.post("/api/control/relationship-rhythms/mutes")
    async def mute_relationship_source(
        mute: RelationshipSourceMute, request: Request
    ):
        require_control_access(request)
        try:
            return relationship.mute_source(mute.source_key)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/control/relationship-rhythms/mutes/{source_key:path}")
    async def unmute_relationship_source(source_key: str, request: Request):
        require_control_access(request)
        return {"removed": relationship.unmute_source(source_key)}

    @app.post("/api/control/relationship-rhythms/events/{event_id}/dismiss")
    async def dismiss_relationship_event(event_id: str, request: Request):
        require_control_access(request)
        try:
            return relationship.dismiss(event_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/control/ship-continuity")
    async def get_ship_continuity(request: Request, limit: int = 100):
        require_control_access(request)
        return {
            "policy": ship_continuity.policy_dict(),
            "events": ship_continuity.list_events(limit=limit),
        }

    @app.put("/api/control/ship-continuity")
    async def update_ship_continuity(
        update: ShipContinuityUpdate, request: Request
    ):
        require_control_access(request)
        try:
            return {"policy": ship_continuity.set_policy(**update.model_dump())}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/control/ship-continuity/preview")
    async def preview_ship_continuity(request: Request):
        require_control_access(request)
        return ship_continuity.preview_ambient()

    @app.post("/api/control/ship-continuity/proposals", status_code=201)
    async def create_ship_canon_proposal(
        proposal: ShipCanonProposalCreate, request: Request
    ):
        require_control_access(request)
        try:
            return ship_continuity.propose_canon_update(**proposal.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/control/ship-continuity/proposals/{proposal_id}/approve")
    async def approve_ship_canon_proposal(proposal_id: int, request: Request):
        require_control_access(request)
        try:
            return ship_continuity.approve_canon_update(proposal_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/control/memory-policy")
    async def get_memory_policy(request: Request):
        require_control_access(request)
        return {"policy": policy.get_policy()}

    @app.put("/api/control/memory-policy")
    async def update_memory_policy(update: MemoryPolicyUpdate, request: Request):
        require_control_access(request)
        try:
            return {"policy": policy.set_policy(**update.model_dump())}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
