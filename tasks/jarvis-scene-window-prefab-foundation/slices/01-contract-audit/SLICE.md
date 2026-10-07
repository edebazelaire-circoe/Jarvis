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

## Slice 00 contract (binding, wins over the body above)

**Nature: documentation only. No code, no schema stub.**

Files:
- NEW `docs/prefabs.md`: canonical contract. Copy and edit R1-R6 of `docs/06-resolved-architecture.md`: terminology (prefab definition, version, publication, base/custom/fork/revision/base_edit, instance block, shell, shim, frame), manifest and input schema, message protocol, storage layout, validation authority, event classes, tool and route list. Mark each section "Status: contract — implemented by Slice NN". Route lists live **only** here until registered.
- `docs/scene-model.md`: new section "Prefab windows" (instance block, kind rule, exact-version pin, `PREFAB_INVALID` + `detail`, no schema bump and why, legacy path retained) and a note under the Brain tool mapping; Decision 1 refinement paragraph (R8.8).
- `docs/ARCHITECTURE.md`: in §"Constellation scene store" (~1819) and §"Scene renderer" (~3012), one paragraph each pointing to `docs/prefabs.md`. **Quote no `/api/prefabs` path** (`tests/unit/test_documented_routes.py` would fail until registered).
- `docs/SECURITY.md`: new control "16. Prefab sandbox (contract)", stating the boundary in R1 D-RENDER and the base-edit gate.
- File the Issues listed in 06 §Issues under `Issues/`.

In: the docs above. Out: any Python or JS change; the `docs/local-data.md` row (S02).

Acceptance:
- `pytest tests/unit/test_documented_routes.py tests/unit/test_v2_architecture.py` green (no route quoted).
- `docs/prefabs.md` names every module and route of R6 exactly.
- PM review confirms one canonical scene path (existing `SceneService`) and one canonical prefab path (`PrefabService` + sandboxed runtime).

Depends on: 00.
QA: qa-verification (doc consistency against code citations).
