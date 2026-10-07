# Slice 00 — Project Manager readiness gate

## Goal

Act as the Project Manager and orchestrator for this handoff. Execute this Slice yourself; do not delegate it. Reach an explicit readiness state before dispatching implementation work.

## Context

This task was recreated after the previous Presentation task was deleted. Several Jarvis subsystems have evolved since the original discussion, especially ambient capture, Board/Session runtime, Tool Brain planning and Scene/Prefab work.

## Canonical Concepts

Presentation interaction mode, ambient authority, Session/Context, Tool Brain, Scene/Prefab runtime, canonical conversation events.

## Scope

### In Scope

- Perform an independent blind audit of the current repository based only on this task's product goal before reading the handoff's documentation-level conclusions.
- Inspect current Presentation-related code/docs, mode settings, ambient lane, context assembly, speech arbitration, Control Center, event timeline and tests.
- Inspect current state/public contracts of external handoffs named in `README.md`.
- Reconcile repository reality with this handoff.
- Resolve every Slice to an existing Workspace Task Type.
- Repair/split/reorder/supersede Slices if repository reality requires it.
- Produce one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.

### Out of Scope

- Editing product code.
- Inventing missing Task Type labels.
- Dispatching implementation below `READY`.

## Dependencies

None.

## Implementation Steps

1. Blind-audit repository and current task state.
2. Record canonical file/contract references and any already-implemented Presentation behavior.
3. Compare that evidence against the handoff only after the blind audit.
4. Verify dependency states for Tool Brain and Scene/Prefab work.
5. Resolve Slice Task Types and Work Agents according to current workspace rules.
6. Amend the handoff if needed.
7. Record readiness state and blockers.
8. Before each later Slice dispatch, perform a targeted freshness check of the files/contracts that Slice depends on.

## Files Likely Touched

Task handoff files only if planning repair is required.

## Architecture Constraints

Repository reality wins. Preserve already-landed canonical contracts. No product-code edits in Slice 00.

## Automated Validation

Validate Slice IDs/dependencies, unique Human-check IDs, canonical references, Task Type validity, and Drive/local handoff consistency.

## Acceptance Criteria

- Blind audit completed before relying on this handoff's conclusions.
- External dependency status is known.
- All Slices have valid Task Types or are blocked explicitly.
- Readiness state is recorded.
- No implementation dispatch occurs below `READY`.

## Documentation Updates

Update planning docs only where repository drift makes them materially wrong.

## Handoff Notes

Every implemented Slice later receives baseline `qa-verification`; code adds `code-review`; runtime/user-visible changes add `runtime-validation`; prompt/tool/routing/runtime changes add `agent-trace-analysis`. Human validation never substitutes for machine QA.
