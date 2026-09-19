# Slice 06 — Implement capture-based interaction engine and bimanual frame geometry

## Goal

Replace immediate mouse-click behavior with explicit per-hand capture supporting contextual BODY interaction, one-hand frame move, and two-hand constrained resize.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture and contracts
- per-hand stable identity and latched capture
- BODY content interaction vs edge/corner frame manipulation
- semantic component hooks and compatibility DOM events

## Scope

### In Scope

- Latched capture descriptors per stable hand ID.
- BODY click/drag/scroll/select dispatch based on target semantics.
- One manipulation-zone capture moves the entire frame.
- Two compatible zones on the same frame switch to constrained resize.
- Independent simultaneous interactions on different objects.
- ZONE + BODY never forms resize.
- Reject two captures of the same manipulation zone.
- Edge + overlapping corner: edge owns the shared axis; corner uses only its remaining axis.
- Two corners sharing an axis neutralize that shared axis.
- Clamp to component minimum size and never invert axes when hands cross.
- Rebase the surviving anchor on RESIZE -> MOVE so the frame does not jump.
- Add component semantic hooks, including star drag/open and frame-specific actions where current component contracts support them.
- Use unique/stable per-hand compatibility pointer identity when DOM events are emitted.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

05

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; for browser/frontend UI also load /impeccable and use Claude routing when supported.
2. Freshness-check the exact current Control Center/Constellation contracts before editing.
3. Implement the smallest reusable mechanism that satisfies the locked interaction rules.
4. Add deterministic tests for state, geometry and error paths before relying on webcam checks.
5. Preserve offline operation, cleanup and clean-room licensing boundaries.
6. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- Bare Hands interaction/capture engine
- current Constellation/frame/star adapters discovered by freshness audit
- DOM compatibility adapter
- geometry helpers
- unit/browser tests

## Architecture Constraints

- One hand on a manipulation zone moves; it never resizes.
- Only two compatible manipulation-zone captures on the same object may resize it.
- BODY remains content interaction.
- Captures are latched until release.
- Two hands on distinct objects stay independent.
- Current component names/APIs must be discovered rather than invented.

## Automated Validation

Pure geometry tests must cover every edge/corner ownership class, duplicate zones, ZONE+BODY, min-size clamping, no inversion and RESIZE->MOVE rebasing. Runtime tests cover simultaneous objects, capture latch under jitter, BODY passthrough, star drag, same-frame resize and unique per-hand event identity.

## Acceptance Criteria

All locked interaction rules in the decision log are enforced. One hand cannot accidentally resize. BODY cannot accidentally move/resize a frame. Two distinct objects can be manipulated simultaneously. Releasing one hand from resize continues smoothly as move with no jump.

## Documentation Updates

Document capture state machine, zone-axis ownership matrix, component capability hooks and DOM compatibility behavior.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review for code changes and runtime-validation for user-visible/runtime behavior. Regressions introduced by this Slice are blocking.
