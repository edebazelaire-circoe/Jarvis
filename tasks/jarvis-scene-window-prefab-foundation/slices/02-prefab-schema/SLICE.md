# Slice 02 — Prefab Definition and Instance Schema

## Goal

Implement the canonical prefab definition/instance schemas, structured input types, provenance/versioning, and base-prefab protection policy.

## Context

Jarvis needs reusable definitions that can be safely parameterized and saved without conflating a live scene instance with the source prefab.

## Canonical Concepts

Prefab definition, prefab instance, input schema, base/system prefab, variant/fork, provenance.

## Scope

### In Scope

- Stable prefab identity/version metadata.
- Definition metadata and instance state schema.
- Primitive plus `object`/`array` structured input support.
- Defaults/required/validation semantics.
- Base/system/custom classification.
- Explicit-intent gate for direct base definition mutation.
- Derivation/provenance metadata for forks/new saved prefabs.

### Out of Scope

- Rendering/mount logic.
- Library UI.

## Dependencies

- `01-contract-audit`

## Implementation Steps

1. Extend/reuse the repository's canonical schema mechanism.
2. Add nested structured input validation.
3. Define strict unknown/invalid field behavior.
4. Define definition provenance and exact version references.
5. Add an explicit mutation policy field/guard for base definitions.
6. Add schema fixtures and negative tests.

## Files Likely Touched

Canonical prefab schema/model/validator files and their tests, as identified by Slice 01.

## Architecture Constraints

Do not encode structural HTML as ordinary data inputs. Keep live DOM/runtime handles out of canonical instance state.

## Automated Validation

- Schema unit tests.
- Structured input fixtures (empty/single/nested/malformed).
- Base mutation denial/allow tests.
- Version/provenance round-trip tests.

## Acceptance Criteria

- Object/list inputs validate predictably.
- Base prefab edits require explicit authorized intent.
- Fork/new prefab provenance is inspectable.
- Live instances reference an exact reusable definition without mutating it.

## Documentation Updates

Promote prefab definition, instance, inputs, and protection contracts toward Level 3.

## Handoff Notes

Use `/caveman` and `/coding-guideline`.
