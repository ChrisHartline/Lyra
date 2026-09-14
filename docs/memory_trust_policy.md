# Natural Memory Trust Policy (W6.1a)

## Why this exists

A blanket approval queue makes ordinary relationship memory feel like database
administration. Unrestricted automatic memory has the opposite failure mode:
transient feelings, professional guesses, secrets, or someone else's private
information can become durable. W6.1a uses separate trust lanes so Lyra can
remember naturally without collapsing those boundaries.

## Default lanes

| Lane | Default | Behavior |
|---|---|---|
| Private/shared | Auto | Stable, low-risk, first-person preferences and relationship context stay local and reversible. |
| Professional/project | Review | Inferred durable work context becomes a batch-review candidate. An explicit “remember that” is approval. |
| Story | Auto | Explicit story continuity stays in the story ledger. |
| Campaign | Auto | Explicit campaign continuity stays in the campaign ledger. |

Each lane can be set locally to `auto`, `review`, or `off`. Policy administration
remains token-authenticated and loopback-only.

## Conversational controls

- `Remember that …` validates and stores the detail as explicitly approved.
- `Don't remember this` suppresses semantic-memory creation for that message.
- `What have you remembered recently?` reports recent automatic/explicit items.
- `Forget what I said about …` identifies a semantic-memory target and asks once
  for confirmation before deletion.
- `That's not quite right` followed by `Correct that to …` replaces the most
  recent attributable semantic memory after revalidation and re-embedding.

These controls affect semantic memory, not the raw session transcript. Removing
or correcting chat history is a separate data-lifecycle operation. They also
cannot mutate knowledge-graph observations.

## Safety and data flow

Secrets, credentials, third-party private details, empty content, mixed-ledger
content, and unsafe corrections fail closed. A transient emotion such as “I'm
stressed” stays conversational unless Christopher explicitly asks Lyra to
remember it; no diagnosis is inferred or stored.

Every automatic/explicit item records session, message, channel, lane, approval
mode, proposal reason, and sensitivity flags. Private/shared memories may be
retrieved into the configured conversation model when relevant, but are excluded
from digest/briefing collection and therefore from Notion publication. They are
not copied to the KG, media/avatar providers, or other integrations.

The authenticated control center remains the transparent fallback: recent
automatic/explicit memories are shown separately, and approved semantic memories
can be corrected or forgotten. Audit entries identify whether the policy or the
user acted and preserve a hash—not forgotten text.
