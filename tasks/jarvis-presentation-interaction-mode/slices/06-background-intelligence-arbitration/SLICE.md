# Slice 06 — Background intelligence, priority and preemption

## Goal

Allow Presentation mode to prepare useful work proactively without ever slowing or hijacking explicit user interactions.

## Context

The product principle is "work a lot, manifest little". This requires bounded speculative work plus deterministic arbitration.

## Canonical Concepts

Background sub-agent/task, priority lane, cancellation/deprioritization, prepared resource, explicit addressed turn.

## Scope

### In Scope

- Define triggers/thresholds for high-value speculative preparation.
- Launch bounded background work for research, fact-checking, document resolution, calculations and visual preparation.
- Track ownership, reason, source context and cancellation token/state.
- Give explicit addressed turns absolute priority.
- Cancel/deprioritize stale speculative work and queued speculative UI intents when context changes.
- Register successful results into the Presentation working set as prepared resources/references.

### Out of Scope

- Unbounded autonomous research.
- General task scheduler rewrite.
- UI execution itself.

## Dependencies

- `05-presentation-working-set`
- `04-ambient-presentation-lane`

## Implementation Steps

1. Reuse existing task/sub-agent primitives and concurrency controls.
2. Add Presentation-specific trigger/arbitration policy.
3. Implement explicit-turn preemption hooks.
4. Register completed results with provenance/freshness.
5. Add deterministic tests for cancellation, reuse, stale discard and resource contention.

## Files Likely Touched

Presentation runtime/policy, task/sub-agent adapter glue, working-set integration, tests, docs.

## Architecture Constraints

No new general scheduler. Speculative work must be bounded, observable and disposable.

## Automated Validation

Tests proving explicit-turn latency/priority, bounded concurrency, cancellation/deprioritization and reuse of prepared work.

## Acceptance Criteria

Presentation can prepare useful resources while remaining immediately responsive to explicit user requests.

## Documentation Updates

Document priority order, cancellation semantics and speculative-work limits.

## Handoff Notes

Coding/runtime Slice: load `/caveman` and `/coding-guideline`; requires `agent-trace-analysis`.
