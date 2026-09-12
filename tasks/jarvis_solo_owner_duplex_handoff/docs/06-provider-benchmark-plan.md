# 06 — Provider Benchmark Plan

## Principle

Quality wins, but vendor selection happens only after a repeatable local benchmark.

## Candidate classes

### Speaker verification

Candidates discussed during design:

- sherpa-onnx based speaker verification/identification;
- SpeechBrain ECAPA-style verification;
- Picovoice Eagle if access/licensing is available;
- Vivoka voice biometrics if trial/access is available;
- Sensory speaker/secure-wake technology if access is available.

No candidate is pre-approved as winner.

### Wake word

The repository already has a `WakeWordBackend` boundary. Do not make wake-word replacement part of the critical owner-gating change unless necessary.

Potential later comparison:

- current wake implementation / Porcupine if present in deployment;
- openWakeWord or another local engine after model-license review;
- sherpa-onnx keyword spotting;
- commercial engines if they materially improve false wake/miss rate.

### VAD

The current local `NearEndDetector` is not a general owner recognizer. If a standalone VAD benchmark is needed, compare it separately from speaker verification. Avoid replacing it merely because a candidate engine bundles VAD.

## Benchmark harness contract

Each candidate adapter should accept the same PCM stream after the same selected preprocessing and emit timestamped scores/decisions. The harness should support:

- prerecorded local WAV fixtures;
- synthetic/non-sensitive test fixtures;
- frame-by-frame replay at real-time cadence and accelerated offline mode;
- CSV/JSON summary output;
- thresholds supplied externally;
- no network requirement for local engines.

## Selection rule

A commercial engine is justified only if it materially improves one or more critical user-visible metrics (false owner acceptance, missed interruptions, overlap robustness, confirmation latency) enough to outweigh integration/licensing friction.

Document the final selection with the benchmark data, not vendor marketing claims.
