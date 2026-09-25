# Decision log

## 2026-09-20 — Historical baseline

The prior UI/calibration refinement was implemented and merged as `e684a46824a116216a2bee327de068bfcac37464`. Its HUD, palette, full-screen shell, arming phases, real window practice, and tutorial retirement are inherited rather than reimplemented.

## 2026-09-25 — Calibration changes role

Calibration is an interactive evidence-gathering and tuning session, not a one-shot fixed-threshold generator.

## 2026-09-25 — Facts versus interpretation

Deterministic components own measurements and benchmark scoring. The calibration agent interprets evidence plus subjective feedback, proposes hypotheses and bounded experiments, and must be able to abandon a disproven explanation.

## 2026-09-25 — Gesture segmentation

Primary/secondary pinch calibration segments individual gestures and aggregates per-gesture metrics. Negative examples are collected explicitly.

## 2026-09-25 — User feedback is first-class

Free-form voice feedback and simple UI feedback both enter the calibration session model. Steps do not auto-advance after result.

## 2026-09-25 — Trial profile

Tuning changes are temporary until accepted. Rollback is mandatory.

## 2026-09-25 — Pointing intent

Hand tracking does not imply pointer visibility. Ordinary motion shows no pointer. Wake feedback starts only with credible pointing/wake intent.

## 2026-09-25 — Target preselection

Before press, actionable stars/objects can receive a subtle preview of the candidate that would be selected. Assistance is tunable and bounded by ambiguity.

## 2026-09-25 — Separate Test mode

A deterministic mini-game-like benchmark measures interaction quality without changing settings and supports before/after comparison.

## 2026-09-25 — Score semantics

The score describes Bare Hands interaction quality for the current user/profile/system, not user skill. Dimension scores dominate interpretation.

## 2026-09-25 — Empty-space dismissal

A primary click/pinch in empty space closes an open context menu.

## 2026-09-25 — Successor task

Because the previous handoff was already merged and no matching branch survives, this task starts from current `main`; it does not amend/replay the old implementation branch.
