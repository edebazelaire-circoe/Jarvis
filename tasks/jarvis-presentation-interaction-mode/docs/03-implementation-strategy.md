# Implementation Strategy

## Rollout order

1. Define interaction-mode and output-policy contracts.
2. Add live control plane and persistence, defaulting to Simple.
3. Add left-side selector with Meeting visibly unavailable/future.
4. Add Presentation working set and observation contracts.
5. Add shared audio seam and explicit-address trigger path without changing Simple behavior.
6. Add ambient segmentation/transcription and asynchronous admission.
7. Add Presentation output/speech policy.
8. Add speculative preparation/delegation and prepared display resources.
9. Add fact-check attention notifications and sound.
10. Complete priority addressed turns with working-set + transcript-tail rehydration.
11. Run end-to-end latency, regression, privacy, and manual workstation validation.

## Migration constraints

- Default remains Simple on upgrade and on missing/invalid stored mode.
- Existing `voice_arch`, `voice_architecture`, voice stack settings, and `conversation_mode` are not renamed or repurposed.
- Existing keyboard wake behavior outside Presentation remains unchanged.
- Existing Porcupine standalone microphone path may remain for Simple if safer; Presentation must not open a second competing microphone stream.
- Existing scene authority rules and persistent-write confirmation remain canonical.
- Existing back-brain addressed admission remains canonical; ambient speculative work uses a new restricted path.

## Capacity and priority

- P0: explicit addressed command/question
- P1: user-visible preparation required by active addressed turn
- P2: high-value fact check / contradiction verification
- P3: speculative background research
- P4: enrichment/indexing

P0 must have reserved capacity or preemption rules. A full speculative pool must not block an addressed request.

## Cost controls

Do not invoke a heavy brain continuously per audio frame. Keep streaming capture/segmentation, transcription per bounded utterance, cheap topic/entity/claim analysis, and expensive agent/sub-agent work only when a trigger merits it. Add budgets for concurrent speculative jobs, duplicate work, working-set size and stale resource eviction.

## Failure behavior

- Ambient failure must not disable explicit command lane.
- Wake detector failure must surface clearly and leave manual key usable.
- Fact-check failure should be silent/diagnostic, not a false contradiction.
- Presentation activation fails loudly if microphone ownership cannot be established; never silently create two competing streams.
- If Scene is unavailable, preparation may cache research but must not claim it displayed anything.

## Freshness before each Slice

Slice 00 and the PM must re-check latest repository immediately before dispatch, especially around Bare Hands/scene work, voice arbitration, wake ownership and settings.
