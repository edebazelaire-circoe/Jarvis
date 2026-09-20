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

Implemented by Slice 08 at schema version 2: `jarvis/runtime/control_center_barehands_calibration.js` derives, `jarvis/runtime/barehands_profile.py` persists under its own settings key and routes, and `docs/barehands-contracts.md` §10 is the contract. The click-vs-drag tolerance is stored as `travelSlopNorm`, a fraction of the image width — the unit that survives a resolution change, which is what Slice 04 left open.

## 11. Calibration / Tutorial overlay

One full-screen overlay shell over the current UI with dark/blurred background, target placement, progress, voice-capable instructions and obvious exit paths.

Built by Slice 08 as `JarvisBarehandsCalibration.createFlowOverlay({document, now, setInterval, clearInterval})`. It knows nothing about calibration — it shows steps — so Slice 09's tutorial reuses it unchanged (decision 26). It sits just below the hand overlay (`z-index` 2147482000 against 2147483000) and exempts every Bare Hands root from its `inert` sweep: the user calibrates *with their hands*, so the hand token must stay alive and visible throughout.

## 12. Recorder / Replay / Benchmark

Opt-in trace recorder for landmark/state traces and deterministic replay under alternate filter/threshold/resolver configurations.

Built by Slice 10 as `jarvis/runtime/control_center_barehands_recorder.js`
(`window.JarvisBarehandsRecorder`), with a server-side mirror
(`barehands_trace.py`), a node-driven replay driver (`barehands_replay.py`), a
CLI (`python -m jarvis barehands-replay`) and one Test Lab diagnostic
(`barehands.input_quality`). Contract: `docs/barehands-contracts.md` §14.

**Amended on one point, deliberately: a trace holds no landmarks.** Eight of the
nine items this section listed are derived scalars the controller already
produces through the decision-32 seam; the ninth — the twenty-one points of a
hand — is a reconstruction of the user's hand, and none of the three replays
this section names (filter, threshold, resolver) ever receives points in the
real engine. Recording them would buy nothing this Slice can use and would make
decision 32 a matter of intention. The recorder therefore sits behind the
reducing seam and *cannot* receive them; a whitelist rebuilds every key, and a
schema-driven load-time guard presents landmarks, a base64 image and a free
object to every key of every shape. A future tracker joins the same benchmark by
producing the same derived schema, not by widening it.
