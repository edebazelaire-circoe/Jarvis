# Jarvis — Bare Hands V1

## Purpose

Turn the current native Bare Hands experiment in Jarvis Control Center into a reliable webcam-only interaction subsystem for Jarvis itself. The V1 must separate hand tracking, gesture recognition, pinch/manipulation, and target understanding so that each concern can evolve independently.

This handoff comes from the Bare Hands design/grill session plus a fresh repository review of `edebazelaire-circoe/Jarvis` on `main` at commit `6af6df91c900efa33317ffa836a7eac9abbeb181` (2026-09-19).

## Project identity and destination

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Queue destination: `Jarvis/task/to-do/jarvis-bare-hands-v1/`
- Current native implementation: `jarvis/runtime/control_center_barehands.js`
- Current server/settings support: `jarvis/runtime/barehands_test_mode.py`
- Existing tests: `tests/unit/test_barehands_pointer_js.py`, `tests/unit/test_barehands_test_mode.py`

## Locked product model

Bare Hands V1 is webcam-only and Jarvis-only. Do not require Ultraleap, depth cameras, a second webcam, OCR, system-wide accessibility APIs, or external ML services.

The runtime is organized into independent channels:

1. **Tracking** — where the hands/fingers are and how stable the tracks are.
2. **Gesture recognition** — C wake pose, open palm, fist, double-close, clap, and other semantic gestures.
3. **Pinch / manipulation** — primary pinch, secondary/right-click pinch, click/drag/release intent, frame anchors and bimanual resize.
4. **Target understanding** — Jarvis DOM/component semantics, candidate scoring, body-vs-edge-vs-corner zones, and optional pre-target feedback.

The current MediaPipe Hand Landmarker remains the default tracker in V1. Build interfaces so a future “Pro” backend such as Ultraleap can be added without rewriting gesture/interaction logic.

## Key interaction rules

- No permanent cursor is required.
- Bare Hands lifecycle: `OFF -> SLEEP -> ACTIVE`.
- `OFF`: camera released.
- `SLEEP`: lightweight webcam watcher, used to detect presence + a stable C-shaped wake pose.
- `ACTIVE`: full tracking, gesture, pinch, targeting and interaction.
- Default inactivity: 30 s with no usable hand returns ACTIVE to SLEEP.
- Primary interaction pinch: thumb + index.
- Secondary/right-click pinch: thumb + middle finger.
- Right-click feedback uses red; normal interaction uses blue.
- Optional target preview appears only during interaction intent/pre-pinch, never as a permanent pointer.
- Frame manipulation zones are the four edges and four corners; BODY is content interaction, not a frame-move handle.
- One hand capturing any manipulation zone moves the whole frame.
- Two hands capturing two compatible manipulation zones on the same frame switch to constrained resize.
- Two hands on different objects remain independent interactions.
- Captures are latched until release.
- On `RESIZE -> MOVE` after one hand releases, rebase the surviving anchor so the object does not jump.
- `ZONE + BODY` never forms resize.
- Same-zone double capture is rejected.
- Edge + overlapping corner: edge owns the shared axis; corner owns only its other axis.
- Two corners sharing an axis neutralize the shared axis and resize only along their non-conflicting axes.
- No axis inversion when hands cross; clamp at component minimum size.

## Calibration and tutorial

Calibration and tutorial share a full-screen overlay shell over the current Jarvis UI, with a dark/blurred background and voice-capable instructions.

- **Calibration** is short and functional. It adapts thresholds and spatial/motion parameters.
- **Tutorial** is longer and teaches the interaction vocabulary. It does not modify calibration data.
- Calibration is optional and launched explicitly from a button or voice command.
- One simple visible profile in V1; per-hand internal parameters are allowed.
- Calibration may succeed partially per function and fall back to standard defaults for failed stages.
- Store derived parameters/quality metrics only by default; do not retain images/video.
- No continuous auto-learning in V1.
- No personalized ML model in V1; use statistical/threshold calibration only.

## Licensing constraint

The repository includes pinned upstream `jaredrhod/barehands` under AGPL-3.0-or-later as a third-party component. The native Control Center implementation explicitly states it is a reduced reimplementation and does not copy upstream AGPL code. Preserve this separation. Concepts may inform design; do not copy upstream AGPL implementation into native Jarvis unless the licensing decision explicitly changes.

## How the Project Manager starts

1. Open `slices/TODO.md`.
2. Execute Slice `00-project-manager` personally; do not delegate it.
3. Perform the blind repository/context audit before relying on this handoff's conclusions.
4. Reconcile the latest Control Center/Constellation/voice command architecture with this task.
5. Resolve valid Workspace Task Types; planning metadata intentionally leaves `task_type` null.
6. Reach `READY` before implementation dispatch.
7. Perform a targeted freshness check immediately before every Slice.

## QA doctrine

Every implemented Slice gets `qa-verification`. Code changes add `code-review`. User-visible/runtime behavior adds `runtime-validation`. Agent prompts/tools/routing/runtime changes add `agent-trace-analysis` with real trace evidence. A regression caused by the current Slice is blocking and cannot be parked in `Issues/`. Human validation happens only after maximum reasonable machine validation.

All coding Slices require `/caveman` and `/coding-guideline`. Frontend/browser Slices additionally require `/impeccable` and should use a Claude agent when the host supports that routing rule.
