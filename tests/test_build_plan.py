from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_build_plan", ROOT / "scripts" / "validate_build_plan.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def test_build_plan_has_unique_defined_ordered_gate_ids():
    assert validator.validate_plan() == []


def test_validator_rejects_duplicate_undefined_and_ranged_gates():
    path = ROOT / "data" / "test_tmp" / "build_plan" / "invalid.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "### W4.1 \N{EM DASH} First\n"
        "### W4.1 \N{EM DASH} Duplicate\n"
        "### W4.2\N{EN DASH}W4.3 \N{EM DASH} Hidden range\n"
        "| Task | Status | Evidence |\n"
        "|---|---|---|\n"
        "| W4.2 | Not started | \N{EM DASH} |\n",
        encoding="utf-8",
    )

    errors = validator.validate_plan(path)

    assert any("Duplicate definition ids: W4.1" in error for error in errors)
    assert any("Definitions missing progress rows: W4.1" in error for error in errors)
    assert any("Progress rows missing definitions: W4.2" in error for error in errors)
    assert any("Hidden gate ranges" in error for error in errors)
