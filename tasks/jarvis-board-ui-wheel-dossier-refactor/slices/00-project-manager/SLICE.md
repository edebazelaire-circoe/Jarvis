# Slice 00 — Project Manager readiness and reconciliation gate

## Goal

Blind-audit the actual repository and project state, reconcile this handoff with current HEAD, resolve Task Type from the real Workspace vocabulary, and block dispatch until the task is genuinely implementation-ready.

## Canonical context

Do **not** begin by trusting later implementation prescriptions. First audit the repository independently. Then read `../../README.md`, `../../docs/00-overview.md` through `07-human-intent-audit.md`, the reference assets, and the current canonical repository contracts.

Planning reference only: `main@cd5dfa47c53e6d8c7baa39892a5f0ffbe225bef5`.

## Dependencies

- none

## Scope / implementation steps

1. Record current HEAD SHA and active branch/worktree state.
2. Blindly identify current owners for Boards/type, interaction behaviour, Control Center shell, orbital wheel, capture, scene selection/visibility, Board memory, Artifacts, Workspace UI and agent/MCP routing.
3. Inspect active Drive tasks under `Jarvis/task/to-do`, `current` and relevant `done` tasks for overlap/conflict. The previous orbital-wheel task was merged at planning time; verify its queue state and never assume old planning is still current.
4. Resolve Workspace Task Type from the current project vocabulary. Do not invent a value. Update `task.json` and every Slice `metadata.json` consistently.
5. Read `grill-session.md` and `docs/07-human-intent-audit.md` and compare the actual code/contracts against the locked human decisions D01–D20/D28.
6. Specifically confirm the known planning-time contradiction: current docs said `board_kind` and `interaction_mode` are independent. Determine the clean migration path now.
7. Validate the proposed `empty -> assistant` and legacy interaction-mode seeding rules against real stored formats/migrations and compatibility tests.
8. Validate current wheel interaction reducer and decide what can be preserved while replacing visual/IA layers.
9. Validate that Dossier can be built as a projection over Board memory + linked Artifacts; identify any genuinely missing semantic service/API operations before Slice 05.
10. Validate existing scene `hidden` vs `archived` semantics and selection batch operations; do not introduce a third visibility disposition.
11. Reconcile likely-file lists/test names in all later Slices against HEAD.
12. Produce a readiness decision: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT` or `HUMAN_DECISION_REQUIRED`.
13. If intent is clear but this handoff is stale, repair planning docs/slice boundaries/metadata. Do not edit product code in Slice 00.
14. No coding Slice is dispatched below `READY`.

## Out of scope

- Product code changes.
- Running/restarting the user's live Jarvis instance.
- Resolving product ambiguities by silently preserving the old UX.

## Files likely touched

Planning docs and metadata in this task only. No product code.

## Architecture constraints

The human intent in `docs/01-decision-log.md` is the product source for this task, but newer canonical code may require an implementation-plan rewrite. A newer technical contract may change *how* the intent is implemented; it does not silently reinstate a rejected mode selector or duplicate storage.

## Automated validation

- `qa-verification` mandatory on the readiness package.
- Confirm all referenced source paths/tests exist or update the plan.
- Confirm JSON metadata/manifests parse.

## Acceptance criteria

- Exact HEAD and relevant task queue state recorded.
- Task Type resolved from real vocabulary.
- Known BoardKind/InteractionMode conflict has an explicit migration plan.
- Each later Slice has accurate owners/dependencies/testing targets.
- No active task conflict remains unhandled.
- Human-intent audit re-read and still valid or repaired.
- Final readiness is `READY` before dispatch.

## Documentation updates

Update planning docs if the audit changes the implementation path. Append evidence/readiness decision to `../../LOG.md`; do not fabricate implementation progress.

## Handoff notes

This Slice is a gate, not a coding task. It is allowed and expected to subdivide later Slices if current HEAD makes that safer.
