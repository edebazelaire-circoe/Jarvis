# Task 07 — Improve VAD, interruption, and noise handling

## Goal

Reduce false interruption behavior from environmental noise while preserving responsive true barge-in.

## Context

The transcript recorded 71 local speech detections while JARVIS spoke, 63 not confirmed by OpenAI, including seven bus-triggered false detections. Local candidate detection currently has too much user-visible effect.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Separate local candidate speech from confirmed user interruption.
- Tune/use semantic VAD where provider support exists and expose eagerness/configuration through capability-aware settings later.
- Delay destructive cancellation/ducking until sufficient confidence while keeping low-latency audio capture.
- Integrate with existing Solo Owner / owner voice recognition work rather than duplicating it.
- Record candidate, confirmed, rejected, and cancellation outcome diagnostics.
- Establish a real local device end-of-output proof for natural completion, preserving interruption epochs and PortAudio lock safety. Task05 conservatively reports partial/unknown delivery because the existing cursor subtracts device latency and the Python queue fence does not establish device drain.

### Out of Scope
- Training a custom speaker model from scratch.
- Solving all acoustic echo cancellation.

## Dependencies
- Task 05 adapter; Task 01 inventory of existing owner-recognition plan.

## Implementation Steps
- 1. Map current local VAD and provider VAD timing.
- 2. Introduce candidate/confirmed interruption state.
- 3. Define thresholds/hysteresis and provider-specific semantic VAD settings behind adapter capability flags.
- 4. Add owner-recognition signal when existing subsystem can provide it.
- 5. Build bus/noise fixture from trace characteristics or synthetic equivalent.
- 6. Measure false-positive and true interruption latency before/after.

## Files Likely Touched
- VAD/barge-in controller
- Realtime adapter settings
- Owner-recognition integration points
- Diagnostics
- VAD tests/fixtures

## Architecture Constraints
- A weak local detection must not immediately destroy valid speech output.
- Do not make true barge-in feel unresponsive merely to improve false-positive statistics.
- Provider-specific knobs remain inside adapters/config registry.

## Testing Requirements
- Bus/noise fixture no longer causes repeated audible ducking/cancellation.
- Confirmed owner speech still interrupts promptly.
- Provider refusal `no active response found` is handled and traced without corrupting state.
- Natural complete playback may confirm the matching full generated transcript only after an actual device completion boundary. Buffered, interrupted, failed, or stale-epoch output remains partial/unknown; no duration-to-character alignment guesses. Exercise real audio wrapper behavior with a controlled device buffer, not only manually injected canonical completion.

## Acceptance Criteria
- False interruption rate in the replay fixture is materially reduced from the source behavior.
- All interruption state transitions are observable in trace.

## Documentation Updates
- Record chosen thresholds, semantics, and owner-recognition dependency in docs/05-reflex-optimization.md.

## Handoff Notes

Benchmark thresholds rather than tuning solely by intuition.

Read `docs/device-playback-completion-plan.md` in this handoff before implementing the device completion boundary. Parent-reviewed research identifies checked `RawOutputStream.stop(ignore_errors=False)` as the smallest supported drain proof, with explicit native-worker ownership, epoch validation and timeout uncertainty. The normal canonical path must actually call the mechanism; a standalone unused helper does not satisfy the requirement.
