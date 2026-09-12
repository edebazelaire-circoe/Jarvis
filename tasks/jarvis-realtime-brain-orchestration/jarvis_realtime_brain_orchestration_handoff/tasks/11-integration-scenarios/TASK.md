# Task 11 - Add End-to-End Async Conversation Scenarios

## Goal

Prove the architecture as a coherent system with deterministic multi-component tests before relying on live workstation validation.

## Context

By this point the individual layers should exist. This task tests the actual behaviors the user asked for: quick surface interaction, background brain work, ongoing conversation, and interruption.

## Scope

### In Scope

- Build integration fakes/harness for Voice + local Core protocol + fake Realtime + fake slow brain backend.
- Cover the primary async conversation scenarios.
- Cover mute/background and reactivation.
- Cover event stream disconnect/reconnect and stale speech handling.
- Add regression gates for one-session multiple turns.

### Out of Scope

- Real OpenAI benchmark claims.
- Real microphone acoustic acceptance (Task 12).

## Dependencies

Tasks 05 through 10.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Build a deterministic fake Realtime session that can emit speech/transcript/output ids and accept speech/cancel/truncate commands.
3. Build a slow fake BrainBackend that emits delayed progress/question/result events.
4. Scenario: user asks long task -> fast surface ack -> brain work starts -> progress spoken -> result spoken.
5. Scenario: user interrupts progress -> output stops -> new intent revises work -> result reflects latest intent.
6. Scenario: user says `Jarvis Mute` while work runs -> Voice BACKGROUND -> work completes in Core -> no stale live speech -> later activation retains context.
7. Scenario: ambient noise events during LIVE do not keep session alive.
8. Scenario: Core event WebSocket drops and reconnects; expired progress is not replayed/spoken.
9. Run the relevant full V2 unit/integration suite.

## Files Likely Touched

- integration test harness/fakes
- existing V2 voice tests
- only small production fixes exposed by integration tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

All scenarios above must be automated and deterministic. No paid/network API is required for the default suite.

## Acceptance Criteria

- The requested conversational architecture is demonstrated end to end with fakes.
- No scenario requires keeping a blocking Realtime tool call open for the strong brain.
- Voice mute does not terminate Core work.
- Interruption does not automatically cancel work.

## Handoff Notes

If this task exposes a large production defect, create a focused new task rather than hiding a major refactor inside the integration-test slice. Update `tasks/TODO.md` accordingly.
