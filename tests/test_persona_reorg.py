from __future__ import annotations

from pathlib import Path


def test_c2_backstory_split_zero_content_loss_and_story_scaffold():
    root = Path.cwd()
    original = (root / "agents/lyra/references/backstory.md").read_text(encoding="utf-8")

    parts = [
        (root / "agents/lyra/references/backstory_homeworld.md").read_text(encoding="utf-8"),
        (root / "agents/lyra/references/backstory_escape.md").read_text(encoding="utf-8"),
        (root / "agents/lyra/references/backstory_current_situation.md").read_text(encoding="utf-8"),
        (root / "agents/lyra/references/backstory_personality_impact.md").read_text(encoding="utf-8"),
        (root / "agents/lyra/references/backstory_long_term_hopes.md").read_text(encoding="utf-8"),
    ]

    for phrase in [
        "## Origin",
        "## The Escape",
        "## Current Situation",
        "## Personality Impact",
        "## Long-term Hopes",
    ]:
        assert phrase in original
        assert any(phrase in p for p in parts)

    assert (root / "agents/lyra/state/story/ship.md").exists()
    assert (root / "agents/lyra/state/story/arcs.md").exists()
    assert (root / "agents/lyra/state/story/timeline.md").exists()

    guide = (root / "agents/lyra/DIRECTORY_GUIDE.md").read_text(encoding="utf-8")
    assert "state/story" in guide or "state/" in guide
