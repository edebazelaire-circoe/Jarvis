# Slice 04 — Scene Object ↔ Prefab Instance Bridge

## Goal

Allow the existing scene system to create and control prefab-backed objects declaratively without exposing DOM internals to the Brain or task agents.

## Context

Rework FENETRES established that agents decide what the user should see through a controlled scene layer. Prefabs provide object definitions; the scene must own live instances.

## Canonical Concepts

Scene object, prefab instance, object owner, scene lifecycle.

## Scope

### In Scope

- Instantiate prefab-backed scene objects.
- Update props/data/state through the scene contract.
- Show/hide/focus/reorder/destroy through existing scene semantics.
- Preserve owner/provenance metadata.
- Bridge semantic prefab events upward without granting direct runtime authority.

### Out of Scope

- Presentation conductor.
- Direct prefab-to-tool calls.

## Dependencies

- `03-dynamic-prefab-runtime`

## Implementation Steps

1. Adapt the existing scene object model to reference prefab id/version and validated inputs.
2. Add instance creation/update/destruction hooks to the scene lifecycle.
3. Preserve task/agent/board ownership using existing context contracts.
4. Route prefab semantic events through a controlled scene/object bridge.
5. Add diagnostics for ownership/lifecycle violations.

## Files Likely Touched

Scene manager/object model, prefab runtime integration adapter, event bridge, tests.

## Architecture Constraints

The Brain/task agent issues declarative scene/object operations. It should not reach into DOM nodes or arbitrary JavaScript closures.

## Automated Validation

- Create/update/hide/show/destroy lifecycle.
- Owner/provenance retention.
- Event propagation without direct tool execution.
- Scene rerender/update state survival according to contract.

## Acceptance Criteria

- Prefab-backed objects behave like first-class scene objects.
- Existing non-prefab scene objects continue to work or have an explicit migration adapter.
- No unrestricted authority path is introduced.

## Documentation Updates

Document public scene↔prefab contract and event boundary.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.

## Slice 00 contract (binding)

Create / touch:
- `jarvis/domain/scene.py`: `ScenePrefabRef`, `ScenePayload.prefab` (optional key, emitted only when present), kind rule in `SceneObject.__post_init__`, `SceneRefusal.PREFAB_INVALID`, `SceneUpdate.detail` (default `""`, only with a refusal, ≤300).
- `jarvis/core/scene_service.py`: `prefab_validator` hook in `_apply_serialized` (06 D-SCENE); refusal diagnostics include the detail.
- `jarvis/core/v2_app.py`: pass `self.prefabs` to `SceneService`; build `PrefabEventService`.
- `jarvis/core/prefab_events.py`: `PrefabEventService` (06 D-EVENTS: state, notify, ring 256, rate limit, `take_undelivered_notify`).
- `jarvis/protocol/scene_wire.py` (`command_body` emits `detail`), `jarvis/runtime/scene_view.py` (`decode_command_response` accepts `detail`).
- `jarvis/protocol/prefab_routes.py` + `jarvis/runtime/prefab_relay.py`: `POST/GET /v1/prefabs/events`, `POST/GET /api/prefabs/events` (actor forced `user`); ARCHITECTURE quotes them.
- `control_center_scene_layout.js` `viewModel`: node gains `prefab: {id, version, props, data}|null`, `prefabKey`; parity test on bounds extended (`test_scene_renderer_logic.py`).
- `control_center_scene_page.js`:
  - `fill()` prefab branch: head as today, persistent `.sc-prefab-slot` never detached.
  - Content key includes `prefabKey`, not props/data.
  - `applyNodes` calls `host.update` on props/data/theme change and `host.unmount` on removal or shape change.
  - `naturalWindowHeight` counts the slot's reported height.
  - Host events → `/api/prefabs/events` with `basis`; on `stale`, re-send `update` from the current state.
- `control_center_scene_capture.js`: prefab fallback drawing (06 D-RENDER).
- `docs/scene-model.md` (status implemented), `docs/prefabs.md`.

Acceptance:
- `test_scene_prefab_payload.py`: legacy wire byte-identical; round-trip; non-window kind refused; 16 KiB bound.
- `test_scene_service_prefab.py`: valid create; unknown version → `invalid/prefab_invalid` with detail, revision unchanged; no validator → refused; `patch_selection` annotation and move on a prefab window not revalidated; reload from `SQLiteSceneRepository` keeps the block.
- `test_prefab_events.py`: state toggle applied as actor user through the reducer (new revision, patch on stream); writes outside `writes` refused; stale basis → `stale`; mismatching prefab id/version refused; notify recorded and not written; ring bound; 429.
- Node: page/host integration with fakes. A content-key change of title does not remount the frame; data change → one `update` message; removal → unmount.
- Existing scene suites green unchanged: `test_scene_*`, `test_display_mcp.py`, `test_presentation_*`.
- Browser: create a `test.counter` window through `/api/scene/commands` (user); drag, resize, pin, select, Bare Hands zones on the head; counter state event persists across page reload; capture shows the fallback.

In: bridge, events. Out: base prefabs, MCP, brain context.
Depends on: 03.
QA: qa-verification + code-review + runtime-validation. Frontend: /impeccable, Claude agent.
