# ADR-005 — Location and visual-reference ownership

**Status:** Accepted
**Date:** 2026-09-20
**Amends:** ADR-003; SRS FR-P4, FR-P7, and FR-V4

## Context

ADR-003 established repo-root data packs as Lyra's persona source of truth and
kept `agents/lyra/` as the Agent Skills host. Visual references were later
collected under `agents/lyra/assets/visual_references/`, while FR-V4 and W9.1
specified a repo-root `assets/visual_references/` library. Stable location prose
also appeared in a repo-root `locations/` directory without an explicit
ownership decision.

Keeping canonical-looking assets in the skill host would recreate the dual
source-of-truth problem ADR-003 was adopted to eliminate. Conversely, storing
location history and narrative constraints inside image metadata would make
canon depend on a rendering implementation.

## Decision

1. The repo-root `locations/` pack is canonical for stable place lore: names,
   history, atmosphere, constraints, narrative use, and definition status.
2. Repo-root `assets/visual_references/` is the single canonical visual library,
   organized into `lyra/`, `wardrobe/`, `locations/`, `ship/`, and `props/`.
3. A location image or preset links to lore through a stable `location_id`.
   Visual metadata records angle, lighting, season, crop, provenance/rights,
   canon status, allowed transformations, and supersession. It does not copy
   location prose or become canon merely by existing.
4. Ship facts and spaces remain owned by `ship/`. Location entries and visual
   presets link to ship identifiers rather than duplicating layout, systems, or
   current status.
5. `agents/lyra/` remains the Agent Skills host. Its `assets/` directory is for
   implementation assets intrinsically owned by a skill, not a second Lyra
   visual library. Skills resolve canonical references by catalog ID.
6. The former `agents/lyra/assets/visual_references/` staging tree was moved to
   the repo-root library and removed on 2026-09-20 after candidate hashes and
   source references were verified. Synchronized copies are prohibited.
7. Generator recipes and provider-specific prompts are operational skill
   references, not persona canon. Canonical appearance facts remain in
   `personality/appearance.md`; a future selfie skill derives prompts from those
   facts and approved asset metadata.

## Consequences

- Location lore can evolve independently of which images or providers are used.
- Multiple representative images may map to one place without restating canon.
- Hollow Ribbon may remain canon-but-thin while visual candidates stay
  non-canonical until Christopher approves both the textual and visual details.
- W9.1 still requires the full machine-readable catalog, provenance/rights
  review, canon approvals, and duplicate/conflict analysis; the path migration
  itself is complete.
- `personality/lyra_i2i_reference_prompts.md` must be reviewed and moved into the
  future selfie skill's references; any identity assertions that conflict with
  `personality/appearance.md` require Christopher's decision rather than silent
  reconciliation.

## Alternatives considered

- **Keep visuals under `agents/lyra/assets/`:** rejected because the host would
  own a second identity source and portability would remain ambiguous.
- **Copy visuals into both trees and synchronize:** rejected because drift is
  inevitable and provenance/canon status could disagree.
- **Put location prose inside visual preset metadata:** rejected because world
  canon should not depend on an image-generation tool or provider.
