from __future__ import annotations

from pathlib import Path

from scripts.sync_subagents import sync


def test_c31_context_packs_exist_and_are_referenced():
    root = Path.cwd()
    refs = root / "agents/lyra/subagents/references"
    required = [
        refs / "task_packet.md",
        refs / "tools_and_mcp.md",
        refs / "researcher_playbook.md",
        refs / "python_playbook.md",
        refs / "cpp_playbook.md",
        refs / "eval_prompts.md",
    ]
    assert all(path.is_file() for path in required)

    researcher = (root / "agents/lyra/subagents/researcher.md").read_text(encoding="utf-8")
    python_agent = (root / "agents/lyra/subagents/python-developer.md").read_text(
        encoding="utf-8"
    )
    cpp_agent = (root / "agents/lyra/subagents/cpp-developer.md").read_text(
        encoding="utf-8"
    )

    assert "references/researcher_playbook.md" in researcher
    assert "references/tools_and_mcp.md" in researcher
    assert "lyra-corpus.search_corpus" in researcher
    assert "references/python_playbook.md" in python_agent
    assert "references/tools_and_mcp.md" in python_agent
    assert "references/cpp_playbook.md" in cpp_agent
    assert "references/tools_and_mcp.md" in cpp_agent
    assert "Tools / MCP allowed" in (refs / "task_packet.md").read_text(encoding="utf-8")

    results = sync(check=True)
    assert results
    assert all(result.valid for result in results)
