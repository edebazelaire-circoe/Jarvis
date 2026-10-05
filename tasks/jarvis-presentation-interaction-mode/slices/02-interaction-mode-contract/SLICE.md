# Slice 02 — Canonical Presentation mode state and lifecycle

## Goal

Make PRESENTATION a reliable effective interaction mode without regressing SIMPLE or redefining current persistence ownership.

## Context

Board/Session work already established interaction-mode persistence semantics. Presentation behavior needs a single authoritative effective mode visible to runtime subsystems.

## Canonical Concepts

Interaction mode, Board/Session persistence, effective runtime state, SIMPLE, PRESENTATION, reserved REUNION.

## Scope

### In Scope

- Reconcile/complete `SIMPLE` and `PRESENTATION` enum/state handling.
- Preserve `SIMPLE` as default/safe fallback.
- Respect current canonical persistence scope discovered in Slice 01.
- Emit mode-change events consumed by ambient/presentation runtime and observability.
- Ensure Presentation teardown stops Presentation-only speculative activity.
- Preserve REUNION as reserved only if already product-visible.

### Out of Scope

- Meeting behavior.
- Ambient analysis itself.
- Control Center visuals beyond backend/state hooks.

## Dependencies

- `01-contract-reconciliation`

## Implementation Steps

1. Reuse canonical settings/effective-mode owner.
2. Add missing lifecycle hooks for entering/exiting PRESENTATION.
3. Make transitions idempotent and restart-safe according to current Session/Board contracts.
4. Add deterministic tests for default, activation, deactivation, restart/rehydration and invalid state.

## Files Likely Touched

Interaction-mode runtime/settings, persistence adapter, mode events, tests, docs.

## Architecture Constraints

No second settings store. No new voice architecture branch. Capture lifecycle remains independent.

## Automated Validation

Unit/integration tests for state transitions, persistence, fallback and Presentation teardown.

## Acceptance Criteria

Every runtime subsystem can observe one canonical effective mode, SIMPLE remains unchanged, and PRESENTATION transitions are deterministic.

## Documentation Updates

Document lifecycle, persistence owner and explicit non-goals.

## Handoff Notes

Coding Slice: load `/caveman` and `/coding-guideline`.
