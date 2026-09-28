# Slice 10 — Close interaction gaps, migrate schemas, integrate and validate end-to-end

## Goal

Finish the user-facing interaction gaps and prove the new adaptive loop works on current Jarvis.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Primary click/pinch in empty space closes open context menu.
- Profile/settings/session migration from current schema.
- Remove/rename stale “calibrating” claims for metrics that do not affect runtime, or wire them before advertising them.
- End-to-end calibration agent + trial + accept + benchmark comparison.
- Verify command/MCP/tool catalog surfaces.
- Full tests, runtime validation, offline/privacy/resource cleanup.
- Real-webcam Human validation checklist and final canonical docs.
- (Added by agent 0, 2026-09-25, from Slice 04) Split the adaptive section (§12, ~1250 lines) of `control_center_barehands_contracts.js` into its own module — cost recorded in LOG (page script marker + load-order test, 3 JS readers, 6 Python node loaders, ~21 test harnesses, frozen export object).
- (Added by agent 0, from Slice 04 QA) Test that a stale compatibility-detector frame/time/slop key on a tracked hand yields a readback mismatch (mutant N09).
- (Added by agent 0, from Slice 05 QA) Tests: target ring actually drawn while the exercise forces preview (mutant S12); step-threshold boundary of the held-target jump rule (S05).
- (Added by agent 0, from Slice 07 QA) Valider/Passer buttons must refuse like voice while a trial on the current exercise is unresolved; keepAwake self-wake must not override a deliberate sleep request during calibration; after an ignored double-click, focus the new screen's title; report "Sera enregistré" reachable without scrolling at 1440x900 (or scroll affordance near content); docs/barehands-contracts.md ~3727 "les cinq phases ont été vues" to reconcile; tests for the 9 Slice 07 survivors (stale-line clearing, feelings panel hidden at report, public save() guard, clean-only release latency mixed test, trial-pending scope, detour exception in forward-rerun refusal, focus after Retour).

### Out of Scope

- New hardware tracker.
- Continuous auto-learning.
- General scene redesign.
- Playground.

## Dependencies

03, 04, 05, 06, 07, 08, 09

## Implementation Steps

1. Freshness-check all touched systems.
2. Add empty-space context dismissal through canonical interaction route.
3. Complete migrations/deprecations.
4. Run all targeted and broad suites.
5. Run agent trace analysis.
6. Produce real-webcam Human checklist and execute only after machine QA is clear.
7. Update canonical docs and operations guide.

## Files Likely Touched

- all Bare Hands modules touched by prior Slices
- context menu interaction path
- profile/settings migration
- docs/tests

## Architecture Constraints

No old profile is silently destroyed. No calibration metric is presented as behavior-changing unless a runtime reader exists. Current privacy/offline boundaries remain intact.

## Automated Validation

Existing Bare Hands behavior remains usable; new loop works end to end; Test does not mutate state; old profiles migrate; empty primary click closes context menu; Human webcam checklist passes or records exact blockers.

## Acceptance Criteria

Adaptive calibration and Test mode are ready for normal Jarvis use.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
