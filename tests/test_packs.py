from __future__ import annotations

from pathlib import Path

import inspect
import json
import shutil
import uuid

import pytest

from lyra.memory import MemoryService
from lyra.packs import (
    LEGACY_POINTERS,
    REQUIRED_JSON,
    REQUIRED_MARKDOWN,
    STORY_CANON_DIR,
    PackError,
    compose_runtime_context,
    load_packs,
    validate_pack_layout,
)

ROOT = Path(__file__).resolve().parents[1]


def _case_dir(name: str) -> Path:
    root = ROOT / "data/test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    case = root / f"{name}_{uuid.uuid4().hex[:8]}"
    case.mkdir(parents=True, exist_ok=True)
    return case


def _copy_pack_tree(case: Path) -> None:
    for relative in REQUIRED_MARKDOWN + REQUIRED_JSON:
        target = case / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")


def test_e1_pack_layout_and_frontmatter():
    errors = validate_pack_layout()
    assert errors == [], "\n".join(errors)

    for relative in REQUIRED_MARKDOWN + REQUIRED_JSON:
        assert (ROOT / relative).is_file()

    adr = (ROOT / "docs/adr/003-data-packs-source-of-truth.md").read_text(encoding="utf-8")
    srs = (ROOT / "docs/lyra_system_requirements.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs/lyra_build_plan.md").read_text(encoding="utf-8")
    guide = (ROOT / "agents/lyra/DIRECTORY_GUIDE.md").read_text(encoding="utf-8")
    for text in (adr, srs, plan, guide):
        assert "personality/system_prompt.md" in text
        assert "state/relationship.md" in text
        assert "ship/current_status.json" in text


def test_e3_ship_status_schema_and_cargo_is_prose():
    status = json.loads((ROOT / "ship/current_status.json").read_text(encoding="utf-8"))

    assert status["overall_condition"]
    assert status["location"]["type"]
    for name in ("quantum_drive", "power_core", "stealth", "life_support", "hull"):
        assert status["systems"][name]["status"]

    cargo = (ROOT / "ship/cargo_and_layout.md").read_text(encoding="utf-8")
    assert cargo.startswith("---")
    assert "pack: ship" in cargo
    assert "overall_condition" not in cargo, "cargo layout must not clone status JSON"
    assert "Cargo Bay" in cargo


def test_e3_ship_status_schema_violations_are_reported():
    case = _case_dir("e3_status_schema")
    try:
        _copy_pack_tree(case)
        (case / "ship/current_status.json").write_text(
            json.dumps({"overall_condition": "x", "systems": {}, "location": {}}),
            encoding="utf-8",
        )

        errors = validate_pack_layout(case)
        assert any("living_conversion" in e for e in errors)
        assert any("quantum_drive" in e for e in errors)
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_e4_evolving_state_lives_only_in_the_state_pack():
    relationship = (ROOT / "state/relationship.md").read_text(encoding="utf-8")
    assert "Early Romantic" in relationship
    assert "First night together" in relationship
    assert "Chosen" in relationship

    machine = json.loads((ROOT / "state/relationship.json").read_text(encoding="utf-8"))
    assert machine["stage"]
    assert machine["bond_status"]

    for relative in ("personality/system_prompt.md", "personality/character_bible.md"):
        tier0 = (ROOT / relative).read_text(encoding="utf-8")
        for marker in ("Early Romantic", "Honeymoon", "First night together"):
            assert marker not in tier0, f"{relative} leaked evolving state"

    pointer = (ROOT / "agents/lyra/state/relationship_state.md").read_text(
        encoding="utf-8"
    )
    assert "state/relationship.md" in pointer
    assert "Early Romantic" not in pointer


def test_e4_user_knowledge_excludes_story_and_campaign_content():
    user_knowledge = (ROOT / "state/user_knowledge.md").read_text(encoding="utf-8")
    lowered = user_knowledge.lower()

    for story_marker in (
        "campaign",
        "silent drift",
        "vossari",
        "starweaving",
        "quantum drive",
        "spaceship",
        "the ship",
    ):
        assert story_marker not in lowered, f"biography leaked story content: {story_marker}"

    arcs = (ROOT / "state/active_arcs.md").read_text(encoding="utf-8")
    assert "Silent Drift" in arcs


def test_e3_ship_lore_has_no_duplicate_source_of_truth():
    pointer = (ROOT / "agents/lyra/references/ship_reference.md").read_text(
        encoding="utf-8"
    )
    assert "ship/ship_reference.md" in pointer
    assert "Entanglement coils" not in pointer


def test_e5_loader_composes_runtime_context():
    packs = load_packs()

    assert packs.document("personality/system_prompt.md").pack == "personality"
    assert packs.ship_status["overall_condition"]
    assert packs.relationship["stage"]
    assert not packs.body("personality/system_prompt.md").startswith("---")

    context = compose_runtime_context(packs)
    assert "Persona Behavior Contract" in context
    assert "Stable Character Index" in context
    assert "Emotional Bioluminescence Map" in context
    assert "Scout Ship Reference" in context
    assert "Early Romantic" in context
    assert "grounded_repair" in context
    assert packs.document("locations/locations.md").pack == "locations"
    assert "Hollow Ribbon" not in context, "W9.3 will add selective location routing"

    lean = compose_runtime_context(packs, include_ship=False, include_state=False)
    assert "Scout Ship Reference" not in lean
    assert "Early Romantic" not in lean


def test_e5_loader_fails_loudly_on_missing_file():
    case = _case_dir("e5_missing")
    try:
        _copy_pack_tree(case)
        (case / "personality/appearance.md").unlink()

        with pytest.raises(PackError) as excinfo:
            load_packs(case)
        assert "personality/appearance.md" in str(excinfo.value)
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_e5_duplicate_source_of_truth_is_rejected():
    assert validate_pack_layout() == []

    case = _case_dir("e5_dual_sot")
    try:
        _copy_pack_tree(case)
        legacy = case / "agents/lyra/system_prompt.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            (ROOT / "personality/system_prompt.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        errors = validate_pack_layout(case)
        assert any("still holds full content" in e for e in errors)
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_e5_legacy_paths_are_pointers_to_the_packs():
    for legacy, pack_path in LEGACY_POINTERS.items():
        path = ROOT / legacy
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert pack_path in text
        assert len(text) < 600


def test_e5_story_canon_regenerates_into_the_state_pack():
    assert STORY_CANON_DIR == "state/story"
    for name in ("ship.md", "arcs.md", "timeline.md"):
        assert (ROOT / STORY_CANON_DIR / name).is_file()

    default_dir = inspect.signature(
        MemoryService.regenerate_story_canon
    ).parameters["story_dir"].default
    assert default_dir == STORY_CANON_DIR
