# Slice 05 — Tool Brain Runtime and Hybrid Wakeups

## Goal

Implement the provider-neutral Tool Brain decision runtime with event-driven wakeups, periodic safety ticks, targeted inspection loops and an observe-only shadow mode.

## Context

The Tool Brain is an orchestration decision component, not a new source of UI truth. It must be fast to wake, bounded in context and replaceable at the model layer.

## Canonical Concepts

Tool Brain runtime, wake event, decision input/output, model adapter, shadow mode, inspection loop.

## Scope

### In Scope

- Lifecycle/service boundary for Tool Brain.
- Provider/model-neutral decision adapter.
- Event subscriptions for important user/Jarvis/UI/runtime changes.
- Configurable periodic fallback tick.
- Decision context assembly: trigger + snapshot + capability manifest + queue summary.
- Structured decision schema for inspections and action proposals.
- Bounded multi-step inspection before final action selection.
- Shadow/observe-only mode producing full traces without mutation.
- Latency/error metrics.

### Out of Scope

- Persistent training/fine-tuning pipeline.
- Non-UI tool delegation.
- Final action execution semantics (Slice 06).

## Dependencies

- `02-ui-tool-choice-contract`
- `03-perception-world-model`
- `04-jarvis-intent-speech-contract`

## Implementation Steps

1. Define Tool Brain request/response schemas independent of one model provider.
2. Subscribe to canonical events with debouncing/coalescing where safe.
3. Implement periodic fallback without delaying critical event-driven wakes.
4. Add bounded inspection turns using read-only tools/choices.
5. Implement shadow mode and record would-be actions.
6. Add cancellation of in-flight decisions when a newer high-priority event supersedes them where runtime supports it.
7. Instrument decision latency and errors.

## Files Likely Touched

New Tool Brain runtime/model adapter/event subscription modules plus configuration and tests.

## Architecture Constraints

No direct mutation from the model adapter. Structured outputs go to the queue/executor boundary. No hidden dependency on one model vendor response format.

## Automated Validation

- Immediate events wake without waiting for the periodic tick.
- Tick works when no events arrive.
- Shadow mode performs zero mutations.
- Inspection loops are bounded and choice-constrained.
- Superseded decisions do not enqueue stale actions.

## Acceptance Criteria

- Real traces show Tool Brain receiving the intended state and proposing valid UI actions in shadow mode.
- Runtime can swap decision adapters without changing perception/tool contracts.

## Documentation Updates

Document runtime lifecycle, wake classes, decision schema and configuration.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. Agent runtime requires `agent-trace-analysis` with real traces.
