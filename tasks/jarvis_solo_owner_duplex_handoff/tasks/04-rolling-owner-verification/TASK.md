# Task 04 — Integrate rolling owner verification into duplex capture

## Goal

Run owner verification continuously on candidate audio windows without creating a monolithic ignored speaker segment.

## Context

The user explicitly raised the case where another person speaks continuously and the owner starts talking over them. Owner recognition must continue on rolling evidence.

## Scope
### In Scope
- Feed AEC-cleaned candidate PCM to verifier.
- Sliding/bounded evidence windows.
- owner candidate/confirmed/rejected state machine.
- shadow-only first path.
- do not alter current duck/cut yet unless required to expose the state seam.

### Out of Scope
- final barge-in authority switch (Task 05).
- provider transcript filtering changes.

## Dependencies

Task 03.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Decide whether verification processes every frame or only near-end candidate regions; benchmark CPU implications.
2. Keep rolling evidence through non-owner speech; never set a global “ignore until silence” latch.
3. Ensure owner can be confirmed during overlapping/ongoing non-owner speech when the engine supports it.
4. Add bounded state and reset at session boundaries.
5. Emit shadow latency/score diagnostics.

## Files Likely Touched

- `jarvis/audio/duplex.py`
- speaker verifier adapter/port
- voice diagnostics
- `tests/unit/test_voice_duplex.py`

## Architecture Constraints

- AEC remains before speaker verification.
- `NearEndDetector` is candidate prefilter, not identity.
- No network I/O.

## Testing Requirements

- long non-owner sequence then owner sequence without silence;
- non-owner + owner overlap scripted fake verifier;
- no unbounded buffer growth;
- reset between sessions;
- shadow mode leaves legacy/current output identical.

## Acceptance Criteria

- Owner state can transition during an already-active non-owner acoustic segment.
- No global non-owner latch blocks later owner detection.

## Documentation Updates

Add state-machine notes/diagnostic meanings.

## Handoff Notes

Prefer deterministic fake-verifier tests for overlap semantics; real-model overlap quality belongs to Task 09/14.
