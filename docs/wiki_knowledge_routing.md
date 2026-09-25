# W9.3 Agent Wiki and Knowledge Routing

**Status:** Gate passed on 2026-09-24.

## Outcome

Lyra now has a local, read-only Markdown wiki adapter over ten explicitly
allowlisted canonical pages. The adapter does not copy those pages into a new
store. It verifies their SHA-256 hashes, builds an in-memory lexical index, and
returns bounded content with page, bucket, provenance, authority, and
epistemic-status metadata.

The active catalog is `agents/lyra/wiki/catalog.json`. It exposes approved
backstory topics, the stable location gazetteer, a concise expertise-domain
index, and the W9.4 scene-media creative constraints. Tier 0 prompts,
source-material snapshots, ship/live state, relationship
or story state, chat logs, memory/KG records, corpus chunks, secrets, and other
agents' files are outside the allowlist.

## Tool contracts

- `wiki_search` performs deterministic lexical retrieval with an optional
  `lore`, `place`, `expertise`, `creative_constraint`, `terminology`, or
  `person` filter.
- `wiki_read` accepts only a stable page ID from Lyra's catalog. It never
  accepts a filesystem path.
- `knowledge_route` returns the authority, read tools, durable-write boundary,
  and epistemic status for a declared information class.

Every wiki result is labeled `reference_not_lived_memory` and carries the
instruction that it cannot be presented as a remembered interaction or an
invented anecdote. The same rule is appended to the conversation runtime as
operational retrieval policy; Tier 0 itself remains unchanged.

## Authority routing

| Information class | Authority | Read path | Durable-write boundary |
|---|---|---|---|
| Stable persona and relationship contract | Tier 0 `personality/` | startup context | Christopher hand-edit only |
| Standing lore, places, expertise, constraints | Reference wiki | `wiki_search`, `wiki_read` | reviewed Git edit only |
| Research sources | Corpus | `search_corpus` | explicit source ingestion |
| Approved structured observations | Local KG | `search_nodes`, `open_nodes`, `read_graph` | propose, then human approval |
| Approved episodes/recollections | Semantic memory | `search_memories` with an explicit ledger | approved memory flow |
| Ship definition and live condition | `ship/` | ship continuity context | ship continuity approval flow |
| Evolving Lyra/Christopher story | `state/story/` | story continuity context | approved story-memory regeneration |
| Campaign state | Named VTT/campaign repository | campaign-specific integration | campaign workflow only |

Retrieval never moves content between these planes. In particular, opening a
wiki page cannot create memory, a KG observation, a corpus record, or canon.

## Isolation and failure behavior

Catalog validation fails on duplicate/invalid page IDs, unknown buckets,
missing provenance, automatic chat ingestion, chat/session provenance, unsafe
or cross-owner paths, source-material exposure, missing files, content-hash
drift, or a mismatched agent ID. Runtime reads fail closed for unknown and
cross-agent page IDs.

The wiki is registered as its own local `lyra-wiki` MCP server and through the
conversation runtime's fixed read-only tool registry. It exposes no add,
update, delete, import, approve, or filesystem operation.

## Retrieval decision

The catalog currently contains ten short pages, so deterministic lexical
retrieval is transparent, fast, and sufficient. W9.3 does not add embeddings
or a second pgvector index. An optional semantic path should be considered only
after page-count growth and a fixed retrieval evaluation demonstrate misses;
if needed, it should reuse the corpus embedding infrastructure without turning
the wiki into a corpus database.

## Validation

Run:

```powershell
.\venv\Scripts\python.exe scripts\validate_wiki.py
.\venv\Scripts\python.exe -m pytest -q tests\test_wiki.py
```

The focused acceptance suite covers catalog integrity, deterministic and
bucketed search, exact reads, missing/cross-agent page handling, authority
routing, runtime-tool registration, no-chat-ingest guarantees, and prompt/path
leakage resistance.

Final evidence on 2026-09-24: wiki validator `VALID` (9 pages; lexical;
read-only); focused wiki/runtime/pack/backstory gate `35 passed`; expanded
wiki/runtime/web/docs/backstory integration gate `43 passed`; full repository
JUnit suite `200 passed`, 0 failures, 0 errors, 0 skipped (72.492 seconds).
Compileall, documentation freshness, build-plan validation, backstory
validation, and diff checks passed.

Post-gate catalog update on 2026-09-24: W9.4 added
`constraints.scene_media` as the tenth allowlisted page. It summarizes durable
generation, privacy, canon, failure, and deletion constraints while linking to
the operational runbook rather than copying implementation detail. Wiki
validator -> `VALID` (10 pages; lexical; read-only); combined wiki/scene/docs
gate -> `17 passed`.
