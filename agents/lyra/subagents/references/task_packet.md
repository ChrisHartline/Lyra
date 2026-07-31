# Subagent task packet template (C3.1)

Pass this packet when launching a Python or C++ subagent. Subagents do not
inherit conversation context, so every field must be self-contained.

## Packet

```markdown
## Objective
<one sentence outcome>

## Repository / target
<path or repo name; for C++ include build target>

## Governing requirements
- <docs/lyra_build_plan.md gate ID or other requirement>
- <SRS / ADR references if any>

## Allowed scope
- Files/directories the worker may touch
- Explicit non-goals

## Constraints / invariants
- Plane boundaries (Notion / pgvector / KG / story)
- Secrets from `.env` only
- No commits/pushes unless requested

## Definition of done
- Behavior change
- Tests that must pass
- Docs/progress-log updates if this is a gate

## Commands that must pass
```text
venv\Scripts\python -m pytest <narrow> -q
venv\Scripts\python -m pytest -q
```

## Expected handoff
- Implementation summary
- Exact verification commands + observed results
- Risks / remaining human approvals
```

## Parent responsibilities

- Own persona, approvals, Notion publishes, and final user-facing voice.
- Load relevant domain skills before or during the handoff if needed.
- Do not ask the worker to invent missing acceptance criteria.
