# Slice 04 — JARVIS runtime controls, Capture submenu and transient recording HUD

## Goal

Wire the JARVIS and Capture wheel categories to canonical runtime/capture truth and replace permanent fragmented capture UI with contextual actions plus transient active-recording indicators.

## Dependencies

- `03-orbital-wheel-redesign`

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

## Files likely touched

- `jarvis/runtime/control_center_capture_wheel.js`
- `jarvis/runtime/control_center_capture_rail.js` only if view-model adaptation is needed
- `jarvis/runtime/control_center_tool_wheel.js` registrations/icons
- lifecycle/status module(s) for JARVIS submenu
- `control_center.html` recording host/layers
- `docs/capture.md`, `docs/control-center-shell.md`

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
