# Slice 05 - Introduce shared audio capture and explicit-address trigger lane

## Goal
Provide Presentation with continuous microphone capture while guaranteeing wake word/manual key creates a low-latency explicitly addressed turn independent from ambient backlog.

## Context
Current Porcupine owns a separate `RawInputStream` and suspends during active sessions; `SoundDeviceRealtimeAudio` also owns microphone input. That conflicts with always-on Presentation capture.

## Canonical Concepts
Single physical microphone owner; `ExplicitAddressTrigger`; short memory-only PCM ring/pre-roll; bounded consumer queues.

## Scope
### In Scope
- Add `AudioCaptureHub` or equivalent shared-capture abstraction for Presentation.
- Fan PCM to bounded subscribers without persistence.
- Feed wake detector from shared PCM, not a second mic in Presentation.
- Keep keyboard backend as trigger source.
- Normalize both into typed source+monotonic-time trigger.
- Bounded PCM ring for command pre-roll.
- Adapter so interactive realtime path consumes shared capture on addressed turn.
- Preserve existing Simple microphone/wake behavior unless proven safe to refactor globally.
- Safe lifecycle/device ownership/failure isolation.
### Out of Scope
Ambient transcription, brain handling, Meeting.

## Dependencies
Slices 02 and 04.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Audit `SoundDeviceRealtimeAudio`, duplex capture, speaker verification and wake ownership invariants.
3. Define subscriber/backpressure contract.
4. Prefer Presentation-only shared ownership first if global rewrite is risky.
5. Add Porcupine feed adapter; retain Simple standalone adapter if needed.
6. Normalize keyboard/wake signals.
7. Implement bounded pre-roll and trigger boundaries.
8. Add lifecycle/device-busy/backpressure/shutdown/no-persistence tests.

## Files Likely Touched
`realtime_audio.py`, wake adapters, `voice_v2.py`, new capture hub/ports, audio/wake tests.

## Architecture Constraints
Exactly one input stream in Presentation; trigger detection independent from ambient completion; Simple is hard regression boundary; no raw audio files.

## Automated Validation
Wake backend, realtime audio lifecycle, duplex, voice runtime plus new fan-out/load tests.

## Acceptance Criteria
One input owner; manual trigger immediate under load; wake detector shares captured stream; pre-roll bounded/memory-only; non-Presentation tests green.

## Documentation Updates
Document microphone ownership and trigger semantics.

## Handoff Notes
Human check `HV-PRES-AUDIO-01` validates real microphone/wake/manual behavior.
