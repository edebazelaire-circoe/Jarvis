# Target architecture

## 1. Measurement seam

Extend the existing derived-scalar seam/recorder rather than exposing video or full landmarks to the agent. The active calibration session may hold short-lived structured telemetry including timestamps, hand/channel identity, tracking quality, pointer/raw positions, motion/stillness, primary/secondary ratios, pinch state transitions, target candidates/distances, captures, click/drag intent, wake/pointing scores, and UI effect timestamps.

Persist only derived profile values and optional benchmark summaries. Raw session telemetry is ephemeral unless the user explicitly starts the existing diagnostic recorder.

## 2. Gesture episode segmenter

Convert frame streams into semantic episodes: open baseline, closing, minimum, opening, new open baseline. Produce per-episode duration, minimum ratio, opening/closing velocity, press detection delay, release detection delay, travel, stillness and quality. Aggregate episodes robustly.

## 3. Evidence and hypothesis layer

Deterministic/heuristic code may produce evidence statements such as “release confirmation consumed 240 ms p95” or “false press rate rose during high-speed pass across torso”. It may rank candidate hypotheses, but hypotheses remain provisional.

The calibration agent sees evidence, current parameters, trial history and user feedback. It chooses a safe next trial or asks a focused question. A failed experiment must update hypothesis confidence rather than repeat the same recommendation.

## 4. Trial profile manager

Maintain saved profile, active effective profile/settings, and session trial delta separately. Validate every patch against engine invariants. Support apply/rollback/accept and keep a short in-session history.

## 5. Pointing-intent gate

Introduce a canonical pointing-intent signal distinct from tracking and lifecycle. Cursor/wake visuals subscribe to this signal. SLEEP ordinary motion renders no cursor; credible C/pre-pinch/pointing posture begins wake feedback. ACTIVE pointer visibility likewise depends on pointing intent, not raw hand presence.

## 6. Target preview and assistance

Reuse the existing target resolver and browser collector. Extend preselection to all actionable targets where semantically safe, including stars. Keep the pointer position honest; highlight the candidate instead of snapping pointer coordinates. Assistance radius/hysteresis can be a trial parameter, bounded by nearby-target ambiguity.

## 7. Calibration Agent control plane

Do not expose arbitrary unverified settings mutation through the legacy Bare Hands voice command table. Define a scoped calibration-session API/tool surface with read-current-measures, propose/apply trial, rollback, accept, rerun exercise, and session status. Receipts must report values actually applied.

The agent runs only while the calibration session is active and receives calibration-specific context. It does not own tracking or scoring.

## 8. Test/benchmark engine

A separate deterministic runner generates controlled equivalent layouts with a seeded/randomized exercise plan. It records target acquisition, missed/false clicks, wrong-target selection, drag/drop success, premature release, reacquisition count, placement error, pointer stability, latency and transition quality.

No benchmark action changes settings/profile state.

## 9. Scoring

Produce dimension scores with raw supporting metrics. The global score may use a weak-dimension-sensitive aggregation such as a geometric mean or explicit caps, but Slice 08 must justify and test the exact formula. Never label the result as “user accuracy”.
