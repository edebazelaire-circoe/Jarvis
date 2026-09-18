# Slice 02 — Scene store & persistence

## Goal
A Core-owned `SceneService`/`SceneStore` that applies Slice 01 commands, persists the active scene durably, keeps a bounded in-memory patch ring for transport, and exposes a local revision wait primitive for long-polling.

PM amendment (Slice 02 review): scene updates are **not** published on `CoreEventBus` — `/v1/events` forwards every bus event unfiltered to all WebSocket clients (voice included), so scene payloads/bursts would bloat the voice socket and risk evicting its non-lossy subscriber.

## Context
Audit facts: Core work state is memory-only and gets a new `store_id` each start (`jarvis/core/work_state.py:10-22, :168`). Durable Core state lives in SQLite `data/state/jarvis.sqlite3` via `jarvis/adapters/sqlite_state.py`, whose `schema_version` table refuses newer versions and has no migration framework. The scene, unlike work state, must survive restart (Decision 11).

## Canonical Concepts
Core owns the scene (same process as work truth and bus). Persist to a **separate** SQLite file `data/state/scene.sqlite3` through a new adapter that copies `sqlite_state.py` conventions (schema_version table, JSON `data` columns) so `jarvis.sqlite3` schema stays at 1. A stable `scene_id` persists across restarts (unlike work `store_id`); revision continues from the persisted value. Archived objects are retained in storage but excluded from the active snapshot.

PM amendment (Slice 01 QA re-verification): `apply_scene_patch` does not enforce immutable fields (`origin`, `kind`) on crafted `put_object`. If this Slice replays patches from storage or accepts externally produced patches, add a domain guard (reviewed change in `jarvis/domain/scene.py`) or persist snapshots only. `SceneObject.origin` was added without a `schema_version` bump because nothing was persisted yet: from this Slice on, any wire/storage shape change requires a version bump and explicit refusal of unknown versions.

## Scope
### In Scope
Port `jarvis/ports/scene.py` (reader/command sink), adapter `jarvis/adapters/sqlite_scene.py`, service `jarvis/core/scene_service.py` (serialized command application via asyncio lock, write-through persistence, patch ring, bus publish), wiring in `jarvis/core/v2_app.py`.
### Out of Scope
HTTP routes (03), runtime projection (04), reconciliation logic (10).

## Dependencies
01.

## Implementation Steps
1. Port protocols. 2. SQLite adapter (objects, relations, meta: scene_id, revision). 3. Service with lock, apply, persist-then-publish, patch ring (e.g. 512). 4. Wire into Core app lifecycle. 5. Tests incl. reopen-after-close preserves revision/objects, corrupted/newer schema refusal is explicit and journaled.

## Files Likely Touched
`jarvis/ports/scene.py`, `jarvis/adapters/sqlite_scene.py`, `jarvis/core/scene_service.py`, `jarvis/core/v2_app.py`, `jarvis/core/v2_services.py` (event name), tests.

## Architecture Constraints
Core must not import adapters directly (composition in `v2_app.py`/`app.py`); `scripts/verify_release.py` must stay green. A persistence failure must not advance revision nor publish; it is journaled and surfaced.

## Automated Validation
Targeted unit tests + `tests/integration/test_v2_core_recovery.py` still green + `verify_release.py`.

## Acceptance Criteria
Restarting Core restores identical active snapshot and revision; revision never regresses; archived excluded from active snapshot but queryable.

## Documentation Updates
ARCHITECTURE.md persistence section; OPERATIONS.md data file location.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline`. QA: qa-verification + code-review + runtime-validation (real Core restart).
