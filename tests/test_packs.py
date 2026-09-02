from __future__ import annotations

from pathlib import Path

from lyra.packs import REQUIRED_JSON, REQUIRED_MARKDOWN, validate_pack_layout

ROOT = Path(__file__).resolve().parents[1]


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
