# Slice 01 — Define Bare Hands V1 contracts, schemas and compatibility boundaries

## Goal

Create the stable interfaces and schemas that separate tracking, gestures, pinch intent, target resolution, interaction, tools/settings and calibration while keeping the current experiment functional during migration.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture and contracts
- current native MediaPipe implementation
- stable hand/capture identity
- semantic interaction events rather than raw mouse-only emulation

## Scope

### In Scope

Define tracker-neutral HandFrame/track identity structures, semantic gesture/pinch events, target/capture region model, interaction events, versioned settings/profile schemas, and explicit native-vs-AGPL boundary documentation. Provide compatibility adapters from the current JarvisBarehandsCore shape.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

00

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; if this Slice changes browser/frontend UI also load /impeccable and use Claude routing when supported.
2. Freshness-check the exact files/contracts named below before editing.
3. Implement the smallest reusable contract/mechanism that satisfies the Slice.
4. Add or update deterministic automated tests before relying on webcam manual checks.
5. Preserve failure cleanup, offline operation and existing security boundaries.
6. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- jarvis/runtime/control_center_barehands.js or extracted Bare Hands modules
- jarvis/runtime/barehands_test_mode.py
- `jarvis/runtime/control_center_scene_page.js` — it reads `pointerId===9001` (`:1874`), sniffs `#jarvisHands .jh-token` (`:1726`) and styles on `.jh-badge` (`:819`) (Slice 00, F2)
- `jarvis/runtime/control_center.html` — the `inert` sweep exempts `#jarvisHands` by id (`:2075`) (Slice 00, F2)
- `jarvis/runtime/control_center.py` and `jarvis/runtime/control_center.html` — marker constant, marker placement and load-order assertion for any new page module (Slice 00, F3)
- settings schema/storage files discovered by freshness audit
- Bare Hands tests
- contributor/architecture docs

## Architecture Constraints

- MediaPipe-specific data must not leak across the tracker abstraction boundary unnecessarily.
- Per-hand and per-capture state must be explicit and testable.
- User-visible behavior must follow the decision log rather than legacy mouse-only assumptions.
- Unknown current repository component names must be discovered, not invented.
- Replacing the hard-coded `pointerId 9001` is a cross-module change. The scene page currently identifies Bare Hands by that literal and by the `#jarvisHands` DOM shape; both consumers must move in this Slice or the scene stops recognising hand input (Slice 00, F2).

## Automated Validation

Contract/unit tests prove schema validation, compatibility defaults, two-hand IDs, and no accidental dependence on one hard-coded DOM pointer ID.

## Acceptance Criteria

All later Slices can depend on documented interfaces without importing MediaPipe/browser details directly. Existing enabled/disabled behavior remains compatible while the new schema defaults are introduced safely.

## Documentation Updates

Document the canonical event/schema contracts and clean-room boundary.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review for code changes and runtime-validation for user-visible/runtime behavior. Regressions introduced by this Slice are blocking.
