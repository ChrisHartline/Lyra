# Ship Continuity and Ambient Developments (W8.3)

Ship continuity lets Lyra report the ship's established condition and introduce
occasional atmosphere without silently rewriting canon. It is restricted to
story-scoped web sessions and is disabled and paused by default.

## Behavior

- **Status briefs** respond only to an explicit ship-status request in a
  `story` session. They are grounded in `ship/current_status.json` and approved
  files under `state/story/`. Runtime guidance forbids lookup narration,
  invented repairs, discoveries, movement, or status changes while preserving
  Lyra's in-fiction technical register.
- **Ambient beats** are optional proactive messages grounded in the same source
  set. `quiet`, `balanced`, and `vivid` change descriptive density, not canon.
  Every beat is recorded as `ephemeral_noncanonical` with source references and
  a content hash; the narrative itself remains in ordinary session history.
- **Canon proposals** are explicit local-control submissions. They enter the
  existing memory-control plane as pending `story` proposals. Approval writes
  the approved memory and regenerates `state/story/`; it never edits
  `ship/current_status.json` directly.

General, professional, private-shared, campaign, and Telegram-bound sessions
cannot be selected. Ship continuity writes nothing to biography memory, the
knowledge graph, corpus, commitments, shared journal, relationship state,
campaign state, Notion, or Tier 0 persona files.

## Delivery and controls

Ambient delivery uses Away Mode category `status`, so quiet hours and daily
notification budgets can batch or suppress it. Policy contains independent
master, pause, brief, and ambient switches plus intensity, cadence, local time,
timezone, and one explicit story-session target.

All mutation and preview controls require the loopback-only
`X-Lyra-Control-Token` boundary:

- `GET|PUT /api/control/ship-continuity` — inspect events or update policy.
- `GET /api/control/ship-continuity/preview` — preview an ambient beat without
  delivering or consuming it.
- `POST /api/control/ship-continuity/proposals` — create a pending story-canon
  proposal from a story session.
- `POST /api/control/ship-continuity/proposals/{id}/approve` — explicitly
  approve that ship-continuity proposal and regenerate readable story canon.

Recommended activation is incremental: select a story session, enable briefs
while remaining paused from ambient delivery, validate a direct status response,
then unpause ambient delivery at `quiet` intensity if desired.
