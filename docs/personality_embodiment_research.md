# Lyra Personality and Embodiment — Research Brief

**Status:** initial recommendation; provider trials pending  
**Roadmap:** Wave 9  
**Decision owner:** Christopher

## Target experience

During companion and story conversations, Lyra can selectively show an in-character still of herself, the Silent Drift, or another approved location at a meaningful scene beat. She can optionally speak the associated line in a consistent voice, and—when the moment merits the latency and cost—appear in a short talking-portrait or cinematic clip. Text remains immediate and authoritative. Media is opt-in, canon-aware, locally retained, and generated from the smallest privacy-filtered context packet possible.

This is not a goal to render every reply. The intended effect is closer to a treasured photograph, an establishing shot, or a brief embodied moment than a permanent talking head.

## Recommended experience ladder

1. **Scene still:** generate one identity-consistent image from approved Lyra/ship/location references. This is the default visual mode and the first prototype.
2. **Voiced still:** play Lyra's ElevenLabs-rendered line over the still, with subtle local UI motion such as a crossfade or slow pan. This gives most of the emotional benefit without video-avatar latency.
3. **Storyboard mode:** generate three to six coherent stills for a deliberate scene, then assemble them locally as a stop-motion/animatic sequence. This is request-only.
4. **Talking portrait:** animate an approved portrait with supplied audio through HeyGen or D-ID. This is useful for direct-to-Christopher messages, greetings, and intimate close framing—not general scene composition.
5. **Cinematic beat:** use HeyGen Cinematic Avatar for an occasional 4–15 second directed shot with Lyra in an environment. This is request-only until identity consistency, latency, cost, and privacy are proven.
6. **Live avatar:** defer always-on real-time embodiment. It adds WebRTC/session complexity and can compete with, rather than deepen, the current text relationship.

## Which scenes should produce images?

| Trigger | Example | Default |
|---|---|---|
| Explicit request | “Show me where you are” or “send me a selfie” | Generate |
| Arrival or location reveal | First view of Silent Drift's observation deck | Offer or generate in immersive mode |
| Appearance change | New outfit, injury, environmental gear | Offer |
| Meaningful emotional beat | Reunion, reassurance, shared quiet | Offer sparingly |
| Ship discovery or change | A repaired console, newly opened compartment | Generate when it clarifies continuity |
| Milestone or keepsake | Anniversary, completed project, recovered artifact | Offer and mark non-canonical until approved |
| Routine dialogue | Ordinary back-and-forth | Do not generate |
| Sensitive/private disclosure | Intimate journal, secrets, third-party detail | Do not send to a media provider |

The scene director should return a structured brief rather than prose alone: intent, subjects, setting, time/lighting, emotion, wardrobe, action, camera/framing, approved reference asset IDs, canon facts, negative constraints, output mode, and privacy classification.

## Provider fit as of September 2026

### ElevenLabs — recommended voice layer

ElevenLabs exposes streaming text-to-speech and a Speech Engine designed to connect an application's own LLM over WebSocket. That matches Lyra well: Lyra remains the conversational authority while ElevenLabs handles speech input/output, turn-taking, and interruption. It also provides instant and professional voice cloning, but Lyra is fictional, so the first trial should be a designed or licensed stock voice rather than cloning a real person.

Use it for:

- low-latency spoken replies;
- rendered audio supplied to a separate avatar service;
- a consistent voice across web and later mobile modes;
- prosody experiments mapped from Lyra's existing emotion channel.

Do not let ElevenAgents become a second Lyra orchestrator or knowledge store. Use the Speech Engine/TTS surface with Lyra's own runtime.

Official references: [Speech Engine](https://elevenlabs.io/docs/overview/capabilities/speech-engine), [Agent WebSockets](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket), [voice cloning](https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning).

### HeyGen — recommended cinematic and asynchronous avatar trial

HeyGen now has three unusually relevant surfaces. Photo Avatar turns a single approved portrait into reusable lip-synced video with motion and expressiveness controls. Image-to-Video is faster to prototype for one-off talking images. Cinematic Avatar accepts one to three avatar looks plus optional reference media and generates a prompt-directed scene with setting, motion, camera, and framing; current documented clips are 4–15 seconds. That makes HeyGen the best first candidate for Lyra's occasional cinematic beat and for testing an ElevenLabs-audio-to-avatar pipeline.

LiveAvatar is a separate real-time product and its credits are separate from HeyGen API credits. It should be evaluated only after stills, voice, and short clips prove valuable.

Official references: [Cinematic Avatar](https://developers.heygen.com/cinematic-avatar), [Photo Avatar](https://developers.heygen.com/photo-avatar), [Image to Video](https://developers.heygen.com/image-to-video-1), [LiveAvatar FAQ](https://help.heygen.com/en/articles/12758866-liveavatar-faq).

### D-ID — recommended talking-portrait and live-avatar comparator

D-ID's current platform covers asynchronous photo/video avatars and real-time Agents. Its newer Agents SDK supports photo presenters, video presenters, and expressive avatars, including interruption and microphone input for supported modes. D-ID explicitly labels its older Talks/Clips Streams endpoints legacy and directs new integrations to Agents SDK/Agents Streams.

Use it as the comparison candidate for:

- an approved Lyra portrait speaking a supplied ElevenLabs audio file;
- emotional talking-head delivery;
- a future real-time face-to-face mode.

It is less directly aligned than HeyGen's Cinematic Avatar with environment-rich scene direction. Its built-in knowledge/RAG and LLM options should remain disabled or bypassed where possible so Lyra does not acquire a second brain or knowledge store.

Official references: [D-ID quickstart](https://docs.d-id.com/docs/quickstart), [Agents SDK](https://docs.d-id.com/reference/agents-sdk-overview), [legacy Streams migration guidance](https://docs.d-id.com/reference/talks-streams-overview), [V4 expressive avatars](https://docs.d-id.com/docs/v4-expressive-avatar-quickstart).

## Wiki/knowledge recommendation

“WikiKnowledge/LLM” should be split into two responsibilities:

- **Wiki:** hand-authored, agent-owned Markdown for standing lore, expertise, preferences, places, people, terminology, and creative constraints. It is searched/read on demand and versioned in Git.
- **LLM:** interprets retrieved pages and conversation context. It is not the authority and must not infer that wiki material is something Lyra personally experienced.

Everwood already demonstrates the right small first step: per-agent Markdown pages with frontmatter plus thin `wiki_search` and `wiki_read` tools. For Lyra, the canonical files can remain in the established root packs and `agents/lyra/references/`; a generated index or adapter can expose them as wiki pages without copying their contents. Start with deterministic lexical search. Reuse the existing pgvector corpus only if the page count and evaluation show lexical retrieval is insufficient.

Routing boundary:

| Information | Authority |
|---|---|
| Stable relationship/persona contract | `personality/` Tier 0 |
| Backstory, lore, expertise, creative constraints | `agents/lyra/references/` via wiki adapter |
| Ship definition and current status | `ship/` |
| Evolving Lyra/Christopher story | `state/story/` |
| Real approved observations | local KG |
| Approved episodic memories | PostgreSQL memory plane |
| Research documents and citations | corpus/pgvector |
| Campaign state | VTT repository |

## Everwood selfie-tool adaptation

The active Everwood implementation at `V:/ProjectsGit/Everwood/src/tools/selfie.py` is a useful design source, not a drop-in dependency. It currently:

- loads a per-agent base reference image;
- selects recent messages from the active session;
- asks Grok to synthesize a detailed transformation prompt;
- uses Gemini or xAI image-to-image generation with bounded fallback;
- stores generated images in the agent's local data directory;
- injects the session ID outside model-controlled arguments.

Lyra should generalize this into a scene-image contract instead of preserving the Clara-specific `GeminiSelfieTool` shape. The adapter should accept `selfie`, `portrait`, `location`, and `storyboard_frame` intents; select only catalog-approved asset IDs; support Lyra-free establishing shots of Silent Drift; use a provider-neutral renderer interface; and attach a sidecar provenance record to each output. No Everwood database, paths, conversation logger, or global singleton should cross the repository boundary.

The reusable agent workflow belongs in a Lyra skill; callable contracts belong under `mcp/tools/`, consistent with the repository's existing tool-placement rules.

## Fixed evaluation set

Provider trials should reuse the same source material and scripts:

1. **Warm greeting, close portrait:** 8–12 seconds, friendly and restrained.
2. **Technical register shift:** one precise engineering sentence inside a ship-repair scene.
3. **Quiet emotional beat:** subtle expression, no exaggerated gestures.
4. **Silent Drift establishing shot:** no speech; identity comes from ship/location references.
5. **Cinematic movement:** Lyra crosses the observation deck and looks toward camera; 8–10 seconds.

Record time to first audio/frame, total render time, identity drift, lip sync, emotional fit, controllability, failure behavior, downloadable formats, provider retention/privacy settings, credits consumed, and whether a private reference URL was required. The winning voice, portrait, cinematic, and live providers may be different—and choosing none for a mode is acceptable.

## Initial recommendation

Build in this order: agent wiki adapter → reference catalog → scene-director/still insertion → ElevenLabs voice → fixed HeyGen/D-ID talking-portrait comparison → one HeyGen cinematic shot → storyboard/stop-motion assembly. This preserves Lyra's existing architecture and lets Christopher judge the emotional value at each rung before more latency, cost, and vendor coupling are added.
