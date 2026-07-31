from __future__ import annotations

from pathlib import Path

from scripts.sync_subagents import sync


def test_c31_context_packs_exist_and_are_referenced():
    root = Path.cwd()
    refs = root / "agents/lyra/subagents/references"
    required = [
        refs / "task_packet.md",
        refs / "python_playbook.md",
        refs / "cpp_playbook.md",
        refs / "eval_prompts.md",
    ]
    assert all(path.is_file() for path in required)

    python_agent = (root / "agents/lyra/subagents/python-developer.md").read_text(
        encoding="utf-8"
    )
    cpp_agent = (root / "agents/lyra/subagents/cpp-developer.md").read_text(
        encoding="utf-8"
    )
    assert "references/python_playbook.md" in python_agent
    assert "references/task_packet.md" in python_agent
    assert "references/cpp_playbook.md" in cpp_agent
    assert "references/task_packet.md" in cpp_agent

    results = sync(check=True)
    assert results
    assert all(result.valid for result in results)
