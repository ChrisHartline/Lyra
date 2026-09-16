# Research Garden (W7.3)

Research Garden is an optional, quiet resurfacing loop. It notices evidence-backed
connections among saved research sources, old unanswered questions, and confirmed
active commitments. It does not invent a task or ask the conversational model to
guess at a relationship.

The feature defaults disabled. Its persisted policy selects web or Telegram,
an interval from 1 to 720 hours, a dormant-question age from 1 to 365 days, and
one to ten suggestions per run. A dormant question must be a visible user message
containing a question mark in a session that has also been inactive for the
configured period.

Candidate matching is deterministic. Two evidence records must share either two
meaningful terms or one term of at least seven characters. Each suggestion stores
the two source-plane identifiers and timestamps, a stable fingerprint, its topic,
and delivery state. Existing fingerprints prevent repeat suggestions. Superseded
sources, non-active commitments, story/campaign questions, and text rejected by
the never-persist filter do not participate.

Delivery enters ordinary shared session history and labels every citation as
`source`, `question`, or `commitment`. It explicitly says that the connections are
not new commitments. Away Mode handles the delivery as non-urgent `research`:
quiet hours batch it and an exhausted daily budget suppresses it.

Workstation-local, token-authenticated controls live under
`/api/control/research-garden`:

- `GET` returns policy, suggestion history, and active topic mutes.
- `PUT` updates enablement, channel, interval, dormant age, and result limit.
- `GET /preview` performs read-only discovery without scheduling a notification.
- `POST /mutes` and `DELETE /mutes/{topic}` manage optional-expiry topic mutes.
- `POST /{suggestion_id}/dismiss` dismisses a suggestion.
- `GET /{suggestion_id}/draft` creates a local, unpublished digest draft.

These controls reject tailnet/proxied callers even when they present the local
control token. The scheduler and draft path do not write to Notion, semantic
memory, the knowledge graph, the corpus, or commitment state. Any later promotion
or publication must use that destination's existing explicit approval path.
