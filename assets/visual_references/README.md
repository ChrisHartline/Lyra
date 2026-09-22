# Visual References

Store visual reference assets for Lyra here.

## Folders

- `lyra/approved/` - Christopher-approved identity anchors and their manifest
- `lyra/candidates/` - generated identity candidates awaiting Christopher's approval
- `lyra/references/true_form/` - existing true-form scene references
- `lyra/references/disguise/` - existing holographic-disguise scene references
- `lyra/references/details/` - anatomy and identity detail references
- `wardrobe/` - clothing, disguise outfits, footwear, and accessories
- `locations/` - recurring Earth, Hollow Ribbon, Silent Drift, and other places
- `ship/` - ship exterior/interior references, callouts, and colorways
- `props/` - tools, weapons, personal objects, consoles, and continuity items

`catalog.json` is the authoritative machine-readable registry for every image
in this tree. `catalog.schema.json` documents its shape, while
`../../scripts/validate_visual_assets.py` verifies coverage, stable IDs, file
hashes, provenance safety, subject types, supersession links, and the human
canon-approval boundary.

Canonical Lyra anchors are also indexed by
`lyra/approved/canonical_anchors.json`. Christopher approved the six current
anchors, including both hair-down variants, on 2026-09-22. Scene images remain
supporting references and do not override an approved identity anchor.
Candidate, reference, and approved states are explicit catalog values. Moving
or renaming a file never promotes it. No current asset is approved for an
external renderer.

Run the gate check from the repository root:

```powershell
.\venv\Scripts\python.exe scripts\validate_visual_assets.py
```

## Suggested Naming

- `lyra_canonical_true_portrait_v1.png`
- `lyra_canonical_disguise_full_body_v1.png`
- `lyra_expression_sheet_v1.png`
- `ship_exterior_three_quarter_v1.png`
- `ship_interior_bridge_v1.png`
