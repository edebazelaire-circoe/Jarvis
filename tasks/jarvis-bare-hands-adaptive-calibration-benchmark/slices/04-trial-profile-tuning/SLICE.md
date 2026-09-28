# Slice 04 — Implement bounded trial profiles and expanded tunable parameters

## Goal

Allow safe temporary tuning without persisting every experiment.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Distinguish saved profile/settings, effective runtime values and session trial delta.
- `apply_trial`, `rollback_trial`, `accept_trial`.
- Session history of trial patches/outcomes.
- Safe tunable axes for press/release confirmation, click/drag separation, pointer filter responsiveness/stability, pointing intent/wake parameters and later target assistance.
- Make click and drag thresholds independently representable while maintaining actual engine invariants.
- Read back effective values after apply.

### Out of Scope

- Agent deciding which trial to choose.
- Automatic persistence.
- Unbounded arbitrary engine option mutation.

## Dependencies

01, 02, 03

## Implementation Steps

1. Define allowed trial keys/bounds from contracts.
2. Add a single composition path from saved + trial to engine.
3. Implement rollback/accept and failure receipts.
4. Extend persistence schema only for accepted values.
5. Add migration and invariant tests.

## Files Likely Touched

- `control_center_barehands.js`
- contracts/profile/test_mode API
- tests

## Architecture Constraints

Every tunable parameter has explicit bounds and a runtime reader. A parameter with no runtime effect cannot be advertised as calibration. Trial failure leaves saved state untouched.

## Automated Validation

Apply/readback/rollback/accept are deterministic; invalid patches fail loudly; current profiles migrate without data loss.

## Acceptance Criteria

Calibration can experiment safely and revert immediately.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
