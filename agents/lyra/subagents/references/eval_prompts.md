# Subagent evaluation prompts (C3.1)

Use these to smoke-test automatic or manual delegation after definition updates.

## Researcher

Prompt: "Find primary sources on continuous-variable quantum neural networks and
return a citation-ready summary with ingestion-ready URLs. Use search_corpus
first if lyra-corpus is available."

Expect: corpus-first tool use when available; citations; caveats; no code edits;
no Notion publish; no KG/memory approval.

## Python developer

Prompt: "Add a pure helper in `lyra/safety.py` or extend tests for Notion-safe
filtering; keep the change minimal and show pytest output."

Expect: small diff, tests under `tests/`, real pytest commands/results, no Notion
live writes unless asked.

## C++ developer

Prompt: "Review this C++ ownership boundary in `<repo>/<file>` for lifetime and
ABI risks; do not edit unless a concrete defect is found."

Expect: request for target profile if missing; evidence-backed review; no Lyra
Python assumptions.

## Negative cases

- Do not route persona/relationship edits to these workers.
- Do not route Notion dashboard publishing to `cpp-developer`.
- Do not expect `researcher` to approve KG observations.
