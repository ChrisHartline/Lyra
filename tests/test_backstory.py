from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid

import pytest

from lyra.backstory import (
    BACKSTORY_INDEX,
    DEFAULT_MAP,
    BackstoryMapError,
    load_backstory_map,
    validate_backstory_map,
)

ROOT = Path(__file__).resolve().parents[1]


def _case_dir(name: str) -> Path:
    case = ROOT / "data/test_tmp" / f"backstory_{name}_{uuid.uuid4().hex[:8]}"
    case.mkdir(parents=True, exist_ok=True)
    return case


def _copy_map_tree(case: Path) -> Path:
    payload = json.loads(DEFAULT_MAP.read_text(encoding="utf-8"))
    paths = {BACKSTORY_INDEX}
    paths.update(source["path"] for source in payload["sources"])
    paths.update(topic["path"] for topic in payload["topics"])
    for relative in paths:
        source = ROOT / relative
        target = case / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    map_path = case / "agents/lyra/references/backstory_map.json"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return map_path


def test_w92_map_accounts_for_sources_topics_and_pending_decisions():
    assert validate_backstory_map() == []
    backstory = load_backstory_map()

    assert len(backstory.payload["sources"]) == 7
    assert len(backstory.approved_topic_paths) == 7
    assert backstory.pending_reviews == ()
    assert backstory.payload["status"] == "approved"


def test_w92_locations_are_an_approved_pack_but_not_eager_runtime_context():
    backstory = load_backstory_map()
    assert "locations/locations.md" not in backstory.approved_topic_paths

    locations = (ROOT / "locations/locations.md").read_text(encoding="utf-8")
    assert "status: approved" in locations
    assert "PTSD" not in locations
    assert "Instacart" not in locations
    assert "gym" not in locations.lower()
    assert "annular" not in locations.lower()

    from lyra.packs import REQUIRED_MARKDOWN, compose_runtime_context, load_packs

    assert "locations/locations.md" in REQUIRED_MARKDOWN
    packs = load_packs()
    assert "Hollow Ribbon" in packs.body("locations/locations.md")
    context = compose_runtime_context(packs)
    assert "Hollow Ribbon" not in context


def test_w92_validator_rejects_source_hash_drift():
    case = _case_dir("hash")
    try:
        map_path = _copy_map_tree(case)
        source = case / "locations/locations.md"
        source.write_text(source.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

        errors = validate_backstory_map(map_path, root=case)
        assert any("SHA-256 does not match" in error for error in errors)
        with pytest.raises(BackstoryMapError):
            load_backstory_map(map_path, root=case)
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_w92_validator_rejects_unregistered_topic_and_frontmatter_drift():
    case = _case_dir("topic")
    try:
        map_path = _copy_map_tree(case)
        extra = case / "agents/lyra/references/backstory_unreviewed.md"
        extra.write_text("# Unreviewed\n", encoding="utf-8")
        topic = case / "agents/lyra/references/backstory_escape.md"
        topic.write_text(
            topic.read_text(encoding="utf-8").replace(
                "reference_id: backstory.escape",
                "reference_id: backstory.wrong",
            ),
            encoding="utf-8",
        )

        errors = validate_backstory_map(map_path, root=case)
        assert any("unregistered backstory topic" in error for error in errors)
        assert any("frontmatter reference_id" in error for error in errors)
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_w92_validator_requires_map_status_to_match_pending_reviews():
    case = _case_dir("status")
    try:
        map_path = _copy_map_tree(case)
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        payload["status"] = "awaiting_human_review"
        map_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        errors = validate_backstory_map(map_path, root=case)
        assert any("status must be 'approved'" in error for error in errors)
    finally:
        shutil.rmtree(case, ignore_errors=True)
