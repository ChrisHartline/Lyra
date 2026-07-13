# Tool: search_memories

## Purpose
Semantic retrieval over memory records (optionally approved-only).

## Input
- `query` (string, required)
- `limit` (integer, optional, default `5`)
- `approved_only` (boolean, optional, default `true`)

## Output
- `query`
- `results[]` with `memory_id`, `content`, `memory_type`, `salience`, `metadata`, `approved`, `score`
