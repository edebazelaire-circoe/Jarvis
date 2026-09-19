# Slice 02 — Implement OFF/SLEEP/ACTIVE lifecycle and C-pose wake flow

## Goal

Replace simple enabled/running behavior with the locked lifecycle and interaction activation semantics.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture and contracts
- current native MediaPipe implementation
- stable hand/capture identity
- semantic interaction events rather than raw mouse-only emulation

## Scope

### In Scope

Implement OFF/SLEEP/ACTIVE state machine; OFF releases camera; SLEEP runs reduced watcher; ACTIVE full pipeline. Add C-pose progress/wake event, UI/voice hooks, 30 s no-usable-hand ACTIVE->SLEEP timeout, cancellation/teardown and recovery behavior.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

01

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; if this Slice changes browser/frontend UI also load /impeccable and use Claude routing when supported.
2. Freshness-check the exact files/contracts named below before editing.
3. Implement the smallest reusable contract/mechanism that satisfies the Slice.
4. Add or update deterministic automated tests before relying on webcam manual checks.
5. Preserve failure cleanup, offline operation and existing security boundaries.
6. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- Bare Hands controller/runtime modules
- Control Center overlay/status UI
- settings/runtime endpoints
- voice command adapter discovered by Slice 00
- tests

## Architecture Constraints

- MediaPipe-specific data must not leak across the tracker abstraction boundary unnecessarily.
- Per-hand and per-capture state must be explicit and testable.
- User-visible behavior must follow the decision log rather than legacy mouse-only assumptions.
- Unknown current repository component names must be discovered, not invented.

## Automated Validation

Unit tests for every lifecycle transition, timers, cancellation during startup, camera unplug, wake-progress reset, and no-hand timeout. Runtime validation must confirm OFF actually releases camera.

## Acceptance Criteria

C-pose wake can activate from SLEEP; button/voice can activate/deactivate; 30 s no hand sleeps; errors never leak camera/model/RAF resources.

## Documentation Updates

Update lifecycle/status documentation and user-facing setting descriptions.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review for code changes and runtime-validation for user-visible/runtime behavior. Regressions introduced by this Slice are blocking.
