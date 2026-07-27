# ADR-001 — n8n as optional capability onboarding plane

**Status:** Accepted  
**Date:** 2026-07-26  
**SRS sections affected:** §2.4, §2.5, IF-1, Appendix B; related: FR-T1–T3 (Telegram may use n8n as an early bridge)

## Context

Lyra's Phase 1 data plane (pgvector, corpus MCP, memory approval) is in place. Christopher already runs Telegram and has n8n experience. Building every integration as first-party Python slows capability growth; n8n workflows are a fast way to onboard glue (notifications, webhooks, SaaS side-effects) without growing Lyra's core.

Risk to avoid: a second brain — n8n must not own persona, memory, or corpus retrieval.

## Decision

1. **Role.** n8n is an optional **automation plane** (workstation or existing host). Lyra remains the owner of identity, memory, and corpus. n8n executes workflows; it does not become the semantic store.
2. **How Lyra calls n8n (tool registration).** Prefer MCP contracts under `mcp/tools/`:
   - **Experiment path:** one generic tool, e.g. `run_n8n_workflow`, with `workflow` (id or alias) + JSON `payload`, POSTing to a webhook (or n8n API) configured via `.env`.
   - **Promote path:** when a workflow proves useful, give it a **named** MCP tool (`notify_telegram`, `create_calendar_hold`, etc.) whose contract documents inputs/outputs and whose implementation is a thin webhook client. Named tools beat a grab-bag for the agent.
3. **How to register a new capability (checklist).**
   1. Build/test the workflow in n8n (Webhook trigger or equivalent).
   2. Store credentials inside n8n; put only webhook URL + shared secret in Lyra `.env`.
   3. Add `mcp/tools/<tool-name>.md` (purpose, input schema, output, failure modes).
   4. Add/extend the MCP server handler to call the webhook.
   5. Add a pytest that mocks the webhook (no live n8n required in CI).
   6. If the workflow touches Notion/Telegram/etc., keep Lyra's FR boundaries (e.g. Notion stays human dashboard; corpus stays pgvector).
4. **Telegram.** Native Bot API remains Phase 2 (FR-T1–T3). Until then, n8n may bridge "notify Christopher" workflows. Replacing the bridge with a first-party bot later does not require changing memory/corpus contracts.
5. **Stack coherence (NFR-8).** n8n appears on the deployment map as optional. No second vector DB, no n8n-owned long-term memory.

## Consequences

- **Positive:** Fast onboarding of integrations via workflows; MCP tool surface stays the single calling convention for agents.
- **Positive:** Keeps A4's stance — MCP tool design remains open and incremental.
- **Negative / watch:** Dual orchestration risk if workflows start summarizing sessions or writing memories. Mitigate by policy: n8n may *call* Lyra MCP write tools only through the same approval rules; it must not bypass `propose_memory` / `approved=false`.
- **Follow-up:** When first live workflow lands, record its tool name and env keys in `mcp/README.md`.

## Alternatives considered

- **All integrations in Python only** — cleaner single runtime, slower capability growth.
- **n8n as primary agent orchestrator** — rejected; conflicts with FR-S6 and persona ownership.
- **Remote n8n cloud only** — allowed later via ADR if needed; default is self-hosted / existing host to match privacy posture (NFR-1).
