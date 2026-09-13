# Task 20 — Run cross-architecture benchmark, choose provisional defaults, and close migration

## Goal

Validate the three modes end-to-end, compare them on real JARVIS workloads, and set evidence-based provisional defaults without removing alternatives.

## Context

GPT-Live is the principal expected Duplex target, but Realtime Mini and Realtime Mini + Luna must remain switchable so performance/cost tradeoffs can be measured rather than assumed.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Define a repeatable benchmark script/conversation suite using common scenarios.
- Run Simple Realtime baseline, Front Brain Realtime+Luna, and Duplex GPT-Live when credentials/models are available.
- Include quiet/ambient periods, short confirmations, long monologues, direct questions, long backend work, interruption/noise, and mode switch.
- Collect Task 18 metrics and cost data.
- Compare reflex quality, latency, stale output, blocking, barge-in, task delegation, session active time, and cost.
- Choose provisional default architecture/config from evidence and record rationale.
- Run full regression suite and migration checks.

### Out of Scope
- Deleting non-winning architectures.
- Pretending unavailable provider tests were run.

## Dependencies
- All Tasks 01-19.

## Implementation Steps
- 1. Freeze benchmark prompt/config revisions and test scenarios.
- 2. Run deterministic replay first.
- 3. Run live provider tests only where authorized credentials/model access exist.
- 4. Collect metrics and manually annotate conversational quality cases.
- 5. Compare against baseline and acceptance thresholds from testing docs.
- 6. Set provisional default only if evidence is adequate; otherwise keep current safe default and mark unresolved.
- 7. Write final benchmark/migration section for orchestrator final report.

## Files Likely Touched
- Benchmark runner/scenarios
- Benchmark reports
- Default config if evidence supports change
- Docs/decision log
- Regression tests

## Architecture Constraints
- Do not tune one architecture on a different scenario set.
- Record exact model/prompt/config fingerprints.
- Unavailable Live/Gemini tests remain explicit gaps, not inferred passes.
- Keep architecture switch available after choosing a default.

## Testing Requirements
- Full unit/integration/architecture/replay suite.
- At least one representative end-to-end conversation per available architecture.
- Live lifecycle orphan/stop tests re-run before declaring Duplex usable.

## Acceptance Criteria
- Benchmark report compares all available modes on the same metrics.
- A provisional default is justified by evidence or explicitly left unresolved.
- No regression gate from the source incident suite fails.
- Existing settings migrate without silent behavior loss.

## Documentation Updates
- Finalize decision log, benchmark plan/results, open questions, and implementation report.

## Handoff Notes

This is a closeout/decision task, not permission to collapse the architecture back into one provider-specific path.
