# Slice 04 — Scene Object ↔ Prefab Instance Bridge

## Goal

Allow the existing scene system to create and control prefab-backed objects declaratively without exposing DOM internals to the Brain or task agents.

## Context

Rework FENETRES established that agents decide what the user should see through a controlled scene layer. Prefabs provide object definitions; the scene must own live instances.

## Canonical Concepts

Scene object, prefab instance, object owner, scene lifecycle.

## Scope

### In Scope

- Instantiate prefab-backed scene objects.
- Update props/data/state through the scene contract.
- Show/hide/focus/reorder/destroy through existing scene semantics.
- Preserve owner/provenance metadata.
- Bridge semantic prefab events upward without granting direct runtime authority.

### Out of Scope

- Presentation conductor.
- Direct prefab-to-tool calls.

## Dependencies

- `03-dynamic-prefab-runtime`

## Implementation Steps

1. Adapt the existing scene object model to reference prefab id/version and validated inputs.
2. Add instance creation/update/destruction hooks to the scene lifecycle.
3. Preserve task/agent/board ownership using existing context contracts.
4. Route prefab semantic events through a controlled scene/object bridge.
5. Add diagnostics for ownership/lifecycle violations.

## Files Likely Touched

Scene manager/object model, prefab runtime integration adapter, event bridge, tests.

## Architecture Constraints

The Brain/task agent issues declarative scene/object operations. It should not reach into DOM nodes or arbitrary JavaScript closures.

## Automated Validation

- Create/update/hide/show/destroy lifecycle.
- Owner/provenance retention.
- Event propagation without direct tool execution.
- Scene rerender/update state survival according to contract.

## Acceptance Criteria

- Prefab-backed objects behave like first-class scene objects.
- Existing non-prefab scene objects continue to work or have an explicit migration adapter.
- No unrestricted authority path is introduced.

## Documentation Updates

Document public scene↔prefab contract and event boundary.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.
