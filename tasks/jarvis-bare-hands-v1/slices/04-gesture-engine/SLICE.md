# Slice 04 — Build semantic gesture and primary/secondary pinch engines

## Goal

Separate semantic gesture recognition from contact-like pinch manipulation and add a dedicated right-click gesture.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture and contracts
- current native MediaPipe implementation
- stable hand/capture identity
- semantic interaction events rather than raw mouse-only emulation

## Scope

### In Scope

Implement primary thumb-index and secondary thumb-middle approach/down/move/up/cancel states with hysteresis and confidence. Add deterministic recognizers/events for C wake, open palm, fist, double-close and clap/palms-together, with arbitration rules that prevent global gestures stealing active captures. Keep gesture bindings decoupled from recognition.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

03

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; if this Slice changes browser/frontend UI also load /impeccable and use Claude routing when supported.
2. Freshness-check the exact files/contracts named below before editing.
3. Implement the smallest reusable contract/mechanism that satisfies the Slice.
4. Add or update deterministic automated tests before relying on webcam manual checks.
5. Preserve failure cleanup, offline operation and existing security boundaries.
6. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- Bare Hands gesture/pinch modules
- lifecycle hook for C wake
- unit tests and synthetic landmark fixtures

## Architecture Constraints

- MediaPipe-specific data must not leak across the tracker abstraction boundary unnecessarily.
- Per-hand and per-capture state must be explicit and testable.
- User-visible behavior must follow the decision log rather than legacy mouse-only assumptions.
- Unknown current repository component names must be discovered, not invented.

## Automated Validation

Tests distinguish index vs middle pinch, reject whole-hand closure as right click where possible, cover double-close timing, clap debounce, active-capture arbitration, lost-hand cancellation and per-hand independence.

## Acceptance Criteria

Secondary pinch reliably emits a distinct semantic right-click channel; primary pinch remains suitable for click/drag/scroll inference; global gestures are emitted as semantic events without hard-coded destructive actions.

## Documentation Updates

Document gesture vocabulary, event payloads and arbitration priorities.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review for code changes and runtime-validation for user-visible/runtime behavior. Regressions introduced by this Slice are blocking.
