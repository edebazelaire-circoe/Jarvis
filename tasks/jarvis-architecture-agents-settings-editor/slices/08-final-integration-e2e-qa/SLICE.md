# Slice 08 - Final integration / E2E / QA convergence

## Goal

Prove the final Architecture & Agents page works as one product and that UI changes correspond to real runtime behavior.

## Context

This is the single broad validation phase. It owns the complete unit test suite and final integration/E2E campaign.

## Canonical Concepts

- task acceptance criteria
- canonical runtime architecture/routing/model/role docs

## Scope

### In Scope

- Full unit suite once.
- Full relevant integration/E2E browser suite.
- Runtime graph mutation verification.
- Brain config/delegation verification.
- Role routing candidate verification.
- Legacy migration/deep-link verification.
- Accessibility/keyboard/context-action validation.
- Visual comparison against approved references.
- Regression attribution and fix routing back to responsible Slice.

### Out of Scope

- No acceptance of known regressions as Issues.
- No human validation before machine findings are cleared.

## Dependencies

### Hard `depends_on`

- 07: final wired product must exist before convergence validation.

### Soft `requires`

None.

### Can Start With

Converged Slice 07 build and final documentation.

### Produces

- final unit/integration/E2E results;
- runtime/agent trace evidence;
- QA decision;
- human-validation-ready build only after machine checks pass.

### Integration Checkpoint

Final acceptance gate.

## Implementation Steps

1. Start full unit suite and E2E/integration suites concurrently if isolated/resources allow; otherwise run in the same final phase.
2. Execute every runtime scenario in `docs/04-testing-and-quality.md`.
3. Verify real graph behavior, not only UI toggles.
4. Verify delegation never/high modes with agent traces.
5. Verify role policy changes actual candidate selection.
6. Verify migration/deep links and absence of forbidden settings.
7. Run accessibility/keyboard/context-menu checks.
8. Compare visual composition to references while respecting canonical data.
9. Attribute failures to responsible Slice; run targeted fix verification, then repeat necessary final gate.
10. Only after machine acceptance, request the human checks in this Slice manifest.

## Files Likely Touched

Only test fixes/QA evidence and responsible implementation corrections as directed by PM.

## Architecture Constraints

Machine proof of runtime effect is mandatory. A visually correct but behaviorally fake graph fails acceptance.

## Automated Validation

This Slice **does run the complete unit test suite once**, plus integration/E2E in the same final validation phase. Capture both outcomes before acceptance.

## Acceptance Criteria

- Full unit suite passes.
- Integration/E2E passes.
- Locked edge mutation is rejected correctly.
- Editable edge mutation changes runtime behavior and restores correctly.
- Brain config model/delegation changes are effective.
- Role policy affects only the targeted role's candidate selection.
- Seven-role/current-registry rendering is data-driven.
- No Brain tab, personality controls or raw CLI technical controls leak into the normal page.
- Keyboard/touch-equivalent interactions and focus behavior pass.
- Visual result is recognizably aligned with both approved references.

## Documentation Updates

Record final validation outcomes in runtime LOG/evidence locations chosen by the PM; do not rewrite planning metadata with fictional results.

## Handoff Notes

Final convergence agent owns broad testing. Human validation follows machine acceptance.
