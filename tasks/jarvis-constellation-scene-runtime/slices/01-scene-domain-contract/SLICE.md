# Slice 01 — Scene domain contract

> Contract written by the Project Manager during Slice 00 (2026-09-16): the Drive handoff shipped Slices 01–11 as empty folders.

## Goal
Define the pure, typed Scene domain in `jarvis/domain/scene.py` (no I/O): objects, relations, geometry, layers, representation, visibility/disposition, constraints, commands, actor authority, and a pure `apply_scene_command` reducer that yields a new revision plus a patch.

## Context
Core already has the pattern to copy: `jarvis/domain/work_state.py` (typed dataclasses, `ALLOWED_WORK_TRANSITIONS`, pure `apply_observation` with outcomes). Scene is a projection; Core work state remains execution truth (Decision 17).

## Canonical Concepts
- `SceneObject`: stable `object_id`; `kind` (`agent`, `job`, `artifact`, `attention`, `window`, `group` — closed enum, extendable later); `category` token (primary colour source, Decision 7); `exec_state` (mirrors `WorkStatus` + `unknown`, secondary cue only); `representation` (`point` | `capsule` | `window`, Decision 6); `geometry` `{x, y, w, h}` in scene units; `layer` int (bands 50/100/120/150/220/300 are conventions, any int allowed, Decision 8); `order` tiebreak; `visibility` (`visible` | `hidden`); `disposition` (`active` | `archived`, Decisions 12–13); `constraints` (`pinned_by_user`, `placed_by` = runtime|brain|user|resolver); `work_ref` (Core `work_id`/`source`+`external_id`) for runtime-owned nodes; `payload` (bounded JSON: title, summary, items for artifacts).
- `SceneRelation`: `relation_id`, `from_id`, `to_id`, `kind` (`parent_of`, `explains`, `groups`), layer.
- `SceneCommand` with `actor` ∈ {`runtime`, `brain`, `user`} and ops: `upsert_object`, `patch_object`, `set_geometry`, `set_representation`, `set_visibility`, `pin`/`unpin`, `link`/`unlink`, `archive`, `attach_signal`.
- Authority matrix (enforced by the reducer, not by callers): `runtime` may only upsert/patch execution nodes (`agent`/`job`), their `parent_of` relations and `attention` signals — never geometry of a user-pinned object, never artifacts. `brain` may do everything except `archive` and cannot move/resize a `pinned_by_user` object. `user` may do everything including `archive`. `archive` by a non-user actor is rejected (Decision 14), independently of the MCP catalog.
- Completion never changes `disposition` or `visibility` (Decision 12).
- `SceneSnapshot {scene_id, revision, objects, relations}`; `ScenePatch {revision, ops}`; revision strictly monotonic; rejected/duplicate commands do not advance it.
- `schema_version: 1` on serialized forms; bounded sizes (object count, payload bytes) with explicit errors.

## Scope
### In Scope
Domain types, validation, authority matrix, reducer, JSON encode/decode, bounds, unit tests.
### Out of Scope
Persistence, HTTP, rendering, AutoResolver geometry (Slice 05 is browser-side), MCP.

## Dependencies
00 READY.

## Implementation Steps
1. Model types and enums mirroring `work_state.py` style.
2. Reducer returning outcome (`applied`, `duplicate`, `rejected_authority`, `invalid`) + patch.
3. Encode/decode with `schema_version`.
4. Tests: every authority cell, archive-by-brain rejection, completion keeps disposition, pinned geometry protection, revision monotonicity, bounds.

## Files Likely Touched
`jarvis/domain/scene.py`, `tests/unit/test_scene_contracts.py`.

## Architecture Constraints
Pure domain: no imports from `core`, `adapters`, `runtime`, asyncio or I/O. Follow `work_state.py` conventions.

## Automated Validation
`python -W error::ResourceWarning -m pytest -q tests/unit/test_scene_contracts.py`; `python scripts/verify_release.py`.

## Acceptance Criteria
Authority matrix fully tested; archive impossible for brain/runtime at reducer level; representation change preserves identity; no I/O in module.

## Documentation Updates
`docs/state-model.md` (or new `docs/scene-model.md` linked from ARCHITECTURE) describing objects, authority, lifecycle.

## Handoff Notes
Required skills: `/caveman`, `/coding-guideline`. QA: qa-verification + code-review.
