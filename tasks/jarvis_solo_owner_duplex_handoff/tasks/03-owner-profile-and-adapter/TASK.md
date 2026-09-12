# Task 03 — Add owner profile lifecycle and first local verifier adapter

## Goal

Provide one working local speaker-verification engine and a safe owner enrollment/profile lifecycle so hardware shadow testing can begin immediately.

## Context

No final vendor is locked. The first adapter is a baseline, not a permanent product decision.

## Scope
### In Scope
- Select one locally runnable baseline engine after verifying current package/model license and Windows compatibility.
- Recommended first investigation: sherpa-onnx; acceptable fallback: SpeechBrain or another license-compatible local verifier.
- enrollment command/API appropriate to the project;
- local profile load/save/delete metadata;
- model/profile compatibility validation;
- adapter implementing Task 02 port.

### Out of Scope
- Commercial-license negotiation.
- Final vendor selection.
- Multi-user profile management UI.

## Dependencies

Task 02.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Verify library and selected model-weight licensing before adding dependency.
2. Confirm target Windows runtime/CPU install path.
3. Define enrollment input requirements and minimum usable voice duration.
4. Store only what the engine needs; do not commit owner profile data to Git.
5. Add `.gitignore` and explicit profile path/config.
6. Implement adapter and threshold configuration.
7. Add an offline smoke fixture that is redistributable or synthetic; never commit private voice recordings.
8. Record exact engine/model/version in diagnostics.

## Files Likely Touched

- adapter package
- dependency manifest / optional voice extra
- configuration/profile storage module
- `.gitignore`
- tests
- OPERATIONS.md

## Architecture Constraints

- The engine is behind `SpeakerVerifier`.
- Owner biometric/profile material stays local.
- No private enrollment audio committed.
- Model weights must have a documented acceptable license.

## Testing Requirements

- profile create/load/reset/error paths;
- adapter deterministic smoke test where feasible;
- missing model/profile diagnostics;
- corrupt profile handling;
- no Git-tracked private profile artifact.

## Acceptance Criteria

- A real local verifier runs on the target development OS.
- An owner profile can be enrolled and loaded.
- Shadow scores are available through the common port.

## Documentation Updates

Record engine/model/license/version and enrollment procedure.

## Handoff Notes

Do not claim this engine is the final winner; Task 09 benchmarks candidates.
