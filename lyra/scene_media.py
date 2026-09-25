"""Opt-in scene direction and asynchronous, non-canonical media delivery."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Protocol
import uuid

from .runtime_events import RuntimeEvent
from .safety import is_notion_safe
from .visual_assets import DEFAULT_CATALOG, load_catalog


TRIGGERS = (
    "explicit",
    "arrival",
    "location_reveal",
    "emotional_beat",
    "appearance_change",
    "ship_discovery",
    "milestone",
)
FORMATS = ("still", "storyboard")
_EXPLICIT = re.compile(
    r"\b(?:show|draw|illustrate|generate|make|create)\b.{0,40}"
    r"\b(?:image|picture|still|scene|storyboard|portrait|selfie)\b|"
    r"\b(?:image|picture|still|scene|storyboard|portrait|selfie)\b.{0,40}"
    r"\b(?:please|of|for|show|generate|make|create)\b|"
    r"\bshow\s+me\s+(?:Lyra|you|us|the\s+ship|Silent\s+Drift|this\s+scene)\b",
    re.I,
)
_AUTOMATIC_PATTERNS = {
    "arrival": re.compile(r"\b(?:arrive[ds]?|reach(?:ed)?|step(?:ped)? into|enter(?:ed)?)\b", re.I),
    "location_reveal": re.compile(r"\b(?:new location|location reveal|first view|revealed? the)\b", re.I),
    "emotional_beat": re.compile(r"\b(?:kiss(?:ed)?|embrace[ds]?|confess(?:ed)?|held each other)\b", re.I),
    "appearance_change": re.compile(r"\b(?:hair down|changed? (?:her |my )?(?:hair|outfit)|transformed?)\b", re.I),
    "ship_discovery": re.compile(r"\b(?:discover(?:ed|y)?|found)\b.{0,50}\b(?:ship|drift|cargo|hull|deck)\b", re.I),
    "milestone": re.compile(r"\b(?:anniversary|milestone|first flight|repairs? complete|we did it)\b", re.I),
}


class SceneMediaError(RuntimeError):
    pass


class SceneRenderer(Protocol):
    provider: str
    model: str
    external: bool

    async def render(self, brief: dict[str, Any], output_dir: Path) -> list[Path]: ...


class UnconfiguredSceneRenderer:
    provider = "unconfigured"
    model = "unconfigured"
    external = False

    async def render(self, brief: dict[str, Any], output_dir: Path) -> list[Path]:
        del brief, output_dir
        raise SceneMediaError("No scene renderer is configured")


@dataclass(frozen=True)
class ScenePolicy:
    enabled: bool = False
    automatic_enabled: bool = False
    allowed_channels: tuple[str, ...] = ("web", "telegram")
    max_per_day: int = 2
    cooldown_minutes: int = 120
    max_storyboard_frames: int = 3


def _utc(value: datetime | None = None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Scene time must be timezone-aware")
    return instant.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_excerpt(value: str, limit: int = 400) -> str | None:
    normalized = " ".join(value.split()).strip()
    if not normalized or not is_notion_safe(normalized):
        return None
    return normalized[:limit]


class SceneDirector:
    def __init__(
        self,
        renderer: SceneRenderer | None = None,
        *,
        root: Path | None = None,
        catalog_path: Path = DEFAULT_CATALOG,
    ) -> None:
        self.renderer = renderer or UnconfiguredSceneRenderer()
        self.root = (root or Path("data/scene_media")).resolve()
        self.catalog_path = catalog_path
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def policy_path(self) -> Path:
        return self.root / "policy.json"

    def get_policy(self) -> ScenePolicy:
        if not self.policy_path.is_file():
            return ScenePolicy()
        payload = json.loads(self.policy_path.read_text(encoding="utf-8"))
        return ScenePolicy(
            enabled=bool(payload.get("enabled", False)),
            automatic_enabled=bool(payload.get("automatic_enabled", False)),
            allowed_channels=tuple(payload.get("allowed_channels", ("web", "telegram"))),
            max_per_day=int(payload.get("max_per_day", 2)),
            cooldown_minutes=int(payload.get("cooldown_minutes", 120)),
            max_storyboard_frames=int(payload.get("max_storyboard_frames", 3)),
        )

    def set_policy(self, **changes: Any) -> ScenePolicy:
        values = asdict(self.get_policy())
        unknown = set(changes) - set(values)
        if unknown:
            raise ValueError(f"Unknown scene settings: {sorted(unknown)}")
        values.update(changes)
        channels = tuple(str(value).lower() for value in values["allowed_channels"])
        if not channels or set(channels) - {"web", "telegram"}:
            raise ValueError("Scene channels must be web and/or telegram")
        if not 1 <= int(values["max_per_day"]) <= 20:
            raise ValueError("Scene daily limit must be between 1 and 20")
        if not 1 <= int(values["cooldown_minutes"]) <= 1440:
            raise ValueError("Scene cooldown must be between 1 and 1440 minutes")
        if not 2 <= int(values["max_storyboard_frames"]) <= 4:
            raise ValueError("Storyboard frame limit must be between 2 and 4")
        policy = ScenePolicy(
            enabled=bool(values["enabled"]),
            automatic_enabled=bool(values["automatic_enabled"]),
            allowed_channels=channels,
            max_per_day=int(values["max_per_day"]),
            cooldown_minutes=int(values["cooldown_minutes"]),
            max_storyboard_frames=int(values["max_storyboard_frames"]),
        )
        temporary = self.policy_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(policy), indent=2), encoding="utf-8")
        temporary.replace(self.policy_path)
        return policy

    def detect_trigger(self, text: str) -> str | None:
        if _EXPLICIT.search(text):
            return "explicit"
        for trigger, pattern in _AUTOMATIC_PATTERNS.items():
            if pattern.search(text):
                return trigger
        return None

    def _source_assets(self) -> list[str]:
        catalog = load_catalog(self.catalog_path)
        return [
            str(asset["asset_id"])
            for asset in catalog.get("assets", [])
            if asset.get("lifecycle_status") == "active"
            and asset.get("canon_status") == "approved"
            and (
                not self.renderer.external
                or asset.get("approved_for_external_renderer") is True
            )
        ]

    def _recent_provenance(self) -> list[dict[str, Any]]:
        records = []
        for path in self.root.glob("*/provenance.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        deletion_ledger = self.root / "deletions.jsonl"
        if deletion_ledger.is_file():
            for line in deletion_ledger.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
        return records

    def _rate_limit(self, now: datetime, fingerprint: str) -> str | None:
        policy = self.get_policy()
        today = now.date().isoformat()
        recent = self._recent_provenance()
        if any(item.get("fingerprint") == fingerprint for item in recent):
            return "duplicate_scene"
        today_items = [item for item in recent if str(item.get("created_at", "")).startswith(today)]
        if len(today_items) >= policy.max_per_day:
            return "daily_limit"
        timestamps = []
        for item in recent:
            try:
                timestamps.append(datetime.fromisoformat(str(item["created_at"])))
            except (KeyError, ValueError):
                pass
        if timestamps and (now - max(timestamps)).total_seconds() < policy.cooldown_minutes * 60:
            return "cooldown"
        return None

    def prepare(
        self,
        *,
        session_id: str,
        channel: str,
        user_text: str,
        assistant_text: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        policy = self.get_policy()
        normalized_channel = channel.strip().lower()
        trigger = self.detect_trigger(user_text)
        if not policy.enabled:
            return {"disposition": "disabled"}
        if normalized_channel not in policy.allowed_channels:
            return {"disposition": "channel_disabled"}
        if trigger is None:
            return {"disposition": "no_trigger"}
        if trigger != "explicit" and not policy.automatic_enabled:
            return {"disposition": "automatic_disabled", "trigger": trigger}
        excerpts = [
            item for item in (_clean_excerpt(user_text), _clean_excerpt(assistant_text)) if item
        ]
        if not excerpts:
            return {"disposition": "privacy_blocked", "trigger": trigger}
        scene_format = "storyboard" if re.search(r"\bstoryboard\b", user_text, re.I) else "still"
        frame_count = policy.max_storyboard_frames if scene_format == "storyboard" else 1
        fingerprint = _hash(f"{session_id}|{trigger}|{scene_format}|{'|'.join(excerpts)}")
        instant = _utc(now)
        reason = self._rate_limit(instant, fingerprint)
        if reason:
            return {"disposition": "rate_limited", "reason": reason, "trigger": trigger}
        request_id = str(uuid.uuid4())
        brief = {
            "schema_version": 1,
            "request_id": request_id,
            "format": scene_format,
            "frame_count": frame_count,
            "trigger": trigger,
            "channel": normalized_channel,
            "scene_context": excerpts,
            "canon_refs": ["personality/appearance.md", "locations/locations.md"],
            "source_asset_ids": self._source_assets(),
            "composition": "one coherent scene; preserve approved identity and setting constraints",
            "negative_constraints": [
                "no secrets or unrelated conversation history",
                "no invented canon",
                "no unapproved identity substitution",
            ],
            "canon_status": "generated_noncanonical",
        }
        return {
            "disposition": "render",
            "brief": brief,
            "created_at": instant.isoformat(),
            "fingerprint": fingerprint,
        }

    async def render_for_turn(self, **arguments: Any):
        plan = self.prepare(**arguments)
        if plan["disposition"] != "render":
            return
        brief = plan["brief"]
        request_dir = self.root / brief["request_id"]
        request_dir.mkdir()
        try:
            paths = await self.renderer.render(brief, request_dir)
            if not paths:
                raise SceneMediaError("Renderer returned no frames")
            frames = []
            for path in paths[: int(brief["frame_count"])]:
                resolved = path.resolve()
                if resolved.parent != request_dir or not resolved.is_file():
                    raise SceneMediaError("Renderer returned an unsafe artifact path")
                frames.append(
                    {
                        "filename": resolved.name,
                        "local_path": str(resolved),
                        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
                    }
                )
            provenance = {
                "request_id": brief["request_id"],
                "created_at": plan["created_at"],
                "fingerprint": plan["fingerprint"],
                "provider": self.renderer.provider,
                "model": self.renderer.model,
                "external_renderer": self.renderer.external,
                "prompt": brief,
                "source_asset_ids": brief["source_asset_ids"],
                "frames": frames,
                "canon_status": "generated_noncanonical",
            }
            (request_dir / "provenance.json").write_text(
                json.dumps(provenance, indent=2), encoding="utf-8"
            )
            yield RuntimeEvent.media(
                name=brief["format"],
                request_id=brief["request_id"],
                frames=[
                    {
                        **frame,
                        "url": f"/api/scene-media/{brief['request_id']}/{frame['filename']}",
                    }
                    for frame in frames
                ],
                caption="Generated scene — non-canonical until approved",
                canon_status="generated_noncanonical",
            )
        except Exception:
            failure = {
                "request_id": brief["request_id"],
                "created_at": plan["created_at"],
                "fingerprint": plan["fingerprint"],
                "provider": self.renderer.provider,
                "model": self.renderer.model,
                "prompt": brief,
                "source_asset_ids": brief["source_asset_ids"],
                "frames": [],
                "status": "failed",
                "canon_status": "generated_noncanonical",
            }
            (request_dir / "provenance.json").write_text(
                json.dumps(failure, indent=2), encoding="utf-8"
            )
            return

    def artifact_path(self, request_id: str, filename: str) -> Path:
        try:
            normalized = str(uuid.UUID(request_id))
        except ValueError as exc:
            raise SceneMediaError("Invalid scene request ID") from exc
        if Path(filename).name != filename or filename == "provenance.json":
            raise SceneMediaError("Invalid scene artifact name")
        path = (self.root / normalized / filename).resolve()
        if path.parent != (self.root / normalized).resolve() or not path.is_file():
            raise SceneMediaError("Scene artifact not found")
        return path

    def delete(self, request_id: str) -> bool:
        try:
            normalized = str(uuid.UUID(request_id))
        except ValueError as exc:
            raise SceneMediaError("Invalid scene request ID") from exc
        directory = (self.root / normalized).resolve()
        if directory.parent != self.root or not directory.is_dir():
            return False
        retained = {"request_id": normalized}
        provenance_path = directory / "provenance.json"
        if provenance_path.is_file():
            try:
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                retained.update(
                    {
                        key: provenance[key]
                        for key in ("created_at", "fingerprint")
                        if key in provenance
                    }
                )
            except ValueError:
                pass
        for path in directory.iterdir():
            if not path.is_file():
                raise SceneMediaError("Scene directory contains an unexpected nested path")
            path.unlink()
        directory.rmdir()
        with (self.root / "deletions.jsonl").open("a", encoding="utf-8") as stream:
            retained["deleted_at"] = _utc().isoformat()
            stream.write(json.dumps(retained) + "\n")
        return True
