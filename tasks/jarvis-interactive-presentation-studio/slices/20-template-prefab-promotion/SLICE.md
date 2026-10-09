# Slice 20 - Template and Prefab Promotion

## Goal
Promote successful presentation work into reusable shared templates/prefabs without leaking project-specific content.

## Context
A good presentation direction, scene, DA or animation pattern should become reusable material for future work.

## Canonical Concepts
Promotion, template, prefab, parameterization, provenance, shared library.

## Scope
### In Scope
- Promote whole presentation variant as a presentation template.
- Promote an individual scene.
- Promote DA profile and motion pattern where the shared library model supports them.
- Detect/strip or parameterize project-specific content/references.
- Validate through canonical prefab/template authoring/promotion flow.
- Preserve derivation provenance.

### Out of Scope
- Creating a second presentation-only template catalog.

## Dependencies
- `17-scene-local-variants`
- `19-variant-compare-mix`
- `04-presentation-scene-control-contract`
- External: shared prefab/template promotion contract.

## Implementation Steps
1. Reuse shared library authoring/promotion API.
2. Define extraction adapters for presentation-specific artifacts.
3. Require explicit selection of reusable dimensions/content parameters.
4. Validate no broken project-local resource references remain.
5. Add preview/instantiate tests for promoted templates.

## Files Likely Touched
Presentation-to-prefab/template adapter, shared library integration, tests.

## Architecture Constraints
Do not copy a project artifact verbatim and call it a reusable template.

## Automated Validation
Promotion sanitization, parameterization, provenance, instantiate-and-render tests.

## Acceptance Criteria
A retained creative result can be reused in a future presentation without carrying accidental project-specific state.

## Documentation Updates
Promotion workflow and reusable presentation template contract.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; frontend preview work also uses `/impeccable`.
