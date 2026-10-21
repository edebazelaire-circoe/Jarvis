# Slice 10 - Integrated accessibility and release QA

> Authored by agent 0 during Slice 00: the Drive publication of this handoff contained an empty folder for this Slice. Content is derived strictly from `docs/02`, `docs/03`, `docs/04`, `docs/06` and `docs/07`; no new product decision is introduced.

## Goal

Validate the whole Settings experience end to end before Human acceptance.

## Context

All categories are migrated and legacy machinery removed. This Slice proves the result in a real browser against a sandbox Core, never the live JARVIS.

## Canonical Concepts

- `docs/04-testing-and-quality.md`
- all Slice acceptance criteria

## Scope

### In Scope

- Full regression sweep of the Settings-related suites (exact list in LOG.md, Slice 00).
- Sandbox run (own data root, own ports) of Core + Control Center; browser walkthrough of all six categories.
- Keyboard-only traversal, visible focus, live regions, reduced motion, contrast of disabled/read-only states.
- Screenshots at common desktop sizes, 100% and 125% zoom; no horizontal overflow.
- Controller cleanup when switching categories (no leaked timers/requests).
- Consolidated `HUMAN-CHECKS.md` with every HV-SETTINGS check.

### Out of Scope

- New features. Findings go back to the owning Slice as rework.

## Dependencies

- `09-legacy-routing-and-deeplink-compatibility`

## Implementation Steps

1. Merge `origin/main` into the task branch; re-run the sweep.
2. Sandbox runtime validation with evidence (screenshots, console logs).
3. Accessibility audit.
4. Write `HUMAN-CHECKS.md`.

## Files Likely Touched

- tests only, plus `tasks/jarvis-settings-ui-reorganization/HUMAN-CHECKS.md`

## Automated Validation

- All Settings suites green (pre-existing failures on main documented, not hidden).
- Browser walkthrough evidence attached.

## Acceptance Criteria

- Machine validation exhausted; Human checks are the only remaining step.

## Documentation Updates

Final `docs/settings/INDEX.md` review.

## Handoff Notes

Human validation never replaces QA.
