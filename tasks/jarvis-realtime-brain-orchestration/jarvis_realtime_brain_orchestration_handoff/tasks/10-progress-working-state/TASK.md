# Task 10 - Add Structured Work Progress and Public Brain State

## Goal

Let long brain work produce useful incremental public updates/questions without exposing hidden reasoning or coupling workers directly to speech.

## Context

The existing `JobService` emits completion/failure but no structured progress. The desired experience needs the brain to know enough about ongoing work to occasionally speak useful status or ask a question.

## Scope

### In Scope

- Add a provider-neutral job/work progress emission seam.
- Maintain/update safe `BrainWorkingState` revisions.
- Publish `brain.work.started/progress/completed/failed` events.
- Let BrainOrchestrator decide when progress becomes a `SpeechRequest`.
- Support brain-generated questions that can be answered while work remains active.
- Persist only high-level public/restart-relevant state.

### Out of Scope

- Raw model token/thought streaming.
- Direct worker-to-Voice speech.
- Multiple orchestrator instances.

## Dependencies

Tasks 07 and 08.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Design the smallest `JobProgress`/event sink compatible with existing `JobWorker` implementations.
3. Extend `JobService` or worker context so progress can reach `CoreEventBus` safely.
4. Update BrainOrchestrator working state from work lifecycle/progress.
5. Add coalescing/rate-limiting policy so frequent worker progress does not become speech spam.
6. Add question semantics: brain may issue a high-priority question while retaining current work state.
7. Add persistence/rehydration only for state necessary across Core restart or Voice reconnect.
8. Add tests that explicitly reject hidden reasoning fields and avoid transcript content in default diagnostics.

## Files Likely Touched

- `jarvis/core/v2_services.py`
- `jarvis/core/brain_service.py`
- `jarvis/ports/v2.py`
- `jarvis/domain/v2.py`
- state repository/schema only if justified
- job/brain/scheduler tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- progress event order and correlation ids;
- progress coalescing/rate limiting;
- final result supersedes progress speech;
- question can be emitted before job completion;
- state rehydration test if persistence is added;
- explicit check that no `thoughts`/raw reasoning is persisted.

## Acceptance Criteria

- Brain can produce useful incremental public status without exposing chain-of-thought.
- Workers report facts/progress; brain decides speech.
- High-frequency progress cannot flood Voice.

## Handoff Notes

If existing workers cannot report progress yet, land the contract plus one representative fake/worker implementation. Do not retrofit every worker in one task unless necessary for acceptance.
