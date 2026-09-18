# Slice 03 — Scene transport

## Goal
Expose the scene to the browser and to command producers: snapshot + monotonic patches with resync (Decision 20), and a single command endpoint with explicit actor.

## Context
Audit facts: the Control Center browser polls full JSON (`/api/status` 1 s, `/api/work` 1 s); there is no WebSocket/SSE in the Control Center. Precedents to reuse: `CoreWorkView`/`accept_snapshot` revision guard (`jarvis/runtime/work_view.py:50`, `control_center_work.js:17`), long-poll with epoch+seq (`/api/agent/notices`, `control_center.py:2450`), Core bearer-token transport `CoreWorkTransport` (token file `runtime/core.token`), POST origin guard `_origin_guard`.

## Canonical Concepts
- Core: `GET /v1/scene/snapshot`, `GET /v1/scene/patches?scene_id=&after=<rev>&wait_s=` (long-poll; returns `resync_required` when `after` is outside the ring or `scene_id` differs), `POST /v1/scene/commands` (actor validated server-side: token-authenticated callers declare `runtime`/`brain`; the Control Center proxy forces `user`).
- Control Center: `GET /api/scene`, `GET /api/scene/patches`, `POST /api/scene/commands` (actor forced to `user`, origin guard applies). Degraded payload when Core is down, like `/api/work`.
- Pure JS client logic (`control_center_scene.js` pure part): apply patches in order, detect gap → refetch snapshot.

PM amendment (Slice 01 QA, F3): worst-case snapshot is ~8 MB (512 objects × 16 KiB payload); measured 1.4 MB / 25 ms decode at realistic bounds. Transport must bound response size (aiohttp `client_max_size` for commands; compact snapshot projection or gzip for the browser if needed) and never re-send full snapshots on every poll; decoders must catch only `ValueError`/`TypeError` and map them to 400.

PM amendment (Slice 02 review): the Core long-poll uses `SceneService.wait_for_revision` (local wait primitive), never `CoreEventBus`/`/v1/events`.

PM amendment (Slice 02 QA): restoring an older `scene.sqlite3` backup keeps the same `scene_id` while revisions get reused, so a client keyed on `(scene_id, revision)` could apply new patches onto a divergent cache. Transport must carry a per-load epoch (generated at each `SceneService.start()`, returned with snapshot and patches); any epoch change forces resync. Also expose scene availability (`ready`/`unavailable` + code) in `/v1/health` and the Control Center degraded payload.

## Scope
### In Scope
Core routes, Control Center proxy view, pure JS patch-application logic + node tests, `test_documented_routes.py` compliance.
### Out of Scope
Rendering (05), MCP (06).

## Dependencies
01, 02.

## Implementation Steps
1. Core routes in `jarvis/protocol/server.py`. 2. `CoreSceneView` in `jarvis/runtime/scene_view.py`. 3. Control Center routes. 4. Pure JS client with `module.exports`. 5. Tests: gap/resync, scene_id change, actor forcing, user cannot impersonate brain, degraded mode.

## Files Likely Touched
`jarvis/protocol/server.py`, `jarvis/runtime/scene_view.py`, `jarvis/runtime/control_center.py`, `jarvis/app.py`, `jarvis/runtime/control_center_scene.js`, tests.

## Architecture Constraints
No new transport stack (no WebSocket in the Control Center for V1); bounded long-poll; loopback only.

## Automated Validation
Unit + integration tests; `tests/unit/test_documented_routes.py`; node-based JS tests via `tests/conftest.py` pattern.

## Acceptance Criteria
Browser client converges to server snapshot after arbitrary gaps/reconnects; user-origin commands can never carry `brain`/`runtime` actor.

## Documentation Updates
ARCHITECTURE.md routes; OPERATIONS.md.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline`. QA: qa-verification + code-review + runtime-validation.
