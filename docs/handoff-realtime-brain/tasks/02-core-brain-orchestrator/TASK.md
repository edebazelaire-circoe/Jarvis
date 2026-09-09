# Task 02 - Add Core-Owned BrainOrchestrator Skeleton

## Goal

Create a long-lived Core service that accepts authoritative turns, owns structured brain state, invokes a fake/provider-neutral brain backend asynchronously, and publishes typed events.

## Context

Core already owns conversations, jobs, and `CoreEventBus`. This task establishes ownership before any Voice migration.

## Scope

### In Scope

- Add a focused `BrainOrchestrator` service.
- Inject `BrainBackend` at the Core composition root.
- Accept a typed authoritative turn from a service method.
- Publish `brain.turn.accepted`, safe state events, and speech events produced by a fake backend.
- Ensure backend work is asynchronous and Core service submission returns promptly.
- Define cancellation/shutdown behavior for brain tasks.

### Out of Scope

- HTTP/protocol ingress.
- Real Claude integration.
- Voice consumption of events.
- Job progress streaming.

## Dependencies

Task 01.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Create `jarvis/core/brain_service.py` or another focused Core module.
3. Inject ConversationService, CoreEventBus, JobService if needed, and BrainBackend through the constructor.
4. Implement turn acceptance, deduplication seam, structured state revision, async backend task ownership, and event publication.
5. Add a deterministic fake BrainBackend for tests.
6. Wire the service in `JarvisCoreApplication` while preserving headless startup with a fake/no-op backend.
7. Define Core shutdown behavior so owned brain tasks are cancelled/settled predictably.
8. Add tests proving submission returns before a slow fake backend completes.

## Files Likely Touched

- `jarvis/core/brain_service.py` (new)
- `jarvis/core/v2_app.py`
- `jarvis/domain/v2.py` if a tiny contract refinement is needed
- test fakes and Core unit tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- Slow fake backend test: accept returns before backend completion.
- Event ordering test: turn accepted before result speech.
- Core stop test with in-flight brain work.
- No-provider startup test.

## Acceptance Criteria

- Brain ownership is in Core.
- A turn can launch asynchronous brain work without Voice or HTTP.
- Speech events are published on `CoreEventBus`.
- Core still starts without real OpenAI/Claude/microphone dependencies.

## Handoff Notes

Do not overload `v2_services.py` if a separate `brain_service.py` yields a clearer ownership boundary.
