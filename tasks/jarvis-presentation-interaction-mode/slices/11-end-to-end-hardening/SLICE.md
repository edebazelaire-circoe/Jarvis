# Slice 11 — End-to-end Presentation hardening

## Goal

Prove the complete Presentation experience under realistic deterministic scenarios and eliminate regressions, privacy leaks and latency hazards.

## Context

Presentation spans audio context, mode state, Brain reasoning, sub-agents, speech, Tool Brain, scene/prefab and observability. Unit correctness alone is insufficient.

## Canonical Concepts

End-to-end scenario, deterministic replay, latency budget, privacy boundary, explicit-turn priority, SIMPLE regression safety.

## Scope

### In Scope

- Build/reuse deterministic presentation transcript/audio fakes and scenario fixtures.
- Run the scenario matrix in `docs/04-testing-and-quality.md`.
- Validate SIMPLE mode regression safety.
- Validate mode transitions, cancellation, stale-context behavior, prepared-resource reuse, contradiction attention, and recording boundary.
- Measure explicit-turn latency impact and background concurrency/resource use.
- Run full required QA composition and remediate findings.

### Out of Scope

- Adding unrelated new Presentation features.
- Per-user interruption preference learning.
- REUNION behavior.

## Dependencies

- `03-control-center-mode-ui`
- `04-ambient-presentation-lane`
- `05-presentation-working-set`
- `06-background-intelligence-arbitration`
- `07-manifestation-policy`
- `08-tool-brain-integration`
- `09-scene-prefab-integration`
- `10-observability-attention`

## Implementation Steps

1. Assemble deterministic end-to-end fixtures/replays.
2. Execute required scenario matrix.
3. Measure/compare explicit-turn latency and resource usage.
4. Run QA: `qa-verification`, `code-review`, `runtime-validation`, `agent-trace-analysis`.
5. Fix every regression introduced by the task.
6. Perform final Human validation only after machine QA is clean.

## Files Likely Touched

E2E/runtime tests, fixtures, performance tests, docs; product code only for remediation.

## Architecture Constraints

Do not weaken authority/privacy boundaries to make tests pass. SIMPLE must remain the baseline behavior outside PRESENTATION.

## Automated Validation

Full Presentation scenario matrix plus existing Jarvis regression suites and trace assertions.

## Acceptance Criteria

- All deterministic scenarios pass.
- Ambient speech never gains unintended command authority.
- Explicit requests remain highest priority.
- Presentation mode alone does not create durable recordings.
- Visual actions use Tool Brain and canonical scene/prefab paths.
- SIMPLE behavior is not regressed.
- Required QA has no blocking findings.

## Documentation Updates

Finalize operator/developer docs, known limitations and validation evidence references.

## Handoff Notes

Coding/runtime/frontend Slice as required by fixes: load all mandated skills for the affected surface. Human check only after automated QA is exhausted.
