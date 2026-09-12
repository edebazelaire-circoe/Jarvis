# Task 00 — Orchestrate the implementation

## Goal

Own the complete execution of this handoff, keep the task graph accurate, and ensure every slice is verified before the next one begins.

## Context

The handoff combines a reviewed `main` baseline with a later architectural correction. Much of the duplex implementation is already good and must be preserved. The main implementation deltas are owner-aware audio gating and Core-owned detailed work state.

## Scope
### In Scope
- Read all root/docs files before dispatching implementation.
- Refresh `main` and compare it to the recorded baseline commit.
- Update `tasks/TODO.md` if repository drift changes prerequisites.
- Execute or delegate tasks in dependency order.
- Require task-level tests and acceptance evidence.
- Maintain implementation notes and final report.

### Out of Scope
- Coding unrelated features.
- Replacing technologies without benchmark evidence.

## Dependencies

None.

## Implementation Steps

1. Read `README.md`, all `docs/*.md`, and `tasks/TODO.md`.
2. Inspect current `main` and record drift since `8fc7a117...`.
3. For each coding task, ensure the coding agent loads `/caveman` and `/coding-guideline`.
4. Before starting a task, verify dependencies are complete.
5. After each task, run its required tests and update TODO status.
6. If implementation reality contradicts this plan, edit the raw task files/TODO before proceeding; do not silently diverge.
7. At completion, run the full regression/release suite and write the final implementation report.

## Files Likely Touched

- This handoff's `tasks/TODO.md` during orchestration.
- Project docs/status files as implementation proceeds.

## Architecture Constraints

- Preserve Core authority.
- Preserve existing AEC/concurrency unless evidence requires change.
- No UI-as-source-of-truth shortcut.
- No vendor hardwiring above typed adapter boundaries.

## Testing Requirements

Orchestrator does not implement behavior directly, but it must ensure every task's tests pass before advancing.

## Acceptance Criteria

- Current repository drift is understood.
- Task ordering reflects actual dependencies.
- Every completed task has evidence.
- Final regression suite and report exist.

## Documentation Updates

Maintain TODO and final implementation report.

## Handoff Notes

This is the controlling task. Do not skip it even if one coding task looks obvious.
