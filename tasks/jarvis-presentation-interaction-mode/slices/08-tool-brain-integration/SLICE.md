# Slice 08 — Integrate Presentation semantic UI intents with Tool Brain

## Goal

Route Presentation display/attention intentions through the canonical Tool Brain instead of directly invoking UI tools.

## Context

`jarvis-tool-brain-ui-orchestrator` owns UI decision/timing, current-state constrained tool choice, action queueing and cancellation.

## Canonical Concepts

Tool Brain, semantic UI intent, UI perception snapshot, action queue, runtime precondition validation, Presentation urgency.

## Scope

### In Scope

- Consume the Tool Brain public contract after a freshness audit.
- Publish Presentation semantic intent with enough context, resource refs and urgency for Tool Brain to act.
- Propagate cancellation/replacement when explicit turns or context changes invalidate speculative UI actions.
- Preserve speech/UI synchronization hints where Tool Brain supports them.
- Add trace correlation from Presentation decision -> Tool Brain intent -> UI action.

### Out of Scope

- Reimplementing Tool Brain.
- Direct low-level UI calls in the normal path.
- Hard-coding one model implementation.

## Dependencies

- `07-manifestation-policy`
- External: `jarvis-tool-brain-ui-orchestrator` public contract available/stable enough for integration.

## Implementation Steps

1. Freshness-audit Tool Brain contract immediately before work.
2. Add the narrow Presentation adapter/publisher.
3. Map urgency/cancellation/resource refs without leaking Presentation internals.
4. Add fake Tool Brain integration tests and real trace validation.

## Files Likely Touched

Presentation-to-Tool-Brain adapter, shared intent/event schemas if needed, integration tests, docs.

## Architecture Constraints

Tool Brain remains UI decision owner. Runtime state remains authoritative and may reject stale actions.

## Automated Validation

Fake/contract tests for intent publication, cancellation, stale rejection and trace correlation; no direct UI-tool invocation path from Presentation policy.

## Acceptance Criteria

Presentation can request visual/attention outcomes without choosing concrete UI tools, and stale/speculative requests can be cancelled/replanned.

## Documentation Updates

Document semantic contract and ownership boundary.

## Handoff Notes

Coding/runtime Slice: load `/caveman` and `/coding-guideline`; requires `agent-trace-analysis`.


## Slice 00 contract (binding)

**Status: DEFERRED (A2).** Not dispatched in this run.

Entry condition (checked by agent 0 before any dispatch):
- `jarvis-tool-brain-ui-orchestrator` is merged on `main`;
- its public intake for semantic UI intents, with cancellation, is documented at Level 3;
- a freshness check of `jarvis/core/presentation_display.py` and `jarvis/domain/presentation_intent.py` against that contract passes.

Intended binding:
- one `ToolBrainDisplaySink` implementing `PresentationDisplaySink` (Slice 07), selected in `PresentationComposition.build`;
- `withdraw_speculative` → Tool Brain cancellation of queued speculative UI actions (scenario 9);
- policy, gate and intent semantics unchanged except additive fields;
- trace assertion: a display action carries a Tool Brain receipt;
- `DirectSceneDisplaySink` retained as the fallback when Tool Brain is unavailable, said once.

QA tier when undeferred: glue + agent-trace-analysis.

Depends on: 07, plus the external merge.
