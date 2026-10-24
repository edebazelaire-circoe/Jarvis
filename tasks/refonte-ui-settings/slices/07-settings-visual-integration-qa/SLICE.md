# Slice 07 — Settings visual integration and final QA

## Goal

Converge the five page refactors, resolve shared styling/integration conflicts, and prove the Settings visual redesign is coherent, responsive, accessible and regression-safe as a whole.

## Context

This Slice is the final convergence gate after all five reference-driven page Slices are complete. It owns cross-page consistency, shared hot-file reconciliation and the final screenshot/QA campaign.

## Canonical Concepts

- all five files in `references/ui/`
- `docs/04-testing-and-quality.md`
- `docs/06-visual-contract.md`
- approved outputs from Slices 02–06

## Scope

### In Scope

- Merge/reconcile shared CSS/component changes from page Slices.
- Ensure all targeted views use one coherent Settings visual system.
- Validate navigation/deep links/tab state across Personalisation, Architecture & Agents and Mémoire & connaissances.
- Validate overlays/dropdowns/floating panels do not conflict in z-index/focus behavior.
- Verify responsive breakpoints and scroll ownership across all five views.
- Run final screenshot regression set at the exact reference viewports plus narrower desktop/tablet widths.
- Run repository-appropriate final unit/integration/E2E suite.
- Fix regressions introduced by the refactor.
- Prepare final Human validation packet with reference/implementation image pairs.

### Out of Scope

- Do not add new product features unrelated to visual integration.
- Do not reopen canonical runtime decisions merely to improve screenshot similarity.

## Dependencies

- `02-personnalisation-ui`
- `03-architecture-agents-subagents-ui`
- `04-architecture-agents-architecture-ui`
- `05-memory-settings-ui`
- `06-memory-center-ui`

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent when supported.
2. Rebase/reconcile page branches and eliminate duplicated/conflicting shared styles or components.
3. Verify shared visual tokens are used consistently and page-specific overrides are justified.
4. Navigate through all targeted views in a real runtime session and test open/close/tab/profile/dropdown/popup behaviors.
5. Run automated accessibility checks available in the repository plus targeted keyboard navigation passes.
6. Capture the five final screenshots at exact reference dimensions:
   - Personalisation: 1672×941;
   - Sous-agents: 1254×1254;
   - Architecture: 1254×1254 with brain panel open;
   - Mémoire: 1254×1254;
   - Memory Center: 1254×1254.
7. Capture at least one narrower viewport for every view and verify no page-level horizontal overflow.
8. Compare reference/implementation pairs and fix unexplained hierarchy, spacing, typography or layering divergences.
9. Run final repository-appropriate unit/integration/E2E suites. Run independent suites concurrently when safe.
10. Require final `qa-verification`, `code-review` and `runtime-validation`; add `agent-trace-analysis` only if this task ended up changing agent/runtime behavior despite the UI-only intent.
11. Present the final five visual pairs to Human validation after machine QA is clean.

## Files Likely Touched

Shared Settings styles/components/tests plus any page files requiring integration conflict resolution.

## Architecture Constraints

- One coherent design system; no copy-pasted divergent page theme.
- Canonical backend/runtime semantics remain unchanged unless a separately justified fix was necessary and validated.
- Regressions introduced by the task are blocking.

## Automated Validation

- Final build/lint/type checks pass.
- Final repository-appropriate unit/integration/E2E suites pass.
- All five deterministic screenshot cases pass or have documented, Human-approved intentional differences.
- Accessibility/focus checks pass for tabs, dropdowns, switches, selects, tables and floating panel.
- No page-level horizontal overflow at supported target widths and 125% zoom.

## Acceptance Criteria

- All five target views visibly belong to the same Settings redesign.
- Each page has direct screenshot evidence against its supplied reference.
- Navigation and interactive behavior remain stable.
- No user-visible regressions or fake data were introduced.
- Human validation approves the final visual packet.

## Documentation Updates

Update visual-system documentation, screenshot fixture documentation and any route/component ownership docs changed during convergence.

## Handoff Notes

Do not accept "close enough" without side-by-side evidence; the explicit purpose of this task is to make the visual work concrete and verifiable.
