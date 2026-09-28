# Overview

## Goal

Turn Bare Hands calibration from a fixed statistical wizard into an explainable, voice-first diagnostic/tuning loop, then add an independent deterministic benchmark that proves whether the resulting profile improves actual interaction quality.

## Scope

In scope: richer scalar/session telemetry, pinch segmentation, negative examples, press/release latency, pointer-intent gating, target preselection/assistance calibration, bounded trial profiles, calibration-agent control plane, interactive exercise redesign, deterministic Test mode, multidimensional scoring, before/after comparison, migration, QA and documentation.

## Non-goals

- No personalized neural model training.
- No cloud vision service or raw-video retention.
- No continuous autonomous learning during ordinary Bare Hands use.
- No open-ended arcade/playground product in this task.
- No rewriting MediaPipe itself.
- No agent in the per-frame tracking loop.
- No global score that hides dimension failures.

## Mental model

`measurement -> evidence -> hypotheses -> bounded trial -> retest -> accept/rollback`

The separate Test path is `controlled exercise -> deterministic measures -> dimension scores -> comparison`; it never mutates the profile.
