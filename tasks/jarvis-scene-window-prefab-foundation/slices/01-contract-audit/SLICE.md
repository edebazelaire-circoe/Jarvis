# Slice 01 — Canonical Scene, Window, and Prefab Contracts

## Goal

Turn the audited repository's existing scene/window/prefab behavior into one explicit canonical contract before runtime changes begin.

## Context

The product direction already exists across Rework FENETRES and prefab discussions. This Slice converts that direction and actual repository behavior into durable definitions and migration boundaries.

## Canonical Concepts

Scene object, window family, prefab definition, prefab instance, base prefab, variant/fork, shared prefab library.

## Scope

### In Scope

- Document current scene ownership and lifecycle authority.
- Recover the already-defined window families; do not invent replacements.
- Identify any existing prefab registry/runtime and choose the one canonical path.
- Define definition-vs-instance boundary and terminology.
- Define compatibility seam for future Presentation consumers.

### Out of Scope

- Runtime rewrite.
- Window visual redesign.
- Presentation behavior.

## Dependencies

- `00-project-manager`

## Implementation Steps

1. Trace real create/show/update/hide/destroy paths for windows/scene objects.
2. Trace any existing prefab registration/render/mount paths.
3. Name the canonical concepts using existing repository vocabulary where possible.
4. Record deprecated/duplicate paths and a migration plan, but do not delete them yet.
5. Create/update dedicated repository contract documentation to Level 2 minimum.

## Files Likely Touched

Repository docs/concepts/architecture files identified by Slice 00; possibly schema stubs only if required to make the contract testable.

## Architecture Constraints

Session / Board / Context semantics must not be redesigned. Presentation interaction semantics remain separate.

## Automated Validation

- Documentation/concept link checks if present.
- Static architecture/conformance checks already used by the repo.

## Acceptance Criteria

- One canonical scene/object path is named.
- One canonical prefab path is named or a migration target is explicitly chosen.
- Existing window families are enumerated from evidence.
- Definition vs instance semantics are unambiguous.
- Future Presentation integration depends only on public contracts.

## Documentation Updates

Promote relevant concepts to at least Level 2.

## Handoff Notes

If two plausible canonical systems exist, escalate to the PM instead of merging them silently.
