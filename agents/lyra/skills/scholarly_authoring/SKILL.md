---
name: scholarly-authoring
description: Draft, revise, validate, and package academic and professional research documents, including IEEE papers, ACM papers, arXiv drafts, whitepapers, modeling and simulation reports, financial modeling papers, quantum AI papers, and Overleaf-ready LaTeX projects.
disable-model-invocation: true
---

# Scholarly Authoring Skill

## Purpose

Create rigorous academic and technical writing artifacts from user-provided source material, notes, experiments, datasets, verified references, and project requirements.

## Scope

- IEEE, ACM, arXiv, whitepaper, and technical report drafting
- Outline design, claim-evidence mapping, and section planning
- Citation-aware writing with explicit evidence boundaries
- Packaging for Overleaf and publication-style handoff

## Core Rule

Assist the author. Do not fabricate research.

Never invent:

- citations
- sources
- datasets
- experimental results
- model performance metrics
- quotations
- page numbers
- institutional claims

When information is missing, insert a clear `TODO:` marker in the generated document.

## Supported Output Profiles

Use the relevant profile based on the user's target format:

- IEEE paper
- ACM paper
- arXiv preprint
- academic course paper
- modeling and simulation report
- financial modeling whitepaper
- quantum computing / AI manuscript
- technical research note

## Standard Publication Workspace

Create generated work under:

```text
publications/<project-slug>/
├── main.tex
├── references.bib
├── figures/
├── tables/
├── notes/
│   ├── claim-evidence-map.md
│   ├── review-report.md
│   └── todo.md
└── README.md
```

## Workflow

1. Intake requirements.
2. Identify document profile.
3. Build claim-evidence map.
4. Draft outline.
5. Draft document body.
6. Insert citations from verified metadata only.
7. Request or create figure/table plan.
8. Validate formatting, citations, and TODO markers.
9. Package for Overleaf or the requested target.

## Default Output Shape

1. Assumptions and requested target format
2. Claim-evidence map (including unresolved TODOs)
3. Draft or revision output
4. Integrity and format validation report
5. Next edits required for publication readiness

## Intake Checklist

Ask for or infer when possible:

- target venue or format
- audience
- page limit
- citation style
- source material
- datasets or experiments
- desired contribution
- deadline constraints
- required sections
- forbidden topics or claims

## Claim-Evidence Map

Before drafting, create a compact map:

```text
Claim | Evidence Source | Citation Key | Confidence | TODO
```

Claims without evidence must be marked as provisional.

## IEEE Default Structure

For IEEE-style work, prefer:

```latex
\section{Introduction}
\section{Background and Related Work}
\section{Problem Statement}
\section{System Architecture}
\section{Methodology}
\section{Implementation}
\section{Evaluation}
\section{Discussion}
\section{Limitations and Future Work}
\section{Conclusion}
```

For short conference papers, merge or remove sections as needed.

## Required Quality Checks

Before finalizing, produce `notes/review-report.md` covering:

- missing evidence
- unsupported claims
- citation coverage
- figure/table completeness
- IEEE or target-format issues
- clarity and contribution
- academic integrity risks

## Guardrails

- Never fabricate evidence, citations, or quantitative outcomes.
- Mark unknowns with explicit `TODO:` placeholders.
- Keep claims proportional to verified evidence only.

## Related Subagents

Use these subagent instructions when useful:

- `subagents/outline-agent.md`
- `subagents/citation-agent.md`
- `subagents/figure-agent.md`
- `subagents/table-agent.md`
- `subagents/reviewer-agent.md`
