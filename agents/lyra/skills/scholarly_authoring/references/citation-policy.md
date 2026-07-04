# Citation Policy

## Rules

- Use only verified citation metadata from the user, corpus, DOI lookup, trusted source, or existing `library.bib`.
- Never invent BibTeX entries.
- Never cite an agent-generated summary as if it were a primary source.
- Prefer canonical sources over summaries.
- Keep generated drafts separate from source material.

## Citation Confidence

Use these states:

- `verified`: metadata checked or user-provided
- `partial`: citation has missing fields
- `needed`: a source is needed but not available
- `do-not-use`: source seems unreliable or generated

## TODO Pattern

Use comments like:

```latex
% TODO: Add verified citation for transformer memory claim.
```
