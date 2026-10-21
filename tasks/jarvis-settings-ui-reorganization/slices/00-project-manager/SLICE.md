# Slice 00 - Project Manager readiness and reconciliation gate

## Goal

You are the Project Manager and orchestrator for this handoff. Execute this Slice yourself; do not delegate it. Establish whether the handoff is safe to execute against the current repository, repair the plan if necessary, and resolve Work Agent Task Types before dispatch.

## Context

This rebuilt handoff was authored from `main` at `20292e5c292dc8ab9a012ccf00ecb82b5c7f820e`. Settings are composed from `control_center.html` plus multiple injected modules. A previous Settings IA contract exists under `tasks/jarvis-settings-model-catalog-ux/`, but the user has now locked a new six-category top-level organization. `main` changed between the original audit and this rebuild, including a new top-level Sub-agents surface.

## Canonical Concepts

- `docs/00-overview.md`
- `docs/01-decision-log.md`
- `docs/02-architecture.md`
- `docs/05-documentation-levels.md`
- `docs/06-current-settings-inventory.md`
- `docs/07-target-settings-map.md`
- `docs/settings/INDEX.md`
- `docs/settings/memory.md`
- `docs/voice-settings-schema.md`
- previous IA evidence: `tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json`

## Scope

### In Scope

- Perform an independent blind repository/context audit based only on Slice goals before reading this handoff's documentation-level conclusions.
- Inventory current Settings entry points, dynamic registration/injection, schemas, persistence and tests.
- Compare the blind audit with the handoff and record discrepancies.
- Check for newer settings/personality/profile/sub-agent work that landed after the source SHA.
- Resolve valid Workspace Task Types for every implementation Slice; do not invent types.
- Split, reorder, supersede or add Slices if current code requires it.
- Return one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.

### Out of Scope

- Do not edit product code.
- Do not implement the new Settings UI.

## Dependencies

None.

## Implementation Steps

1. Blind-audit current `main`: Settings HTML/runtime modules, tests, docs and active feature injections.
2. Check current repository SHA and compare with the source snapshot.
3. Reconcile current behavior against the six-category target map.
4. Identify persistence/runtime semantics that would be accidentally changed by pure UI relocation.
5. Resolve current Workspace Task Type vocabulary and update Slice metadata before dispatch.
6. Confirm required skills and frontend Claude routing are available; if unavailable, document the exact host limitation.
7. Repair the handoff if stale: update contracts, split/reorder Slices, or add prerequisites.
8. Record readiness state and only dispatch if `READY`.
9. Immediately before every later Slice dispatch, perform a targeted freshness check of that Slice's files/contracts/tests.

## Files Likely Touched

Planning/handoff files only. Product code must not be edited in Slice 00.

## Architecture Constraints

- The Project Manager owns orchestration and planning repair, not product implementation.
- New implementation work remains delegated one Work Agent per Slice.
- Do not weaken locked user decisions merely because the old IA contract differs; record a conflict only if live runtime constraints make them incompatible.

## Automated Validation

- Verify Slice IDs and dependency graph are internally consistent.
- Verify every Slice has `metadata.json` and `human-validation.json`.
- Verify Human check IDs are globally unique.
- Verify canonical references still exist on current `main`.
- Verify there are exactly six target top-level categories in the new planning contract.

## Acceptance Criteria

- Blind audit completed before relying on handoff conclusions.
- Discrepancies reconciled.
- One readiness state recorded.
- No implementation dispatch below `READY`.
- Every implementation Slice has a valid Workspace Task Type or remains explicitly blocked.

## Documentation Updates

Update handoff docs only when the live audit proves they are stale.

## Handoff Notes

Every implemented Slice requires baseline `qa-verification`; code adds `code-review`; user-visible/runtime work adds `runtime-validation`; agent runtime changes add `agent-trace-analysis` with real traces.
