# Slice 05 — Build semantic target resolver and visual targeting feedback

## Goal

Use Jarvis's own UI/component geometry to resolve intended targets before capture instead of depending only on exact pixel hit testing.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture and contracts
- current native MediaPipe implementation
- stable hand/capture identity
- semantic interaction events rather than raw mouse-only emulation

## Scope

### In Scope

Implement semantic candidate discovery around the filtered intent point; score actionable Jarvis targets; define BODY plus 4 edges + 4 corners for frame-like components; prioritize corner > edge > body in overlap; provide configurable pre-target visualization: blue BODY/normal, yellow selected edge/corner segment, red secondary/right-click intent. Keep preview dynamic until pinch-down, then hand off a stable capture descriptor.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

01, 03, 04

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; if this Slice changes browser/frontend UI also load /impeccable and use Claude routing when supported.
2. Freshness-check the exact files/contracts named below before editing.
3. Implement the smallest reusable contract/mechanism that satisfies the Slice.
4. Add or update deterministic automated tests before relying on webcam manual checks.
5. Preserve failure cleanup, offline operation and existing security boundaries.
6. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- Control Center/Constellation browser code discovered by freshness audit
- Bare Hands target resolver modules
- CSS/overlay assets
- UI tests

## Architecture Constraints

- MediaPipe-specific data must not leak across the tracker abstraction boundary unnecessarily.
- Per-hand and per-capture state must be explicit and testable.
- User-visible behavior must follow the decision log rather than legacy mouse-only assumptions.
- Unknown current repository component names must be discovered, not invented.

## Automated Validation

Deterministic DOM fixtures prove candidate scoring, neighborhood assistance, zone geometry, correct corner/edge priority, feedback on/off setting, and no permanent cursor when idle.

## Acceptance Criteria

Users can see what will be captured during pre-pinch; small pointer error near a clear target resolves predictably; exact selected edge/corner alone highlights yellow; right-click intent pulses red.

## Documentation Updates

Document component opt-in/metadata required for semantic targets and frame zones.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review for code changes and runtime-validation for user-visible/runtime behavior. Regressions introduced by this Slice are blocking.
