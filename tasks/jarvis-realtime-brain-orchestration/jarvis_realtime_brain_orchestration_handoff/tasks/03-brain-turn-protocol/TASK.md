# Task 03 - Add Authoritative Brain-Turn Protocol Ingress

## Goal

Expose one authenticated local protocol operation that persists a completed user turn exactly once and dispatches it to `BrainOrchestrator`, while reusing the existing `/v1/events` stream for egress.

## Context

Today Voice can append a turn separately through `LocalCoreClient.append_turn()`. The new async path needs one atomic/authoritative entrypoint to prevent duplicate persistence and duplicate brain execution.

## Scope

### In Scope

- Add a versioned loopback endpoint for conversation brain turns.
- Add matching `LocalCoreClient.submit_brain_turn()`.
- Deduplicate by correlation/provider item id as appropriate.
- Persist the turn and dispatch brain work through one service path.
- Verify `brain.*` events are delivered over existing `/v1/events`.

### Out of Scope

- Voice calling the new endpoint.
- Changing provider transport.
- Replacing `/v1/events` with another bus.

## Dependencies

Task 02.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Choose the final endpoint name, preferably nested under conversation id.
3. Add request validation for text, correlation id, optional provider item id, and interruption metadata.
4. Route to a Core service method that owns persistence + brain dispatch.
5. Ensure retries are idempotent and do not produce duplicate user turns/work.
6. Add `LocalCoreClient` support.
7. Add protocol tests for success, duplicate retry, missing conversation, malformed body, and event streaming.

## Files Likely Touched

- `jarvis/protocol/server.py`
- `jarvis/protocol/client.py`
- `jarvis/core/brain_service.py`
- `jarvis/core/v2_services.py` only if ConversationService needs an idempotent helper
- protocol tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- Endpoint/client roundtrip using fake Core/backend.
- Duplicate request persists/dispatches once.
- `/v1/events` delivers `brain.speech.requested` with original conversation id.
- Existing auth/protocol-version tests continue to pass.

## Acceptance Criteria

- Voice has one future method to submit an authoritative final turn.
- Core responds quickly without waiting for the strong brain.
- No second IPC/event server is introduced.

## Handoff Notes

Avoid a transaction illusion if the existing repository cannot atomically combine persistence and task launch. Guarantee logical idempotency and document the crash window instead of hiding it.
