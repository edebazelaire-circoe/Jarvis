# Slice graph / TODO

## Readiness gate

- `00-project-manager` — no dependencies; must reach `READY` before implementation dispatch.

## Shared foundation

- `01-settings-visual-foundation` — depends on `00-project-manager`.

## Page-specific UI refactors

All five depend on Slice 01 and may run in parallel when file ownership allows:

- `02-personnalisation-ui` — reference `01-personnalisation.png`.
- `03-architecture-agents-subagents-ui` — reference `02-architecture-agents-subagents.png`.
- `04-architecture-agents-architecture-ui` — reference `03-architecture-agents-architecture.png`.
- `05-memory-settings-ui` — reference `04-memory-settings.png`.
- `06-memory-center-ui` — reference `05-memory-center.png`.

## Convergence

- `07-settings-visual-integration-qa` — depends on Slices 02, 03, 04, 05 and 06.

## Main hard chain

`00 -> 01 -> {02,03,04,05,06} -> 07`

## Dispatch rule

A page Slice is not complete because the DOM exists. Completion requires page-specific screenshot evidence, responsive behavior, accessibility checks, state coverage and Human validation against its supplied reference.
