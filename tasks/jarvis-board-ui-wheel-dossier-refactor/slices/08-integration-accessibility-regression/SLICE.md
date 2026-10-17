# Slice 08 — Integration, accessibility, trace and regression closure

## Goal

Prove the refactor works as one system, remove compatibility debris that is no longer needed, close canonical documentation contradictions, and collect machine evidence before human acceptance.

## Dependencies

- `04-jarvis-runtime-capture-controls`
- `07-dossier-fullscreen-ui`

## Scope / implementation steps

1. Run a fresh code/docs audit for old UI/module/route references: interaction-mode selector, top-left Boards HUD, permanent hidden chip, old first-level capture wedges and duplicate settings/navigation.
2. Remove dead page composition/imports/handlers after parity is proven; do not leave hidden duplicate systems polling in background.
3. Exercise Board switch across all three types, including restart/resume and Presentation behaviour, with Dossier closed/open.
4. Exercise wheel state while right rail/panels/chat/Dossier/capture indicators appear; fix z-index/safe-area collisions in both themes.
5. Exercise mouse, keyboard, screen-reader semantics, reduced motion, forced colours and Bare Hands paths.
6. Run capture concurrency/status-loss/reload scenarios.
7. Run Dossier Ranger/Present/edit flows across canonical API and agent/MCP path; collect real agent traces showing correct Board attribution and no arbitrary filesystem bypass.
8. Verify Board context seen by agent after a human Dossier correction. Trace evidence should demonstrate the corrected canonical source is retrieved/hydrated, not a stale UI-only copy.
9. Verify hidden vs archived vs Dossier distinctions in scene snapshots and UI.
10. Update top-level docs so there is one current story; remove obsolete screenshots/instructions where necessary.
11. Compare final DOM/runtime screenshots to `assets/current-ui-before.png` and `assets/style-reference-radial-ui.png` qualitatively.
12. Produce implementation evidence summary and rollback instructions.

## Out of scope

- New feature requests discovered during acceptance unless they are regressions caused by this task.

## Files likely touched

Cross-cutting tests/docs and any integration fixes discovered. PM must keep changes narrowly tied to the task.

## Architecture constraints

No hidden duplicate polling/state owner remains after migration. One Board type truth, one capture truth, one scene truth, one Dossier projection over canonical sources.

## Automated validation

Mandatory full chain:

- `qa-verification`
- `code-review`
- `runtime-validation`
- `agent-trace-analysis`
- relevant unit/integration/browser suites at current HEAD
- isolated end-to-end run(s) with real browser and, where agent trace is required, real configured agent path

## Acceptance criteria

- All locked decisions D01–D20/D28 are machine-verifiable where applicable.
- Obsolete UI is absent, not merely visually hidden.
- No stale documentation says Board type and interaction mode are independently user-controlled.
- No duplicate state/polling owners introduced.
- Accessibility paths work.
- Real trace proves Dossier/agent context parity after human edits.
- Runtime screenshots demonstrate substantial wheel redesign and reduced clutter.
- Rollback path is documented.

## Documentation updates

Close all canonical docs, README/operator notes and task LOG with exact evidence references.
