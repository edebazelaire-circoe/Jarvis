# Overview

## Goal

Implement a product-level Jarvis interaction mode called Presentation without coupling it to the underlying voice architecture. Presentation mode continuously understands a live presentation and prepares useful material in the background, while explicit addressed interaction remains low latency and user-controlled.

## Mental model

Presentation mode follows one core product rule:

> Jarvis works a lot, but manifests little.

Separate these concerns:

1. Ambient listening and transcription.
2. Ambient understanding and speculative preparation.
3. Explicit-address detection (wake word or manual key).
4. Priority command/question handling.
5. Visual manifestation.
6. Spoken manifestation.
7. Discreet attention/fact-check signaling.

Ambient speech is evidence/context. It is never an action authorization.

## User-visible modes

- `SIMPLE`: current ordinary assistant behavior. Default.
- `PRESENTATION`: continuous ambient support with quiet-by-default manifestation.
- `REUNION`: visible future/reserved option only in V1. No meeting behavior is defined by this handoff.

Internally, prefer a dedicated `InteractionMode` concept and do not overload either existing `VoiceArchitectureId.SIMPLE` or the existing `conversation_mode` (`open_room` / `solo_owner`) authorization concept.

## Presentation behavior

- Continuous audio capture while Presentation mode is active.
- Ambient transcription stays close to real time.
- Enrichment/research may lag and runs asynchronously.
- The explicit command path must never wait for ambient work.
- Wake word and manual wake key are explicit-address priority triggers.
- Ambient analysis may dispatch lower-priority sub-agents.
- Results feed a bounded session working set/cache.
- The command path receives both the committed/enriched working set and a fresh transcript tail.
- Visual action commands normally produce `visual_only` behavior.
- Genuine questions may produce `visual_and_voice` or `voice_only` behavior.
- No automatic filler acknowledgements for visual commands.
- Ambient contradictions create attention notifications, not spontaneous TTS.

## Non-goals

- Designing Meeting mode semantics.
- Per-user interruption preference settings.
- Unsolicited spoken fact-check interruption.
- Treating Presentation as a new voice architecture.
- Replacing the existing scene authority model.
- Weakening the existing addressed-admission rule for ordinary back-brain work.
- Promoting session cache content into long-term memory automatically.
