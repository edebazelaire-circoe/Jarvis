# Slice 16 - Presentation Variant Graph and Branch Operations

## Goal
Implement durable creative presentation branches as the replacement for long linear snapshot history.

## Context
Variants represent alternative creative directions, not tiny undo states.

## Canonical Concepts
Variant graph, parent, short display ID, title, rationale, active variant, branch deletion.

## Scope
### In Scope
- Create branch from current/selected variant.
- Immutable short monotonic numeric display ID.
- Human title/rename.
- Parentage/rationale/provenance.
- Switch active branch.
- Delete/archive abandoned branch with descendants under destructive-action policy.
- Autosave isolated per active variant.

### Out of Scope
- Scene-local variants.
- Visual tree UI.
- Semantic cross-branch mixing.

## Dependencies
- `02-presentation-artifact-contract`
- `08-autosave-undo`

## Implementation Steps
1. Define variant graph persistence.
2. Allocate display IDs without accidental reuse.
3. Implement branch/switch/rename/delete operations.
4. Ensure undo ring is branch-local and reset/rebound safely on switch.
5. Preserve graph consistency on crash/restart.

## Files Likely Touched
Presentation variant domain/persistence/service and tests.

## Architecture Constraints
Do not model every autosave or undo state as a branch node.

## Automated Validation
Branch graph integrity, ID stability, switch/autosave isolation, descendant deletion confirmation, recovery tests.

## Acceptance Criteria
A project can hold several durable creative directions and return to any retained branch safely.

## Documentation Updates
Variant graph and operation contract.

## Handoff Notes
Use `/caveman` and `/coding-guideline`.
