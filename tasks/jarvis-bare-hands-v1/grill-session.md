# Reconstructed Bare Hands planning / grill session

> Reconstructed from the active conversation because the host does not provide a verbatim transcript export in the task creator. This document preserves decisions and corrections without inventing implementation outcomes.

## Starting point

The native Bare Hands experiment already uses MediaPipe Hand Landmarker in-browser, tracks two hands, maps `INDEX_TIP` to the viewport, applies fixed exponential smoothing, detects thumb-index pinch via a normalized distance ratio, freezes the click anchor once pinch begins, and dispatches synthetic mouse/pointer events via `document.elementFromPoint()`.

The existing implementation is useful but currently lacks robust target assistance, drag/resize semantics, stable multi-hand identity, calibration, global gesture vocabulary, semantic frame zones, dedicated right click, and a replay/benchmark loop.

## Technology direction

The user accepted keeping standard webcams and MediaPipe as the V1 baseline. Hardware-specialized tracking (for example Ultraleap) is deferred to a future optional Pro mode. The architecture must remain tracker-agnostic.

The user strongly preferred a multi-channel architecture: tracking, gesture recognition, pinch/manipulation, and target understanding. Jarvis-only targeting is explicitly in scope for V1 so the system can exploit DOM/component semantics instead of treating the UI as an unknown screen.

## Activation / lifecycle

The user chose no permanent pointer. Bare Hands should use `OFF`, `SLEEP`, and `ACTIVE` states.

- OFF: webcam is fully released.
- SLEEP: a lightweight camera watcher remains able to recognize a stable C-shaped “about to pinch” pose.
- ACTIVE: full hand tracking and interaction.
- The C pose should show about a one-second circular progress indicator before activating.
- Manual UI activation/deactivation is required.
- Voice activation/deactivation is required through Jarvis's existing voice-command path.
- 30 seconds with no usable hand returns ACTIVE to SLEEP.

## Interaction model

The user corrected an earlier “object body moves the frame” proposal. BODY is content interaction. Frame geometry manipulation is only through edges/corners.

A frame has LEFT, RIGHT, TOP, BOTTOM, TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT plus BODY.

- One hand captures any edge/corner: the whole frame moves.
- Two hands capturing two compatible manipulation zones on the same frame: switch to bimanual resize.
- Each captured zone contributes only its allowed geometric axes.
- Example: LEFT + BOTTOM_RIGHT => left hand controls only `xMin`; right hand controls `xMax` + `yMax`.
- Jitter never changes a captured zone until release.
- Two hands on two different objects remain independent interactions.
- ZONE + BODY on the same frame is not resize.
- Same zone twice is rejected.
- Edge + overlapping corner: edge keeps the overlapping axis, corner uses only its other axis.
- Two corners sharing an axis neutralize the shared axis.
- Hands crossing never invert object axes; clamp to component minimum dimensions.
- If one hand releases during resize, rebase and continue moving with the remaining anchor without a jump.

BODY interactions should be context-sensitive: buttons click, draggable stars drag, scrollable content can scroll, text may select/scroll depending target behavior, and component-specific behavior can override defaults.

Example semantic actions discussed:

- Star: pinch-drag moves it; double-click/pinch may open it as a frame.
- Frame: a component-specific shortcut may collapse it back to a point of light.
- These object-specific actions are extension points, not reasons to distort core capture rules.

## Primary / secondary pinch

Primary pinch is thumb + index. Secondary/right-click is thumb + middle finger, not a long-press overload. Primary pinch can still distinguish click, drag, scroll and other continuous intent from movement, duration, release and target semantics.

Visual feedback:

- normal/body targeting: blue;
- manipulation edge/corner targeting: yellow and only the selected segment/corner;
- secondary/right-click intent/validation: red pulse.

Target preview before final capture is desired, but must be configurable in Bare Hands Settings.

## Tools vs Settings

Two separate concepts are required:

- **Bare Hands Tools**: active interaction modes such as default pointer/mouse, hand/pan, highlighter, drawing, selection, and future tools.
- **Bare Hands Settings**: behavior/configuration such as target feedback visibility, sensitivity, calibration, sleep timeout, assistance/snapping, visual feedback and related options.

The default interaction remains context-sensitive. Tools force/alter intent where appropriate rather than replacing the entire interaction engine.

## Calibration

Calibration should be an explicit optional button/voice-launched flow, not mandatory at first use.

Use a full-screen overlay over the current Jarvis UI, dark/blurred behind it, with targets and short exercises. Calibration should not just “test” Bare Hands; it should actually adapt derived parameters.

Short calibration concepts:

- show hands / neutral samples;
- C pose;
- several thumb-index pinches;
- several thumb-middle pinches;
- aim/pinch at targets in different screen areas;
- short drag exercise;
- small bimanual resize exercise.

Calibration may adapt per-hand internally while exposing only one simple profile.

It may adapt:

- press/release thresholds and hysteresis;
- right-click pinch thresholds;
- jitter/stillness estimates;
- click-vs-drag motion threshold;
- spatial correction / mapping parameters;
- confidence/quality metrics.

Use threshold/statistical personalization in V1, not a personalized neural model. If a user cannot fully close a conventional pinch, the calibration should learn their comfortable positive posture where possible, but must refuse to widen thresholds so far that neutral motion becomes indistinguishable from pinch.

Calibration is partial: a failed function keeps standard defaults without invalidating successful parts.

No continuous self-learning in V1. Normal usage may record diagnostics but does not mutate calibration parameters.

Store derived parameters and quality metrics only by default. No image/video retention unless an explicit diagnostic recording mode is later enabled.

## Tutorial

Tutorial lives beside Calibration in the same overlay shell, but is longer and educational. It should teach activation, primary/secondary pinch, target feedback, body interactions, frame anchors, move, bimanual resize, object examples, tools, and exit paths. Tutorial must not modify calibration state.

## Diagnostics / benchmarking

A Replay/Benchmark path is desirable so the same landmark sessions can be compared under different filters, thresholds and resolver parameters. Record timestamps, landmarks, handedness/confidence, raw/filtered pointer, velocities, pinch state, candidates, captures and outcomes. Raw video is opt-in only.

Important future metrics include target acquisition success, click error, jitter, false pinches, latency, hand-loss recovery, drag stability and two-hand resize stability.
