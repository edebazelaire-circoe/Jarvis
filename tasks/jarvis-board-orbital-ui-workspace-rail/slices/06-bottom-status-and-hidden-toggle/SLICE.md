# Slice 06 - Bottom status center, recording indicators, and hidden-object eye

## Goal
Replace the F9 visual hint/right notification pills/hidden-object capsule with a compact bottom-center status system.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `01-shell-contract-and-design-system`
- `04-capture-wheel-migration`

## Scope / implementation steps
Remove the permanent bottom-center `F9 - DEMARRER` capsule while preserving any still-supported keyboard behavior. Re-render existing notification category data as a horizontal bottom-center strip. Required categories: alert/warning, completed task, pending question. A fourth item only if mapped to a canonical current category. Preserve click-through/popover semantics and unread/seen mutations.

Place Audio/Video active indicators adjacent as distinct `REC`/audio timer states. Add a compact eye/eye-off button for hidden-object visibility; remove permanent hidden-object count text. The eye calls the existing scene visibility behavior and reflects canonical state.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center.html`
- `notification/background-pill rendering code`
- `jarvis/runtime/control_center_scene_page.js or scene interaction module`
- `capture view model for persistent indicators`

## Architecture constraints
- No optimistic duplicate state when a canonical Core/runtime owner exists.
- Preserve error/refusal semantics and make unknown/unconfirmed states explicit.
- Update the explicit Control Center layer registry when introducing/moving overlays.
- Author-provided text is rendered safely; previews use bounded/safe routes.
- Code slices run `/caveman` and `/coding-guideline`; frontend code additionally runs `/impeccable` and uses a Claude agent when supported by the host.

## Automated validation
- `qa-verification` is mandatory.
- `code-review` is mandatory.
- `runtime-validation` is mandatory.
- Run focused unit/integration tests for the exact behavior changed, plus neighboring regression tests named by current repository contracts.
- Runtime/UI validation must use an isolated Jarvis instance/worktree/data root unless the user explicitly authorizes the live instance.

## Acceptance criteria
- No F9 capsule remains in the approved shell.
- Required notification counters are readable, clickable and data-equivalent to the old model.
- Recording timers are visible while active and not confused with unread counters.
- Eye toggle is the only permanent hidden-object control in this zone; state is accessible by icon + label.
- No overlap with bottom-left context control or right rail.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
