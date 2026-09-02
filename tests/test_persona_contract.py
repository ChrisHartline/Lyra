from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LYRA = ROOT / "agents/lyra"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_c4_avatar_loader_points_to_real_tier0_files():
    avatar_skill = _read(ROOT / ".cursor/skills/lyra-avatar/SKILL.md")

    for relative in ("personality/system_prompt.md", "personality/character_bible.md"):
        assert relative in avatar_skill
        assert (ROOT / relative).is_file()

    assert "agents/lyra/system-prompt.md" not in avatar_skill


def test_c4_tier0_excludes_evolving_state_and_detailed_lore():
    system_prompt = _read(ROOT / "personality/system_prompt.md")
    character_bible = _read(ROOT / "personality/character_bible.md")
    tier0 = f"{system_prompt}\n{character_bible}"

    assert "Christopher's girlfriend" in system_prompt
    assert "girlfriend, affectionate companion" in character_bible
    assert "personal and real" in system_prompt

    for evolving_marker in (
        "Early romantic stage",
        "Honeymoon Phase",
        "First date",
        "First night together",
        "approximately 3 weeks",
    ):
        assert evolving_marker not in tier0

    for reference_owned_detail in (
        "5'1",
        "lavender-purple",
        "star-shaped freckles",
        "seven-strand",
    ):
        assert reference_owned_detail not in tier0

    relationship_state = _read(ROOT / "state/relationship.md")
    assert "Current Stage" in relationship_state
    assert "Early Romantic" in relationship_state


def test_c4_mode_contract_prevents_professional_persona_leakage():
    system_prompt = _read(ROOT / "personality/system_prompt.md")

    assert "Technical Assistant — default for engineering work" in system_prompt
    assert "Professional Deliverable" in system_prompt
    assert "light" in system_prompt.lower()
    for forbidden_artifact_style in (
        "nicknames",
        "flirting",
        "alien lore",
        "color narration",
        "roleplay actions",
    ):
        assert forbidden_artifact_style in system_prompt


def test_c4_reference_and_state_ownership_is_resolvable():
    required = (
        ROOT / "personality/appearance.md",
        ROOT / "personality/emotional_color_map.md",
        ROOT / "personality/speech_and_idioms.md",
        ROOT / "ship/ship_reference.md",
        ROOT / "state/relationship.md",
        ROOT / "state/active_arcs.md",
        ROOT / "state/user_knowledge.md",
        LYRA / "references/observation_etiquette.md",
    )
    assert all(path.is_file() for path in required)

    character_bible = _read(ROOT / "personality/character_bible.md")
    assert "relationship stage" in character_bible
    assert "personality/appearance.md" in character_bible
    assert "personality/speech_and_idioms.md" in character_bible
    assert "agents/lyra/references/observation_etiquette.md" in character_bible
    assert "state/relationship.md" in character_bible
    assert "skills/*/SKILL.md" in character_bible
