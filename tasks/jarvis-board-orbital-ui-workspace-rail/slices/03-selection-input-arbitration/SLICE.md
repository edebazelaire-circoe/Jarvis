# Slice 03 - Mouse/Bare Hands selection arbitration

## Goal
Reduce Selection to Mouse/Bare Hands and implement intelligent, non-flapping control takeover.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `02-orbital-tool-wheel`

## Scope / implementation steps
Wire the Selection wedge to a two-choice radial submenu: Mouse and Bare Hands only. Remove legacy/extra selection choices from this surface. Replace the disliked Bare Hands selector icon with a new clean product icon consistent with the approved reference.

Implement intentional Mouse takeover: click is immediate; movement uses a bounded displacement/velocity threshold with hysteresis and debouncing. Micro jitter never changes mode. Once Mouse is active, hand presence does not auto-return to Bare Hands. Return occurs only by explicit UI selection or the canonical Jarvis command path.

Reuse the canonical Bare Hands lifecycle/state transitions; do not add another lifecycle state variable that can diverge.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `Bare Hands HUD/contracts/input modules`
- `new arbitration module if appropriate`
- `control_center.html integration`
- `tests for Bare Hands/Mouse UI logic`

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
- Exactly Mouse and Bare Hands are offered.
- Explicit mouse click takes over immediately.
- Meaningful movement takes over; jitter does not in automated and runtime tests.
- No automatic return to Bare Hands.
- Failed Bare Hands activation is rendered truthfully.
- New Bare Hands icon is visually approved against the design direction and has an accessible label.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
