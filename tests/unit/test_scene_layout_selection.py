"""Atomic arbitrary scene geometry, strict wire and stale-safe geometry undo."""

from dataclasses import replace
import asyncio
import json

import pytest

from jarvis.domain.scene import (
    MAX_REVISION, MAX_SCENE_OBJECTS, PlacedBy, SceneActor, SceneCommand, SceneCommandOutcome,
    SceneGeometry, SceneObjectFields, SceneOp, SceneRefusal, SceneSnapshot, Visibility, apply_scene_command,
)
from jarvis.domain.scene_batch import SceneGeometryTarget, SceneGeometryTargets
from jarvis.domain.scene_selection import SceneSelection
from tests.unit.test_scene_batch import assert_refused_untouched, assert_report_invariants, note, scene
from tests.unit.test_scene_contracts import cmd, run
from tests.unit.test_scene_service import started
from jarvis.core.scene_service import SCENE_COMMAND_REFUSED_KIND, SCENE_PERSIST_FAILED_KIND
from jarvis.ports.scene import ScenePersistenceError, SceneStoreError, SceneStoreErrorCode


def layout(*entries, actor=SceneActor.USER, pin=None):
    return SceneCommand(op=SceneOp.LAYOUT_SELECTION, actor=actor,
                        selection=SceneSelection(ids=tuple(entry.object_id for entry in entries)),
                        targets=SceneGeometryTargets(entries), pin=pin)


def test_arbitrary_layout_is_one_patch_in_selection_order_and_preserves_other_fields():
    before = scene()
    targets = SceneGeometryTargets((SceneGeometryTarget("n2", SceneGeometry(70, 40, 12, 18)),
                                    SceneGeometryTarget("n1", SceneGeometry(5, 10, 30, 20))))
    command = SceneCommand(op=SceneOp.LAYOUT_SELECTION, actor=SceneActor.USER,
                           selection=SceneSelection(ids=("n1", "n2")), targets=targets, pin=True)
    update = apply_scene_command(before, command)
    assert update.outcome is SceneCommandOutcome.APPLIED
    assert update.snapshot.revision == before.revision + 1 == update.patch.revision
    assert [op.object.object_id for op in update.patch.ops] == ["n1", "n2"]
    assert_report_invariants(update)
    for target in targets.entries:
        old, new = before.get_object(target.object_id), update.snapshot.get_object(target.object_id)
        assert new.geometry == target.geometry and new.constraints.pinned_by_user
        assert new.constraints.placed_by is PlacedBy.USER
        assert replace(new, geometry=old.geometry, constraints=old.constraints) == old
    assert update.snapshot.get_object("n2").visibility is Visibility.HIDDEN


@pytest.mark.parametrize("bad_id,reason", [("ghost", SceneRefusal.UNKNOWN_OBJECT), ("loose", SceneRefusal.UNPLACED)])
def test_unknown_or_unplaced_required_member_prevents_every_write(bad_id, reason):
    before = scene()
    update = apply_scene_command(before, layout(SceneGeometryTarget("n1", SceneGeometry(5, 5, 20, 10)),
                                                SceneGeometryTarget(bad_id, SceneGeometry(10, 10, 20, 10))))
    assert_refused_untouched(before, update)
    assert update.reason is reason


def test_archived_target_prevents_every_write():
    before = run(scene(), cmd(SceneOp.ARCHIVE, SceneActor.USER, object_id="n2"))
    update = apply_scene_command(before, layout(SceneGeometryTarget("n1", SceneGeometry(5, 5, 20, 10)),
                                                SceneGeometryTarget("n2", SceneGeometry(10, 10, 20, 10))))
    assert_refused_untouched(before, update)
    assert update.reason is SceneRefusal.OBJECT_ARCHIVED


@pytest.mark.parametrize("actor", [SceneActor.USER, SceneActor.BRAIN])
def test_explicit_layout_can_move_pinned_members_and_optionally_pin_others(actor):
    before = scene()
    update = apply_scene_command(before, layout(SceneGeometryTarget("n3", SceneGeometry(-10, -5, 20, 20)), actor=actor))
    assert update.outcome is SceneCommandOutcome.APPLIED
    assert update.snapshot.get_object("n3").constraints.pinned_by_user
    assert update.snapshot.get_object("n3").constraints.placed_by.value == actor.value


def test_runtime_is_refused_even_when_geometry_is_unchanged():
    before = scene()
    update = apply_scene_command(before, layout(SceneGeometryTarget("n1", before.get_object("n1").geometry), actor=SceneActor.RUNTIME))
    assert_refused_untouched(before, update)
    assert update.reason is SceneRefusal.OP_NOT_ALLOWED


def test_geometry_compare_undo_is_atomic_and_preserves_pin_and_non_geometry_updates():
    before = scene()
    requested = (SceneGeometryTarget("n1", SceneGeometry(5, 10, 35, 15)),
                 SceneGeometryTarget("n3", SceneGeometry(50, 10, 35, 15)))
    after = apply_scene_command(before, layout(*requested, pin=True)).snapshot
    # A later public payload update must not be undone with the geometry.
    after = run(after, cmd(SceneOp.PATCH_OBJECT, SceneActor.USER, object_id="n1",
                           fields=SceneObjectFields(category="updated")))
    undo = layout(*(SceneGeometryTarget(entry.object_id, before.get_object(entry.object_id).geometry, entry.geometry)
                    for entry in requested))
    update = apply_scene_command(after, undo)
    assert update.outcome is SceneCommandOutcome.APPLIED
    assert update.snapshot.revision == after.revision + 1
    assert update.snapshot.get_object("n1").category == "updated"
    assert all(update.snapshot.get_object(entry.object_id).constraints.pinned_by_user for entry in requested)
    assert all(update.snapshot.get_object(entry.object_id).geometry == before.get_object(entry.object_id).geometry
               for entry in requested)


def test_any_stale_compare_refuses_all_targets_in_selection_order_even_for_noop_targets():
    before = scene()
    targets = tuple(SceneGeometryTarget(object_id, before.get_object(object_id).geometry, SceneGeometry(99, 99, 20, 10))
                    for object_id in ("n3", "n1"))
    update = apply_scene_command(before, layout(*targets))
    assert_refused_untouched(before, update)
    assert update.reason is SceneRefusal.GEOMETRY_CHANGED
    assert [entry.object_id for entry in update.batch.refused] == ["n3", "n1"]


def test_unrelated_geometry_change_does_not_invalidate_target_compare():
    before = scene()
    changed = run(before, cmd(SceneOp.SET_GEOMETRY, SceneActor.USER, object_id="n2", geometry=SceneGeometry(99, 99, 20, 10)))
    update = apply_scene_command(changed, layout(SceneGeometryTarget("n1", SceneGeometry(1, 2, 20, 10), before.get_object("n1").geometry)))
    assert update.outcome is SceneCommandOutcome.APPLIED


def test_duplicate_is_no_revision_and_revision_exhaustion_is_all_or_nothing():
    before = scene()
    command = layout(SceneGeometryTarget("n1", before.get_object("n1").geometry))
    duplicate = apply_scene_command(before, command)
    assert duplicate.outcome is SceneCommandOutcome.DUPLICATE and duplicate.snapshot is before and duplicate.patch is None
    assert_report_invariants(duplicate)
    exhausted = replace(before, revision=MAX_REVISION)
    update = apply_scene_command(exhausted, layout(SceneGeometryTarget("n1", SceneGeometry(2, 2, 20, 10))))
    assert_refused_untouched(exhausted, update)
    assert update.reason is SceneRefusal.REVISION_EXHAUSTED


def test_512_targets_are_one_patch_without_chunking():
    before = SceneSnapshot(scene_id="layout-max")
    for i in range(MAX_SCENE_OBJECTS):
        before = run(before, note(f"n{i}", geometry=SceneGeometry(0, 0, 10, 10)))
    command = layout(*(SceneGeometryTarget(f"n{i}", SceneGeometry(i, 1, 12, 15)) for i in range(MAX_SCENE_OBJECTS)))
    update = apply_scene_command(before, command)
    assert update.outcome is SceneCommandOutcome.APPLIED and len(update.patch.ops) == MAX_SCENE_OBJECTS
    assert update.snapshot.revision == before.revision + 1
    assert_report_invariants(update)


def payload():
    return layout(SceneGeometryTarget("n1", SceneGeometry(1, 2, 20, 10), SceneGeometry(0, 0, 20, 10))).to_payload()


def test_wire_roundtrip_compares_all_geometries():
    value = payload()
    assert SceneCommand.from_payload(json.loads(json.dumps(value))).to_payload() == value
    assert value["targets"][0]["expected_geometry"] == {"x": 0, "y": 0, "w": 20, "h": 10}


@pytest.mark.parametrize("change", [
    lambda p: p.update(selection={"kind": "window"}),
    lambda p: p.update(selection={"ids": ["n1", "n2"]}),
    lambda p: p.update(targets=[]),
    lambda p: p.update(targets=p["targets"] * 2),
    lambda p: p.update(targets=p["targets"] * (MAX_SCENE_OBJECTS + 1)),
    lambda p: p.update(targets={"n1": p["targets"][0]["geometry"]}),
    lambda p: p["targets"][0].update(extra=True),
    lambda p: p["targets"][0].update(expected_geometry=None),
    lambda p: p["targets"][0]["geometry"].update(w=0),
    lambda p: p["targets"][0]["geometry"].update(x=float("nan")),
    lambda p: p["targets"][0]["geometry"].update(w=True),
    lambda p: p.update(pin=False),
])
def test_invalid_layout_wire_is_rejected_at_boundary(change):
    value = payload()
    change(value)
    with pytest.raises((TypeError, ValueError)):
        SceneCommand.from_payload(value)


def test_mixed_compared_and_uncompared_targets_are_rejected():
    with pytest.raises(ValueError, match="every target"):
        layout(SceneGeometryTarget("n1", SceneGeometry(1, 1, 10, 10)),
               SceneGeometryTarget("n2", SceneGeometry(2, 2, 10, 10), SceneGeometry(0, 0, 10, 10)))


def test_layout_patch_converges_through_existing_js_applier(scene_logic):
    before = scene()
    update = apply_scene_command(before, layout(SceneGeometryTarget("n1", SceneGeometry(4, 5, 30, 12)),
                                               SceneGeometryTarget("n3", SceneGeometry(50, 5, 30, 12)), pin=True))
    response = {"scene_id": before.scene_id, "epoch": "layout-epoch", "revision": before.revision,
                "snapshot": before.to_payload()}
    actual = scene_logic("""
        const state=S.fromSnapshot(D.before);
        if(!state.ok)return {error:state.reason};
        const result=S.applyPatch(state.state,D.patch);
        if(!result.ok)return {error:result.reason};
        return S.toSnapshot(result.state);
    """, {"before": response, "patch": update.patch.to_payload()})
    assert actual == update.snapshot.to_payload()


async def test_concurrent_compares_serialize_and_only_one_can_commit():
    service, repository, diagnostics = await started()
    try:
        await service.apply(note("n1", geometry=SceneGeometry(0, 0, 10, 10)))
        before = await service.snapshot()
        commands = [layout(SceneGeometryTarget("n1", SceneGeometry(x, 0, 10, 10), before.get_object("n1").geometry))
                    for x in (1, 2)]
        results = await asyncio.gather(*(service.apply(command) for command in commands))
        assert [result.outcome for result in results] == [SceneCommandOutcome.APPLIED, SceneCommandOutcome.INVALID]
        assert results[1].reason is SceneRefusal.GEOMETRY_CHANGED
        assert repository.max_in_commit == 1 and repository.commits == [1, 2]
        refused = diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND)
        assert refused and refused[-1][1]["reason"] == "geometry_changed"
    finally:
        await service.close()


async def test_layout_persistence_failure_leaves_all_geometry_unchanged_and_is_logged():
    service, repository, diagnostics = await started()
    try:
        for i in range(2):
            await service.apply(note(f"n{i}", geometry=SceneGeometry(i * 20, 0, 10, 10)))
        before = await service.snapshot()
        repository.fail_commit = SceneStoreError(SceneStoreErrorCode.STORAGE_IO, "layout write failed")
        with pytest.raises(ScenePersistenceError):
            await service.apply(layout(*(SceneGeometryTarget(f"n{i}", SceneGeometry(i * 30, 5, 15, 15)) for i in range(2))))
        assert await service.snapshot() == before == repository.stored
        assert repository.commits == [1, 2]
        assert diagnostics.kinds(SCENE_PERSIST_FAILED_KIND)
    finally:
        await service.close()
