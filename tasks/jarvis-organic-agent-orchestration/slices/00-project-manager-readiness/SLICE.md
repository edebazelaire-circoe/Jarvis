# Slice 00 — Project Manager readiness, blind audit & Task Type gate

## Goal

Re-audit the current repository blindly, resolve the authoritative Workspace Task Type vocabulary, reconcile this handoff against current HEAD, and declare whether implementation is ready.

## Dependencies

None

## Readiness authority

This Slice is executed by the fresh Project Manager itself. It MUST audit current HEAD before reading/relying on this handoff's conclusions, then reconcile. It may edit planning/docs/metadata, not product code.

## Scope — in

- Record current HEAD and active runtime topology.
- Read repository rules and independently inspect current Work State, agent tracking, Scene, loadouts, settings, prefab/output, tests and task conventions before relying on this handoff.
- Resolve the exact Workspace Task Type labels/ids/keys and assign one to every implementation Slice.
- Reconcile product decisions with current code; update stale file paths/slice boundaries without silently changing locked product decisions.
- Choose/confirm the canonical persistence seam for durable mission history.
- Define a targeted freshness check that runs before dispatching each later Slice.

## Scope — out

- Product code changes.
- Inventing a Task Type.
- Changing locked user decisions merely to fit current implementation.

## Implementation steps

1. Read `CLAUDE.md` and record HEAD.
2. Perform the blind audit and write findings/evidence into this task LOG/reference notes.
3. Resolve Task Type vocabulary from authoritative workspace/project sources.
4. Update every Slice `metadata.json` with exact Task Type.
5. Validate the proposed Core-owned durable Mission History seam against current persistence domains and migrations.
6. Check whether role/loadout, agent spawn, Scene relation, Settings or prefab APIs changed since the handoff baseline.
7. Emit exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
8. Do not dispatch Slice 01 until state is READY.

## Files likely touched

- Handoff planning/docs only unless current repository conventions require metadata update.

## Architecture constraints

- Preserve Core Work State as canonical live execution truth.
- Preserve Scene as projection, never a second execution state machine.
- No speculative/planned future graph.
- No rigid orchestration workflow/protocol introduced under the name Work Method or Relation.
- Follow `CLAUDE.md`; do not start/restart the user's live JARVIS without explicit permission.
- Any new schema evolves through a versioned migration and schema snapshot.

## Required implementation skills

No implementation skill required.

## Independent QA

Required: qa-verification.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Human Validation

- None for this Slice.

See `human-validation.json`.

## Acceptance criteria

- [ ] Blind audit precedes reconciliation.
- [ ] HEAD and relevant canonical owners recorded.
- [ ] Task Type blocker resolved or state is HUMAN_DECISION_REQUIRED.
- [ ] All implementation Slice metadata contains exact approved Task Types before dispatch.
- [ ] No product implementation performed.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.
