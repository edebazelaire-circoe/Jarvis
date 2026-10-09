# Slice 01b (PROPOSED, CONDITIONAL) - Asset Delivery to Prefab Frames

Status: proposal from Slice 01 (`docs/07-integration-map.md` G2/5.4). Only needed if the Human wants real images/fonts/media inside presentation scenes. If not, Slice 09 documents "CSS/SVG/inline-data art direction only" and this Slice is dropped.

## Goal
Define how a studio scene shows non-inline visual assets (photos, logos, illustrations, media) without weakening the frame sandbox, or state explicitly that it cannot.

## Evidence (the constraint)
- Frame `sandbox="allow-scripts"`, opaque origin (`jarvis/runtime/control_center_prefab_protocol.js:44`), CSP `default-src 'none'; ... img-src data:; font-src data:` (:45): no network, no external image/font/media.
- Scene payload (title + props + data) <= 16 KiB (`jarvis/domain/scene.py:93`); template/style <= 32 KiB each, behavior <= 64 KiB (`jarvis/domain/prefab.py:89-92`). A single raster image as `data:` already exceeds the style budget.
- Artifacts store payload files under `artifacts/<id>/` (`docs/artifacts.md`) but nothing serves them to a frame.

## Scope
### In Scope
- Options analysis with a threat model (the frame is untrusted code written by the model): (1) status quo + SVG/CSS only; (2) host-mediated asset channel: frame requests an asset id over `jv:1`, the host fetches it from a Control Center route and posts back a `data:`/`blob:` already size-checked (new `jv` message pair, `FRAME_TYPES`/`HOST_TYPES` change, must not enable network from the frame); (3) relaxing `img-src` to a same-origin asset prefix (weakens the CSP; requires SECURITY.md control 16 review).
- If an option is chosen: strict allowlist of asset kinds and sizes, asset references as `ResourceReference` (`jarvis/domain/presentation_working_set.py:653`) or `jart_` ids, loopback-guarded route (`READ_GUARDED_ROUTES`), visible failure for a missing asset.
- Evidence tests for the CSP/sandbox invariants (`tests/unit/test_prefab_protocol_js.py`, `test_prefab_host_js.py`, `test_prefab_frame_containment.py`).

### Out of Scope
- Video generation (D22). Studio persistence of assets (Slice 02 stores references only).

## Dependencies
- `01-contract-audit`. Informs `09` (art direction) and `14` (cinematic quality).

## Acceptance Criteria
Either a documented, tested asset path that keeps `sandbox="allow-scripts"` and a CSP without network, or an explicit "not supported" in `docs/prefabs.md` and `docs/presentation-studio.md` with the CSS/SVG-only guidance used by Slice 09.

## Documentation Updates
`docs/prefabs.md` (Runtime / Known limitations), `docs/SECURITY.md` control 16 if the CSP changes, `docs/presentation-studio.md`.

## QA tier
standard if documentation-only; critical if the protocol or CSP changes.
