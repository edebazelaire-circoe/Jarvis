# Task 18 — Add per-session voice benchmark metrics and reports

## Goal

Measure architecture quality, latency, correctness, and cost on the same metrics so default choices are evidence-driven.

## Context

Raw model speed is not enough. The source failures include backend blocking, speech-queue delay, stale output, voice/backend divergence, false barge-ins, and stalls.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Record architecture, provider/model IDs, prompt fingerprints, config snapshot ID, session duration, Live active seconds, and provider usage.
- Measure time to first audible reaction and time to first useful answer where events permit.
- Measure backend task start/result, frontend blocking time, delegation latency, speech queue wait, stale cancellation, user interruption, false/rejected barge-in, output stall, unnecessary acknowledgement, and divergence between intended/spoken output.
- Produce machine-readable per-session record plus readable summary.
- Add cost estimator layer using versioned pricing metadata rather than hardcoded UI constants.

### Out of Scope
- Declaring a winning architecture.
- Building a large analytics platform.

## Dependencies
- Tasks 04 state, 06-08 conversation policies, 10/12 modes, 13 lifecycle.

## Implementation Steps
- 1. Define metric event schema and session fingerprint.
- 2. Instrument canonical boundaries rather than provider-specific call sites where possible.
- 3. Add derivation for queue/backbrain/front latency components.
- 4. Add session summary writer/reporter.
- 5. Add pricing metadata interface and clearly label estimates.
- 6. Test metrics with fake clock and deterministic event stream.

## Files Likely Touched
- Tracing/metrics module
- Canonical event instrumentation
- Session report writer
- Pricing metadata adapter
- Tests

## Architecture Constraints
- Metrics must be comparable across architectures.
- Do not conflate backend-ready latency with speech-queue latency.
- Cost estimates must record pricing version/source/date.

## Testing Requirements
- Synthetic timeline yields expected latency decomposition.
- Intended-vs-spoken divergence increments metric.
- Live active seconds come from lifecycle state, not UI timer.
- Same test fixture produces comparable metric keys in all architectures.

## Acceptance Criteria
- A benchmark session produces one report sufficient to compare Simple, Front Brain, and Duplex on quality, latency, and cost.

## Documentation Updates
- Update docs/08-benchmark-plan.md with exact metric names/report location.

## Handoff Notes

Avoid subjective score collapse too early; retain raw measurements and annotated user-quality outcomes.

Task07 adds checked all-part device completion and distinguishes stop requested from stop confirmed. Keep provider first PCM, attempted playback, first successful native write, and full device drain separate in metrics. Inventory still finds the unguarded bridge first-audio callback preceding the native write; do not relabel that observation as proven device delivery. Align the metric producer with its documented boundary and cover write rejection/failure/pending cleanup, while preserving existing six latency measurements and correlation tests. Guarded preambles already report first-audio only after a successful write.
