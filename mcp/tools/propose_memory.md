# Tool: propose_memory

## Purpose
Insert a candidate memory row (`approved=false`) for later approval flow.

## Input
- `content` (string, required)
- `memory_type` (string, optional, default `fact`)
- `salience` (integer, optional, default `5`)
- `metadata` (object, optional)

## Output
- `memory_id`
- `approved` (always `false` at proposal time)
