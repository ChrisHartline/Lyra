# Visual asset catalog

W9.1 owns the machine-readable visual library under
`assets/visual_references/`. The catalog records what an image is and how it
may be used; it does not replace appearance canon in
`personality/appearance.md` or location/ship facts in their owning packs.

## Files and validation

- `assets/visual_references/catalog.json` is the authoritative registry.
- `assets/visual_references/catalog.schema.json` documents the catalog shape.
- `assets/visual_references/lyra/approved/canonical_anchors.json` retains the
  generated-anchor lineage and source-image graph.
- `scripts/validate_visual_assets.py` validates all local image coverage,
  stable IDs, safe relative paths, SHA-256 hashes, allowed subject types,
  provenance/rights metadata, transformation and external-renderer gates,
  supersession references, duplicate content, candidate placement, manifest
  agreement, and canon approval records.

Run the check from the repository root:

```powershell
.\venv\Scripts\python.exe scripts\validate_visual_assets.py
```

An image has three independent controls:

1. `lifecycle_status` says whether the file is active or superseded.
2. `canon_status` separates `candidate`, non-canonical `reference`, and
   human-`approved` canon.
3. `approved_for_external_renderer` governs whether the file may leave the
   workstation. This flag cannot be true unless canon is approved and rights
   are cleared.

Unknown provenance or rights fail closed: no transformations are allowed and
external-renderer approval remains false. No provider URL, credential, or
private remote locator belongs in the catalog.

## Current inventory and review

The active inventory contains 27 images: six approved identity anchors,
15 non-canonical Lyra scene/detail references, and six wardrobe references.
No ship, prop, or location images are currently present. Those empty subject
folders do not create placeholder catalog entries.

The W9.1 audit and Christopher's final review recorded these decisions:

| Review | Finding | Recorded decision |
|---|---|---|
| Exact duplicates | No SHA-256 duplicates among 27 active files | No removal; future duplicate content fails validation |
| Red-couch group | Four distinct true-form/disguise pose and footwear images reuse one hotel/red-dress setup | Retain as an intentional supporting-reference continuity group |
| Hair variants | Two portraits intentionally preserve each base face while changing braided hair to loose hair | Christopher approved both variants with their base anchors on 2026-09-22 |
| Legacy identity variation | Scene references depict multiple facial identities | Keep only as pose, wardrobe, lighting, and scene references; never use them as identity authority |
| Provenance/rights | Christopher confirmed that the anchors were AI-generated for his sole use, but no provider-output license record is attached; legacy source/license locators are also unavailable | Record `unknown_pending_review`; permit no transformation or external-renderer use |
| Canon placement | Six generated anchors were approved after review | Move them into `lyra/approved/`; hashes and manifest relationships remain unchanged |

## Christopher canon sign-off — completed 2026-09-22

Christopher resolved catalog review item
`approval.lyra.canonical-appearance-set` by approving all six assets:

- `lyra.true.portrait.v1`
- `lyra.true.full_body.v1`
- `lyra.true.portrait.hair_down.v1`
- `lyra.disguise.portrait.v1`
- `lyra.disguise.full_body.v1`
- `lyra.disguise.portrait.hair_down.v1`

He explicitly approved both hair-down variants and directed the textual
appearance base to follow the images. Under that authorization:

- `personality/appearance.md` now specifies warm amber-hazel eyes with a golden
  shimmer;
- it describes fine luminous gold freckles across the face and upper body,
  especially the cheeks, nose, shoulders, and collarbones; and
- `personality/emotional_color_map.md` now describes those fine gold freckles
  brightening with strong emotion.

The images do not establish scale, so the existing 155 cm height remains
authoritative. Clothing/framing does not contradict or establish the no-navel
detail. No other persona text was inferred from the images.

## Rights boundary still fail-closed

Christopher's statement that the anchors were AI-generated and that he is the
only user improves provenance but is not treated as a legal/license
determination. `usage_rights.status` therefore remains
`unknown_pending_review`, allowed transformations remain empty, and every
`approved_for_external_renderer` flag remains false. This is operationally
safe and does not block W9.1 canon acceptance; any future renderer integration
must perform its own rights review.
