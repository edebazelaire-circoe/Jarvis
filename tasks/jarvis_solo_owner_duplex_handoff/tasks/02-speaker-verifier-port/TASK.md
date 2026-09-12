# Task 02 — Add SpeakerVerifier port, fake, and shadow telemetry

## Goal

Create a provider-neutral speaker-verification boundary and prove it can run in shadow mode without affecting audio routing.

## Context

The current `NearEndDetector` is acoustic only. It must feed a separate identity authority.

## Scope
### In Scope
- Typed `SpeakerVerification` result.
- `SpeakerVerifier` port suitable for local streaming use.
- deterministic fake/noop implementation for tests.
- lifecycle/reset/close semantics.
- shadow diagnostics with bounded metadata.

### Out of Scope
- Real model adapter.
- Owner-gated barge-in.

## Dependencies

Task 01.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Choose a port location consistent with existing `WakeWordBackend`/audio boundaries.
2. Ensure capture-thread calls never require network/async waits.
3. Define score semantics explicitly (`higher = more likely owner`, range if normalized).
4. Add a fake verifier that can script scores over frames/windows.
5. Add shadow-mode hooks and diagnostic events without raw embeddings/audio.
6. Keep verifier failures non-fatal to Voice, but surface `unavailable/degraded` state.

## Files Likely Touched

- `jarvis/ports/v2.py` or dedicated audio ports
- new adapter/fake modules
- `jarvis/audio/duplex.py` integration seam
- tests/unit audio tests

## Architecture Constraints

- No provider-specific types above adapter boundary.
- No hidden network call in capture callback.
- Diagnostics are metadata-only.

## Testing Requirements

- fake score sequences;
- reset behavior;
- exception/degraded behavior;
- shadow mode does not change emitted PCM/signals;
- telemetry contains no PCM/embedding content.

## Acceptance Criteria

- A verifier can be injected and observed without behavior change.
- Tests can simulate owner/non-owner/ambiguous score sequences deterministically.

## Documentation Updates

Document port contract and score semantics.

## Handoff Notes

This seam is what allows later Eagle/Vivoka/sherpa/SpeechBrain comparisons without rewriting the bridge.
