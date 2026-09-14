# Tool: propose_memory

## Purpose
Insert a candidate memory row (`approved=false`) for later approval flow.

## Input
- `content` (string, required)
- `memory_type` (string, optional, default `fact`)
- `salience` (integer, optional, default `5`)
- `metadata` (object, optional)

The service applies never-persist filtering, requires a biography/story/campaign
ledger, adds provenance/reason/sensitivity defaults, and refuses KG observation
content (use `propose_observation` for that destination).

## Output
- `memory_id`
- `approved` (always `false` at proposal time)

The proposal appears in the authenticated local W6.1 control center. This tool
cannot approve, correct, reject, or forget it.

W6.1a does not change this MCP contract: agent/tool proposals remain pending.
Only the deterministic conversation policy may promote safe lane-qualified
content, and every promotion records its source message, lane, mode, and actor.
