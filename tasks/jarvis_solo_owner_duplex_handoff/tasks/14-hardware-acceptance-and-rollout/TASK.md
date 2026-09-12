# Task 14 — Run hardware acceptance, benchmark, select defaults, and document rollout

## Goal

Validate the architecture on the real workstation, select evidence-backed defaults, and close the handoff with rollback-ready documentation.

## Context

The latest main audio fixes were heavily tested in simulation/fake PortAudio but explicitly not fully validated on the actual microphone/speakers against the real provider. This task closes that gap.

## Scope
### In Scope
- real microphone + laptop speakers;
- headset path;
- office conversation/background speech;
- owner interruption during non-owner speech;
- long continuous sessions;
- server vs semantic VAD comparison;
- speaker-verifier threshold/default selection;
- optional commercial engine comparison if access exists;
- full regression/release verification;
- final report and rollout/rollback instructions.

### Out of Scope
- negotiating commercial contracts as a prerequisite to closing the local baseline.
- future room-assistant permissions.

## Dependencies

Tasks 05–09 and 10–13 complete enough for integrated acceptance.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Record exact hardware, OS, audio device, sample rates, engine/model versions.
2. Run scenarios from `docs/04-testing-and-quality.md`.
3. Collect owner false accept/reject and P50/P95 confirmation latency.
4. Measure end-to-end owner barge-in local stop latency.
5. Compare semantic/server VAD on natural hesitant speech.
6. If more than one speaker engine is available, run the same benchmark manifest and select based on data.
7. Verify work-state parity: UI and brain use same Core state.
8. Run full test/release suite.
9. Write final implementation report including deviations and rollback.

## Files Likely Touched

- benchmark result artifacts under an appropriate non-sensitive docs/results location
- `docs/OPERATIONS.md`
- acceptance status docs
- final resolution report
- defaults/config only after evidence

## Architecture Constraints

- Do not commit private voice recordings or biometric profiles.
- Do not choose a commercial engine based only on marketing benchmarks.
- Preserve a simple rollback to open/current voice behavior.

## Testing Requirements

All scenario and regression requirements from `docs/04-testing-and-quality.md` plus full repository release verification.

## Acceptance Criteria

- Solo Owner works on real hardware without repeated interruptions from nearby conversation.
- Owner can interrupt JARVIS reliably, including during background speech.
- No self-echo loop.
- sentence beginnings are preserved.
- Core work-state is shared by brain/UI.
- chosen defaults are supported by measured results.
- rollback is documented and tested.

## Documentation Updates

Complete final report, acceptance status, operations, and any benchmark decision record.

## Handoff Notes

This task is the gate for declaring the hybrid architecture complete.
