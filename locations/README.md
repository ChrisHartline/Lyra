# Locations Pack

This repo-root pack is the canonical source for Lyra's recurring places: their
names, history, atmosphere, constraints, narrative use, and current degree of
definition. Christopher approved the cleaned W9.2 gazetteer on 2026-09-24.
`locations.md` may later be split into one file per stable location without
changing ownership.

Every canonical place should receive a stable `location_id`, for example:

- `earth.kansas_city.apartment`
- `earth.state_park.ship_hide`
- `vossari.silent_drift`
- `vossari.elyrias_veil`
- `station.hollow_ribbon`

Reference images and visual presets live separately under
`assets/visual_references/locations/`. Their catalog entries link here with
`location_id` and describe only visual evidence such as angle, lighting,
season, crop, provenance, rights, canon status, and allowed transformations.
They do not become location canon merely by existing.

Ship interiors are factual members of the `ship/` pack. Location prose may
link to a ship space, and a scene preset may use a `ship.*` location identifier,
but neither should duplicate ship layout or current-status facts.

The old `agents/lyra/assets/visual_references/` staging tree was hash-verified,
migrated into the root visual library, and removed on 2026-09-20. Do not
recreate it or maintain synchronized copies.
