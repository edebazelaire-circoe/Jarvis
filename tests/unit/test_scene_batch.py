"""Commandes de sélection atomiques (handoff jarvis-mcp-semantic-batch-inspector, Slice 03).

Contrat : `docs/scene-selection-batch.md` §3–§5, module `jarvis.domain.scene_batch`.
Ce qui doit tenir :

- tout ou rien : un lot refusé laisse la révision intacte, un lot appliqué
  l'avance d'exactement un, avec **un** patch qui porte tous les membres et
  les cascades ;
- tous les fautifs listés, en ordre canonique, motif = premier fautif ;
- explicite ≠ filtre pour un membre non placé (refus / écarté) ;
- translation rigide : écart commun, écarts relatifs conservés, bornes
  élargies « jamais pire », quantification vers zéro, épingle dans le même
  patch ;
- `duplicate` quand rien ne change ; même autorité pour `brain` et `user`,
  `runtime` refusé ; borne unique de 512.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.scene import (
    MAX_SCENE_OBJECTS,
    SCENE_SAFE_AREA,
    ExecState,
    PatchOpKind,
    RelationKind,
    Representation,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneGeometry,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    Visibility,
    WorkRef,
    apply_scene_command,
)
from jarvis.domain.scene_batch import SceneDelta, SelectionChanges, group_delta
from jarvis.domain.scene_selection import ConstellationScope, SceneSelection
from tests.unit.test_scene_contracts import cmd, run, star, upsert

APPLIED = SceneCommandOutcome.APPLIED
DUPLICATE = SceneCommandOutcome.DUPLICATE
INVALID = SceneCommandOutcome.INVALID
REJECTED = SceneCommandOutcome.REJECTED_AUTHORITY
RUNTIME, BRAIN, USER = SceneActor.RUNTIME, SceneActor.BRAIN, SceneActor.USER


def ids(*values: str) -> SceneSelection:
    return SceneSelection(ids=values)


def note(object_id: str, *, geometry: SceneGeometry | None = None, **fields) -> SceneCommand:
    return upsert(USER, object_id, kind=SceneObjectKind.WINDOW, category="note", geometry=geometry, **fields)


def scene() -> SceneSnapshot:
    """Trois notes placées (une masquée, une épinglée), une non placée, une étoile et son signal."""

    return run(
        SceneSnapshot(scene_id="scene-batch"),
        note("n1", geometry=SceneGeometry(0, 0, 20, 10), payload=ScenePayload(title="Un")),
        note("n2", geometry=SceneGeometry(30, 15, 10, 10), visibility=Visibility.HIDDEN),
        note("n3", geometry=SceneGeometry(-40, -20, 10, 10)),
        cmd(SceneOp.PIN, USER, object_id="n3"),
        note("loose"),
        star("codex:1", work_ref=WorkRef(source="codex", external_id="1"), exec_state=ExecState.COMPLETED),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="attention!1",
            fields=SceneObjectFields(category="attention", exec_state=ExecState.COMPLETED,
                                     work_ref=WorkRef(source="codex", external_id="1")),
            target_id="codex:1"),
        cmd(SceneOp.LINK, USER, relation=SceneRelation("rel-n1-n2", RelationKind.EXPLAINS, "n1", "n2")),
    )


def apply(before: SceneSnapshot, op: SceneOp, actor: SceneActor = USER, **arguments):
    return apply_scene_command(before, cmd(op, actor, **arguments))


def assert_refused_untouched(before: SceneSnapshot, update) -> None:
    assert update.outcome in (INVALID, REJECTED)
    assert update.snapshot is before and update.patch is None
    assert update.snapshot.revision == before.revision
    assert update.batch is not None


def assert_report_invariants(update) -> None:
    report = update.batch
    matched = list(report.matched_ids)
    parts = [*report.changed_ids, *report.unchanged_ids, *(entry.object_id for entry in report.skipped)]
    assert sorted(parts) == sorted(matched) and len(set(parts)) == len(parts)
    assert (update.outcome is APPLIED) == bool(report.changed_ids)
    assert not report.refused


# --------------------------------------------------------------------- atomicité


def test_a_refused_batch_leaves_the_revision_and_every_member_untouched():
    before = scene()
    update = apply(before, SceneOp.PATCH_SELECTION, selection=ids("n1", "ghost", "n2", "nobody"),
                   changes=SelectionChanges(visibility=Visibility.HIDDEN))
    assert_refused_untouched(before, update)
    assert (update.outcome, update.reason) == (INVALID, SceneRefusal.UNKNOWN_OBJECT)
    # Tous les fautifs, dans l'ordre de l'appelant ; rien n'a été appliqué.
    assert [entry.to_payload() for entry in update.batch.refused] == [
        {"id": "ghost", "reason": "unknown_object", "field": "ids"},
        {"id": "nobody", "reason": "unknown_object", "field": "ids"},
    ]
    assert before.get_object("n1").visibility is Visibility.VISIBLE


def test_an_applied_batch_is_one_patch_and_exactly_one_revision():
    before = scene()
    update = apply(before, SceneOp.PATCH_SELECTION, selection=SceneSelection(kinds=(SceneObjectKind.WINDOW,)),
                   changes=SelectionChanges(layer=300, category="focus"))
    assert update.outcome is APPLIED and update.snapshot.revision == before.revision + 1
    assert update.patch.revision == before.revision + 1
    assert [op.object.object_id for op in update.patch.ops] == ["n1", "n2", "n3", "loose"]
    assert all(update.snapshot.get_object(i).layer == 300 for i in ("n1", "n2", "n3", "loose"))
    assert update.batch.changed_ids == ("n1", "n2", "n3", "loose") and update.batch.hidden_count == 1
    assert_report_invariants(update)


def test_an_all_no_op_batch_is_a_duplicate_without_revision_or_patch():
    before = scene()
    update = apply(before, SceneOp.PATCH_SELECTION, selection=ids("n1", "n3"),
                   changes=SelectionChanges(visibility=Visibility.VISIBLE))
    assert (update.outcome, update.patch, update.snapshot) == (DUPLICATE, None, before)
    assert update.batch.unchanged_ids == ("n1", "n3") and update.batch.changed_ids == ()
    assert_report_invariants(update)
    # Un filtre qui ne trouve rien : doublon honnête, listes vides.
    empty = apply(before, SceneOp.ARCHIVE_SELECTION, selection=SceneSelection(category="absent"))
    assert empty.outcome is DUPLICATE and empty.batch.matched_ids == () and empty.batch.cascade_ids == ()


def test_mixed_members_change_only_what_differs():
    before = scene()
    update = apply(before, SceneOp.PIN_SELECTION, selection=ids("n3", "n1"))
    assert update.outcome is APPLIED
    assert (update.batch.changed_ids, update.batch.unchanged_ids) == (("n1",), ("n3",))
    assert [op.object.object_id for op in update.patch.ops] == ["n1"]
    assert update.snapshot.get_object("n1").constraints.pinned_by_user
    unpinned = apply(update.snapshot, SceneOp.UNPIN_SELECTION, selection=ids("n1", "n3", "loose"))
    assert unpinned.batch.changed_ids == ("n1", "n3") and unpinned.batch.unchanged_ids == ("loose",)
    assert not any(item.constraints.pinned_by_user for item in unpinned.snapshot.objects)


# --------------------------------------------------------------------- refus


def test_refusals_list_references_first_then_ids_and_the_reason_is_the_first():
    before = run(scene(), cmd(SceneOp.ARCHIVE, USER, object_id="n2"))
    selection = SceneSelection(constellation=ConstellationScope("n2"), group="n1", exclude=("ghost",))
    update = apply(before, SceneOp.PATCH_SELECTION, selection=selection, changes=SelectionChanges(order=3))
    assert_refused_untouched(before, update)
    assert update.reason is SceneRefusal.OBJECT_ARCHIVED
    assert [entry.to_payload() for entry in update.batch.refused] == [
        {"id": "n2", "reason": "object_archived", "field": "constellation"},
        {"id": "n1", "reason": "invalid_selection", "field": "group"},
        {"id": "ghost", "reason": "unknown_object", "field": "exclude"},
    ]
    explicit = apply(before, SceneOp.PIN_SELECTION, selection=ids("n1", "n2", "ghost", "loose"))
    assert explicit.reason is SceneRefusal.OBJECT_ARCHIVED
    assert [(e.object_id, e.reason.value) for e in explicit.batch.refused] == [
        ("n2", "object_archived"), ("ghost", "unknown_object"), ("loose", "unplaced")]


def test_runtime_is_refused_before_any_resolution():
    before = scene()
    # `runtime` n'a pas les commandes de sélection ; `brain` et `user` ne
    # réécrivent jamais la vérité d'exécution — ce que `changes` ne porte pas :
    # la seule règle par membre qui peut tomber ici est celle de `_plan_object_write`.
    update = apply(before, SceneOp.PATCH_SELECTION, RUNTIME, selection=ids("n1"),
                   changes=SelectionChanges(order=1))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.OP_NOT_ALLOWED)
    assert_refused_untouched(before, update)


# --------------------------------------------------------------------- explicite / filtre


def test_an_explicit_unplaced_member_refuses_translate_and_pin():
    before = scene()
    for op, extra in ((SceneOp.TRANSLATE_SELECTION, {"delta": SceneDelta(5, 0)}), (SceneOp.PIN_SELECTION, {})):
        update = apply(before, op, selection=ids("n1", "loose"), **extra)
        assert_refused_untouched(before, update)
        assert (update.outcome, update.reason) == (INVALID, SceneRefusal.UNPLACED)
        assert [e.to_payload() for e in update.batch.refused] == [{"id": "loose", "reason": "unplaced", "field": "ids"}]


def test_a_filter_matched_unplaced_member_is_skipped_and_reported():
    before = scene()
    update = apply(before, SceneOp.TRANSLATE_SELECTION, selection=SceneSelection(kinds=(SceneObjectKind.WINDOW,)),
                   delta=SceneDelta(2, 1))
    assert update.outcome is APPLIED
    assert [entry.to_payload() for entry in update.batch.skipped] == [{"id": "loose", "reason": "unplaced"}]
    assert update.batch.changed_ids == ("n1", "n2", "n3") and update.snapshot.get_object("loose").geometry is None
    assert_report_invariants(update)


# --------------------------------------------------------------------- translation


def test_translation_moves_every_member_by_one_common_delta_and_keeps_offsets():
    before = scene()
    update = apply(before, SceneOp.TRANSLATE_SELECTION, BRAIN, selection=ids("n1", "n2", "n3"), delta=SceneDelta(7.5, -3))
    assert update.outcome is APPLIED and len(update.patch.ops) == 3
    for object_id in ("n1", "n2", "n3"):
        old, new = before.get_object(object_id), update.snapshot.get_object(object_id)
        assert (new.geometry.x - old.geometry.x, new.geometry.y - old.geometry.y) == pytest.approx((7.5, -3))
        assert (new.geometry.w, new.geometry.h) == (old.geometry.w, old.geometry.h)
        assert new.constraints.placed_by.value == "brain"
    # Un membre épinglé bouge (commande explicite) et le reste ; masqué, il suit le groupe.
    assert update.snapshot.get_object("n3").constraints.pinned_by_user
    assert update.snapshot.get_object("n2").visibility is Visibility.HIDDEN
    assert update.batch.to_payload()["delta"] == {"requested": {"dx": 7.5, "dy": -3.0},
                                                   "effective": {"dx": 7.5, "dy": -3.0}, "clamped": False}


def test_the_group_clamp_is_one_common_delta_at_the_safe_area_edge():
    x0, y0, x1, y1 = SCENE_SAFE_AREA
    # Groupe de n3 (x -40) à n2 (x1 = 40) : il ne peut aller qu'à `x1 - 40` à droite.
    before = scene()
    update = apply(before, SceneOp.TRANSLATE_SELECTION, selection=ids("n1", "n2", "n3"), delta=SceneDelta(10_000, 0))
    assert update.batch.delta.effective == (x1 - 40, 0.0) and update.batch.delta.clamped
    moved = {i: update.snapshot.get_object(i).geometry for i in ("n1", "n2", "n3")}
    assert moved["n2"].x + moved["n2"].w == x1  # le bord du groupe touche la zone sûre
    assert moved["n1"].x - moved["n3"].x == 40  # écarts intacts : pas de borne par membre
    # Déterministe : le même lot rejoué sur le même instantané donne le même patch.
    again = apply(before, SceneOp.TRANSLATE_SELECTION, selection=ids("n1", "n2", "n3"), delta=SceneDelta(10_000, 0))
    assert again.patch == update.patch
    # Vers le haut à gauche : borné par le coin du membre le plus excentré.
    up = apply(before, SceneOp.TRANSLATE_SELECTION, selection=ids("n1", "n2", "n3"), delta=SceneDelta(-10_000, -10_000))
    assert up.batch.delta.effective == (x0 - (-40), y0 - (-20))


def test_a_group_outside_the_area_never_gets_worse_and_is_never_forced_back():
    boxes = [SceneGeometry(200, 0, 10, 10)]  # au-delà du bord droit (138)
    assert group_delta(boxes, 5, 0) == (0.0, 0.0)  # pas plus loin
    assert group_delta(boxes, -30, 0) == (-30.0, 0.0)  # revenir est permis, sans y être forcé
    wide = [SceneGeometry(-200, 0, 10, 10), SceneGeometry(190, 0, 10, 10)]  # plus large que la zone
    assert group_delta(wide, 50, 4) == (0.0, 4.0)  # immobile sur x, libre sur y


def test_the_effective_delta_is_quantised_toward_zero():
    boxes = [SceneGeometry(0, 0, 10, 10)]
    assert group_delta(boxes, 2.37, -2.37) == (2.3, -2.3)
    assert group_delta(boxes, 2.3, 0.1) == (2.3, 0.1)  # la grille elle-même ne perd rien
    # Borne non alignée : jamais au-delà.
    edge = [SceneGeometry(0, 0, 10.05, 10)]
    dx, _ = group_delta(edge, 1_000, 0)
    assert dx == 127.9 and 0 + 10.05 + dx <= SCENE_SAFE_AREA[2]


def test_a_delta_clamped_to_nothing_is_a_duplicate_unless_it_pins():
    before = run(scene(), cmd(SceneOp.SET_GEOMETRY, USER, object_id="n1",
                               geometry=SceneGeometry(SCENE_SAFE_AREA[2] - 20, 0, 20, 10)))
    update = apply(before, SceneOp.TRANSLATE_SELECTION, selection=ids("n1"), delta=SceneDelta(10, 0))
    assert update.outcome is DUPLICATE and update.batch.delta.clamped and update.batch.delta.effective == (0.0, 0.0)
    pinned = apply(before, SceneOp.TRANSLATE_SELECTION, selection=ids("n1"), delta=SceneDelta(10, 0), pin=True)
    assert pinned.outcome is APPLIED and pinned.snapshot.get_object("n1").constraints.pinned_by_user
    assert pinned.snapshot.get_object("n1").geometry == before.get_object("n1").geometry


def test_the_pin_flag_pins_every_moved_member_in_the_same_patch():
    before = scene()
    update = apply(before, SceneOp.TRANSLATE_SELECTION, selection=ids("n1", "n2", "n3"), delta=SceneDelta(1, 1), pin=True)
    assert update.outcome is APPLIED and update.snapshot.revision == before.revision + 1
    assert [op.object.object_id for op in update.patch.ops] == ["n1", "n2", "n3"]
    assert all(op.object.constraints.pinned_by_user for op in update.patch.ops)


# --------------------------------------------------------------------- patch


def test_patch_selection_merges_the_annotation_and_keeps_the_content():
    before = scene()
    update = apply(before, SceneOp.PATCH_SELECTION, selection=ids("n1", "n2"),
                   changes=SelectionChanges(annotation="à revoir", representation=Representation.CAPSULE))
    n1 = update.snapshot.get_object("n1")
    assert n1.payload.title == "Un" and n1.payload.annotation == "à revoir"
    assert n1.representation is Representation.CAPSULE and n1.geometry == before.get_object("n1").geometry
    cleared = apply(update.snapshot, SceneOp.PATCH_SELECTION, selection=ids("n1"), changes=SelectionChanges(annotation=""))
    assert cleared.snapshot.get_object("n1").payload.annotation == "" and cleared.snapshot.get_object("n1").payload.title == "Un"


# --------------------------------------------------------------------- archivage


def test_archive_selection_takes_every_member_and_cascade_in_one_patch():
    before = scene()
    update = apply(before, SceneOp.ARCHIVE_SELECTION, BRAIN, selection=ids("n1", "codex:1", "n3"))
    assert update.outcome is APPLIED and update.snapshot.revision == before.revision + 1
    archived = [op.object.object_id for op in update.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT]
    # Ordre des membres, le signal avant son étoile ; épinglé compris.
    assert archived == ["n1", "attention!1", "codex:1", "n3"]
    deleted = [op.relation_id for op in update.patch.ops if op.op is PatchOpKind.DELETE_RELATION]
    assert sorted(deleted) == ["attention!1", "rel-n1-n2"]
    assert update.batch.cascade_ids == ("attention!1",) and update.batch.changed_ids == ("n1", "codex:1", "n3")
    assert_report_invariants(update)


def test_a_signal_selected_and_cascaded_appears_once_as_a_member():
    before = scene()
    update = apply(before, SceneOp.ARCHIVE_SELECTION, selection=ids("codex:1", "attention!1"))
    assert update.batch.cascade_ids == () and update.batch.matched_ids == ("codex:1", "attention!1")
    archived = [op.object.object_id for op in update.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT]
    assert archived == ["attention!1", "codex:1"]


def test_explicit_ids_already_archived_are_unchanged_in_their_place():
    before = run(scene(), cmd(SceneOp.ARCHIVE, USER, object_id="n2"))
    update = apply(before, SceneOp.ARCHIVE_SELECTION, selection=ids("n1", "n2", "n3"))
    assert update.outcome is APPLIED
    assert update.batch.matched_ids == ("n1", "n2", "n3") and update.batch.unchanged_ids == ("n2",)
    assert_report_invariants(update)
    only = apply(before, SceneOp.ARCHIVE_SELECTION, selection=ids("n2"))
    assert only.outcome is DUPLICATE and only.batch.unchanged_ids == ("n2",)
    # Toute autre opération refuse un id archivé.
    assert apply(before, SceneOp.PIN_SELECTION, selection=ids("n1", "n2")).reason is SceneRefusal.OBJECT_ARCHIVED


def test_archive_many_keeps_its_content_rule():
    before = scene()
    many = apply(before, SceneOp.ARCHIVE_MANY, object_ids=("n1",))
    assert (many.outcome, many.reason) == (INVALID, SceneRefusal.NOT_BULK_ARCHIVABLE)
    assert apply(before, SceneOp.ARCHIVE_SELECTION, selection=ids("n1")).outcome is APPLIED


# --------------------------------------------------------------------- autorité


SELECTION_COMMANDS = {
    SceneOp.PATCH_SELECTION: {"selection": SceneSelection(kinds=(SceneObjectKind.WINDOW,)),
                              "changes": SelectionChanges(visibility=Visibility.HIDDEN)},
    SceneOp.TRANSLATE_SELECTION: {"selection": ids("n1", "n3"), "delta": SceneDelta(3, 4), "pin": True},
    SceneOp.PIN_SELECTION: {"selection": ids("n1", "n2")},
    SceneOp.UNPIN_SELECTION: {"selection": ids("n3")},
    SceneOp.ARCHIVE_SELECTION: {"selection": ids("codex:1", "n2")},
}


@pytest.mark.parametrize("op", sorted(SELECTION_COMMANDS))
def test_brain_and_user_have_the_same_hand_and_runtime_has_none(op):
    before = scene()
    by_user = apply(before, op, USER, **SELECTION_COMMANDS[op])
    by_brain = apply(before, op, BRAIN, **SELECTION_COMMANDS[op])
    assert by_user.outcome is by_brain.outcome is APPLIED
    assert by_user.batch == by_brain.batch
    assert [op.op for op in by_user.patch.ops] == [op.op for op in by_brain.patch.ops]
    refused = apply(before, op, RUNTIME, **SELECTION_COMMANDS[op])
    assert (refused.outcome, refused.reason) == (REJECTED, SceneRefusal.OP_NOT_ALLOWED)
    assert_refused_untouched(before, refused)
    assert refused.batch.to_payload()["matched_ids"] == []


# --------------------------------------------------------------------- forme et bornes


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"op": "translate_selection", "selection": {"ids": ["a"]}, "delta": {"dx": 0, "dy": 0}}, "moves nothing"),
        ({"op": "translate_selection", "selection": {"ids": ["a"]}, "delta": {"dx": 1, "dy": 0}, "pin": False}, "only accepts true"),
        ({"op": "translate_selection", "selection": {"ids": ["a"]}, "delta": {"dx": 1e9, "dy": 0}}, "within"),
        ({"op": "translate_selection", "selection": {"ids": ["a"]}, "delta": {"dx": True, "dy": 1}}, "number"),
        ({"op": "translate_selection", "selection": {"ids": ["a"]}, "delta": {"dx": 1}}, "delta"),
        ({"op": "patch_selection", "selection": {"ids": ["a"]}, "changes": {}}, "at least one"),
        ({"op": "patch_selection", "selection": {"ids": ["a"]}, "changes": {"title": "x"}}, "title"),
        ({"op": "patch_selection", "selection": {"ids": ["a"]}, "changes": {"geometry": {}}}, "geometry"),
        ({"op": "patch_selection", "selection": {"ids": ["a"]}, "changes": {"annotation": "x" * 61}}, "annotation"),
        ({"op": "patch_selection", "selection": {"ids": ["a"]}}, "requires"),
        ({"op": "pin_selection", "selection": {"ids": ["a", "a"]}}, "repeat"),
        ({"op": "pin_selection", "selection": {"ids": ["a"]}, "object_id": "a"}, "does not take"),
        ({"op": "pin_selection", "selection": {"ids": [f"o{i}" for i in range(513)]}}, "at most 512"),
        ({"op": "archive_selection", "selection": {}}, "ids or at least one filter"),
    ],
)
def test_malformed_selection_commands_do_not_decode(payload, message):
    with pytest.raises((TypeError, ValueError), match=message):
        SceneCommand.from_payload({"schema_version": 1, "actor": "user", **payload})


def test_the_bound_is_512_members_in_one_revision():
    objects = [note(f"o{index}", geometry=SceneGeometry(0, 0, 5, 5)) for index in range(MAX_SCENE_OBJECTS)]
    before = run(SceneSnapshot(scene_id="full"), *objects)
    everything = tuple(f"o{index}" for index in range(MAX_SCENE_OBJECTS))
    update = apply(before, SceneOp.TRANSLATE_SELECTION, selection=SceneSelection(ids=everything), delta=SceneDelta(1, 1))
    assert update.outcome is APPLIED and len(update.patch.ops) == MAX_SCENE_OBJECTS
    assert update.snapshot.revision == before.revision + 1
    archived = apply(update.snapshot, SceneOp.ARCHIVE_SELECTION, selection=SceneSelection(kinds=(SceneObjectKind.WINDOW,)))
    assert archived.outcome is APPLIED and len(archived.patch.ops) == MAX_SCENE_OBJECTS
    assert archived.snapshot.objects == ()


def test_selection_commands_round_trip_through_json():
    for op, arguments in SELECTION_COMMANDS.items():
        command = cmd(op, BRAIN, **arguments)
        wire = json.loads(json.dumps(command.to_payload()))
        assert SceneCommand.from_payload(wire) == command
    report = apply(scene(), SceneOp.TRANSLATE_SELECTION, **SELECTION_COMMANDS[SceneOp.TRANSLATE_SELECTION]).batch
    wire = json.loads(json.dumps(report.to_payload()))
    assert set(wire) == {"mode", "matched_ids", "hidden_count", "changed_ids", "unchanged_ids", "skipped", "refused", "delta"}
    assert "best_effort" not in json.dumps(wire)
