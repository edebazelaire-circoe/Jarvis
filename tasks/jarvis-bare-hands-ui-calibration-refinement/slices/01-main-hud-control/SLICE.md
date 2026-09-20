# Slice 01 — Add first-class Bare Hands HUD lifecycle control

## Goal

Make OFF/SLEEP/ACTIVE directly controllable and visible from the main Jarvis HUD with one authoritative hand-icon button and a visual state chooser.

## Context

The current implementation exposes Bare Hands mainly through Settings/Experimental even though lifecycle is already a first-class runtime contract. The new UI must project the real controller state and stay synchronized with every activation path.

## Canonical Concepts

- Bare Hands `LIFECYCLE` / controller state mapping in `control_center_barehands_contracts.js`
- `window.JarvisBarehands` lifecycle/activate/sleep behavior
- persisted `enabled` master state in `barehands_test_mode.py`
- existing Control Center top HUD/action-button styling

## Scope

### In Scope

- Add a slightly larger square hand-icon Bare Hands button to the main HUD near the upper-left status area chosen in Slice 00.
- Render OFF dim grey, SLEEP normal blue, ACTIVE brighter electric blue with subtle glow.
- Normal click opens a compact visual three-state chooser made from the same hand-button motif, allowing direct OFF/SLEEP/ACTIVE selection.
- Map selection onto the existing authoritative lifecycle/master-enabled mechanisms.
- Update the button when lifecycle changes through UI, C-wake, voice/MCP, inactivity, errors/recovery, or reload.
- Provide keyboard/focus/ARIA equivalents to mouse activation.

### Out of Scope

- Right-click quick-action menu (Slice 02).
- Tool palette.
- Calibration redesign.
- New lifecycle states.

## Dependencies

00

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Freshness-check the main HUD and Bare Hands controller/state API.
3. Implement one UI adapter that derives presentation from authoritative state rather than storing a duplicate lifecycle.
4. Implement the visual selector and exact transition paths for OFF, SLEEP, ACTIVE.
5. Ensure OFF performs actual teardown/master disable, SLEEP enables watcher without full interaction, ACTIVE enables full interaction.
6. Subscribe/refresh on every existing state-change path.
7. Add unit/browser tests and runtime validation.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_barehands.js`
- possibly a new small Bare Hands HUD module if extraction improves isolation
- Bare Hands lifecycle/UI tests

## Architecture Constraints

- No second lifecycle store in the UI.
- OFF remains the only mode in which C-wake cannot activate because the camera/master mode is actually disabled.
- ACTIVE is blue, not green.
- ERROR is not a fourth selectable mode; preserve existing error semantics and make failure discoverable without pretending it is OFF/SLEEP/ACTIVE.

## Automated Validation

- Visual-state mapping for each lifecycle.
- Direct chooser selection for all three modes.
- OFF releases camera/resources.
- External transitions update the button.
- C-wake produces SLEEP→ACTIVE visual update.
- ACTIVE inactivity timeout produces ACTIVE→SLEEP visual update.
- Voice/MCP receipts produce matching UI state.
- Keyboard and ARIA state tests.

## Acceptance Criteria

- User can see and select Bare Hands lifecycle without opening Settings.
- Button is always synchronized with the real controller.
- OFF/SLEEP/ACTIVE are visually distinct exactly as specified.
- No existing lifecycle cleanup or voice path regresses.

## Documentation Updates

Document the HUD lifecycle control as the canonical user-facing lifecycle selector.

## Handoff Notes

Baseline `qa-verification`, `code-review`, and `runtime-validation` are required.
