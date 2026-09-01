# Task 06 - Implement TTS and interruption loop

## Goal

Fermer la boucle vocale : texte de l'agent -> parole, avec interruption utilisateur propre.

## Context

Le moteur TTS final n'est pas verrouille. Cette task doit choisir le chemin le plus rapide/stable tout en respectant `TTSBackend`.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- Implement one production TTS adapter.
- Start speaking early when possible.
- Cancellation token / stop playback.
- Pressing PTT while speaking interrupts output.
- Publish speaking waveform/level if available or approximate state only.

### Out of Scope
- Voice cloning.
- Multiple voices/personas.
- Open mic barge-in.

## Dependencies

Tasks 03-05 complete.

## Implementation Steps

1. Select TTS engine and record decision.
2. Implement adapter under port.
3. Add playback service and cancellation.
4. Integrate response chunking if beneficial.
5. Wire PTT press to cancel current speech before recording.
6. Publish speaking/idle state reliably.

## Files Likely Touched

- `jarvis/ports/tts.py`
- `jarvis/adapters/*tts*.py`
- `jarvis/audio/playback.py`
- `jarvis/core/orchestrator.py`
- tests

## Architecture Constraints

Core cannot depend on TTS engine. Cancellation must be explicit, not process kill. Voice failure must degrade to text/log diagnostic rather than kill session.

## Testing Requirements

- Cancellation mid-utterance.
- TTS backend failure mapping.
- State returns to idle after cancellation.
- Repeated interrupt/reply loop regression test.

## Acceptance Criteria

- User can ask a voice question and hear the answer.
- Pressing PTT stops speech promptly.
- Next turn is not desynchronized.
- TTS implementation is swappable.

## Documentation Updates

Record TTS choice and setup.

## Handoff Notes

If streaming adds instability, ship sentence-level chunks first and defer finer-grain realtime audio.
