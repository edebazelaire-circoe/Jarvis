# Task 07 - Move Claude / Strong Brain Ownership into Core

## Goal

Remove the blocking Voice-owned `claude_task` orchestration path and reuse the existing local Claude capability behind the Core `BrainBackend` port.

## Context

Current Voice intercepts `claude_task`, calls `ClaudeGateway.ask()`, keeps the Realtime socket alive while waiting, then sends a tool result. This couples long work to the voice session and prevents independent async progress.

## Scope

### In Scope

- Implement a Core-side `BrainBackend` adapter that can reach the existing Control Center Claude agent or equivalent current backend.
- Wire it into `JarvisCoreApplication` composition/config without importing provider transport into Core business modules.
- Route authoritative brain turns to this backend asynchronously.
- Publish accepted/final speech/work events.
- Remove/bypass direct Voice -> Claude orchestration in continuous-brain mode.
- Preserve legacy mode temporarily if required for rollback.

### Out of Scope

- Perfect token-level Claude streaming.
- Multiple simultaneous agents.
- Speech queue policy (Task 08).

## Dependencies

Tasks 02, 03, and 05.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Inspect current `ControlCenter.agent_ask`, `ClaudeLocalAgent`, and `ClaudeGateway` paths before deciding whether to move, wrap, or replace the HTTP gateway.
3. Implement a provider-neutral backend adapter outside `jarvis/core`.
4. Inject it into Core's composition root.
5. Make turn submission return immediately while the backend continues.
6. Translate backend completion/failure into safe brain events and `SpeechRequest`s.
7. In continuous mode, remove `CLAUDE_TOOL` interception as the path for substantive work; the final transcript is sent to Core instead.
8. Remove Voice keepalive logic that existed only to hold a long blocking Claude tool call, when no longer needed by any path.
9. Add tests proving Voice can mute while a fake/real-adapter-simulated brain task remains owned by Core.

## Files Likely Touched

- `jarvis/runtime/claude_gateway.py` (move/refactor/deprecate)
- new `jarvis/adapters/claude_brain.py` or equivalent
- `jarvis/core/v2_app.py`
- `jarvis/core/brain_service.py`
- `jarvis/runtime/realtime_audio.py`
- `jarvis/runtime/control_center.py` only if the adapter contract requires a small endpoint change
- tests for Voice-to-Claude and Core brain integration


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- Slow fake backend remains active after Voice mute.
- Core emits final speech after backend completion.
- Backend failure becomes safe public error speech/event, not a Voice crash.
- Continuous mode no longer blocks inside `_call_claude()`.
- Legacy mode remains explicit if retained.

## Acceptance Criteria

- Strong brain lifetime is independent of Realtime lifetime.
- Voice no longer owns the Claude provider in continuous mode.
- Core uses a provider-neutral port and remains testable with a fake backend.

## Handoff Notes

Do not force a streaming Claude transport into this task. The architecture win is ownership + async event flow; richer progress can be layered in Task 10.
