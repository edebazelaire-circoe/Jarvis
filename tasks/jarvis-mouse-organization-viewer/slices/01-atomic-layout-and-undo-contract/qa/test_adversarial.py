"""Independent QA probes; no changes to production or canonical conformance tests."""
from dataclasses import replace

from jarvis.domain.scene import SceneCommand, SceneCommandOutcome, SceneGeometry, SceneRefusal, apply_scene_command
from jarvis.domain.scene_batch import SceneGeometryTarget
from tests.unit.test_scene_batch import scene
from tests.unit.test_scene_layout_selection import layout
from tests.integration.test_scene_layout_transport import layout_wire, seed
from tests.integration.test_scene_transport import core, snapshot_of  # noqa: F401


def test_later_stale_member_prevents_earlier_valid_move_and_pin():
    before = scene()
    first = before.get_object("n1")
    second = before.get_object("n3")
    command = layout(
        SceneGeometryTarget("n1", SceneGeometry(9, 7, 21, 13), first.geometry),
        SceneGeometryTarget("n3", SceneGeometry(40, 7, 21, 13), replace(second.geometry, x=second.geometry.x + 1)),
        pin=True,
    )
    update = apply_scene_command(before, command)
    assert update.outcome is SceneCommandOutcome.INVALID
    assert update.reason is SceneRefusal.GEOMETRY_CHANGED
    assert update.snapshot is before and update.patch is None
    assert update.batch.changed_ids == ()
    assert [r.object_id for r in update.batch.refused] == ["n3"]
    assert before.get_object("n1") is first


async def test_sqlite_restart_preserves_atomic_layout_then_compare_undo(core):
    await seed(core)
    baseline = await snapshot_of(core)
    command = layout_wire(compare=True)
    status, applied, _ = await core.request("POST", "/v1/scene/commands", json=command)
    assert status == 200 and applied["outcome"] == "applied" and applied["revision"] == 3
    persisted = await snapshot_of(core)
    await core.stop()
    await core.start()
    reloaded = await snapshot_of(core)
    assert reloaded["snapshot"] == persisted["snapshot"]
    originals = {o["object_id"]: o["geometry"] for o in baseline["snapshot"]["objects"]}
    undo = {"schema_version": 1, "op": "layout_selection", "actor": "user", "selection": command["selection"],
            "targets": [{"object_id": t["object_id"], "geometry": originals[t["object_id"]], "expected_geometry": t["geometry"]}
                        for t in command["targets"]]}
    status, reverted, _ = await core.request("POST", "/v1/scene/commands", json=undo)
    assert status == 200 and reverted["outcome"] == "applied" and reverted["revision"] == 4
    result = await snapshot_of(core)
    assert all(o["geometry"] == originals[o["object_id"]] and o["constraints"]["pinned_by_user"]
               for o in result["snapshot"]["objects"])
    status, stale, _ = await core.request("POST", "/v1/scene/commands", json=undo)
    assert status == 200 and stale["outcome"] == "invalid" and stale["reason"] == "geometry_changed"
    assert (await snapshot_of(core))["snapshot"] == result["snapshot"]


def test_target_wire_cannot_smuggle_execution_or_payload_updates():
    command = layout_wire()
    command["targets"][0]["payload"] = {"summary": "must not cross layout seam"}
    try:
        SceneCommand.from_payload(command)
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError("layout target accepted a non-geometry field")
