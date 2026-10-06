from __future__ import annotations

import copy

from lyra.visual_assets import ROOT, load_catalog, validate_catalog, validate_catalog_data


def test_w91_catalog_covers_every_active_visual_and_is_fail_closed():
    catalog = load_catalog()
    appearance = (ROOT / "personality" / "appearance.md").read_text(encoding="utf-8")

    assert validate_catalog() == []
    assert len(catalog["assets"]) == 40
    assert sum(asset["canon_status"] == "approved" for asset in catalog["assets"]) == 6
    assert sum(asset["canon_status"] == "candidate" for asset in catalog["assets"]) == 0
    assert sum(asset["canon_status"] == "reference" for asset in catalog["assets"]) == 34
    assert all(not asset["approved_for_external_renderer"] for asset in catalog["assets"])
    assert all(
        asset["approval"]["decided_by"] == "Christopher"
        for asset in catalog["assets"]
        if asset["canon_status"] == "approved"
    )
    assert "warm amber-hazel" in appearance
    assert "Fine, luminous gold freckles" in appearance
    assert "striking violet" not in appearance
    assert "star-shaped freckles" not in appearance


def test_w91_validator_rejects_missing_files_duplicate_ids_and_invalid_subjects():
    catalog = load_catalog()
    broken = copy.deepcopy(catalog)
    broken["assets"][0]["path"] = "lyra/references/details/missing.jpg"
    broken["assets"][1]["asset_id"] = broken["assets"][0]["asset_id"]
    broken["assets"][2]["subject"] = "unknown"

    errors = validate_catalog_data(broken)

    assert any("file is missing" in error for error in errors)
    assert any("duplicate asset IDs" in error for error in errors)
    assert any("invalid subject" in error for error in errors)


def test_w91_validator_rejects_unapproved_canon_duplicate_content_and_remote_data():
    catalog = load_catalog()
    broken = copy.deepcopy(catalog)
    broken["assets"][0]["canon_status"] = "approved"
    broken["assets"][0]["approval"] = {
        "status": "pending",
        "decided_by": None,
        "decided_at": None,
    }
    broken["assets"][1]["sha256"] = broken["assets"][0]["sha256"]
    broken["assets"][2]["provenance"]["source_locator"] = "https://private.invalid/a"
    broken["assets"][3]["provenance"]["api_key"] = "must-not-exist"

    errors = validate_catalog_data(broken)

    assert any("canonical without human approval" in error for error in errors)
    assert any("duplicate file content" in error for error in errors)
    assert any("committed remote URL" in error for error in errors)
    assert any("prohibited credential field" in error for error in errors)


def test_w91_validator_rejects_external_use_without_cleared_rights_and_approval():
    catalog = load_catalog()
    broken = copy.deepcopy(catalog)
    broken["assets"][0]["approved_for_external_renderer"] = True
    broken["assets"][0]["allowed_transformations"] = ["crop"]

    errors = validate_catalog_data(broken)

    assert any("cannot leave the workstation" in error for error in errors)
    assert any("transformations must stay empty" in error for error in errors)
