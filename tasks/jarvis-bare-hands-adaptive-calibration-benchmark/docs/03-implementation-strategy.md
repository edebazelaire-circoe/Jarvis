# Implementation strategy

## Rollout order

1. Freeze telemetry, feedback, trial-profile and benchmark contracts.
2. Add gesture episode segmentation and timing metrics.
3. Add negative examples and canonical pointing-intent/pointer visibility.
4. Add bounded trial profile application/rollback/accept.
5. Extend target preselection and assistance calibration.
6. Add the scoped calibration agent + voice loop with hypothesis tracking.
7. Rebuild calibration exercises around result/review/retry rather than auto-advance.
8. Build the deterministic benchmark engine and scoring.
9. Add Test UI and before/after comparison.
10. Close interaction-polish gaps, migrate schemas, run end-to-end QA and real-webcam Human validation.

## Migration constraints

- Existing v2 profiles/settings must continue to load safely.
- Schema upgrades must archive or migrate older profile blocks, never silently overwrite foreign/newer versions.
- Existing `barehands_calibrate` remains a valid entry point.
- Deprecated `barehands_tutorial` compatibility remains as currently documented unless Slice 00 finds a newer migration.
- Current full-screen shell and existing real-window practice adapter are reused.
- Existing recorder privacy whitelist is the preferred diagnostic seam.

## Freshness hotspots

Before each dependent Slice, re-check current voice/agent runtime, MCP catalog work, scene/star semantics, Bare Hands command routing, current settings schema, and `docs/barehands-contracts.md`. These areas are moving quickly.
