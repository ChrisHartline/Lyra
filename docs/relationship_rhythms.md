# Relationship Rhythms and Milestones (W8.2)

Relationship rhythms let Lyra acknowledge approved shared continuity without
turning ordinary conversation into automatic memory or rewriting her persona.
The capability is local, private-session-only, and disabled by default.

## Three independent behaviors

- **Callbacks** offer at most one relevant approved source per source/day to the
  conversational model. Deterministic word overlap provides relevance; the model
  is told to use the callback only when it fits naturally.
- **Recurring check-ins** offer a quiet relationship check-in at the selected
  local time and cadence.
- **Milestone acknowledgements** acknowledge each approved relationship-state or
  shared-journal milestone once.

The master switch and each behavior switch are independent. Proactive check-ins
and milestones additionally require one selected session that has already been
authorized for the private shared journal. Telegram-bound sessions cannot be
authorized or selected. Callbacks likewise run only during private web turns.
Regardless of scheduler frequency, at most one proactive relationship message
is handled per local day.

## Sources and correction

The only sources are tracked `state/relationship.json`, the `Milestones` section
of `state/relationship.md`, and active entries from the explicitly approved
private shared journal. Stable source references accompany callback guidance and
delivered-message metadata. A journal correction is made through the journal's
audited edit control; a relationship-state correction is a deliberate source
file edit. W8.2 never edits either source.

Any source can be muted immediately and unmuted later. The mute table stores the
source key plus a label hash, not the source text. The event ledger stores event
type, status, target, source references, timestamps, and a content SHA-256—never
a second copy of the relationship narrative. The actual generated or
deterministic message remains only in the private session history.

## Delivery and separation

Proactive messages use Away Mode category `social`, so quiet hours and the daily
budget can batch or suppress them. The Away Mode notification record receives an
opaque relationship/event/hash marker rather than private wording. Delivery is
web-only and goes only to the locally selected private session.

Relationship rhythms do not create journal entries, semantic memories, KG
observations, corpus sources, commitments, story/campaign state, Notion content,
professional artifacts, digest inputs, or media prompts. They do not change
Tier 0 personality files or advance relationship state.

## Local controls

All controls require `X-Lyra-Control-Token`, reject non-loopback and proxied
callers, and are intentionally unavailable from Telegram:

- `GET|PUT /api/control/relationship-rhythms` — inspect policy/events/mutes or
  update the master, callback, check-in, milestone, cadence, time, timezone, and
  target-session settings.
- `GET /api/control/relationship-rhythms/preview` — preview the next currently
  available check-in or milestone without delivering or consuming it.
- `POST /api/control/relationship-rhythms/mutes` — mute a source by stable key.
- `DELETE /api/control/relationship-rhythms/mutes/{source_key}` — unmute it.
- `POST /api/control/relationship-rhythms/events/{event_id}/dismiss` — dismiss an
  operational event.

Recommended activation is incremental: authorize a dedicated private web
session, enable the master switch plus callbacks, validate a natural callback,
then optionally enable milestones and recurring check-ins. Christopher's lived
interaction sign-off is the final W8.2 acceptance step.
