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


## Slice 00 contract (binding)

Scope in:
- **Pool and reserve defaults.**
  - `DEFAULT_SPECULATIVE_POOL = 3` and `DEFAULT_RESERVED_EXPLICIT_SLOTS = 1` in `domain/presentation_speculative.py`. `MAX_SPECULATIVE_POOL = 8` (:404) stays the hard ceiling.
  - `PresentationSpeculativeService` defaults to them (`core/presentation_speculative.py:393-403`).
  - `_presentation_composition` (`app.py:730`) reads `presentation_speculative_pool` and `presentation_reserved_explicit_slots` from the existing settings overrides. Invalid values fall back to the defaults with one warning line.
  - These settings are passed through `PresentationComposition` to the service ctor (`presentation_runtime.py:1439-1445`).
  - No UI surface.
- **Reachability, explicit.**
  - Add a derived `REACHABLE_CAPABILITIES` = trigger table (`:550`) ∪ explicit REFRESH capabilities.
  - Document `CODE_INSPECTION` and `DATA_ANALYSIS` as **unreachable in V1**: kept in the closed vocabulary, no trigger.
  - Document effective tools = `CAPABILITY_TOOLS` ∩ `CLI_GRANTABLE_TOOLS` (`claude_local.py:294`); `memory_search` and `scene_*` are stripped.
  - Replace the prose at `:214-219`.
- **Named visual command.** Record that it is resolved by Slice 05 P5, not by a matcher here.

Scope out: lexical matching; CPU/RAM arbitration beyond the pool; timeline events (10).

Files: `jarvis/domain/presentation_speculative.py`, `jarvis/core/presentation_speculative.py`, `jarvis/runtime/presentation_runtime.py`, `jarvis/app.py`, `docs/presentation-speculative-preparation.md`, `docs/OPERATIONS.md` (settings keys), `tests/unit/test_presentation_speculative.py`.

Acceptance:
- `test_default_pool_is_two_speculative_plus_one_reserved`: a third speculative job is refused or queued per the existing rule; an explicit one is admitted.
- `test_pool_setting_configurable_within_ceiling`; `test_invalid_pool_setting_falls_back_with_one_warning`.
- `test_reachability_table_matches_trigger_and_refresh_paths`; `test_effective_cli_tools_per_capability`.
- `test_addressed_turn_preempts_with_smaller_pool`: existing preemption semantics hold at pool 3.
- Existing `test_presentation_speculative.py` and `test_presentation_integration.py` green. Assertions that hard-code 8/2 are updated to the constants, not deleted.

QA tier: glue. Passes:
- qa-verification + code-review;
- runtime-validation on this host: one real `presentation_preparation` run with the installed Claude CLI. This proves the `--tools` argv is accepted (residual risk 5) and records the peak RSS of 2 concurrent real sub-agents against free RAM.

Not yours: projection content (05); subagent events (10).

Depends on: 05.

Documentation: speculative arbitration Level 3.
