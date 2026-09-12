# Task 08 - Add Voice SpeechScheduler for Brain Output

## Goal

Consume brain speech events from Core and render them through the active Realtime session with priority, expiry, supersession, and provenance.

## Context

Core already streams events over `/v1/events`; after Task 07 it can produce brain speech independent of Voice. Voice needs one component responsible for deciding what should be spoken now.

## Scope

### In Scope

- Add a `SpeechScheduler` in the Voice/runtime layer.
- Subscribe to `LocalCoreClient.events()` while Voice is active.
- Filter by conversation id and valid speech event type.
- Queue by priority and drop expired/superseded speech.
- Ensure final result supersedes obsolete progress for the same work.
- Send selected speech via the new faithful Realtime speech method.
- Persist actual assistant output with brain provenance when completed.
- Emit delivery diagnostics.

### Out of Scope

- Barge-in truncation (Task 09).
- Job progress generation (Task 10).
- Durable replay of every speech event.

## Dependencies

Tasks 03, 04, and 07.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Implement a focused scheduler independent from the Realtime provider adapter.
3. Start/stop its Core event subscription with the ACTIVE Voice transport.
4. Implement priority, TTL, `supersedes_key`, and conversation filtering.
5. Keep one active brain speech output at a time.
6. On completion, append assistant turn with `source=brain.speech`, `speech_id`, and `work_id` metadata.
7. If Voice is BACKGROUND, do not speak live; allow Core notification/state mechanisms to handle later user awareness.
8. Add deterministic scheduling tests.

## Files Likely Touched

- new `jarvis/runtime/speech_scheduler.py`
- `jarvis/runtime/voice_v2.py`
- `jarvis/protocol/client.py` only if event-consumer ergonomics need a focused helper
- conversation turn metadata handling
- scheduler unit tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- priority ordering;
- expiry drop;
- supersession drop;
- conversation filtering;
- Core event stream disconnect/reconnect behavior;
- final assistant-turn provenance;
- no speech after Voice transitions to BACKGROUND.

## Acceptance Criteria

- Brain can ask Voice to speak without direct access to the Realtime session.
- Stale progress does not pile up and play later.
- The text spoken is faithful to the brain request.

## Handoff Notes

Do not make the scheduler rewrite text. It schedules public text; wording belongs to the brain and vocal rendering belongs to Realtime.
