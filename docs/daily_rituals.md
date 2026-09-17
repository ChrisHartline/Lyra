# Morning and Evening Rituals (W7.1)

Rituals are optional, calm orientation points—not a second task manager. Morning
offers a small view of what is active; evening offers a close/carry/release
reflection. Both default disabled and can be configured independently.

Each line identifies its source plane: `commitment`, `session`, `digest`,
`observation`, or `memory`. Only confirmed commitments and approved memory data
are eligible. Private/shared memory is available to normal conversation but is
excluded from ritual briefing collection and Notion publication.

Local token-authenticated controls expose policy, preview, skip, and snooze at
`/api/control/rituals`. Settings include morning/evening times, IANA timezone,
web or Telegram channel, optional Notion publication, and vacation-through date.
Disable both rituals to stop them without changing conversation or memory.

Delivery uses Away Mode category `digest`. Quiet hours batch it; an exhausted
daily budget suppresses it. A unique ritual/date record prevents duplicates and
records planned, delivered, skipped, batched, suppressed, or failed status while
retaining only a content hash. The delivered message itself lives in the shared
session history.

Optional Notion publication deliberately uses the smaller Notion-safe briefing,
not the richer local/Telegram ritual text.

Private shared journal entries and journal-authorized session names are excluded
from morning/evening source collection. Journal continuity is available only in
the private session where it was explicitly enabled.

Scoped text-to-speech is now planned at W9.5a. It may later be separately enabled
for rituals, but W7.1 remains text-authoritative and does not activate voice.
