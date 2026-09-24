# Tool: wiki_read

## Purpose

Read one exact page from the active agent's wiki allowlist by stable page ID.
Call `wiki_search` first when the page ID is unknown.

## Input

- `page_id` (string, required)

## Output

Bounded Markdown content plus page ID, agent ID, bucket, provenance, content
hash, authority, epistemic status, and truncation flag.

## Failure behavior

Unknown and cross-agent page IDs fail closed. Filesystem paths are never tool
inputs, so callers cannot traverse into Tier 0, state, secrets, or source
material.
