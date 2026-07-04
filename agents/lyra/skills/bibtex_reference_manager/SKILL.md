---
name: bibtex-reference-manager
description: Manage verified BibTeX references, citation keys, source metadata, citation TODOs, and bibliography hygiene for academic papers, IEEE manuscripts, LaTeX projects, and research writing workflows.
disable-model-invocation: true
---

# BibTeX Reference Manager Skill

## Purpose

Maintain clean, verified, reusable citation metadata for research and publication workflows.

## Scope

- BibTeX library maintenance and normalization
- Citation key convention enforcement
- Missing metadata detection and TODO tracking
- Citation hygiene for drafts and publication packages

## Hard Rules

- Do not invent BibTeX entries.
- Do not cite generated summaries as primary sources.
- Preserve canonical source metadata.
- Mark missing metadata explicitly.

## Standard Files

```text
citations/
├── library.bib
├── tags.yaml
└── annotations/
```

## Workflow

1. Read existing `library.bib`.
2. Identify citation needs from the draft.
3. Match known sources.
4. Add verified entries only.
5. Report missing references.
6. Normalize citation keys.

## Default Output Shape

1. Existing library status
2. Added or updated entries
3. Missing metadata and unresolved citations
4. Normalization decisions and key changes
5. Final bibliography hygiene checklist

## Citation Key Pattern

Prefer:

```text
lastnameYYYYshorttitle
```

Example:

```text
vaswani2017attention
```

## Guardrails

- Never invent or infer citation metadata without source confirmation.
- Preserve canonical bibliographic fields when conflicts exist.
- Report unresolved references explicitly instead of guessing.
