# Slice 04 - Presentation Scene Module and Control Contract

## Goal
Define the presentation-specific metadata and typed edit-control surface layered on top of shared prefab/scene instances.

## Context
Each scene should be independently authorable/reusable, and common edits should not require source rewrites.

## Canonical Concepts
Logical scene, scene module, declared control, presentation scene metadata, prefab instance.

## Scope
### In Scope
- Logical scene identity/order/section metadata.
- Mapping to canonical prefab/scene definition/instance IDs.
- Typed controls for curated visual/layout/motion/content parameters.
- Score anchor hooks and preview metadata.
- Control discovery/introspection for agents and GUI.

### Out of Scope
- Actual edit mutation engine.
- Generic prefab input schema owned by the Scene/Prefab task.

## Dependencies
- `02-presentation-artifact-contract`
- External: Scene/Prefab definition + instance + input contracts.

## Implementation Steps
1. Reuse generic prefab input/control primitives where they already fit.
2. Add only presentation-specific metadata/control annotations.
3. Ensure controls expose labels, types, valid ranges/enums, defaults and semantic meaning.
4. Add introspection API/fixtures.

## Files Likely Touched
Presentation scene model/adapter, scene/prefab integration layer, tests.

## Architecture Constraints
Do not expose every CSS property as a control. Common changes should be smart and comprehensible.

## Automated Validation
Control schema validation, bounds/enums, discovery, reference integrity and prefab compatibility tests.

## Acceptance Criteria
An agent or inspector can ask what is editable on a scene and receive stable semantic controls.

## Documentation Updates
Document presentation scene/control extension points.

## Handoff Notes
Use `/caveman` and `/coding-guideline`.
