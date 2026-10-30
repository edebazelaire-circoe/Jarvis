# S1 implementation — atomic layout and safe geometry compare

Implemented 2026-10-30 in task/mov-s1 (worktree C:/Projects/jarvis/mov1). Independent QA pending; this is an implementation report, not approval.

## Final API
Additional SceneOp.LAYOUT_SELECTION, wire op `layout_selection`. Existing POST /v1/scene/commands and POST /api/scene/commands are reused.

```json
{
  "schema_version": 1,
  "op": "layout_selection",
  "actor": "user",
  "selection": {"ids": ["a", "b"]},
  "targets": [
    {"object_id": "a", "geometry": {"x": 0, "y": 0, "w": 30, "h": 20}},
    {"object_id": "b", "geometry": {"x": 34, "y": 0, "w": 30, "h": 20}}
  ],
  "pin": true
}
```

Python values: SceneGeometryTargets(tuple[SceneGeometryTarget, ...]); each SceneGeometryTarget(object_id, geometry, expected_geometry=None). Both in jarvis/domain/scene_batch.py. targets serializes as the JSON list above. Strict explicit selection only; target IDs must equal selection IDs exactly, no duplicates, max512, each active and placed. Uses canonical resolver and object writer. Target order does not determine application order: explicit selection order does.

For undo, reverse geometries and provide expected_geometry for EVERY target:
```json
{"object_id":"a","geometry":{"x":5,"y":8,"w":20,"h":10},"expected_geometry":{"x":0,"y":0,"w":30,"h":20}}
```
Mixed compared/uncompared targets are rejected. Core compares all current rectangles on its locked snapshot before any write; mismatch gives outcome=invalid, reason=geometry_changed and normal batch.refused list [{id,reason,field:"ids"}] in selection order, no patch/revision. Unknown, archived, unplaced required IDs also refuse whole action. Unrelated/non-geometry updates do not invalidate compare.

pin accepts only true and is optional. It pins all members in the same patch. Omit pin during geometry-only undo: current pin is preserved (originally unpinned objects stay pinned if the operation pinned them). Geometry changes record current explicit actor as placed_by, so undo does not restore old resolver provenance. Payload, status, visibility and representation are untouched. Hidden members retain canonical explicit-selection eligibility. S05 owns UI ring invalidation on hidden/unavailable/representation-changed entries.

## Reuse and integration
- Added to SELECTION_OPS: existing apply_selection_command, SceneBatchReport, CoreSceneView large-patch omission, command logging and HTTP encoding work unchanged.
- One successful action → one patch/revision; duplicate → none; runtime refused by existing authority matrix.
- _plan_object_write is reused for per-field authority and placement provenance.
- SceneService lock/transaction, diagnostic success/refusal/persistence failure and standard patch polling remain canonical.
- Existing JS patch applier accepts generated patches; parity exercised.
- No new route, schema migration, MCP tool, history service or scene-page JS code.
- Updated canonical docs/scene-selection-batch.md §8 and existing authority/roundtrip tests.

## Wire budget for S05
Preserve existing 65,536-byte HTTP command budget; no chunking. Preflight UTF-8 size of submitted command and canonical relay serialization (numeric integers become floats in Python payload, usually adding .0). Domain max512 is not an HTTP promise for all IDs/rectangles.
Measured canonical compact JSON for IDs n0..:
- 24 targets with compares: 3,169 bytes.
- 256 targets with compares: 33,409 bytes.
- 512 without compares: 38,273 bytes.
- 512 with compares: 66,945 bytes → HTTP413 payload_too_large, whole action untouched.
Longer IDs/more decimal precision consume more. S05 must give an actionable refusal and not store an unsendable undo.

## Validation actually run
From mov1 using C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe:
- `-m pytest --assert=plain --tb=short -q tests/unit/test_scene_layout_selection.py tests/unit/test_scene_batch.py tests/unit/test_scene_contracts.py tests/unit/test_scene_transport_client.py tests/unit/test_scene_view.py`: **493 passed in39.20s**.
- `-m pytest --assert=plain --tb=short -q tests/integration/test_scene_layout_transport.py tests/integration/test_scene_transport.py -k 'layout or selection_command'`: **7 passed,53 deselected in4.63s**.
- `git diff --check`: passed.

New tests cover distinct rectangles, order, all-or-nothing bad/archived/unplaced members, user/brain pin authority, runtime refusal, stale no-op compare, successful geometry-only undo preserving payload/pins, unrelated changes, revision exhaustion, max512 one patch, malformed/bounded wire, mixed compares, JS patch parity, two concurrent compares (only one commit), persistence failure leaves all state intact and records diagnostic failure.
Integration uses real isolated SQLite + Core HTTP and ControlCenter TestServer; covers one revision, stale refusal, relay actor guard/patch_omitted/normal polls and400/403/413.

Initial assertion-rewrite test processes stalled after100%; terminated ONLY verified own pytest PIDs, then reran with --assert=plain successfully. Initial integration test incorrectly expected client actor brain to be overridden; existing relay correctly refuses403. Corrected test to assert403 then omit actor and verify user placement; no production change needed.

## Not verified here
No full suite (reserved S06), browser organization/undo UI (S05), model calls (no agent/model path changed), independent adversarial/mutation review (PM/QA next). No user's live runtime started/stopped. No user data touched.

