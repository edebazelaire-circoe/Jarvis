# Slice 00 - Project Manager readiness and reconciliation gate

## Goal
Independently audit the current repository, active task queue, canonical contracts and UI runtime before any implementation; reconcile this handoff with HEAD and decide whether work is ready to dispatch.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- none

## Scope / implementation steps
1. Perform a blind repository audit before reading the implementation prescriptions in later slices. Identify the actual owners, APIs, UI modules, test suites, layering rules and in-flight changes for the surfaces in this task.
2. Verify HEAD and record the exact SHA. Compare to planning reference `57f28a7472577f8a193303023a99b026855f09ba`.
3. Inspect neighboring Drive tasks in `Jarvis/task/to-do`, `current`, and relevant `done` handoffs for conflicts/overlap.
4. Resolve the current Workspace Task Type from the project vocabulary. Do not invent a type. Update metadata consistently before delegation.
5. Reconcile the handoff against canonical docs (`capture`, `interaction-mode`, `boards`, artifacts, Bare Hands and presentation contracts).
6. Inspect whether current code already changed after planning (especially Control Center chrome, presentation rail, capture rail, Bare Hands input).
7. Produce a readiness decision: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
8. If the plan is stale but intent is clear, revise/subdivide planning docs and slices. Do not edit product code in Slice 00.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `Repository and Drive task metadata only; planning docs may be revised, no product code.`

## Architecture constraints
- No optimistic duplicate state when a canonical Core/runtime owner exists.
- Preserve error/refusal semantics and make unknown/unconfirmed states explicit.
- Update the explicit Control Center layer registry when introducing/moving overlays.
- Author-provided text is rendered safely; previews use bounded/safe routes.
- Code slices run `/caveman` and `/coding-guideline`; frontend code additionally runs `/impeccable` and uses a Claude agent when supported by the host.

## Automated validation
- `qa-verification` is mandatory.
- Run focused unit/integration tests for the exact behavior changed, plus neighboring regression tests named by current repository contracts.
- Runtime/UI validation must use an isolated Jarvis instance/worktree/data root unless the user explicitly authorizes the live instance.

## Acceptance criteria
- Blind audit evidence exists with exact HEAD SHA and relevant source/tests.
- Every later Slice has validated dependencies/files or has been corrected.
- Task Type uses the real Workspace vocabulary.
- Conflicts with active work are resolved or execution is blocked.
- No coding Slice is dispatched unless final readiness is `READY`.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
