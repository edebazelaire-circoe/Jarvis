# Slice 07 — Prove migration, personalization, catalog UX and rollout

## Goal

Validate the complete settings redesign, backward compatibility and documentation before rollout.

## Context

This Slice is the gate preventing a cosmetic redesign from breaking routing or voice configuration semantics.

## Canonical Concepts

- saved-settings migration
- routing regression
- personalization persistence
- catalog availability truth
- voice category completeness
- release documentation

## Scope

### In Scope

- Run end-to-end automated and runtime UI QA.
- Verify old saved preferences migrate without surprise.
- Verify no backend routing regression from removing UI.
- Finalize docs/rollout notes.

### Out of Scope

- Additional model providers unrelated to current architecture.

## Dependencies

05, 06

## Implementation Steps

1. Create fixtures from pre-redesign settings files.
2. Run API/UI migration and reload tests.
3. Run routing delegation smoke test under Auto and Dupliqué according to audited semantics.
4. Run catalog truth-state tests with missing credentials/CLI/model.
5. Run voice settings save/load across all tabs.
6. Execute QA composition and final Human walkthrough.

## Files Likely Touched

- `tests/integration/*settings*`
- `tests/integration/*routing*`
- `tests/*control_center*`
- `docs/*`

## Architecture Constraints

- No UI success may mask backend config write failure.
- Availability claims remain source-backed after reload.

## Automated Validation

- Full release verifier.
- Migration tests.
- Runtime UI validation.
- Routing/voice regression smoke tests.

## Acceptance Criteria

- Old configurations migrate safely.
- No Aiguillage primary UI remains.
- Auto/Dupliqué and personalization persist.
- Both catalogs correctly represent availability.
- Voice settings are complete and categorized.
- All QA gates pass.

## Documentation Updates

Publish canonical Settings IA, catalog provenance policy, migration notes, and operator troubleshooting.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
