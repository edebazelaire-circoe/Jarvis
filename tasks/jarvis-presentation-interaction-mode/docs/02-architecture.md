# Target Architecture

## Two independent dimensions

```text
Voice architecture: Simple | Front Brain | Duplex | future
Interaction mode:  Simple | Presentation | Meeting(future)
```

Do not branch product capabilities by voice architecture unless a provider capability truly makes the feature unavailable. The interaction policy is injected above/alongside architecture-specific composition.

## Presentation topology

```text
                                      +--> ExplicitAddressDetector
                                      |      (manual key + wake word)
                                      |               |
Mic --> AudioCaptureHub + ring buffer +               v
                                      |       PRIORITY COMMAND LANE
                                      |               |
                                      |               +--> addressed transcript/context
                                      |               +--> Brain (P0)
                                      |               +--> display / optional speech
                                      |
                                      +--> Ambient segment/VAD --> Ambient STT
                                                              |
                                                              v
                                                       AMBIENT LANE
                                                              |
                                             +----------------+----------------+
                                             |                |                |
                                        understanding     fact-check      preparation
                                             |                |                |
                                             +------> Presentation Working Set <+
                                                              |
                                                              +--> hidden/prepared scene artifacts
                                                              +--> attention events
```

## Canonical ownership

Introduce a dedicated interaction-mode contract. Do not reuse `conversation_mode`, which already means room/owner authorization, and do not reuse voice architecture identifiers. Recommended internal values are `assistant`, `presentation`, `meeting` with user labels SIMPLE, PRESENTATION, REUNION. Core should own the effective live mode/revision; Control Center owns user preference persistence and requests live changes; Voice consumes Core truth/events rather than keeping a second optimistic mode state.

## Presentation working set

A bounded session-owned model, separate from long-term memory, containing active topics, resolved entities, bounded facts/claims with provenance, prepared resources, open questions/uncertainties, attention items, freshness and resource temperature (`hot` / `warm` / `discardable`). Do not persist raw audio.

## Fresh transcript tail

Maintain a small recent transcript window independent from enrichment completion. The command lane snapshots it atomically at explicit-address time. It is context, not an instruction stream.

## AudioCaptureHub

Presentation mode requires one physical microphone owner with bounded in-memory fan-out. Existing consumers become subscribers/adapters: ambient segmenter/transcriber, wake detector, realtime interactive voice path, speaker verification/VAD/duplex processor. Keep a short in-memory PCM ring for explicit-address pre-roll. Do not persist it. Existing Simple behavior may retain the old direct ownership path until the shared path is proven.

## Explicit-address lane

Keyboard and wake-word signals normalize to one typed `ExplicitAddressTrigger` carrying source and monotonic time. Presentation mode turns the following speech into a priority addressed turn. It bypasses ambient queues and uses current working-set snapshot plus recent transcript tail.

## Ambient lane

Ambient utterances are observation events, not canonical addressed user commands. They may trigger cheap analysis and lower-priority speculative work. Ordinary `BackBrainTaskService` addressed-only admission remains unchanged; use a distinct presentation-speculative admission/policy path.

## Output disposition

Add typed `silent`, `visual_only`, `voice_only`, `visual_and_voice`. Presentation defaults to silence/visual for commands. Voice is allowed for genuine questions or explicit requests to speak. Ambient work cannot request spontaneous speech in V1.

## Scene/display reuse

The Scene model already supports brain-created `artifact`/`window` objects and visibility changes. Use hidden objects as prepared/staged resources when practical. Never bypass user pin/geometry authority or runtime execution truth. If chart rendering needs a new representation, use a safe structured descriptor, not executable HTML.

## Attention/fact-check path

A typed `PresentationAttention` event includes category, severity, confidence, source references, related topic/claim, and prepared-resource references. Extend the background-event pipeline so Control Center can show a small floating warning and one discreet sound per new event. Deduplicate sound across tabs/windows and polling.
