# Task 04 - Extend Realtime Event and Output-Control Adapter

## Goal

Give the Voice runtime the semantic Realtime hooks required for continuous input, faithful brain speech, and WebSocket barge-in.

## Context

The current adapter maps final input transcripts and audio output but lacks transcript deltas, stable output ids, explicit output cancel/truncate, and a correct brain-speech injection primitive.

## Scope

### In Scope

- Map streaming input transcription deltas with provider item ids.
- Preserve completed transcript mapping with ids/correlation metadata.
- Map response/output identifiers needed for playback interruption.
- Add faithful `speak(SpeechRequest)` or equivalent semantic method.
- Add output cancel and truncate/playback-cursor methods.
- Add deterministic fake-WebSocket tests for provider messages and normalized events.

### Out of Scope

- Continuous Voice lifecycle behavior.
- Speech scheduling.
- Brain orchestration.
- WebRTC migration.

## Dependencies

Task 01.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Re-check current OpenAI Realtime API event names before coding.
3. Extend `OpenAIRealtimeSession.events()` to normalize transcript delta/completed and response/output ids.
4. Implement faithful brain speech without injecting a fake role=`user` conversation item.
5. Implement semantic cancel/truncate required by WebSocket playback interruption.
6. Track only the minimal provider state inside the adapter/session.
7. Update fakes implementing `RealtimeSession`.
8. Add/adjust adapter unit tests.

## Files Likely Touched

- `jarvis/adapters/openai_realtime.py`
- `jarvis/ports/v2.py`
- `tests/unit/test_v2_voice_toggle.py`
- new focused Realtime adapter tests if cleaner


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- Fake WebSocket tests assert exact outbound event sequence for speak/cancel/truncate.
- Transcript delta and completed events include provider item ids.
- Existing server-VAD tests remain green or are intentionally updated to the new normalized contract.
- No networked test in default suite.

## Acceptance Criteria

- Runtime can know which Realtime output is currently playing.
- Runtime can stop/cancel/truncate that output semantically.
- Runtime can ask Realtime to speak brain text without pretending the brain text came from the user.
- Core remains unaware of OpenAI event JSON.

## Handoff Notes

Keep transport details in the adapter. Do not expose raw `conversation.item.truncate` payloads through the Core protocol.
