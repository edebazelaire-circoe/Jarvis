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

## Slice 00 contract (binding)

Goal re-scoped: prefab **definition** domain, file library and Core catalogue service. No scene change and no routes.

Create:
- `jarvis/domain/prefab.py`: everything listed under domain in 06 R6, incl. lint, fingerprint (reuse `jarvis.domain.prompt_registry.fingerprint`), `check_state_event` (pure, used by S04).
- `jarvis/ports/prefabs.py`: `PrefabLibrary`, `PrefabInstanceValidator`, `PrefabStoreError` (codes: `unknown_prefab`, `unknown_version`, `tampered`, `version_exists`, `base_protected`, `base_edit_unconfirmed`, `invalid_definition`, `storage_io`).
- `jarvis/adapters/file_prefab_library.py`: `FilePrefabLibrary(package_root, data_root)` (06 D-STORE). Reuse `safe_folders` and `file_replace.replace_with_retry`.
- `jarvis/core/prefab_service.py`: `PrefabService` with `search`, `get`, `bundle` (returns runtime shim/css only after S03 creates them; until then `runtime: null`), `validate_candidate`, `save`, `edit_base` (gate conditions 1-3; the witness callable is injected and wired in S07; tests use a fake), `validate_instance`.
- `jarvis/prefabs/base/catalog.lock.json` (empty `entries`) + `tests/unit/test_prefab_base_lock.py` (lock ↔ files, no orphan, no unlocked version, fingerprint drift fails).
- Fixtures `tests/fixtures/prefabs/test.counter/1/*` (valid) and `test.bad_*` (invalid cases).

Touch:
- `jarvis/core/v2_app.py`: construct library and service as `self.prefabs`; not yet passed to `SceneService`.
- `tests/unit/test_v2_architecture.py`: add `jarvis.adapters.file_prefab_library` to `CORE_ADAPTER_IMPORT_EXCEPTIONS["jarvis/core/v2_app.py"]` with a comment.
- `docs/local-data.md`: add the `prefabs/<prefab_id>/<version>/` row.
- `docs/prefabs.md`: status of sections → implemented.

Acceptance tests:
- `test_prefab_domain.py`: every input type ok/ko; depth/size; defaults applied; unknown keys refused; provenance field in candidate refused; lint rejects each forbidden token; `jarvis.` → base.
- `test_file_prefab_library.py`: per 06 R7 adapter list.
- `test_prefab_service.py`: save new (origin custom), fork (`derived_from` must exist → origin fork), same custom id → revision v+1, `jarvis.*` via save → `base_protected`, `edit_base` without `confirmed_by_user`/short request/no witness → `base_edit_unconfirmed`, with fake witness → `base_edit` version in data root, package untouched; `validate_instance` ok/unknown/tampered/schema errors with bounded detail.
- Architecture and documented-routes gates green.

In: definitions, library, catalogue, base-edit gate core. Out: rendering, scene payload, routes, MCP.
Depends on: 01.
QA: qa-verification + code-review.
