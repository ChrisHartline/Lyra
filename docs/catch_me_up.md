# Catch Me Up (W7.2)

Catch Me Up is an explicit, read-only re-engagement view inside Lyra's normal
web and Telegram conversations. It answers requests such as:

- `Catch me up`
- `Catch me up since yesterday`
- `Catch me up for the last 3 days`
- `Catch me up since Friday in detail`
- `/catchup since 2026-09-10 concise`

The default window is the previous 24 hours. Supported boundaries are today,
yesterday, the last N hours/days/weeks, weekday names, and ISO dates or
timestamps. Ambiguous boundaries are rejected with examples rather than guessed.
Concise mode returns at most eight merged changes; deep mode returns at most 30
and displays each event timestamp.

Eligible local sources are named session activity, confirmed commitments, and
approved memories in the conversation's requested ledger. Configured Notion
project and digest databases contribute visible page-title changes. Every
factual line ends with citations containing its plane, stable ID or URL, and
source timestamp. Duplicate descriptions merge into one event while preserving
all citations.

Notion failures are non-fatal. An unconfigured reader is labeled `unavailable`,
a failed query is labeled `inaccessible`, and a configured plane whose newest
visible edit is older than 30 days is labeled `stale`. Lyra does not infer any
missing external changes.

The command bypasses the conversational model so its boundary and citations
remain deterministic. It does not write to memory, the knowledge graph,
commitments, corpus, or Notion. The user request and visible response remain in
ordinary session history so the recap follows the same web/Telegram handoff as
the rest of the conversation.

Sessions explicitly authorized for private shared journal retrieval are excluded
from Catch Me Up entirely. This prevents journal-influenced conversation from
leaking into an ordinary or professional recap.
