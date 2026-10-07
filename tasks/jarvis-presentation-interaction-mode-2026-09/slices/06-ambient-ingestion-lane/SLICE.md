# Slice 06 - Implement continuous ambient ingestion and asynchronous analysis admission

## Goal
Turn Presentation audio into near-real-time ambient transcript observations without making observations commands or allowing enrichment backlog to delay explicit interaction.

## Context
Long continuous speech is expected. Heavy work must be selective, not per frame, and ambient backlog may lag.

## Canonical Concepts
Ambient observation not addressed command; recent transcript tail; bounded async analysis queue; cheap analysis before expensive delegation.

## Scope
### In Scope
- Segment continuous audio into bounded utterances/chunks using existing VAD/turn evidence where practical.
- Transcribe ambient chunks through provider-neutral path.
- Append committed/revised transcript evidence to recent tail promptly.
- Emit typed ambient observation events.
- Cheap topic/entity/claim/reference extraction/trigger classification.
- Bounded queues, dedupe/revision, stale cancellation, backpressure diagnostics.
- Ambient failure isolation from command lane.
### Out of Scope
Authorizing actions from ambient text; fact-check alert policy; speculative sub-agent execution.

## Dependencies
Slices 04 and 05.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Audit current transcription/Realtime transcript events; choose least-duplicated seam.
3. Define observation identity/revision and queue budgets.
4. Update transcript tail before optional heavy analysis.
5. Suppress low-value filler and identify research-worthy claims/references.
6. Ensure ambient cannot enter ordinary addressed Brain admission or mutation tools.
7. Add lag/backlog telemetry using IDs/timings, not raw audio.
8. Add slow-worker tests proving command independence.

## Files Likely Touched
Voice/realtime transcript bridge; new ambient service; transcription seam; working-set service; tests/fixtures.

## Architecture Constraints
Ambient text is context only; do not weaken addressed `BackBrainTaskService`; heavy analysis lower priority.

## Automated Validation
Ambient ingestion/revision/backpressure tests plus voice event/admission/replay suites.

## Acceptance Criteria
Continuous speech updates fresh tail; observations trigger analysis without actions; slow ambient does not block trigger acceptance; queue growth bounded/observable.

## Documentation Updates
Document ambient observation admission, queue limits and failure isolation.

## Handoff Notes
Slice 08 consumes triggers; Slice 10 consumes fresh tail.
