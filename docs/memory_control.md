# Memory and Observation Control

W6.1 provides a loopback-only, token-authenticated review surface at
`http://127.0.0.1:8765/control`. It governs both semantic memories in
PostgreSQL and structured observations promoted to the local knowledge graph.
The control center remains workstation-local. W6.1a additionally permits a
narrow set of semantic-memory commands in ordinary allowlisted conversation;
it does not expose KG, policy, filesystem, Git, Notion, or general tool authority.

See [memory trust policy](memory_trust_policy.md) for the rationale, lanes, and
natural-language behavior.

## Configure access

Generate a dedicated secret in `.env` without printing it:

```powershell
.\venv\Scripts\python.exe scripts\configure_control_token.py
```

Restart Lyra, open `/control`, and paste the local value of
`LYRA_CONTROL_TOKEN`. The page retains it only in browser `sessionStorage`, so
closing the tab clears it. Missing credentials fail closed; incorrect values
receive no proposal data.

## Review behavior

- **Approve** makes a semantic memory retrievable or promotes an observation
  into the KG.
- **Correct** applies to pending and approved semantic memories, re-runs the
  never-persist and bucket rules, and creates a fresh embedding. KG correction
  remains in the local review flow.
- **Reject** deletes the candidate and never writes a retrievable fact.
- **Forget** is approved-only, requires confirmation, and removes both the
  proposal row and a promoted KG observation when applicable.
- **Audit** records actor, destination, action, reason, timestamps, and content
  hashes. Rejected or forgotten text is not copied into the audit record.
- **Recently remembered** distinguishes automatic and explicit conversational
  memory from review candidates and retains correction/forget controls.

## Clara/Rhea wiki-memory imports

Treat exports as source material, not trusted memory. A future importer should
stage them locally with file/hash provenance and classify each item:

| Material | Destination |
|---|---|
| A specific lived interaction or autobiographical context | Biography memory proposal |
| A structured fact about a person, project, habit, or commitment | KG observation proposal |
| Stable people/place/lore/expertise pages | Agent wiki (`FR-P7`, W9.3) |
| Lyra/ship story continuity | Story bucket and canonical story references |
| Campaign events | Campaign bucket only |

This is deliberately not “upload the wiki into memory.” Larger reference pages
should remain readable, attributable documents; only small facts that benefit
from semantic recall should become individually reviewable memory proposals.
