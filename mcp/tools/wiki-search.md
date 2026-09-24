# Tool: wiki_search

## Purpose

Deterministic lexical search over the active agent's allowlisted standing
reference pages. It does not search chat logs, memories, corpus chunks, live
state, Tier 0 prompts, or another agent's pages.

## Input

- `query` (string, required; 1-500 characters)
- `limit` (integer, optional; 1-10, default `5`)
- `bucket` (optional): `lore`, `place`, `expertise`, `creative_constraint`,
  `terminology`, or `person`

## Output

Results include `page_id`, title, bucket, bounded excerpt, lexical score, local
path, provenance, SHA-256, authority, and the explicit
`reference_not_lived_memory` epistemic status.

## Authority

Read-only. Retrieval never writes or promotes content. A result is standing
reference material and must not be narrated as Lyra remembering an interaction.
