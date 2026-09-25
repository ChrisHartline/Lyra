from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import time
import uuid

from lyra.providers import ModelProfile
from lyra.runtime import AgentLoop, ModelToolRunner
from lyra.runtime_events import EventKind, RuntimeEvent
from lyra.runtime_tools import ToolRegistry
from lyra.scene_media import SceneDirector


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ModelProfile("conversation", "openai-compatible", "fake", "key", "https://fake")


def _root(name: str) -> Path:
    path = ROOT / "data" / "test_tmp" / f"scene_{name}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    return path


class FakeRenderer:
    provider = "local-test"
    model = "fixed-v1"
    external = False

    def __init__(self, *, fail: bool = False, delay: float = 0) -> None:
        self.fail = fail
        self.delay = delay
        self.briefs = []

    async def render(self, brief, output_dir):
        self.briefs.append(brief)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("provider secret detail")
        count = int(brief["frame_count"])
        paths = []
        for index in range(count):
            path = output_dir / f"frame-{index + 1}.png"
            path.write_bytes(b"png" + bytes([index]))
            paths.append(path)
        return paths


def test_policy_defaults_disabled_and_trigger_classes_are_explicit():
    director = SceneDirector(FakeRenderer(), root=_root("triggers"))
    assert director.get_policy().enabled is False
    cases = {
        "Please generate an image of us in the meadow": "explicit",
        "We arrived at the quiet station": "arrival",
        "The first view revealed the valley": "location_reveal",
        "She kissed him beneath the stars": "emotional_beat",
        "Lyra wore her hair down": "appearance_change",
        "We discovered a sealed room on the ship": "ship_discovery",
        "The repairs are complete — we did it": "milestone",
    }
    assert {text: director.detect_trigger(text) for text in cases} == cases
    assert director.detect_trigger("We talked about ordinary plans.") is None


def test_prepare_is_opt_in_privacy_filtered_bounded_and_rate_limited():
    director = SceneDirector(FakeRenderer(), root=_root("policy"))
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    disabled = director.prepare(
        session_id="s", channel="web", user_text="Generate an image of us",
        assistant_text="All right.", now=now,
    )
    assert disabled == {"disposition": "disabled"}

    director.set_policy(
        enabled=True, automatic_enabled=False, allowed_channels=["web", "telegram"],
        max_per_day=2, cooldown_minutes=120, max_storyboard_frames=3,
    )
    blocked = director.prepare(
        session_id="s", channel="web", user_text="Generate an image; API key sk-abcdef123",
        assistant_text="password hunter2", now=now,
    )
    assert blocked["disposition"] == "privacy_blocked"
    auto = director.prepare(
        session_id="s", channel="web", user_text="We arrived at the station",
        assistant_text="The doors opened.", now=now,
    )
    assert auto["disposition"] == "automatic_disabled"

    plan = director.prepare(
        session_id="s", channel="web", user_text="Please make a storyboard of the meadow",
        assistant_text="Wind moves through the grass.", now=now,
    )
    assert plan["disposition"] == "render"
    brief = plan["brief"]
    assert brief["format"] == "storyboard" and brief["frame_count"] == 3
    assert len(brief["scene_context"]) == 2
    assert all(len(item) <= 400 for item in brief["scene_context"])
    assert brief["canon_status"] == "generated_noncanonical"
    assert len(brief["source_asset_ids"]) == 6


def test_automatic_scenes_require_opt_in_and_cooldown_prevents_every_turn():
    director = SceneDirector(FakeRenderer(), root=_root("cadence"))
    director.set_policy(
        enabled=True, automatic_enabled=True, allowed_channels=["web"],
        max_per_day=2, cooldown_minutes=120, max_storyboard_frames=3,
    )
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)

    async def first_render():
        return [event async for event in director.render_for_turn(
            session_id="s", channel="web", user_text="We arrived at Silent Drift",
            assistant_text="The meadow opened ahead of us.", now=now,
        )]

    assert len(asyncio.run(first_render())) == 1
    ordinary = director.prepare(
        session_id="s", channel="web", user_text="We discussed dinner",
        assistant_text="A quiet reply.", now=now + timedelta(minutes=1),
    )
    cooldown = director.prepare(
        session_id="s", channel="web", user_text="She wore her hair down",
        assistant_text="Gold freckles caught the light.", now=now + timedelta(minutes=1),
    )
    assert ordinary["disposition"] == "no_trigger"
    assert cooldown == {
        "disposition": "rate_limited", "reason": "cooldown", "trigger": "appearance_change"
    }


def test_external_renderer_never_receives_assets_without_external_approval():
    renderer = FakeRenderer()
    renderer.external = True
    director = SceneDirector(renderer, root=_root("external"))
    director.set_policy(
        enabled=True, automatic_enabled=False, allowed_channels=["web"],
        max_per_day=2, cooldown_minutes=1, max_storyboard_frames=3,
    )
    plan = director.prepare(
        session_id="s", channel="web", user_text="Generate an image of Lyra",
        assistant_text="A simple portrait.",
    )
    assert plan["brief"]["source_asset_ids"] == []


def test_render_records_complete_local_provenance_and_deletion_is_independent():
    renderer = FakeRenderer()
    director = SceneDirector(renderer, root=_root("render"))
    director.set_policy(
        enabled=True, automatic_enabled=True, allowed_channels=["web"],
        max_per_day=2, cooldown_minutes=1, max_storyboard_frames=3,
    )

    async def render():
        return [event async for event in director.render_for_turn(
            session_id="session-1", channel="web",
            user_text="Generate an image of Lyra in the meadow",
            assistant_text="She stands beneath a clear sky.",
            now=datetime(2026, 9, 24, 12, tzinfo=UTC),
        )]

    events = asyncio.run(render())
    assert len(events) == 1 and events[0].kind is EventKind.MEDIA
    data = events[0].data
    request_id = str(data["request_id"])
    provenance_path = director.root / request_id / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["provider"] == "local-test"
    assert provenance["model"] == "fixed-v1"
    assert provenance["prompt"]["scene_context"]
    assert provenance["source_asset_ids"]
    assert provenance["frames"][0]["sha256"]
    conversation = ["user message", "assistant reply"]
    assert director.delete(request_id) is True
    assert conversation == ["user message", "assistant reply"]
    assert not provenance_path.exists()
    deletion = json.loads((director.root / "deletions.jsonl").read_text(encoding="utf-8"))
    assert deletion["request_id"] == request_id
    assert deletion["fingerprint"] == provenance["fingerprint"]
    replay = director.prepare(
        session_id="session-1", channel="web",
        user_text="Generate an image of Lyra in the meadow",
        assistant_text="She stands beneath a clear sky.",
        now=datetime(2026, 9, 24, 12, 1, tzinfo=UTC),
    )
    assert replay["reason"] == "duplicate_scene"


def test_failed_renderer_degrades_to_text_and_records_no_secret_error():
    director = SceneDirector(FakeRenderer(fail=True), root=_root("failure"))
    director.set_policy(
        enabled=True, automatic_enabled=False, allowed_channels=["web"],
        max_per_day=2, cooldown_minutes=1, max_storyboard_frames=3,
    )

    async def render():
        return [event async for event in director.render_for_turn(
            session_id="session-1", channel="web",
            user_text="Generate an image of the meadow", assistant_text="Here is the scene.",
        )]

    assert asyncio.run(render()) == []
    records = list(director.root.glob("*/provenance.json"))
    assert len(records) == 1
    text = records[0].read_text(encoding="utf-8")
    assert '"status": "failed"' in text
    assert "provider secret detail" not in text


class Provider:
    async def stream(self, profile, messages, tools=(), *, environ=None):
        del profile, messages, tools, environ
        yield RuntimeEvent.text_delta("The text arrives first.")
        yield RuntimeEvent.completion("stop")


class Sessions:
    def __init__(self):
        self.messages = []

    def recover_interrupted_turns(self, session_id): return 0
    def append_message(self, session_id, role, content, **kwargs):
        self.messages.append((role, content, kwargs))
        return {"message_id": len(self.messages)}
    def start_turn(self, session_id, status): return {"turn_id": "turn-1"}
    def update_turn(self, turn_id, status, error_code=None): return None


class Context:
    def build(self, session_id, **kwargs): return [{"role": "user", "content": kwargs["memory_query"]}]


def test_agent_loop_emits_completion_before_slow_media_without_mutating_text():
    director = SceneDirector(FakeRenderer(delay=0.06), root=_root("async"))
    director.set_policy(
        enabled=True, automatic_enabled=False, allowed_channels=["web"],
        max_per_day=2, cooldown_minutes=1, max_storyboard_frames=3,
    )
    sessions = Sessions()
    loop = AgentLoop(
        sessions=sessions, context=Context(),
        runner=ModelToolRunner(Provider(), PROFILE, ToolRegistry()),
        system_prompt="Lyra", scene_director=director,
    )

    async def collect():
        seen = []
        start = time.monotonic()
        async for event in loop.stream_turn("session-1", "Generate an image of the meadow"):
            seen.append((event.kind, time.monotonic() - start))
        return seen

    seen = asyncio.run(collect())
    assert [kind for kind, _elapsed in seen] == [
        EventKind.TEXT, EventKind.COMPLETION, EventKind.MEDIA,
    ]
    assert seen[1][1] < 0.04
    assert seen[2][1] >= 0.05
    assert [item[1] for item in sessions.messages] == [
        "Generate an image of the meadow", "The text arrives first.",
    ]
