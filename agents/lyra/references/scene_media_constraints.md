---
reference_id: constraints.scene_media
canon_status: operational_reference
source_ids: gate.w9_4
owner: agents/lyra/references
last_reviewed: 2026-09-24
---

# Scene Media Constraints

Scene media is an optional presentation layer, never evidence that an event
happened. Generated stills and storyboards remain non-canonical until an
explicit canon workflow approves an underlying fact; the image itself does not
rewrite persona, relationship, ship, story, campaign, memory, KG, or corpus
state.

The scene director defaults disabled. Automatic triggers require a separate
opt-in and remain subject to deduplication, cooldown, and daily limits. Text is
authoritative and must be delivered before rendering. A failed or unavailable
renderer leaves the complete text response intact.

Renderer input is limited to the sensitivity-filtered current request and
response plus approved canonical references. It excludes prior chat history,
secrets, private journal material, unrelated memories, KG observations, and
corpus passages. Source images may leave the workstation only when the visual
catalog explicitly clears them for external rendering; the current catalog
clears none.

Generated files and prompt/provider/model/source-asset provenance remain local.
Deleting media must not alter conversation history, and deletion retains only
the non-content identifiers needed to preserve deduplication and rate limits.

Operational controls, event behavior, and validation commands live in
`docs/scene_direction.md`.
