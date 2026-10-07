# Slice 02 - Presentation Artifact Domain Contract

## Goal
Define and implement the canonical Presentation Artifact and active presentation-variant data contracts.

## Context
This artifact must hold structured creative state without becoming a second generic scene/prefab model.

## Canonical Concepts
Presentation Artifact, Presentation Variant, resource reference, scene reference, active variant.

## Scope
### In Scope
- Artifact identity/title/metadata.
- Active variant reference.
- Ordered logical scene references.
- DA and score references.
- Resource/source references.
- Validation, serialization and round-trip tests.
- Clear separation of persistent authoring state from runtime-only playback state.

### Out of Scope
- Full scene rendering.
- Variant graph operations beyond the minimal reference needed by the artifact.

## Dependencies
- `01-contract-audit`

## Implementation Steps
1. Reuse repository schema/persistence conventions.
2. Define strict artifact and variant payloads.
3. Keep DOM/runtime handles out of canonical state.
4. Define forward-compatible schema versioning/migration behavior consistent with Jarvis conventions.
5. Add fixtures and negative tests.

## Files Likely Touched
Presentation domain/schema/persistence modules and tests identified by Slice 01.

## Architecture Constraints
Do not copy generic prefab definition fields into this schema; reference the canonical scene/prefab IDs/contracts.

## Automated Validation
Schema, migration, round-trip, malformed input and runtime-handle exclusion tests.

## Acceptance Criteria
A Presentation Artifact can be created, saved, loaded and validated independently of playback/UI.

## Documentation Updates
Create/update the canonical Presentation Artifact contract.

## Handoff Notes
Use `/caveman` and `/coding-guideline`.
