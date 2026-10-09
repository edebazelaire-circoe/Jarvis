# Slice 01a (accepted by PM 2026-10-07) - Prefab Library Capacity for Studio Scene Sources

Status: proposal from Slice 01 (`docs/07-integration-map.md` C6/G1). Not in the plan until the PM accepts it. Numbering is a placeholder: it must run before Slice 06 and before 08/16/17/20 take their pinning decision; existing Slices are not renumbered.

## Goal
Decide and implement how studio scene sources (Tier-3 edits, per-variant forks, scene-local variants, promotion) coexist with the prefab library's hard caps, without weakening immutability, provenance or the sandbox.

## Evidence (the gap)
- `MAX_VERSIONS_PER_ID = 64`, `MAX_PREFAB_IDS = 512` (`jarvis/domain/prefab.py:60-61`), version <= 9999 (`jarvis/domain/_checks.py:39`), `PrefabService._publish` refuses beyond (`jarvis/core/prefab_service.py:616-625`).
- No deletion, prune or GC exists (`jarvis/adapters/file_prefab_library.py`, `jarvis/ports/prefabs.py`: scan/read/publish/sweep only); the base catalogue lock covers only `jarvis.*`.
- Every source edit is one immutable version (`PrefabService.save` -> `revision`). One rehearsal session of spoken tweaks can spend 64 versions of a single scene id. 15 scenes x several variants x scene-local variants multiply ids toward 512, shared with the user's own prefabs.

## Scope
### In Scope
- Measure real consumption for a 15-scene presentation (versions per scene per hour of editing; ids per presentation with and without variant forks).
- Choose and specify one strategy, with a test-first contract. Candidate strategies (the Slice picks one and records why):
  1. **Pin-sharing**: all variants of a scene share one prefab id; a variant is a different `(id, version)` pin; forks only when sources diverge. Reduces ids, not versions.
  2. **Reserved-namespace retention**: for ids in `presentation-studio.*` only, allow Core to retire (move to an `archive/` area, never delete data without a copy) versions that no variant, scene variant, template or scene object pins, keeping the last N; pin check done under the prefab write lock; `MAX_VERSIONS_PER_ID` counts live versions.
  3. **Coalesced drafts**: edits inside a hot-reload session are batched so one burst publishes one version.
  4. Raise caps (needs a measured memory/scan-time argument; `PrefabService._refresh` scans the whole library).
- Whatever is chosen preserves: immutability of any version still pinned, exact-version pins, provenance chain (`publication.json`), base-protection, `catalog.lock.json` for bases, repo `CLAUDE.md` rule "never delete without a copy".
- Visible failure when a cap is reached (named code, human sentence), never a silent drop.

### Out of Scope
- Studio persistence format (Slice 02), edit tiers (05), the hot-reload mechanics (06), asset delivery (01b).

## Dependencies
- `01-contract-audit`. Blocks `06-scene-hot-reload`; informs `08`, `16`, `17`, `20`.

## Reuse
`PrefabService.save/_publish`, `PrefabLibrary` port, `FilePrefabLibrary.publish/sweep` (staging + `os.rename`), `PrefabStoreErrorCode`, `docs/prefabs.md` "Storage and library".

## Automated Validation
Library tests (`tests/unit/test_prefab_library.py`, `test_file_prefab_library.py`, `test_prefab_service*.py`), new capacity/retention tests with a pinned-version-cannot-be-retired proof, concurrent save vs retention test, real filesystem crash test between retire steps.

## Acceptance Criteria
A scene id can absorb the edit volume of a long rehearsal plus variant forks without hitting a cap, or hits a documented, visible, recoverable limit; no pinned version ever disappears; docs/prefabs.md states the final rule.

## Documentation Updates
`docs/prefabs.md` (Storage/limits), `docs/local-data.md` if a new area appears, `docs/presentation-studio.md`.

## QA tier
critical (touches the shared prefab library; code-review + qa-verification + runtime-validation; mutations <= 10).
