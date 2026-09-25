# Slice 01 — Define adaptive calibration, telemetry, feedback, trial and benchmark contracts

## Goal

Create canonical Level-2/3 contracts before behavior changes.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Calibration-session telemetry schema using derived/scalar fields only.
- Gesture-episode schema.
- User-feedback semantic taxonomy plus raw free-text field.
- Evidence/hypothesis/trial-outcome schema.
- Trial-profile patch schema and invariants.
- Benchmark exercise/result/dimension schema.
- Documentation of persistent vs ephemeral data.

### Out of Scope

- UI redesign.
- Agent implementation.
- Runtime tuning behavior.

## Dependencies

00

## Implementation Steps

1. Freshness-check contracts/profile/recorder.
2. Define canonical schemas/constants with validators.
3. Reuse recorder whitelist patterns.
4. Add parity/documentation tests.
5. Update `docs/barehands-contracts.md`.

## Files Likely Touched

- `control_center_barehands_contracts.js`
- `barehands_profile.py` as needed for future schema placeholders
- `control_center_barehands_recorder.js` schema helpers
- `docs/barehands-contracts.md`
- tests

## Architecture Constraints

No raw image/video/full landmarks in normal calibration telemetry. Facts, feedback, hypotheses and settings remain distinct fields/types.

## Automated Validation

Schema/validator tests; privacy whitelist rejects landmarks/images/free nested payloads; JS/Python parity where mirrored.

## Acceptance Criteria

All later Slices can depend on stable named contracts rather than ad-hoc dictionaries.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
