# Slice 17 - Scene-Local Variants

## Goal
Allow lightweight alternatives for an individual logical scene without branching the whole presentation.

## Context
A user may want three product-reveal treatments or two layouts for one scene while keeping the rest identical.

## Canonical Concepts
Scene variant set, selected scene variant, local preview, promote.

## Scope
### In Scope
- Create/rename/select/delete scene-local variants.
- Copy from current scene state.
- Preview without changing top-level presentation branch until selection/commit.
- Promote a chosen local variant into current branch state.
- Preserve local variant provenance.

### Out of Scope
- Top-level variant tree UI.

## Dependencies
- `04-presentation-scene-control-contract`
- `16-presentation-variants-domain`

## Implementation Steps
1. Add local variant model scoped to logical scene + presentation variant.
2. Implement selection/preview/promotion operations.
3. Ensure local variants do not duplicate the rest of the deck unnecessarily.
4. Integrate autosave and bounded undo semantics.

## Files Likely Touched
Presentation scene variant domain/service, preview integration and tests.

## Architecture Constraints
Local scene exploration must remain lightweight and invisible in the top-level graph unless promoted to a full branch.

## Automated Validation
Create/select/delete/promote, persistence, branch isolation and preview rollback tests.

## Acceptance Criteria
A user can compare multiple versions of one scene without polluting the presentation variant tree.

## Documentation Updates
Scene-local variant contract.

## Handoff Notes
Use `/caveman` and `/coding-guideline`.
