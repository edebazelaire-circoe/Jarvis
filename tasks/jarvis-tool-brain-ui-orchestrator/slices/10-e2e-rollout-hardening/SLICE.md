# Slice 10 — End-to-End Rollout and Hardening

## Goal

Prove the complete Tool Brain path under realistic conversation timing, establish a measured responsiveness baseline, and make Tool Brain the default UI-tool owner without regressions.

## Context

The architecture only delivers value if UI behavior feels synchronized with the conversation and remains correct under interruptions, stale state and long answers.

## Canonical Concepts

End-to-end trace, replay fixture, shadow-vs-live comparison, responsiveness budget, rollout gate.

## Scope

### In Scope

- Replay corpus from shadow traces and deterministic fixtures.
- End-to-end scenarios from `docs/04-testing-and-quality.md`.
- Compare shadow decisions to live execution outcomes.
- Measure trigger/decision/queue/execution latency on supported runtime/model setup.
- Set and document a realistic product responsiveness budget based on measurements.
- Failure/restart/interruption stress tests.
- Migration of normal UI-tool ownership to Tool Brain.
- Remove/disable accidental duplicate normal-path Jarvis UI execution.
- Final documentation and regression cleanup.

### Out of Scope

- Training/fine-tuning a dedicated model.
- Delegating non-UI tools.

## Dependencies

- `07-ui-capability-adapters`
- `08-autonomy-ownership-guardrails`
- `09-observability-timeline-extension`

## Implementation Steps

1. Build a representative replay/evaluation set from real and synthetic traces.
2. Run shadow decisions and score validity, timing appropriateness, cancellation behavior and needless UI churn.
3. Enable live execution progressively by reversible action class.
4. Run interruption/stale/Board/browser scenarios end to end.
5. Measure latency distribution and establish a documented budget.
6. Run full QA matrix including agent-trace analysis and UI runtime validation.
7. Make Tool Brain the default normal-path UI decision owner when gates pass.
8. Update canonical architecture/operations docs and remove stale duplicate documentation.

## Files Likely Touched

Integration tests/evals, runtime configuration/feature flags, docs, and any defects found across prior Slice code.

## Architecture Constraints

Do not broaden into non-UI tool delegation as part of “hardening.” New scope discovered here becomes a follow-up task or explicit new Slice if required for correctness.

## Automated Validation

- Full unit/integration/browser suites.
- Deterministic replay assertions.
- No invalid ID/choice reaches canonical mutation owner.
- No obsolete speech-bound action executes after interruption.
- No double UI mutation from two brains.
- Existing Board/scene/timeline behavior remains regression-free.
- Latency metrics are recorded and compared to the documented budget.

## Acceptance Criteria

- Tool Brain is demonstrably the normal-path UI decision owner.
- Representative live traces are understandable in the existing timeline.
- UI changes track long speech and interruptions without obvious stale behavior.
- Failure modes are safe and observable.
- Final docs describe the operational model and future extension point for non-UI tools/model training.

## Documentation Updates

Promote Tool Brain architecture, tool choice contract, perception, queue and observability to stable canonical documentation (Level 3 where implementation/conformance gates exist).

## Handoff Notes

Use `/caveman` and `/coding-guideline`; use `/impeccable` + Claude for any frontend fixes. Perform maximum machine validation before Human checks.
