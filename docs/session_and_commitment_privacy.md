# Session and Commitment Privacy

Lyra uses session purpose and inherited commitment visibility to keep one
continuous assistant from accidentally carrying private relationship context
into professional or proactive surfaces. This is a routing boundary, not a new
approval queue.

## Session purposes

- `general` — daily planning and mixed personal/professional coordination. A
  **Command Deck** session should use this scope.
- `professional` — a bounded class, client, research, or engineering project.
- `story` and `campaign` — fictional continuity. These sessions cannot generate
  real-world Commitment Radar candidates.

Private shared access remains a separately authorized property. A private
shared session is not merely a `general` session with a different label: it has
access to the shared journal, cannot bind to Telegram, and gives its commitments
the `private_shared` visibility scope.

## Visibility inheritance

Commitment Radar assigns visibility from provenance:

| Origin | Visibility | Cross-session behavior |
| --- | --- | --- |
| General session | `general` | Eligible for daily operational surfaces |
| Professional session | `professional` | Eligible for professional/daily operational surfaces |
| Approved dashboard item | `professional` | Eligible for professional/daily operational surfaces |
| Authorized private shared session | `private_shared` | Confined to its private context by default |
| Story or campaign session | none | No real-world candidate is created |

Private commitments are excluded from the general commitment API, proactive
reminders, morning/evening rituals, Catch Me Up, and Research Garden. They are
not silently copied to Notion, briefs, or professional outputs. A local control
operation may deliberately correct an exceptional commitment's visibility.

## Daily ritual targeting

Telegram rituals continue to target the configured allowlisted private chat.
Web rituals require a specific `target_session_id`; there is no "most recent
session" fallback. The target must exist, have `general` or `professional`
purpose, not be private-shared, and not be Telegram-bound. A deleted or newly
ineligible target produces `no_target` and no delivery.

Recommended setup:

1. Create a `general` session named **Command Deck**.
2. Select it as the web ritual target from the local control boundary.
3. Enable morning and/or evening delivery only after the target is accepted.

Manual daily planning remains available in Command Deck whether scheduled
rituals are enabled or not.

## Local controls

- `PUT /api/control/sessions/{session_id}/context-scope`
- `PUT /api/control/commitments/{commitment_id}/visibility`
- `PUT /api/control/rituals` with `target_session_id`

These changes require the existing loopback control authorization. Remote
conversation clients can read only the non-private global commitment view and
cannot change routing policy.
