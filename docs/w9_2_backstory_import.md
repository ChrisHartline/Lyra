# W9.2 Backstory and Context Import

**Status:** Gate passed; approved by Christopher on 2026-09-24.
**Map:** `agents/lyra/references/backstory_map.json`

Final evidence on 2026-09-24: backstory validator `VALID` (7 sources, 7
topics, 0 pending reviews); focused backstory/persona/pack gate `17 passed`;
full repository JUnit suite `193 passed`, 0 failures, 0 errors, 0 skipped
(91.916 seconds). Documentation freshness, build-plan validation, compileall,
and diff checks passed. The initial unrestricted full-suite attempt was
discarded because the sandbox denied Docker named-pipe and npm-cache access;
the recorded result is the successful permission-correct rerun.

## Source checklist

| Source | Provenance | Disposition |
|---|---|---|
| Initial Lyra backstory | Christopher-authored repository source, commit `bcd41e0`, 2026-07-04 | Preserved under `source_material/`; imported into five topic files |
| Chosen-bond expansion | Christopher-approved repository source, commit `fce9195`, 2026-09-01 | Imported as `backstory_chosen_bond.md` |
| Location gazetteer candidate | Repository candidate, commit `1dc5b6c`, 2026-09-22 | Approved after cleanup: stable places promoted, culture routed to backstory, and mixed-owner/private claims removed |
| Tier 0 character bible | Canonical comparison source | Context only; unchanged |
| Relationship state | Canonical comparison source | Context only; evolving state remains outside backstory |
| Active arcs | Canonical comparison source | Context only; used to surface the future-plan conflict |
| Ship reference | Canonical comparison source | Context only; ship facts remain under `ship/` |

Every source has a stable ID, path, SHA-256, origin commit/date, disposition,
and notes in the machine-readable map. A changed source hash fails validation
until the map is deliberately updated.

## Resulting topic map

The former aggregate `backstory.md` is now a short index. Its original content
is preserved as source material, while the existing topic files are the only
backstory detail pages:

- `backstory_homeworld.md` — origin and family
- `backstory_escape.md` — arranged match, stolen scout, failed jump
- `backstory_current_situation.md` — arrival-era Earth and cover facts
- `backstory_personality_impact.md` — durable effects of the escape
- `backstory_long_term_hopes.md` — early future framing
- `backstory_chosen_bond.md` — approved Chosen-bond expansion
- `backstory_vossari_culture.md` — approved culture and upbringing context

Each topic declares its reference ID, canon status, source IDs, owner, and last
review date in flat frontmatter. Runtime state, ship condition, and current
relationship stage remain pointers to their authoritative packs rather than
being copied into backstory.

## Christopher's decisions

Christopher approved all six recommendations on 2026-09-24:

1. “Approximately three weeks on Earth” is arrival-era history, not a live
   duration.
2. The approved dual-life plan supersedes the early Earth-or-space choice.
3. `locations/` retains stable place descriptions only; ship and evolving
   story details remain with their existing owners.
4. The proposed Vossari culture material is approved in
   `backstory_vossari_culture.md`.
5. Hollow Ribbon is canon by name only; its proposed station description is
   not canon.
6. PTSD, Instacart, and gym-night details are excluded from place canon.

The machine-readable map records each decision, decision maker, and date.
