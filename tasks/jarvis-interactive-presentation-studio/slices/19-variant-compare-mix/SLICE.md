# Slice 19 - Variant Comparison and Semantic Branch Composition

## Goal
Compare retained directions side-by-side and create new variants by selectively combining semantic dimensions from them.

## Context
Variants may differ in visual style, narration, structure or commercial/vision emphasis. Comparison and mixing should support creative decision-making rather than file merging.

## Canonical Concepts
Comparison set, synchronized logical scene, semantic dimension, composition provenance.

## Scope
### In Scope
- Compare two or four variants.
- Focus selected pair in 50/50 mode.
- Navigate equivalent logical scenes in sync where mapping exists.
- Allow manual mapping/independent navigation when structures diverge.
- Create a new child variant sourcing narrative/DA/motion/scenes from chosen branches.
- Preserve explicit provenance for every borrowed dimension.

### Out of Scope
- Raw Git/file three-way merge.

## Dependencies
- `18-variant-explorer-ui`
- `16-presentation-variants-domain`
- `10-presentation-score-cues`
- `09-art-direction-profile`

## Implementation Steps
1. Add compare selection/state model.
2. Build responsive 2-up/4-up preview layouts.
3. Implement logical scene mapping/sync.
4. Define semantic composition request and resulting variant provenance.
5. Validate incompatible combinations before commit and surface actionable conflicts.

## Files Likely Touched
Variant UI/domain/composition service and tests.

## Architecture Constraints
Source branches are immutable inputs to composition. Result is always a new child variant.

## Automated Validation
2/4 compare, sync mapping, divergent structure fallback, composition provenance, conflict/refusal tests.

## Acceptance Criteria
The user can visually decide between branches and request combinations without losing or corrupting the originals.

## Documentation Updates
Comparison and semantic composition contract.

## Handoff Notes
Frontend + domain: `/caveman`, `/coding-guideline`, `/impeccable`, Claude when supported.
