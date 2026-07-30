from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from scripts.sync_subagents import sync, validate_subagent


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

    checked = sync(check=True)
    assert checked
    assert all(r.valid for r in checked)


def test_c3_subagent_validation_rejects_bad_metadata():
    case = Path("data/test_tmp") / f"c3_validation_{uuid.uuid4().hex[:8]}"
    case.mkdir(parents=True, exist_ok=True)
    try:
        bad = case / "python-developer.md"
        bad.write_text(
            "\n".join(
                [
                    "---",
                    "name: wrong-name",
                    "description: Test",
                    "model: inherit",
                    "readonly: sometimes",
                    "tools: shell",
                    "---",
                    "",
                    "Body",
                ]
            ),
            encoding="utf-8",
        )

        result = validate_subagent(bad)
        assert result.valid is False
        assert "name-mismatch:wrong-name!=python-developer" in result.missing
        assert "invalid-boolean:readonly" in result.missing
        assert "unsupported:tools" in result.missing
    finally:
        shutil.rmtree(case, ignore_errors=True)


def test_c3_check_detects_drift_and_sync_removes_stale_files():
    case = Path("data/test_tmp") / f"c3_sync_{uuid.uuid4().hex[:8]}"
    src = case / "src"
    dst = case / "dst"
    src.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)
    try:
        source = src / "researcher.md"
        source.write_text(
            "\n".join(
                [
                    "---",
                    "name: researcher",
                    "description: Research",
                    "model: inherit",
                    "---",
                    "",
                    "Body",
                ]
            ),
            encoding="utf-8",
        )
        (dst / "researcher.md").write_text("drift", encoding="utf-8")
        stale = dst / "obsolete.md"
        stale.write_text("obsolete", encoding="utf-8")

        checked = sync(src, dst, check=True)
        issues = {issue for result in checked for issue in result.missing}
        assert {"out-of-sync", "stale-destination"}.issubset(issues)

        synced = sync(src, dst)
        assert all(result.valid for result in synced)
        assert (dst / "researcher.md").read_bytes() == source.read_bytes()
        assert not stale.exists()
    finally:
        shutil.rmtree(case, ignore_errors=True)
