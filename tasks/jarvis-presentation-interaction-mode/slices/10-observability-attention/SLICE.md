# Slice 10 — Presentation observability and discreet attention surface

## Goal

Make Presentation behavior debuggable and surface high-value contradiction attention without spoken interruption.

## Context

The canonical conversation observability task already owns the shared event record and live timeline. Presentation must extend it, not create a separate log.

## Canonical Concepts

Conversation event, trace link, Presentation decision, background job, fact-check attention, Tool Brain action.

## Scope

### In Scope

- Emit canonical events for ambient classification, working-set changes, background work, preemption, manifestation decisions and Tool Brain intent/action correlation.
- Extend the existing timeline/debug surface with Presentation-specific visibility where useful.
- Implement/reuse a discreet small attention/fact-check UI signal plus non-verbal audible cue if product audio conventions support it.
- Let the user explicitly ask Jarvis to explain the attention item.
- Support clearing/expiry/staleness.

### Out of Scope

- A second diagnostics page/log.
- Unsolicited spoken fact-check explanation.
- Full fact-check research engine redesign.

## Dependencies

- `07-manifestation-policy`
- `08-tool-brain-integration`
- `09-scene-prefab-integration`
- External canonical observability contract.

## Implementation Steps

1. Map Presentation lifecycle to canonical event types/trace links.
2. Extend timeline projections/lanes minimally.
3. Implement attention signal through canonical Tool Brain/scene path where appropriate.
4. Add explain/clear/expire semantics.
5. Validate trace correlation end to end.

## Files Likely Touched

Event schemas/producers, timeline UI projection, attention UI adapter, tests, docs.

## Architecture Constraints

Canonical event ledger remains source of truth. Attention is a manifestation of a Presentation decision, not a new conversation turn.

## Automated Validation

Event projection tests, frontend/runtime tests, trace-analysis proving event chain, attention expiry/clear tests.

## Acceptance Criteria

A developer can trace why Jarvis stayed silent, prepared work, interrupted speculative work, displayed something or raised attention; the user gets a discreet actionable signal for high-confidence contradictions.

## Documentation Updates

Document new event types/projections and attention lifecycle.

## Handoff Notes

Frontend/runtime coding Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude when supported. Requires `agent-trace-analysis`.
