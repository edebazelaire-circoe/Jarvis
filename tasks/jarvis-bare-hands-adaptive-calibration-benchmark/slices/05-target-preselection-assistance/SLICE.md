# Slice 05 — Extend target preselection and calibrate assistance

## Goal

Make target intent visible before press and tune assistance from actual selection errors.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Extend hover/preselection to stars and other actionable targets, not only manipulation-zone objects.
- Subtle highlight/name of the candidate that would be selected now.
- Keep pointer coordinates unchanged.
- Collect expected target, selected candidate, distance, ambiguity and candidate switching.
- Calibrate/tune assistance radius and selection hysteresis through trial profiles.
- Add exercises with small/nearby/moving targets.
- Bound assistance when neighboring targets become ambiguous.

### Out of Scope

- Global scene semantic redesign.
- Pointer teleport/snap.
- Infinite hit areas.

## Dependencies

01, 03, 04

## Implementation Steps

1. Freshness-check scene star semantics and target collector.
2. Generalize preview eligibility while preserving region behavior.
3. Add ambiguity metrics.
4. Feed assistance/hysteresis through trial path.
5. Add DOM/Node/runtime tests.

## Files Likely Touched

- `control_center_barehands.js` target resolver glue
- `control_center_barehands_target.js`
- calibration/contracts/tests

## Architecture Constraints

Nearest-target help must remain explainable and bounded; preview and actual capture use the same resolver decision.

## Automated Validation

Previewed target equals captured target under stable intent; neighboring-target tests limit over-assistance; stars receive preview without becoming manipulation zones.

## Acceptance Criteria

User knows before clicking which star/object Jarvis will select, and assistance can be tuned to their aiming style.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
