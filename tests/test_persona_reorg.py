from __future__ import annotations

from pathlib import Path


def test_c2_backstory_source_is_preserved_and_aggregate_is_an_index():
    root = Path.cwd()
    source = (
        root
        / "agents/lyra/references/source_material/backstory_initial_2026-07-04.md"
    ).read_text(encoding="utf-8")
    index = (root / "agents/lyra/references/backstory.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "## Origin",
        "## The Escape",
        "## Current Situation",
        "## Personality Impact",
        "## Long-term Hopes",
    ):
        assert phrase in source
        assert phrase not in index

    for topic in (
        "backstory_homeworld.md",
        "backstory_escape.md",
        "backstory_current_situation.md",
        "backstory_personality_impact.md",
        "backstory_long_term_hopes.md",
        "backstory_chosen_bond.md",
        "backstory_vossari_culture.md",
    ):
        assert topic in index

    assert len(index) < 1600
    assert (root / "state/story/ship.md").exists()
    assert (root / "state/story/arcs.md").exists()
    assert (root / "state/story/timeline.md").exists()
