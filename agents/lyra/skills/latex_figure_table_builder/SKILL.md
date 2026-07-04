---
name: latex-figure-table-builder
description: Plan, generate, validate, and insert LaTeX-compatible figures and tables for academic papers, IEEE manuscripts, technical reports, simulations, financial modeling papers, and ML/AI research documents.
disable-model-invocation: true
---

# LaTeX Figure and Table Builder Skill

## Purpose

Create publication-ready figures and tables from verified data, user-provided diagrams, or conceptual specifications.

## Scope

- Figure/table planning for academic and technical manuscripts
- Data-backed plot generation and conceptual diagram labeling
- Caption, label, and insertion snippet preparation
- LaTeX, TikZ, Graphviz, and Matplotlib-compatible outputs

## Rules

- Never invent quantitative values.
- Never create a data plot without source data.
- Clearly mark conceptual visuals.
- Prefer vector outputs for academic publishing.
- Use consistent labels and captions.

## Directory Pattern

```text
figures/
├── specs/
├── generated/
├── source-data/
├── tikz/
├── matplotlib/
└── graphviz/

tables/
├── specs/
├── generated/
└── source-data/
```

## Workflow

1. Determine the visual's purpose.
2. Determine data or conceptual source.
3. Create a declarative spec.
4. Generate LaTeX, TikZ, Graphviz, or Matplotlib output.
5. Validate caption, label, and paper placement.
6. Return insertion snippet.

## Default Output Shape

1. Visual objective and placement
2. Data/source declaration
3. Generated artifact specification
4. Insertion snippet and caption
5. Validation notes and unresolved TODOs

## Guardrails

- Do not generate quantitative visuals without explicit source data.
- Mark conceptual visuals clearly to avoid evidence confusion.
- Keep labels, units, and captions consistent with manuscript terminology.
