# Slice 02 — Canonical Presentation mode state and lifecycle

## Goal

Make PRESENTATION a reliable effective interaction mode without regressing SIMPLE or redefining current persistence ownership.

## Context

Board/Session work already established interaction-mode persistence semantics. Presentation behavior needs a single authoritative effective mode visible to runtime subsystems.

## Canonical Concepts

Interaction mode, Board/Session persistence, effective runtime state, SIMPLE, PRESENTATION, reserved REUNION.

## Scope

### In Scope

- Reconcile/complete `SIMPLE` and `PRESENTATION` enum/state handling.
- Preserve `SIMPLE` as default/safe fallback.
- Respect current canonical persistence scope discovered in Slice 01.
- Emit mode-change events consumed by ambient/presentation runtime and observability.
- Ensure Presentation teardown stops Presentation-only speculative activity.
- Preserve REUNION as reserved only if already product-visible.

### Out of Scope

- Meeting behavior.
- Ambient analysis itself.
- Control Center visuals beyond backend/state hooks.

## Dependencies

- `01-contract-reconciliation`

## Implementation Steps

1. Reuse canonical settings/effective-mode owner.
2. Add missing lifecycle hooks for entering/exiting PRESENTATION.
3. Make transitions idempotent and restart-safe according to current Session/Board contracts.
4. Add deterministic tests for default, activation, deactivation, restart/rehydration and invalid state.

## Files Likely Touched

Interaction-mode runtime/settings, persistence adapter, mode events, tests, docs.

## Architecture Constraints

No second settings store. No new voice architecture branch. Capture lifecycle remains independent.

## Automated Validation

Unit/integration tests for state transitions, persistence, fallback and Presentation teardown.

## Acceptance Criteria

Every runtime subsystem can observe one canonical effective mode, SIMPLE remains unchanged, and PRESENTATION transitions are deterministic.

## Documentation Updates

Document lifecycle, persistence owner and explicit non-goals.

## Handoff Notes

Coding Slice: load `/caveman` and `/coding-guideline`.


## Slice 00 contract (binding)

Scope in:
- **P1 mode follower.** Add `follow_core_mode(observer, core, journal, *, backoff)` in `runtime/interaction_mode_observer.py`. It is started and owned by `PersistentVoiceRuntime.run` (`voice_v2.py:368`) and cancelled on close.
  - It subscribes `core.events(on_connected=…)`, routes `interaction.mode.changed` to `observer.observe`, and calls `observer.adopt(await core.interaction_mode())` on each connect.
  - It never raises; one warning line per outage.
  - It runs on every voice architecture, legacy included. The scheduler feed (`speech_scheduler.py:1610-1614,1912`) stays.
- **Explicit legacy refusal.** Thanks to P1, `PresentationCoordinator` now sees PRESENTATION on legacy and `_refused_by_precondition` (`presentation_runtime.py:1145`) fires at the mode change. Verify it reaches `signals.alert` and the trace once. Document "PRESENTATION requires a continuous voice architecture" in `docs/interaction-mode.md`, replacing the Known limit at :446-451.
- Verify one effective mode is observable to the ambient lane (stack built), the brain hint (`control_center_brain.py:158-159`), the gate and the HUD.

Scope out: Board kind semantics (stays metadata, `docs/boards.md:198-217`); a second settings store; HUD changes.

Files: `jarvis/runtime/interaction_mode_observer.py`, `jarvis/runtime/voice_v2.py`, `docs/interaction-mode.md`, `docs/presentation-mode.md` (owner row), new `tests/unit/test_interaction_mode_follower.py`.

Acceptance (`test_interaction_mode_follower.py`):
- `test_mode_change_while_voice_is_idle_reaches_the_coordinator`: runtime in BACKGROUND, no `SpeechScheduler`; a fake core emits `interaction.mode.changed` → `observer.mode is PRESENTATION` and fake `coordinator.observe_mode` is called once.
- `test_snapshot_adopted_on_each_reconnect`.
- `test_double_delivery_notifies_listeners_once`: scheduler + follower deliver the same revision → one listener call.
- `test_legacy_architecture_refuses_presentation_visibly_once`: `continuous=False` → one `signals.alert`; trace code from the precondition; no microphone opened (fake hub not started).
- `test_follower_survives_core_outage_and_says_so_once`.
- `test_board_kind_presentation_does_not_change_mode` (add only if not already covered in `test_board_service.py`).
- Existing `test_interaction_mode_*` and `test_presentation_integration.py` green.

QA tier: glue. Passes: qa-verification + code-review + runtime-validation. The runtime pass must show:
- choosing PRESENTATION in the HUD while Jarvis is idle opens exactly one microphone owner (`audio/input_ownership.py`) with no wake needed;
- returning to SIMPLE restores the wake stack;
- on `voice_arch=legacy`, the alert appears.

Not yours: HUD rendering (03); timeline events (10).

Depends on: 01.

Documentation: interaction mode Level 3 (contract + follower tests).
