# Slice 03 — Dynamic Prefab Runtime

## Goal

Make valid prefab definitions dynamically discoverable and safely mountable without adding per-prefab branches to core runtime code.

## Context

A shared library cannot scale if every newly saved prefab requires editing a central registry function or switch.

## Canonical Concepts

Prefab catalog, prefab runtime, behavior lifecycle, style ownership.

## Scope

### In Scope

- Manifest/catalog-driven discovery.
- Template/style/behavior resolution.
- Input validation before mount.
- Mount/update/unmount lifecycle.
- Cleanup guarantees.
- Style scoping/isolation appropriate to the audited frontend architecture.
- Error states for invalid/missing prefab resources.

### Out of Scope

- Scene placement logic.
- Agent authoring operations.

## Dependencies

- `02-prefab-schema`

## Implementation Steps

1. Remove or bypass per-prefab core registration requirements where they exist.
2. Load definitions/resources through the canonical catalog.
3. Mount behavior through one runtime lifecycle API.
4. Guarantee cleanup on rerender/unmount.
5. Enforce CSS ownership/scoping; reject or isolate unsafe global styling patterns.
6. Add runtime diagnostics for definition/load/mount errors.

## Files Likely Touched

Prefab runtime, manifest/catalog loader, frontend style loader, behavior lifecycle helpers, tests.

## Architecture Constraints

No new frontend framework solely for this Slice. Preserve repository build/runtime conventions.

## Automated Validation

- Discovery of a synthetic unknown-to-core prefab.
- Mount/update/unmount cleanup tests.
- Repeated lifecycle leak tests.
- Scoped-style regression tests.
- Invalid resource/error-state tests.

## Acceptance Criteria

- A valid new prefab can be added through the documented catalog path without editing core runtime branching logic.
- Behavior and styles are cleaned up/contained.
- Invalid prefabs fail visibly and diagnostically.

## Documentation Updates

Document runtime lifecycle and registration rules.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.

## Slice 00 contract (binding)

Goal re-scoped: the **one** sandboxed runtime (06 D-RENDER, R4) plus the read routes that feed it.

Create:
- `jarvis/prefabs/runtime/shim.js` (factory `createShim(env)` + bootstrap; API of R4) and `jarvis/prefabs/runtime/shell.css` (`.jv-*`, CSS variables, focus ring, scrollbars, markdown blocks).
- `jarvis/runtime/control_center_prefab_protocol.js` (pure; `window.JarvisPrefabProtocol` + `module.exports`): `SANDBOX = "allow-scripts"`, CSP string, `buildSrcdoc(bundle)`, `parseFrameMessage`, `hostMessage`, `isAllowedUrl`.
- `jarvis/runtime/control_center_prefab_host.js` (DOM; `window.JarvisPrefabHost`; **only** file setting `srcdoc`): `createPrefabHost({fetchBundle, document, now, log, postEvent, mode})` with `mount(slot, instance)`, `update(objectId, props, data, theme)`, `unmount(objectId)`, `pause/resume`, cap 24 with LRU, bundle cache by `id@version`, error band, rate limit, `open_url` handling.
- `jarvis/protocol/prefab_routes.py`: `PrefabProtocolRoutes` with GET `/v1/prefabs`, `/v1/prefabs/{prefab_id}`, `/v1/prefabs/{prefab_id}/{version}`, `/v1/prefabs/{prefab_id}/{version}/bundle`; spliced into `server.py` route table.
- `jarvis/runtime/prefab_relay.py`: `CorePrefabTransport` + `PrefabRelayRoutes` for the matching GET `/api/prefabs*`; add the prefix to `READ_GUARDED_ROUTES` in `control_center.py`.
- Fixture `tests/fixtures/prefabs/test.netprobe/1` (tries `fetch`, `parent.document`, `localStorage`, `window.open`) for browser proof.

Touch:
- `control_center.html`: markers `/*__CONTROL_CENTER_PREFAB_PROTOCOL_JS__*/`, `/*__CONTROL_CENTER_PREFAB_HOST_JS__*/` before the scene page marker.
- `control_center.py` `index` splice + constants.
- `PrefabService.bundle` returns `runtime`.
- `docs/ARCHITECTURE.md` quotes the GET `/api/prefabs*` routes now registered.
- `docs/prefabs.md`.

Acceptance:
- Node: `test_prefab_protocol_js.py`, `test_prefab_shim_js.py`, `test_prefab_host_js.py` (06 R7 JS list), including "a prefab unknown to core code (`test.counter`) mounts through the catalogue path with no code edit".
- Static: `srcdoc` only in host file; no `innerHTML` in protocol/host/shim; protocol module free of `document.`/`window.`/`fetch(`.
- `test_prefab_routes.py` (GET), relay test, `Origin: null` refused, documented-routes and architecture gates.
- Browser (Chrome, real CC): mount `test.counter` and `test.netprobe` in a scratch slot via devtools (`JarvisPrefabHost`); evidence of the sandbox attribute, a CSP violation for fetch, a `parent.document` exception, a visible error band for a throwing behavior, and resize messages.

In: runtime, read routes. Out: scene integration (S04), events route (S04).
Depends on: 02.
QA: qa-verification + code-review + runtime-validation. Frontend: /impeccable, Claude agent.
