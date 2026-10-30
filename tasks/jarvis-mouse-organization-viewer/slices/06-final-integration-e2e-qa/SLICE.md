# Slice 06 - Final integration and end-to-end QA

## Goal

Converge all feature branches on current main, run the complete Jarvis test suite once, perform final runtime/accessibility validation, and prove no regression to scene, Bare Hands, prefab, chat or presentation/fullscreen behavior.

## Context

This is the only Slice that runs the full repository unit/integration/E2E suite. Earlier Slices run focused tests only.

## Canonical Concepts

All contracts and UI behavior from Slices 01-05 plus active neighboring task ownership.

## Scope

### In Scope

- Fresh main/rebase/integration reconciliation.
- Full unit/integration/E2E suite once after convergence.
- Targeted browser/runtime validation of the new desktop workflow.
- Accessibility, reduced motion, focus and 200-percent zoom checks.
- Regression checks for Bare Hands resize, prefab iframe pointer shield, presentation fullscreen, global overlay stacking, chat ingress and existing scene selection commands.
- Final documentation consistency and closeout evidence.

### Out of Scope

- New product features.
- Parking regressions as Issues.
- Broad refactors unrelated to failures caused by this feature.

## Dependencies

### Hard `depends_on`

- `01-atomic-layout-and-undo-contract`
- `03-multi-object-viewer-shell`
- `04-agent-viewer-projection`
- `05-scene-integration-organize-viewer`

Slice 05 already depends on Slice 02.

### Soft `requires`

None.

### Can Start With

All implementation Slices approved and integrated.

### Produces

Release-ready evidence or a concrete rework assignment to the owning Slice.

### Integration Checkpoint

Final release gate for this feature.

## Implementation Steps

1. Confirm the integrated branch contains the approved outputs of every predecessor and no stale fixture production path.
2. Re-run conflict audit against current main and active Jarvis task branches/hot files.
3. Run the full repository unit test suite once.
4. Run full integration/E2E suite once according to current Jarvis project commands.
5. Run targeted browser scenarios: mouse-only session, keyboard-only session, multi-image viewer, document viewer, agent running/completed/unknown, organization + undo, stale undo refusal.
6. Validate 8-way resize and Shift aspect behavior with real pointer events.
7. Validate Bare Hands and keyboard resize did not regress.
8. Validate presentation/browser fullscreen remains a separate correct state machine.
9. Validate overlay stack/focus with current Settings, Studio, menus and prefab frames.
10. Validate reduced motion, keyboard focus, screen-reader semantics and 200-percent zoom.
11. Run code review and runtime validation over final diff. Run agent-trace-analysis if any agent/provider publication path changed.
12. Update closeout docs/evidence and return pass or specific blocking rework.

## Files Likely Touched

Prefer only integration fixes, tests and documentation. Any substantive ownership bug should be sent back to the responsible Slice instead of accumulating unrelated changes here.

## Architecture Constraints

- No feature expansion during final QA.
- New regression == blocking.
- Full test suite only here, once after convergence, unless a failed run requires a corrective rerun.

## Automated Validation

Complete project unit/integration/E2E suite plus the targeted feature matrix in `docs/04-testing-and-quality.md`.

## Acceptance Criteria

- Full suite passes, or every failure is proven pre-existing and unrelated with evidence accepted by the PM.
- Mouse/keyboard workflow works without Voice/Bare Hands.
- Viewer preserves Board state.
- Agent viewer is truthful and privacy-safe.
- Atomic organization/undo behavior is correct under stale state.
- Existing presentation fullscreen, prefab windows, Bare Hands, chat and selection semantics remain valid.
- Final documentation matches shipped behavior.

## Documentation Updates

Finalize canonical docs and add closeout evidence. Do not invent successful screenshots/logs before they exist.

## Handoff Notes

If a blocker belongs to an earlier Slice, return it there with evidence. Do not broaden this Slice into a catch-all implementation phase.

