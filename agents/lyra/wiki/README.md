# Lyra Reference Wiki Adapter

`catalog.json` is an explicit read-only allowlist over canonical Markdown. It
does not copy page content, accept chat logs, or own memory. The runtime builds
a deterministic in-memory lexical index when `WikiService` starts.

Each page carries its authority bucket, provenance, and content hash. Hash drift
fails validation until a deliberate catalog update. Only Lyra's catalog is
loaded for the Lyra agent; page IDs from another agent are not addressable.

The catalog may point to Lyra-owned references and approved shared location
canon. Tier 0 prompts, live state, ship status, source-material snapshots,
memory/KG records, corpus chunks, secrets, logs, and campaign repositories are
not wiki pages and retain their own routing authorities.
