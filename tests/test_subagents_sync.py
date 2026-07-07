from __future__ import annotations

from pathlib import Path
from scripts.sync_subagents import sync


def test_c1_subagent_frontmatter_and_byte_identical_sync():
    root = Path.cwd()
    src = root / "agents" / "lyra" / "subagents"
    assert (src / "researcher.md").exists()

    results = sync()
    assert results
    assert all(r.valid for r in results)

    dst = root / ".cursor" / "agents"
    for file in src.glob("*.md"):
        copied = dst / file.name
        assert copied.exists()
        assert file.read_bytes() == copied.read_bytes()
