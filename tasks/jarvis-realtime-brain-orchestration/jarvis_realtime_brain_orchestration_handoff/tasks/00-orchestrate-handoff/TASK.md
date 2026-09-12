# Task 00 - Orchestrate the Handoff

## Goal

Take ownership of the complete implementation sequence, verify this handoff against the current Jarvis repository, and execute tasks in a safe ordered manner.

## Context

This handoff was reconstructed from an architecture discussion plus a live read of the repository. Jarvis is actively evolving, so implementation must begin by checking whether the source snapshot is still accurate.

## Scope

### In Scope

- Read all files under `docs/` and `tasks/TODO.md`.
- Inspect the current Git branch/status and relevant current files.
- Verify the architecture assumptions listed in `tasks/TODO.md`.
- Load `/caveman` and `/coding-guideline` before any coding slice.
- Maintain task status and update/split/reorder raw tasks when real code discoveries require it.
- Enforce completion/testing of one task before proceeding to dependent tasks.

### Out of Scope

- Implementing the entire architecture inside this orchestration task.
- Silently changing locked decisions.
- Skipping tests because later tasks will test the same layer.

## Dependencies

None.

## Implementation Steps

1. Read `README.md`, `docs/00-overview.md` through `docs/07-open-questions.md`, and `tasks/TODO.md`.
2. Inspect current repository status and branch.
3. Re-read the source files listed in the TODO snapshot.
4. Compare current code behavior against `docs/06-migration-map.md`.
5. If a material mismatch exists, update the affected task files before coding and record the reason.
6. Confirm that the first executable coding slice remains Task 01.
7. For each later task, load required coding skills, run pre-change tests, implement, run post-change tests, update status, then continue.
8. Stop the sequence if a locked decision becomes impossible and document the conflict rather than improvising a contradictory architecture.

## Files Likely Touched

- This handoff's `tasks/TODO.md` and affected task files when the plan must be adjusted.
- No production file is required to change in Task 00.

## Architecture Constraints

- Act as the orchestration owner, not as a single monolithic coding agent.
- Preserve the locked boundary: Realtime has reflexes; Core brain owns truth and intent.
- Preserve the background/mute semantics and provider-neutral Core.

## Testing Requirements

- Run a quick current baseline for the relevant V2 unit tests before Task 01.
- Record any pre-existing failures separately from changes introduced later.

## Acceptance Criteria

- Current repository assumptions are verified or the raw task plan is updated to match reality.
- Baseline test status is recorded.
- Task 01 is ready to execute with no unresolved architecture blocker.
- The orchestrator has explicitly committed to the ordered task/checkpoint workflow.

## Documentation Updates

Update `tasks/TODO.md` if the repository has changed enough to alter dependencies or slicing.

## Handoff Notes

Do not treat the task files as immutable. They are implementation plans. Preserve locked architectural decisions, but improve task slicing when the current code proves a different boundary is safer.
