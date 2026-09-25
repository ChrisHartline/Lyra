# W9.4 Scene Direction and Still Insertion

**Status:** Gate passed on 2026-09-24.

## Boundary

Scene media is an opt-in presentation layer. Text remains authoritative and is
emitted and persisted before rendering begins. A generated still or storyboard
is labeled `generated_noncanonical` and cannot update persona, ship, story,
campaign, memory, KG, corpus, journal, commitment, or chat history.

W9.4 supplies the scene director, media-event delivery, local storage, and
provider-neutral renderer boundary. The production renderer remains
unconfigured until the later renderer gates; W9.4 mock tests exercise successful,
slow, and failed renders without making an external request.

## Policy and triggers

The persistent local policy under `data/scene_media/policy.json` defaults to:

- master disabled;
- automatic triggers disabled;
- web and Telegram eligible only after opt-in;
- at most two renders per day;
- a 120-minute cooldown;
- at most three storyboard frames.

Supported triggers are explicit requests, arrivals, location reveals,
meaningful emotional beats, appearance changes, ship discoveries, and
milestones. Automatic triggers require their own opt-in. Ordinary turns have no
trigger, while duplicate fingerprints, cooldown, and daily limits prevent
generate-every-turn behavior.

## Structured brief and privacy

The director uses only the current user request and assistant response, each
normalized, sensitivity-filtered, and bounded to 400 characters. If no safe
scene context remains, rendering is blocked. No prior history, private journal,
memory, KG data, corpus passages, secrets, or unrelated session context enters
the brief.

Each brief records its format, bounded frame count, trigger, channel, filtered
scene context, canonical source references, eligible visual asset IDs,
composition rule, negative constraints, and non-canonical status. The current
visual catalog has zero assets approved for external rendering, so an external
renderer receives no source images. A local renderer may use the six approved
identity anchors without changing their canon or rights status.

## Delivery and fallback

The conversation stream emits normal text and `completion` before any `media`
event. Web renders media events inline. Telegram sends the completed text first,
then uploads generated frames. Renderer errors are sanitized, create no media
event, and leave the full text reply intact.

Every successful local request directory contains frame files plus
`provenance.json`, including the exact structured prompt, provider, model,
source-asset IDs, hashes, creation time, and canon status. Failed attempts keep
a sanitized provenance record without provider error text.

## Disable and delete

The workstation-local, control-token API provides:

- `GET /api/control/scene-media`
- `PUT /api/control/scene-media`
- `DELETE /api/control/scene-media/{request_id}`
- `GET /api/scene-media/{request_id}/{filename}` for loopback artifact display

Deletion removes only the bounded artifact directory and appends its identifier,
timestamp, and non-content fingerprint to the local deletion ledger. The ledger
preserves rate-limit/deduplication behavior without retaining the prompt. It does
not edit or delete any conversation message.

## Validation

Run:

```powershell
.\venv\Scripts\python.exe scripts\validate_scene_media.py
.\venv\Scripts\python.exe -m pytest -q tests\test_scene_media.py
```

The acceptance tests cover every trigger class, opt-in defaults, privacy
filtering, local-versus-external asset eligibility, cooldown and daily behavior,
structured provenance, non-canonical labeling, asynchronous text-first event
order, safe renderer failure, web control and deletion, Telegram text-first
delivery, and conversation-history independence.

Final evidence on 2026-09-24: scene-media validator `VALID` (disabled by
default; 7 triggers; 0 external assets); focused scene/runtime/web/Telegram gate
`41 passed`; full repository JUnit suite `210 passed`, 0 failures, 0 errors, 0
skipped (83.870 seconds). Visual-catalog validation, compileall, JavaScript syntax,
documentation freshness, build-plan validation, and diff checks passed.
