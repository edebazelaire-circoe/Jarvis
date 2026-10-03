# Slice 03 — Dynamic Prefab Runtime

## Goal

Make valid prefab definitions dynamically discoverable and safely mountable without adding per-prefab branches to core runtime code.

## Context

A shared library cannot scale if every newly saved prefab requires editing a central registry function or switch.

## Canonical Concepts

Prefab catalog, prefab runtime, behavior lifecycle, style ownership.

## Scope

### In Scope

- Manifest/catalog-driven discovery.
- Template/style/behavior resolution.
- Input validation before mount.
- Mount/update/unmount lifecycle.
- Cleanup guarantees.
- Style scoping/isolation appropriate to the audited frontend architecture.
- Error states for invalid/missing prefab resources.

### Out of Scope

- Scene placement logic.
- Agent authoring operations.

## Dependencies

- `02-prefab-schema`

## Implementation Steps

1. Remove or bypass per-prefab core registration requirements where they exist.
2. Load definitions/resources through the canonical catalog.
3. Mount behavior through one runtime lifecycle API.
4. Guarantee cleanup on rerender/unmount.
5. Enforce CSS ownership/scoping; reject or isolate unsafe global styling patterns.
6. Add runtime diagnostics for definition/load/mount errors.

## Files Likely Touched

Prefab runtime, manifest/catalog loader, frontend style loader, behavior lifecycle helpers, tests.

## Architecture Constraints

No new frontend framework solely for this Slice. Preserve repository build/runtime conventions.

## Automated Validation

- Discovery of a synthetic unknown-to-core prefab.
- Mount/update/unmount cleanup tests.
- Repeated lifecycle leak tests.
- Scoped-style regression tests.
- Invalid resource/error-state tests.

## Acceptance Criteria

- A valid new prefab can be added through the documented catalog path without editing core runtime branching logic.
- Behavior and styles are cleaned up/contained.
- Invalid prefabs fail visibly and diagnostically.

## Documentation Updates

Document runtime lifecycle and registration rules.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.
