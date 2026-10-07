# Slice 08 — Autonomy, Ownership and Guardrails

## Goal

Make Tool Brain the single normal-path UI decision owner while preserving safe fallbacks, preventing double execution and mechanically guarding destructive UI actions.

## Context

The user wants Jarvis to know UI capabilities but not compete with Tool Brain for execution. Reversible UI actions can be autonomous; destructive/irreversible actions need stronger policy.

## Canonical Concepts

UI decision owner, reversible action, destructive action, fallback/debug path, authority gate.

## Scope

### In Scope

- One explicit normal-path UI execution owner.
- Prevent simultaneous autonomous UI calls from Jarvis and Tool Brain.
- Classify/gate destructive or irreversible UI operations.
- Preserve a clearly marked debug/fallback path if operationally necessary.
- Define behavior when Tool Brain/model is unavailable.
- Prevent repeated failure/retry thrashing.
- Audit browser/display operations for scope escape.

### Out of Scope

- User content-policy systems unrelated to UI ownership.
- Delegating non-UI permissions.

## Dependencies

- `05-tool-brain-runtime`
- `06-action-queue-revalidation`
- `07-ui-capability-adapters`

## Implementation Steps

1. Introduce/extend an authority gate at the canonical UI facade.
2. Route normal Jarvis UI intents to Tool Brain rather than direct mutations.
3. Add side-effect-class policy for destructive actions.
4. Make any direct debug/fallback execution explicit, logged and mutually exclusive with Tool Brain.
5. Define safe degradation when decision runtime is unavailable.
6. Add concurrency tests proving no double mutation.
7. Add trace evidence for blocked, allowed and fallback paths.

## Files Likely Touched

UI tool routing/facade, Brain runtime integration, Tool Brain runtime and policy tests.

## Architecture Constraints

Capability awareness is not execution authority. Never silently hand all UI tools back to Jarvis on a Tool Brain error without an explicit observable policy.

## Automated Validation

- Normal path has one UI decision owner.
- Concurrent duplicate requests do not double-apply mutations.
- Reversible actions flow autonomously.
- Destructive actions fail closed or require the repository's explicit confirmation policy.
- Decision-runtime outage keeps UI safe.

## Acceptance Criteria

- Ownership boundary is enforceable in code, not only prompt text.
- Jarvis speech remains capability-correct while direct UI calls are suppressed in normal operation.

## Documentation Updates

Document ownership/authority matrix and fallback semantics.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. Routing/prompt changes require `agent-trace-analysis`.
