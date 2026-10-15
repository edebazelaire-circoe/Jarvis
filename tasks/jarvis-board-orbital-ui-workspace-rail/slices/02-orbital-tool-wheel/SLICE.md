# Slice 02 - Retractable orbital tool wheel

## Goal
Deliver the retractable semi-circular tool wheel shell with Mouse, keyboard and Bare Hands reveal/selection behavior.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `01-shell-contract-and-design-system`

## Scope / implementation steps
Create the wheel anchor/core at the left edge. The wheel is hidden at rest. Mouse entering the edge hotspot/anchor opens it. A canonical Bare Hands leftward activation event also opens it. Point/hover focuses a wedge; activation is click/Enter/Space/pinch.

Initial primary slots are exactly Selection, Video, Screenshot and Audio, but callbacks may remain injected until their domain slices. Do not add filler tools. Implement a radial submenu pattern that Selection and secondary capture choices can reuse.

Wheel reveal cannot depend on a network round-trip. It must not create a new global polling loop. Support escape/retract, focus containment only while needed, and reduced motion.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_barehands_hud.js or a new focused wheel module`
- `Bare Hands input/command modules discovered at HEAD`
- `frontend unit tests under tests/unit/`

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
- Closed state shows only the edge anchor.
- Mouse, keyboard and Bare Hands reveal the same wheel.
- Four primary actions are visually/semantically stable and adequately separated for pointing.
- Focus/hover shows one clear label and highlight.
- Bare Hands selection does not double-fire through synthesized pointer/click events.
- Wheel closes cleanly without affecting ongoing domain state.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.
