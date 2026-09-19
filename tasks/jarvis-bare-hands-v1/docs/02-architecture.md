# Target architecture

## 1. HandTracker

Wrap MediaPipe output behind a tracker-neutral contract. V1 uses the existing vendored MediaPipe 0.10.14 Hand Landmarker/model. Expose timestamp, landmarks, handedness/confidence, tracking quality and source dimensions.

## 2. HandTrackManager

Current handedness labels are not sufficient as persistent identity. Associate detections frame-to-frame using spatial continuity and handedness as a hint. Emit stable handTrackId values suitable for two simultaneous captures.

## 3. PointerFilter / motion features

Replace fixed smoothing-only stabilization with adaptive filtering such as One Euro or equivalent. Keep raw and filtered positions observable and compute velocity/stillness features.

## 4. GestureEngine

Independent semantic gesture stream. Initial vocabulary includes C wake posture, open palm, fist/closed hand, double-close sequence, clap/palms-together event, plus extension points. Global gestures must not steal input from an active captured manipulation unless explicitly allowed.

## 5. PinchIntentEngine

Primary thumb-index and secondary thumb-middle use separate approach/press/release states with hysteresis and confidence. Pinch is a contact-like stream, not an immediate click command. Emit approach/down/move/up/cancel with a primary|secondary channel.

## 6. TargetResolver

Do not rely solely on document.elementFromPoint(). Build a semantic candidate resolver using Jarvis DOM/components, candidate bounds, type, actionability, zone geometry and optional target assistance. BODY, edges and corners are first-class regions. In overlap, preview priority is corner > edge > body.

## 7. InteractionEngine

Own per-hand capture state and multi-hand coordination. Support context-sensitive BODY click/drag/scroll/select, one-hand zone move, same-frame two-zone constrained resize, independent interactions on distinct objects, latching until release, conflict decomposition, min-size clamps/no inversion, smooth RESIZE -> MOVE, and component semantic hooks.

Do not encode all behavior as synthetic DOM PointerEvents. The current code uses one hard-coded pointerId 9001 for all hands; V1 needs stable per-hand interaction identity. DOM events may remain a compatibility output for BODY/content actions.

## 8. BareHandsTools

Separate active “what the hand means” modes from engine settings. Provide an extensible tool contract and initial UI palette for default/pointer, hand/pan and selection. (Amended after Slice 07 shipped: highlighter and drawing need an annotation layer that V1 does not have, and no Slice owned them, so they are out of V1 scope. The extension recipe is kept in `docs/barehands-contracts.md` §8.)

## 9. BareHandsSettings

Persist behavior controls separately from tool selection: enable/disable, target feedback, calibration, tutorial, sleep timeout, safe assistance/sensitivity controls, reset profile and diagnostics.

## 10. CalibrationProfile

One simple visible profile; internal left/right values are allowed. Store derived thresholds, hysteresis, motion/jitter stats, spatial mapping/correction, quality and schema version.

## 11. Calibration / Tutorial overlay

One full-screen overlay shell over the current UI with dark/blurred background, target placement, progress, voice-capable instructions and obvious exit paths.

## 12. Recorder / Replay / Benchmark

Opt-in trace recorder for landmark/state traces and deterministic replay under alternate filter/threshold/resolver configurations.
