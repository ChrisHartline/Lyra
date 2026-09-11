# Commitment Radar

Commitment Radar notices possible first-person promises, deadlines, follow-ups,
tasks, and unresolved decisions while keeping Christopher in control.

## Offer before persistence

A message such as “I need to review the draft by Friday” creates an operational
offer linked to that session message. The offer is not an active commitment and
cannot generate a reminder. Lyra receives an instruction to ask one concise
question about whether Christopher wants it tracked.

A later explicit reply such as “Yes, track it” promotes the outstanding offer
for that session to an active commitment. “No thanks” dismisses it. An unrelated
reply neither confirms nor dismisses the offer.

Only one outstanding offer is considered per session, avoiding ambiguous yes/no
confirmation. Local API confirmation is also an explicit action.

## Conservative detection

The first implementation intentionally favors precision over recall. It looks
for first-person intent such as `I'll`, `I will`, `I need to`, `I have to`,
`I should`, `I must`, or `remind me to`. It recognizes ISO dates, `tomorrow`,
and named weekdays. ISO dates and weekdays default to 5:00 PM in the configured
local timezone; `tomorrow` defaults to 9:00 AM.

It does not use a model to infer hidden obligations. Story/campaign context,
mixed ledgers, secrets, and third-party personal detail fail closed before an
offer is written.

## Lifecycle

Durable states are:

- `active`: eligible for a reminder when it has a recognized due time.
- `done`: complete and never reminded.
- `snoozed`: paused until explicitly reactivated; requires a future wake time
  and is never reminded while snoozed.
- `dropped`: intentionally abandoned and never reminded.

Every commitment retains its offer and source link: session/message IDs or an
explicitly approved dashboard URL. No commitment automatically writes to
Notion, semantic memory, or the knowledge graph.

## API

The channel-neutral JSON surface supports:

```text
GET   /api/commitment-offers?status=offered&session_id=<uuid>
POST  /api/commitment-offers/<offer-id>/confirm
POST  /api/commitment-offers/<offer-id>/dismiss
GET   /api/commitments?status=active
GET   /api/commitments/<commitment-id>
PATCH /api/commitments/<commitment-id>
POST  /api/commitment-reminders/plan
```

Example state change:

```json
{
  "status": "snoozed",
  "snoozed_until": "2026-09-12T14:00:00-05:00"
}
```

Reminder planning calls the existing Away Mode policy with category
`commitment`. Its result is `send`, `batch`, or `suppress`; the reason records
quiet hours, budget exhaustion, or the applicable normal-delivery rule.

Confirmation, dismissal, lifecycle changes, and reminder planning are
workstation-local mutations. Tailscale/proxied clients may inspect the
conversation-facing read models, but cannot invoke those state changes.
