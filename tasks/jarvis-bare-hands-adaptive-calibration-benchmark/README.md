# Jarvis — Bare Hands Adaptive Calibration & Benchmark

## Purpose

Replace the current fixed statistical Bare Hands calibration with an interactive, explainable tuning loop driven by measured telemetry plus explicit user feedback, and add a separate deterministic benchmark that can prove whether a profile actually improves interaction quality.

This is a **successor task**, not a replay of `jarvis-bare-hands-ui-calibration-refinement`.

The previous UI/calibration refinement handoff was fully implemented and merged into `main` at commit `e684a46824a116216a2bee327de068bfcac37464` on 2026-09-20. Its delivered product model remains the baseline: first-class HUD control, fixed tool palette, right-click quick actions, full-screen calibration shell, intro/arming phases, real window practice, and retirement of the separate Tutorial flow.

The successor starts from current `main` snapshot `f2005ebc1471b50e80629d840abb5d28e8701d23` (2026-09-25). No surviving branch matching `bare`, `calibr`, or `refinement` was found, and no matching PR was found. Do not resurrect an old task branch; implement from current `main` after Slice 00 freshness checks.

## Project identity and destination

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Base branch: `main`
- Inspected head: `f2005ebc1471b50e80629d840abb5d28e8701d23`
- Prior implemented handoff: `Jarvis/task/to-do/jarvis-bare-hands-ui-calibration-refinement/`
- Prior merge: `e684a46824a116216a2bee327de068bfcac37464`
- Successor queue destination: `Jarvis/task/to-do/jarvis-bare-hands-adaptive-calibration-benchmark/`

## Central product rule

> **A measurement is not a preference.** Measurement says what happened. User feedback says whether that behavior is acceptable. The calibration agent uses both to form and test hypotheses before anything is persisted.

## Target product model

Three distinct surfaces exist:

1. **Calibrer** — an interactive diagnostic/tuning session. It measures, asks for feedback, forms hypotheses, applies bounded trial settings, retests, and only persists after explicit acceptance.
2. **Tester** — a deterministic benchmark. It never changes settings. It runs controlled mini-exercises and reports multidimensional Bare Hands interaction quality, including before/after comparisons.
3. **Playground** — explicitly deferred. Benchmark exercises may feel playful, but an open-ended arcade/game mode is not required by this task.

## Locked decisions

- Keep the current full-screen calibration shell and `INTRO -> ARMED -> RUNNING -> RESULT -> NEXT` foundations, but stop auto-advancing after a result.
- Calibration must preserve a short, structured telemetry history for the active session so a user utterance such as “là ça a merdé” can be correlated with the immediately preceding events.
- Do not persist raw video, screenshots, full landmark arrays, or biometric training data by default.
- Segment intentional pinch gestures into phases (`open baseline -> closing -> minimum -> opening -> open baseline`) and derive per-gesture metrics rather than using a percentile over all frames as the primary model.
- Add explicit negative examples: natural hand movement and aiming without clicking. These must expose false presses, false wake/pointing intent, and unwanted target changes.
- Measure press and release latency as first-class outputs, including confirmation delays and quality/doubt effects.
- User feedback is a first-class input. Voice is the preferred rich path; simple UI ratings/actions remain available.
- The agent may interpret measurements and user feedback, but it must not invent measurement values. Diagnostic conclusions are hypotheses with confidence/evidence, not irreversible deterministic truth.
- Failed tuning experiments are evidence. The system must lower confidence in a hypothesis when a bounded trial does not improve the measured result or user feedback.
- Trial settings are temporary. Support `apply trial`, `rollback`, and `accept`; do not persist every change while tuning.
- Increase the calibratable parameter surface where evidence supports it, including press/release confirmation, click-vs-drag separation, pointer filter responsiveness/stability, target assistance/hysteresis, and wake/pointing intent, all behind validated bounds and invariants.
- `clickSlop` and `dragSlop` are independently measurable/tunable concepts; do not force the calibrated result to preserve an arbitrary factory ratio unless the current engine invariant genuinely requires it.
- Tracking a hand, intending to point, and showing a cursor are separate states. Ordinary hand motion must not display a pointer. In SLEEP, wake feedback appears only after meaningful pointing/wake intent begins.
- Extend preselection/target preview to stars and other actionable targets: before press, show which target would be selected if the user clicked now. Do not physically teleport the pointer.
- Target assistance must be tunable/calibratable and bounded by ambiguity. Prefer the nearest reasonable actionable target, but do not create a giant invisible hit area that steals neighboring targets.
- A left/primary click or primary pinch in empty space closes an open context menu.
- The benchmark reports **Bare Hands interaction quality**, not “user skill”. Global score is secondary to dimension scores and must not hide a catastrophic weak dimension.
- Benchmark trials must be controlled and comparable but not identical between runs; use equivalent randomized layouts to reduce memorization.
- The existing recorder/replay and scalar-only privacy boundary are reusable infrastructure and should be extended where practical instead of creating a second diagnostic stack.

## Current implementation facts to preserve

At the inspected head:

- the pinch detector defaults include `pressRatio=.28`, `releaseRatio=.42`, `pressFrames=2`, `releaseFrames=2`, `releaseMs=60`, and `releaseDoubtMaxMs=400`;
- pointer filtering already exposes `minCutoffHz`, `betaCutoff`, `dCutoffHz`, and related motion/stillness settings;
- target resolution already has `targetAssistPx`, target-region hysteresis, nearest actionable candidate selection, and a pre-target/hover concept;
- current settings expose assistance and gesture sensitivity, applied live;
- the current calibration profile includes primary/secondary press/release ratios, `jitterPx`, `travelSlopNorm`, `reachNorm`, and quality;
- current calibration tests explicitly cover derivation, refusal/fallback, privacy, and the existing stage state machine;
- current target tests explicitly require nothing to be drawn outside intent, while the page still renders hand tokens whenever tracked, which is the cursor/intention mismatch this successor must resolve;
- voice command routing currently exposes calibration but deliberately does not expose arbitrary settings changes, so the agent-tuning control plane requires an explicit verified contract rather than sneaking through the old command table.

## How the Project Manager starts

1. Open `slices/TODO.md`.
2. Execute Slice `00-project-manager` personally. Do not delegate it.
3. Blind-audit current `main` and current active handoffs before reading the documentation-level conclusions in this task.
4. Confirm the prior refinement merge is present and current behavior still matches the facts above.
5. Resolve the Workspace Task Type vocabulary for every Slice; do not invent task types.
6. Reconcile conflicts with newer voice, agent, scene, MCP, or Bare Hands work.
7. Reach `READY` before dispatching implementation.
8. Run a targeted freshness check immediately before every Slice.

## QA doctrine

Every implemented Slice receives `qa-verification`. Code changes also receive `code-review`. User-visible or runtime behavior also receives `runtime-validation`. Agent prompts, tools, routing, command/control modules, or agent runtime changes additionally require `agent-trace-analysis` with real trace evidence. QA agents return evidence and findings; the Project Manager decides approve, rework, continue, add a Slice, file an Issue, or escalate.

A regression caused by the current Slice is blocking and cannot be parked in `Issues/`. Human validation never substitutes for QA; machine validation must be pushed as far as reasonably possible first.

All coding Slices require `/caveman` and `/coding-guideline`. Frontend/browser Slices additionally require `/impeccable` and should use a Claude Work Agent when the host supports that routing rule.
