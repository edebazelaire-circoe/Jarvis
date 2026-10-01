# Slice 07 - Generic desktop screenshot and screen recording

## Goal

Add user-grade desktop screenshot and continuous screen recording as generic capture sources and Artifacts, separate from Jarvis scene capture.

## Context

Current scene capture renders only Jarvis's scene canvas, with a 1280x720/2 MiB bound and 5-file/24-hour diagnostic retention. That code provides useful patterns for IDs, validation and atomic writes but cannot satisfy desktop capture.

## Scope

### In scope

- Audit supported host OS/display stack and choose a maintained capture backend.
- Define desktop source policy for V1 (default display vs selected display/window) based on current host requirements and minimal UX.
- One-shot screenshot -> durable Artifact with dimensions/source/time metadata.
- Continuous screen recording -> Slice 05 lifecycle -> durable media Artifact.
- Permission denied, unsupported platform/source, display loss, encoder/write and partial-finalize errors.
- Optional low-frequency/keyframe extraction primitive for later semantic enrichment; do not run vision on every frame.
- Keep existing scene capture behavior and retention intact.

### Out of scope

Camera capture, OCR/vision enrichment itself, remote desktop/cloud capture.

## Architecture constraints

- User desktop capture is durable user data, not `runtime/scene-captures/` diagnostics.
- Do not pretend a scene-render PNG is a desktop screenshot.
- Multi-monitor/window details must come from audited platform capability, not guessed contracts.
- Screen recorder start/stop is independent from audio recorder and may coexist with it.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation`. Use fake frames/sources for deterministic unit/integration tests, validate screenshot bytes/dimensions, recording finalization, source loss, permission refusal, recovery and Artifact/activity metadata.

## Human validation

After machine QA, exercise real OS screenshot and a short real screen recording, including the platform permission path if one exists.

## Acceptance criteria

A real desktop screenshot and screen recording become durable, indexed Artifacts with truthful source/status metadata; screen recording recovers partial state on interruption; scene capture remains a separate diagnostic feature.
