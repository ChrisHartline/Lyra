# W9.6 Selfie and Scene-Image Tool Design

**Status:** Captured for W9.6; not yet implemented or enabled.
**Updated:** 2026-09-18

## Goal

Adapt Everwood's useful conversation-aware selfie pattern into a Lyra-native,
provider-neutral scene-image capability. A request such as “send me a selfie on
the bridge” should combine an approved Lyra identity reference, the selected
bridge/location preset, a bounded scene brief, and the minimum relevant
conversation context. Grok Imagine is the initial renderer, not the owner of
Lyra's identity, canon, memory, or asset registry.

The same pipeline supports four explicit intents:

- `selfie` — an in-world casual image presented as coming from Lyra;
- `portrait` — a composed character image;
- `location` — an environment image, with or without Lyra present;
- `storyboard_frame` — a deliberately requested scene still for later media work.

## What to reuse from Everwood

Everwood's live implementation is `V:/ProjectsGit/everwood/src/tools/selfie.py`.
It demonstrates a working sequence: resolve an agent reference image, derive a
prompt from session context, submit an image-to-image request, download the
result, and return a local path to chat. Its raw JSON request to
`/v1/images/edits` is the correct transport family for xAI image editing.

Lyra should port the pattern, not import Everwood runtime code. The Everwood
class contains Clara-specific paths, personality data, conversation logging,
provider fallback, console behavior, and a model slug scheduled for retirement.
Those concerns do not cross the project boundary.

## Proposed Lyra pipeline

```text
explicit request / separately enabled scene beat
    -> classify intent and requested setting
    -> resolve stable reference asset IDs locally
    -> build a privacy-filtered structured scene brief
    -> preview policy, budget, and provider payload
    -> illustrate(scene_brief, reference_asset_ids, output_mode)
    -> Grok Imagine adapter
    -> download and verify image locally
    -> save image + provenance sidecar
    -> attach local artifact to the originating chat session
```

Reference selection is deterministic and registry-driven, not improvised by the
model. Initial ordering should be:

1. Lyra identity/appearance reference;
2. location preset;
3. ship, wardrobe, or object reference when explicitly relevant;
4. an approved prior generated image only for a requested refinement.

The first implementation should normally use two references—character and
location—even though the provider supports more. Fewer, better references make
identity and setting failures easier to diagnose.

## Scene context and privacy

Unlike Everwood's current “last 12 messages” summarization, Lyra should not send
a raw recent transcript to a prompt-synthesis model. The scene director receives
only:

- the user's explicit visual request;
- the selected intent and output mode;
- approved canon fields needed for appearance or setting;
- a small, privacy-filtered scene-context excerpt from the originating session;
- stable reference IDs and non-sensitive asset metadata.

Never send secrets, private shared-journal entries, unrelated conversation,
pending memory/KG proposals, professional documents, or hidden reasoning.
Relationship context may affect an image only when it is directly expressed in
the current request/context and passes the outbound filter. Image generation
does not create canon or memory.

## Reference library and registry

Source files remain under:

- `assets/visual_references/lyra/`
- `assets/visual_references/wardrobe/`
- `assets/visual_references/locations/`
- `assets/visual_references/ship/`
- `assets/visual_references/props/`

Location assets carry a stable `location_id` that resolves into the canonical
repo-root `locations/` pack. Visual metadata records presentation facts such as
angle, lighting, season, and crop; it does not restate the location's history or
narrative constraints. Ship spaces resolve to `ship/` as their factual owner.

W9.1 should add a registry with stable asset IDs and, at minimum: file path,
subject/location, angle, crop, lighting, canon status, provenance/rights,
allowed transformations, supersession, and an approved-for-external-renderer
flag. File names alone must not determine which image leaves the workstation.

Generated images and JSON provenance sidecars belong under a gitignored local
path such as `data/media/images/<year>/<month>/`. Each sidecar records the
originating session/message, intent, scene-brief hash, provider/model, reference
asset IDs and hashes, request time, output hash, cost/usage when returned, and
canon status (`non_canonical` by default). It must not copy private source text.

## Grok Imagine adapter

As of 2026-09-18, xAI documents `grok-imagine-image-2.0` for generation and
editing. Multi-image edits accept up to five ordered PNG/JPEG/WebP references
through public URLs, base64 data URIs, or Files API IDs. Lyra's first adapter
should use JSON `POST /v1/images/edits`, base64 data URIs, explicit timeouts, and
immediate local download. It should not request public URLs or provider-side
durable storage by default.

Everwood's `grok-imagine-image-quality` slug entered retirement notice on
2026-09-02 and is scheduled to retire on 2026-11-02. Lyra should not inherit it.
Provider model names remain configuration rather than hard-coded persona/tool
logic.

Official references:

- [Imagine overview](https://docs.x.ai/developers/model-capabilities/imagine)
- [Multi-image editing](https://docs.x.ai/developers/model-capabilities/images/multi-image-editing)
- [Image editing request contract](https://docs.x.ai/developers/model-capabilities/images/editing)
- [Model retirement notice](https://docs.x.ai/developers/migration/imagine-image-quality-nov-2)

## Tool and skill boundary

The low-level provider-neutral renderer remains the SRS interface:

```text
illustrate(scene_brief, reference_asset_ids, output_mode)
```

The agent-facing MCP tool should accept explicit semantic inputs rather than raw
paths or arbitrary URLs, for example:

```text
create_scene_image(
  intent,
  user_direction,
  location_id?,
  wardrobe_id?,
  aspect_ratio?,
  quality?
)
```

The MCP server injects the session/message provenance and resolves assets; the
model cannot read arbitrary files or choose unapproved references. A Lyra skill
defines when to call the tool, how to form a bounded scene brief, and how to
present success/failure without blocking the authoritative text response.

## Controls and acceptance

- Disabled by default; explicit user requests are the initial trigger.
- Separate opt-in is required before system-selected meaningful scene beats.
- Per-image rate, daily cost, quality, reference-count, and concurrency limits.
- Cancellation and visible failure; text conversation continues independently.
- Provider payload preview/audit contains hashes and IDs, not hidden context.
- Generated variants remain non-canonical until Christopher approves one.
- A delete operation removes the local artifact and provenance according to the
  selected retention policy without altering conversation or memory.
- Mock-provider tests cover selection order, privacy filtering, malformed output,
  timeout, cost limit, download verification, and local provenance.
- The live gate uses one Lyra + location render and one Silent Drift location
  render, followed by Christopher's identity/setting/privacy sign-off.
