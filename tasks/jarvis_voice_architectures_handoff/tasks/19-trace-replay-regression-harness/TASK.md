# Task 19 — Build transcript and trace replay regression harness

## Goal

Turn the September 11 failure session into deterministic regression scenarios that future architecture changes cannot silently reintroduce.

## Context

The transcript contains concrete failures: 8/18 backend responses replaced by voice improvisation, stale queue delays near 30-36 seconds, 63 unconfirmed local speech detections, seven bus false detections, and output stalls.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Create replay fixture format from transcript/trace events with fake clock.
- Add scenarios for backend/spoken divergence, stale FIFO output, long blocking backend task, bus/noise false interruption cluster, output stall, user interruption, and session closure.
- Assert corrected policy outcomes rather than exact natural-language strings where possible.
- Make harness runnable against fake adapters and, optionally, recorded provider event adapters.
- Produce regression summary.

### Out of Scope
- Replaying copyrighted/provider raw audio if unavailable.
- Network-dependent tests as the only regression gate.

## Dependencies
- Tasks 03-08 canonical/state/policy layers and Task 18 metrics.

## Implementation Steps
- 1. Translate source transcript incident timeline into deterministic fixture(s).
- 2. Build fake-clock driver for canonical events.
- 3. Encode expected invariants: no stale filler, no backend/spoken silent divergence, rejected noise does not repeatedly duck/cancel, long backend task does not block later turns.
- 4. Add output-stall recovery test.
- 5. Wire metrics assertions into replay report.
- 6. Document how to add future field transcripts as fixtures.

## Files Likely Touched
- Replay harness
- Fixtures derived from source transcript
- Regression tests
- Replay report output

## Architecture Constraints
- Prefer behavioral invariants over matching exact generated prose.
- Keep source evidence traceable to incident timestamps/IDs.
- No network required for core replay gate.

## Testing Requirements
- Run all replay scenarios under fake adapters.
- At minimum verify the historical 35.9s stale response cannot be spoken after supersession.
- Verify historical voice/backend divergence becomes observable and policy-safe.
- Verify bus-like rejected detections do not create repeated destructive interruption.

## Acceptance Criteria
- The historical failure classes are reproducible before fixes where feasible and prevented/detected after fixes.

## Documentation Updates
- Update docs/04-testing-and-quality.md with replay commands and fixture provenance.

## Handoff Notes

Use the copied source transcript under `sources/` as the durable evidence base; if raw trace exists in repo, add a sanitized fixture rather than relying only on prose.
