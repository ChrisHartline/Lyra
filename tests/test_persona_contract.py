from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LYRA = ROOT / "agents/lyra"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_c4_avatar_loader_points_to_real_tier0_files():
    avatar_skill = _read(ROOT / ".cursor/skills/lyra-avatar/SKILL.md")

    for relative in ("agents/lyra/system_prompt.md", "agents/lyra/character_file.md"):
        assert relative in avatar_skill
        assert (ROOT / relative).is_file()

    assert "agents/lyra/system-prompt.md" not in avatar_skill


def test_c4_tier0_excludes_evolving_state_and_detailed_lore():
    system_prompt = _read(LYRA / "system_prompt.md")
    character_file = _read(LYRA / "character_file.md")
    tier0 = f"{system_prompt}\n{character_file}"

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
        "lavender-purple skin",
        "silver-white hair",
        "star-shaped freckles",
    ):
        assert reference_owned_detail not in tier0

    relationship_state = _read(LYRA / "state/relationship_state.md")
    assert "Current Stage" in relationship_state
    assert "Early Romantic" in relationship_state


def test_c4_mode_contract_prevents_professional_persona_leakage():
    system_prompt = _read(LYRA / "system_prompt.md")

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
        LYRA / "references/appearance_reference.md",
        LYRA / "references/color_emotion_map.md",
        LYRA / "references/idiom_list.md",
        LYRA / "references/personality_quirks.md",
        LYRA / "references/ship_reference.md",
        LYRA / "state/relationship_state.md",
        LYRA / "state/story/ship.md",
        LYRA / "state/story/arcs.md",
        LYRA / "state/story/timeline.md",
    )
    assert all(path.is_file() for path in required)

    character_file = _read(LYRA / "character_file.md")
    assert "current relationship stage" in character_file
    assert "references/personality_quirks.md" in character_file
    assert "state/relationship_state.md" in character_file
    assert "skills/*/SKILL.md" in character_file
