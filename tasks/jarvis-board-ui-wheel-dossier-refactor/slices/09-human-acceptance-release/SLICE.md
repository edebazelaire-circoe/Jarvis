# Slice 09 — Final human acceptance and release gate

## Goal

Run the explicit human validation only after machine QA is green, compare the real implementation with the design intent/reference assets, and decide release/rework.

## Dependencies

- `08-integration-accessibility-regression` with all mandatory QA evidence passing

## Scope / implementation steps

1. Project Manager verifies no automated finding remains open from this task.
2. Re-read `../../grill-session.md` and `../../docs/07-human-intent-audit.md` before inviting human acceptance.
3. Execute all `human-validation.json` checks from earlier Slices plus the final holistic check below.
4. Show actual runtime screenshots/states, not generated concept art, for Board shell, wheel categories, active recordings and Dossier.
5. Ask human to judge visual hierarchy/style, not only whether buttons work.
6. If human feedback contradicts a locked decision or reveals a regression, return to the responsible Slice; do not patch around it in release notes.
7. Record final decision/evidence/commit SHA and rollback instructions in `../../LOG.md`.

## Out of scope

- Coding product changes directly in this release gate. Rework goes back to the owning Slice.

## Architecture constraints

Human acceptance cannot waive a known safety/data-loss regression without an explicit new decision. Aesthetic preferences may be adjusted if they preserve locked semantics.

## Automated validation

This Slice itself does not replace prior QA. Verify evidence links and final build/revision only.

## Acceptance criteria

- Human explicitly accepts or rejects the refactor after using the real UI.
- Final state matches the human-intent audit.
- Wheel style is materially updated and only one contextual submenu appears.
- Main Board view is visibly less cluttered.
- Board switcher/type mental model is understandable without explaining “interaction mode”.
- Dossier is usable as a human/agent shared documentary workspace.
- Release/rollback notes are complete.

## Documentation updates

Final `LOG.md` acceptance entry and any release notes required by the repository.
