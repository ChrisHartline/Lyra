# Subagent task packet template

Pass this packet when launching any Lyra subagent. Subagents do not inherit
conversation context, so every field must be self-contained.

## Packet

```markdown
## Objective
<one sentence outcome>

## Worker
<researcher | python-developer | cpp-developer>

## Repository / target
<path or repo name; for C++ include build target>

## Governing requirements
- <docs/lyra_build_plan.md gate ID or other requirement>
- <SRS / ADR references if any>

## Allowed scope
- Files/directories the worker may touch
- Explicit non-goals

## Tools / MCP allowed
- <e.g. lyra-corpus: search_corpus only>
- <e.g. shell+pytest; no Notion publish>
- <see agents/lyra/subagents/references/tools_and_mcp.md>

## Constraints / invariants
- Plane boundaries (Notion / pgvector / KG / story)
- Secrets from `.env` only
- No commits/pushes unless requested
- No approve_memory / approve_observation unless requested

## Definition of done
- Behavior change or research deliverable
- Tests/commands that must pass (implementation workers)
- Docs/progress-log updates if this is a gate

## Commands that must pass
```text
# python-developer example
venv\Scripts\python -m pytest tests/test_<module>.py -q
venv\Scripts\python -m pytest -q
```

## Expected handoff
- Implementation or research summary
- Exact verification commands + observed results (or citation package)
- Risks / remaining human approvals
```

## Parent responsibilities

- Own persona, approvals, Notion publishes, and final user-facing voice.
- Load relevant domain skills before or during the handoff if needed.
- Point the worker at the matching playbook under
  `agents/lyra/subagents/references/`.
- Do not ask the worker to invent missing acceptance criteria.
