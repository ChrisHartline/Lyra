# ADR-004 — Standalone runtime boundaries

**Status:** Accepted
**Date:** 2026-09-01
**SRS sections affected:** §1, §2.2–2.5, FR-S6, FR-M1–M4, FR-T1–T3,
NFR-1–NFR-3, NFR-8, IF-1–IF-2; related Build Waves W4–W6

## Context

Lyra v1 relies on Cursor or another coding host for the model loop, session
context, tool execution, and subagent execution. The completed data, memory,
assistant, and pack gates are host-neutral enough to support a dedicated v2
application, but the SRS does not yet define that application's trust boundary
or session store.

Christopher needs one persistent conversational Lyra across desktop web and
Telegram. He also wants Lyra to collaborate on repositories without granting a
chat message general control of the workstation. Raw conversation history must
remain resumable without becoming approved semantic memory by accident.

## Decision

1. Lyra v2 is a native Python application service on the workstation. It owns
   the conversational model loop, context assembly, MCP clients, session
   history, and channel adapters.
2. The local web application listens only on `127.0.0.1`. Telegram is the first
   mobile channel. Private Tailscale access is an optional, separately gated
   deployment change; public exposure is not authorized.
3. Named raw chat sessions are stored in relational tables in Lyra's existing
   PostgreSQL database until Christopher deletes them. They are operational
   session state, not corpus documents, vector memories, KG observations, or
   story/campaign canon.
4. Raw turns are never automatically copied into another persistence plane.
   Summaries, memories, and observations continue through their existing
   classification, never-persist, and approval gates.
5. The conversational runtime receives only explicitly allowlisted MCP tools.
   It receives no general shell, filesystem-write, Git, or desktop-control
   capability.
6. Repository work is a separate approved workflow. A coding engine runs in an
   isolated repository workspace and receives no GitHub publication credential.
   Publication is a second human-approved action and stops at a draft pull
   request. The first engine is replaceable behind a host-neutral contract.
7. Grok remains the primary persona model. Structured specialist work may use
   Claude through the provider abstraction. Model selection and secrets remain
   runtime configuration, not persona data.

## Consequences

- The deployment map gains a Lyra application service but no new database or
  public hosting surface.
- Session backup/restore becomes part of NFR-9 coverage.
- Web and Telegram can resume the same named sessions while remaining separate
  from approved long-term memory.
- Coding autonomy can grow behind explicit job and publication approvals
  without weakening the conversational tool boundary.
- Tailscale, GitHub contribution, and campaign integration remain later gates;
  this ADR defines their boundaries but does not install or authorize them.

## Alternatives considered

- **Keep raw turns only in memory** — rejected because service restart and
  cross-channel use would break conversational continuity.
- **Give conversational Lyra desktop tools** — rejected because prompt content
  would gain authority unrelated to ordinary conversation.
- **Make the coding host the user-facing persona** — rejected because Lyra owns
  the relationship and final response; coding engines are replaceable workers.
- **Expose the web service to the LAN or public internet** — rejected pending a
  separate authenticated deployment decision.
