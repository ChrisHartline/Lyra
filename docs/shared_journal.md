# Private Shared Journal (W8.1)

The private shared journal preserves explicitly chosen relationship moments,
reflections, and milestones without turning ordinary conversation into an
automatic diary. It is a separate local PostgreSQL plane, not semantic memory,
the knowledge graph, story canon, a campaign ledger, or a Notion database.

## Approval and content boundaries

Entries can be created only through the loopback, token-authenticated control
API. Every create request must contain `approved: true`; there is no observer,
scheduler, model tool, Telegram command, or automatic memory policy that creates
an entry. An entry may optionally cite an existing visible session message; the
session/message relationship and source channel are validated before storage.

Content and titles pass the existing never-persist filter. Credentials, secrets,
private third-party material, and story/campaign content are rejected. Journal
creation does not write to semantic memory, KG, corpus, commitments, Notion, or
notification state.

## Private-session retrieval

A journal entry is not included in normal runtime context. A local control must
explicitly authorize a named session for `private_shared` access. Only then does
the context builder add up to five recent approved journal entries with stable
journal IDs. Runtime excerpts are capped at 1,200 characters per entry and
marked when truncated; the full local entry remains available through control.

Journal-authorized sessions are excluded from Catch Me Up, Research Garden
question mining, and morning/evening recent-session lists. A private session
cannot be bound to Telegram; a Telegram-bound session cannot be authorized as a
private journal session. Both operations lock the session row, preventing a
concurrent handoff from bypassing the boundary. Revoking access removes journal
context on the next turn but does not delete entries.

## Edit, forget, and audit

Editing re-runs the same content filters. Confirmed forget permanently deletes
the journal entry. The append-only audit table records entry ID, action, actor,
time, optional safe reason, and old/new SHA-256 hashes. It never retains replaced
or forgotten text.

The workstation-local endpoints are:

- `GET /api/control/shared-journal` — list entries.
- `POST /api/control/shared-journal` — create an explicitly approved entry.
- `PATCH /api/control/shared-journal/{entry_id}` — edit content/title.
- `POST /api/control/shared-journal/{entry_id}/forget` — confirmed deletion.
- `GET /api/control/shared-journal/audit` — inspect hash-only history.
- `GET|PUT /api/control/shared-journal/sessions/{session_id}` — inspect or change
  private-session access.

All routes require `X-Lyra-Control-Token` and reject non-loopback, forwarded, and
Tailscale-proxied callers. There is intentionally no Telegram mutation path and
no automatic publication path.
