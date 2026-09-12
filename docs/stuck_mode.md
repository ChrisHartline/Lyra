# Stuck Mode

Stuck Mode gives Christopher a deliberate way to change how Lyra helps when
progress has stalled. It is conversation-scoped support, not a diagnosis or a
memory system.

## Entering

An explicit first-person request such as `I'm stuck` always gets through,
including during a cooldown. Lyra asks one concise question that offers:

- technical diagnosis;
- task decomposition;
- decision support;
- a stress check-in; or
- simple companionship.

Christopher may choose `light`, `standard`, or `deep` help. If he confirms
without choosing a depth, Stuck Mode uses `standard`. A request that already
contains both choices, such as `I'm stuck debugging this; go deep`, activates
immediately.

Conservative first-person phrases such as `This still isn't working`, `I can't
decide`, or `I don't know where to start` may cause an observational offer.
They never silently activate Stuck Mode.

## Dismissal and completion

`Not now`, `no thanks`, `drop it`, and equivalent replies dismiss an offer or
active interaction immediately. Observational offers are then suppressed for
24 hours by default. A new explicit `I'm stuck` request overrides that
cooldown.

`I'm unstuck`, `got it`, `I'm good now`, and equivalent replies resolve an
active interaction. Mode and depth can be changed conversationally while it is
active.

## Privacy and reality boundary

The `stuck_interactions` table stores only operational state:

- interaction, session, and trigger-message identifiers;
- whether entry was explicit or observational;
- suggested and selected support modes;
- depth, status, timestamps, and cooldown expiry.

It has no field for raw trigger text, inferred emotion, or diagnosis. Stuck
Mode never writes semantic memory, KG observations, commitments, or Notion
items. Those remain independent, approval-gated flows.

In story or campaign context, only a technical struggle can invoke Stuck Mode.
The runtime instructs Lyra to preserve the active scene and blend the shift to
technical-partner register into her in-character response. Non-technical
fictional distress is not interpreted as Christopher's real-world state.

## Read-only status

The channel-neutral endpoint returns the latest interaction without exposing
raw conversation text:

```text
GET /api/stuck-mode/<session-id>
```

Selection, dismissal, completion, and explicit entry happen through the shared
conversation, so web and Telegram retain one behavioral contract.
