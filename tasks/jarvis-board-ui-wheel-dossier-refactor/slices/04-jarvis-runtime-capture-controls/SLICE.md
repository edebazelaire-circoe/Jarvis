# Slice 04 — JARVIS runtime controls, Capture submenu and transient recording HUD

## Goal

Wire the JARVIS and Capture wheel categories to canonical runtime/capture truth and replace permanent fragmented capture UI with contextual actions plus transient active-recording indicators.

## Dependencies

- `03-orbital-wheel-redesign`

## Slice 00 reconciliation (read first)

- **JARVIS submenu, real capabilities at HEAD:** the page knows, from the one `/api/status` beat (`refreshStatus` in `control_center.html`), `voice_online`, `voice_state` (idle/waiting/listening/speaking/thinking → SLEEP/WAIT/LISTEN/TALK/THINKING), `voice_turn_mode`, `manual_wake_key` (F9 by default, Voice's global shortcut), `agent.name` / `agent_cli`, `agent.state`, sub-agent count, `live`. There is **no** Control Center or Core route to sleep/wake Voice or to change a « thinking » mode (only `GET/POST /api/wake-word` for the wake-word *settings*). So the JARVIS submenu is status-only plus the wake-key hint (removed from `.state` by Slice 02) and links to existing settings (voice/wake word in Réglages). Any click-to-wake/sleep control is out of scope and must not be faked; it is recorded as a follow-up, not invented.
- **Recording indicators already exist and are already transient:** `#recIndicators` (status centre, rank 40, `control_center_capture_wheel.js` view of `JarvisCaptureRail`) shows one chip per **open** Core capture with Core duration, `REC` for the screen and a microphone for audio, and activating a chip stops that capture; refusal note `.ri-note`; right-edge column at ≤ 700 px. Reuse them: move the host to the top-left zone freed by Slice 02 (the Human asked for the video REC « en haut à gauche »), restyle per `../../docs/06-ui-visual-spec.md` §E, and update the status-centre layout (pills only) and registry. Do not build a second indicator system.
- **Paramètres:** register the wheel's `settings` category to open the same `#openSettings` route; fold the launcher's `SET` button into « Plus d’outils » (shortcut `s` unchanged, `docs/control-center-shell.md` › *Global launcher* destination matrix updated, `test_global_launcher_browser.py`).
- No Pause: `CaptureService` has no pause state/API at HEAD (`docs/capture.md`).

## Scope / implementation steps

### JARVIS category

1. Audit canonical lifecycle/voice/brain/model owners at current HEAD. Do not infer control capability from the concept image.
2. Expose useful runtime states/actions in one JARVIS submenu:
   - Sleep/Wake where a canonical gate exists;
   - voice/listening state/action where appropriate;
   - model/brain identity/status as read-only when it is not a user-selectable control;
   - any supported manual focus/autonomy/thinking control only if the repository has a canonical API/contract.
3. Unknown/unconfirmed/error are explicit; no local optimistic truth.
4. Old persistent top-left state text remains retired.

### Capture category

5. Reuse current `JarvisCaptureRail`/CaptureService truth and target discovery.
6. Register Capture submenu actions for screenshot, screen/video recording and audio recording.
7. Target/device nested options come only from Core's advertised capabilities. A single target may still be named clearly rather than hidden.
8. Preserve simultaneous audio + screen recording.
9. Remove old first-level Video/Screenshot/Audio wheel integration and any obsolete permanent capture rail presentation after parity is proven.

### Transient recording HUD

10. Screen/video active → compact red `REC` indicator + canonical elapsed time + stop affordance in top safe area.
11. Audio active → compact orb/wave/microphone indicator + elapsed time + stop affordance; it may coexist with screen REC.
12. Indicators appear from Core-reported open captures and survive page reload consistently; never from the user's click timestamp.
13. If current Core has no Pause state/API, do not draw a Pause control.
14. Screenshot remains momentary; preserve/refine current screenshot preview/toast if useful without adding permanent chrome.
15. Update shell layers/safe areas and capture docs.

## Out of scope

- New capture backend codecs/sources.
- Changing Session/Artifact capture continuity guarantees.
- Inventing new model switches.

## Files likely touched (verified at HEAD 2fb66040)

- `jarvis/runtime/control_center_capture_wheel.js` (category tree, `#recIndicators` view)
- `jarvis/runtime/control_center_capture_rail.js` only if view-model adaptation is needed
- `jarvis/runtime/control_center_tool_wheel.js` (registrations/icons only)
- a small new module for the JARVIS submenu fed by the existing `refreshStatus` beat (no second poll), or a registration inside `control_center.html`'s status code
- `jarvis/runtime/control_center.html` (`#recIndicators` host/zone, status centre, launcher `SET`, registry mirror)
- `docs/capture.md` › *Interface*, `docs/control-center-shell.md` (*Status centre*, *Global launcher*, *Tool wheel*, registry, matrix)
- tests: `test_capture_wheel_browser.py` (+ `_capture_wheel_browser.mjs`), `test_capture_rail_js.py`, `test_capture_targets.py`, `test_status_centre_browser.py`, `test_global_launcher_browser.py`, `test_tool_wheel_js.py`, `test_control_center_shell_layers.py`, `test_control_center_shell_browser.py`, `test_screenshot_preview_browser.py`, `test_board_drop_browser.py` (tray above the status centre)

## Architecture constraints

`CaptureService` in Core remains the only capture truth. Keep failure/refusal semantics, multiple captures/devices, restart behaviour and status polling rules unless a newer contract supersedes them.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation`
- `/impeccable`, `/caveman`, `/coding-guideline`
- capture unit/browser tests including audio+video concurrency, page reload, status loss, failed start and target menus

## Acceptance criteria

- JARVIS submenu shows only truthful supported controls/status.
- Capture primary category owns screenshot/video/audio choices.
- No Video/Screenshot/Audio primary wheel sectors remain.
- Video active shows transient REC/timer/stop.
- Audio active shows transient audio indicator/timer/stop.
- Audio + video indicators coexist without collision.
- Stopping from the indicator calls the same canonical controller path.
- No recording = no recording HUD clutter.

## Documentation updates

Update capture interface section, shell layer registry and any operations docs that refer to old wheel wedges/indicators.
