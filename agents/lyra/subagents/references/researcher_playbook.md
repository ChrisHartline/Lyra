# Researcher playbook

Canonical agent contract: `agents/lyra/subagents/researcher.md`.

## Read first

- Tool policy: `agents/lyra/subagents/references/tools_and_mcp.md`
- Task packet template: `agents/lyra/subagents/references/task_packet.md`
- Corpus contracts: `mcp/tools/search_corpus.md`, `mcp/tools/add_source.md`
- Etiquette (if personal topics appear): `agents/lyra/references/observation_etiquette.md`

## Default research loop

1. Clarify the question and claims that need evidence.
2. Call `search_corpus` first (and `search_memories` only if the packet asks
   for approved biography context).
3. Prefer primary sources (standards, papers, official docs, first-party repos).
4. If corpus misses a key source, list an ingestion-ready URL/path for the
   parent. Do not claim `add_source` succeeded unless you ran it under an
   explicit packet permission.
5. Separate evidence from inference. Note conflicts and gaps.

## Citation shape

For each material claim:

- Claim statement
- Source title
- URL or local path
- Date if known
- Why it supports the claim (one line)

## Handoff to parent

Return:

1. Concise answer
2. Evidence table/list
3. Caveats
4. Ingestion-ready sources not yet in corpus
5. Recommended next step (ingest / Notion research digest / no further action)

The parent owns Notion publishing, approvals, and Lyra's user-facing voice.
