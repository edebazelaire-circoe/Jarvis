# Task 09 - Implement Barge-In and Intent Revision

## Goal

Make user speech interrupt audible Jarvis output quickly while preserving background work until the brain explicitly revises or cancels it.

## Context

OpenAI Realtime can signal speech start and interrupt generation, but the current local WebSocket/audio path must also stop playback and synchronize unplayed audio. The new user turn then becomes authoritative brain input.

## Scope

### In Scope

- Track active speech/output id and playback cursor.
- On user speech start, stop local playback promptly and safely.
- Cancel/truncate active Realtime output using semantic adapter methods.
- Mark the speech request interrupted.
- Submit final interruption transcript to Core with interruption metadata.
- Brain emits intent revision and can cancel/retain work explicitly.
- SpeechScheduler drops stale output after revision.

### Out of Scope

- Automatic cancellation of every running job.
- Multi-agent branching.
- Acoustic echo cancellation implementation.

## Dependencies

Tasks 05 and 08.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Add playback cursor/output ownership required to know how much audio was actually heard.
3. Wire `realtime.speech_started` to a non-blocking local output interruption path.
4. Invoke adapter cancel/truncate as required by current WebSocket semantics.
5. Add `interrupted_speech_id` to the next authoritative completed brain turn.
6. Add brain intent revision semantics: retain jobs by default, cancel only through explicit brain decision.
7. Make scheduler invalidate queued speech whose revision/work was superseded.
8. Add race tests for brain result arriving at the same moment the user interrupts.

## Files Likely Touched

- `jarvis/runtime/realtime_audio.py`
- `jarvis/runtime/speech_scheduler.py`
- `jarvis/adapters/openai_realtime.py`
- `jarvis/core/brain_service.py`
- domain/protocol metadata as needed
- interruption/concurrency tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- speech start stops local playback;
- cancel/truncate called with active output id/cursor;
- new final user turn carries interruption metadata;
- running job remains running by default;
- explicit brain cancellation cancels selected job;
- stale queued progress is not spoken after intent revision.

## Acceptance Criteria

- User can barge in without waiting for Jarvis to finish speaking.
- Conversation history does not claim the user heard audio that was truncated.
- Interruption and task cancellation are separate decisions.

## Handoff Notes

Preserve the existing PortAudio safety lock/abort behavior. Fast interruption must not reintroduce the native access-violation class the current code comments guard against.
