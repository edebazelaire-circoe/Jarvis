# Task 00 — Orchestrate the voice architecture program

## Goal

Drive the full handoff to completion in task order while protecting existing work and keeping documentation, implementation, tests, and task status synchronized.

## Context

This is the mandatory orchestration slice. The program introduces switchable Simple, Front Brain, and Duplex voice architectures, improves reflex behavior, adds GPT-Live client delegation, exposes prompts in Settings, and adds lifecycle/cost safety plus benchmarking.

## Scope
### In Scope
- Read README, all docs, the source transcript, and tasks/TODO.md before delegating work.
- Inspect the repository and current uncommitted changes before assigning coding slices.
- Run one focused implementation agent per task where practical.
- Update tasks/TODO.md after each completed slice and amend future TASK.md files when discoveries invalidate assumptions.
- Require tests and handoff notes before moving to the next dependent task.
- Produce a final implementation report from the provided template.

### Out of Scope
- Implementing feature code directly unless needed to unblock orchestration.
- Silently changing locked product decisions without recording the change.
- Committing unrelated pre-existing modifications.

## Dependencies
- None. Start here.

## Implementation Steps
- 1. Read the complete bundle and identify locked decisions versus provisional items.
- 2. Inspect git status and map unrelated in-progress edits that must be preserved.
- 3. Confirm task dependency order against actual repository structure.
- 4. Delegate Task 01 and continue only after its acceptance criteria pass.
- 5. For every later task, verify prerequisites, tests, docs, and TODO status before advancing.
- 6. If implementation reveals a missing slice, add a numbered task or revise later task scope and record the reason in the decision log.
- 7. At program end, run all regression and benchmark gates and write the final report.

## Files Likely Touched
- tasks/TODO.md
- docs/01-decision-log.md
- docs/09-open-questions.md
- all future TASK.md files as discoveries require
- final implementation report

## Architecture Constraints
- Operate as an orchestrator, not as a monolithic implementer.
- Do not let multiple agents edit the same high-conflict files concurrently.
- Preserve unrelated dirty working-tree changes.
- A task is not complete merely because code exists; its tests and acceptance criteria must pass.

## Testing Requirements
- Require each coding slice to run its focused tests.
- At milestones, run the relevant broader voice/settings regression suite.
- At the end, run the replay harness and cross-architecture benchmark from Tasks 19-20.

## Acceptance Criteria
- All 20 implementation slices are completed or explicitly blocked with evidence.
- tasks/TODO.md reflects reality.
- Docs match shipped behavior and unresolved items are explicit.
- Final report records tests, benchmark results, migration status, and remaining risks.

## Documentation Updates
- Keep decision log, open questions, TODO, and final report synchronized.

## Handoff Notes

Do not assume file paths in this bundle are exact. Task 01 must discover the real code map first.
