# Task 04 - Implement push-to-talk and OpenAI transcription

## Goal

Rendre le premier chemin entree vocale reel : touche -> capture -> transcription texte.

## Context

OpenAI est le premier backend STT. Le modele exact vient de configuration. Les patterns Backtalk sur les peripheriques audio peuvent etre etudies mais le coeur reste provider-agnostic.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- PTT configurable.
- PCM/WAV capture mono standard.
- Microphone preflight.
- OpenAITranscriptionBackend.
- Timeouts/retries limites.
- Provider diagnostics sans contenu sensible.
- Fixture audio test.

### Out of Scope
- Open mic.
- Wake word.
- Speaker recognition.
- Camera audio.

## Dependencies

Tasks 02-03 complete. OpenAI key available for optional live test.

## Implementation Steps

1. Implement PTT listener and audio capture behind service boundary.
2. Normalize clips to stable format.
3. Implement OpenAI adapter using current official SDK/API.
4. Make model configurable via `OPENAI_TRANSCRIPTION_MODEL`.
5. Map provider failures into typed errors.
6. Add opt-in live integration test using a short fixture.
7. Ensure raw audio is not persisted by default.

## Files Likely Touched

- `jarvis/audio/*`
- `jarvis/adapters/openai_transcription.py`
- `tests/unit/test_audio_capture.py`
- `tests/integration/test_openai_transcription.py`
- `tests/fixtures/audio/*`

## Architecture Constraints

Provider adapter owns SDK. Audio capture does not import OpenAI. PTT is default and only V1 mic mode.

## Testing Requirements

- Unit test fake mic source.
- No-mic preflight behavior.
- Fixture transcription contract test.
- Live OpenAI test behind explicit env flag.
- Verify default logs omit transcript text.

## Acceptance Criteria

- Holding/releasing PTT creates one AudioClip.
- Real adapter returns typed transcript.
- Network/provider failure does not crash session.
- No raw audio file remains after normal turn.

## Documentation Updates

Document setup environment variables and privacy behavior.

## Handoff Notes

If current OpenAI SDK naming differs from assumptions, preserve the port contract and update only the adapter.
