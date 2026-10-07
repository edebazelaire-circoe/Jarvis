# Slice 09 - Art Direction Profile and Source Derivation

## Goal
Make art direction a required structured part of every presentation and give Jarvis a disciplined way to source or invent it.

## Context
The user may provide a design system, point to project assets, ask for multiple styles, or simply expect Jarvis to infer a coherent visual direction.

## Canonical Concepts
ArtDirectionProfile, visual tokens, motion language, source/reference provenance.

## Scope
### In Scope
- Structured DA contract.
- Provenance: provided | inferred | generated.
- Reference/resource linkage using existing resource mechanisms.
- Authoring helpers for extracting reusable design signals from accessible sources.
- Validation that every serious/generated presentation variant resolves a DA.

### Out of Scope
- Building a general design-system crawler.
- Copying external project folders into presentation storage without need.

## Dependencies
- `02-presentation-artifact-contract`
- `01-contract-audit`

## Implementation Steps
1. Define profile fields for palette, type, spacing, shape, imagery, charts and motion.
2. Reuse existing resource/file/Git access through agent tools rather than custom filesystem access.
3. Record source/provenance and confidence/notes where useful.
4. Allow a generated fallback when the user supplies no DA.
5. Support creating divergent DA candidates for exploratory authoring.

## Files Likely Touched
Presentation authoring domain, resource integration, agent prompt/skill/module and tests.

## Architecture Constraints
Do not block on a DA question if context can reasonably supply one and the user did not ask to decide manually.

## Automated Validation
Profile schema, provenance, missing-DA fallback, reference extraction stubs/fakes, agent trace scenarios.

## Acceptance Criteria
Every produced presentation variant has a coherent DA with inspectable origin.

## Documentation Updates
Canonical ArtDirectionProfile contract and authoring policy.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; agent behavior requires trace analysis.
