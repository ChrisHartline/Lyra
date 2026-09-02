from __future__ import annotations

from pathlib import Path

import json
import shutil
import uuid

from lyra.packs import (
    REQUIRED_JSON,
    REQUIRED_MARKDOWN,
    validate_pack_layout,
)

ROOT = Path(__file__).resolve().parents[1]


def _case_dir(name: str) -> Path:
    root = ROOT / "data/test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    case = root / f"{name}_{uuid.uuid4().hex[:8]}"
    case.mkdir(parents=True, exist_ok=True)
    return case


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
        for relative in REQUIRED_MARKDOWN:
            target = case / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                (ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8"
            )
        (case / "state/relationship.json").write_text("{}", encoding="utf-8")
        (case / "ship/current_status.json").write_text(
            json.dumps({"overall_condition": "x", "systems": {}, "location": {}}),
            encoding="utf-8",
        )

        errors = validate_pack_layout(case)
        assert any("living_conversion" in e for e in errors)
        assert any("quantum_drive" in e for e in errors)
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_e3_ship_lore_has_no_duplicate_source_of_truth():
    pointer = (ROOT / "agents/lyra/references/ship_reference.md").read_text(
        encoding="utf-8"
    )
    assert "ship/ship_reference.md" in pointer
    assert "Entanglement coils" not in pointer
