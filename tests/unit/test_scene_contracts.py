"""Contrats de la scène constellation (handoff jarvis-constellation-scene-runtime, Slice 01).

Prouve que la matrice d'autorité est appliquée par le réducteur pur, que la
fin d'un travail ne touche ni visibilité ni disposition, que l'épingle de
l'utilisateur protège la géométrie, que la révision est strictement monotone,
que tout est borné et que le fil est strict et versionné.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from jarvis.domain import scene as scene_module
from jarvis.domain.scene import (
    ALLOWED_SCENE_OPS,
    DEFAULT_LAYERS,
    MAX_ID_CHARS,
    MAX_LAYER,
    MAX_ORDER,
    MAX_PATCH_OPS,
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_ITEMS,
    MAX_PAYLOAD_SUMMARY_CHARS,
    MAX_SCENE_COORDINATE,
    MAX_SCENE_EXTENT,
    MAX_SCENE_OBJECTS,
    MAX_SCENE_RELATIONS,
    MAX_TITLE_CHARS,
    SCENE_SCHEMA_VERSION,
    Disposition,
    ExecState,
    PatchOpKind,
    PlacedBy,
    RelationKind,
    Representation,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneConstraints,
    SceneGeometry,
    SceneObject,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePatch,
    ScenePatchOp,
    ScenePayload,
    ScenePayloadItem,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    SceneUpdate,
    UnsupportedSceneSchemaVersion,
    Visibility,
    WorkRef,
    apply_scene_command,
    apply_scene_patch,
)
from jarvis.domain.work_state import WorkStatus

RUNTIME, BRAIN, USER = SceneActor.RUNTIME, SceneActor.BRAIN, SceneActor.USER
APPLIED = SceneCommandOutcome.APPLIED
DUPLICATE = SceneCommandOutcome.DUPLICATE
REJECTED = SceneCommandOutcome.REJECTED_AUTHORITY
INVALID = SceneCommandOutcome.INVALID
GEO = SceneGeometry(10, 20, 40, 40)
GEO_2 = SceneGeometry(300, 20, 40, 40)
TERMINAL_EXEC_STATES = (ExecState.COMPLETED, ExecState.FAILED, ExecState.CANCELLED, ExecState.INTERRUPTED)


def cmd(op: SceneOp, actor: SceneActor, **arguments) -> SceneCommand:
    return SceneCommand(op=op, actor=actor, **arguments)


def upsert(actor: SceneActor, object_id: str, **fields) -> SceneCommand:
    return cmd(SceneOp.UPSERT_OBJECT, actor, object_id=object_id, fields=SceneObjectFields(**fields))


def patch(actor: SceneActor, object_id: str, **fields) -> SceneCommand:
    return cmd(SceneOp.PATCH_OBJECT, actor, object_id=object_id, fields=SceneObjectFields(**fields))


def run(snapshot: SceneSnapshot, *commands: SceneCommand) -> SceneSnapshot:
    """Appliquer des commandes de préparation qui doivent toutes réussir."""

    for command in commands:
        update = apply_scene_command(snapshot, command)
        assert update.outcome is APPLIED, (command, update.outcome, update.reason)
        snapshot = update.snapshot
    return snapshot


def star(object_id: str, *, kind: SceneObjectKind = SceneObjectKind.AGENT, **fields) -> SceneCommand:
    values = {"kind": kind, "category": kind.value, "exec_state": ExecState.RUNNING}
    values.update(fields)
    return upsert(RUNTIME, object_id, **values)


def scene_with_stars() -> SceneSnapshot:
    """Deux étoiles runtime reliées, une étoile épinglée, un artefact du cerveau."""

    return run(
        SceneSnapshot(scene_id="scene-1"),
        star("star-a", work_ref=WorkRef(source="claude", external_id="task-a")),
        star("star-b", kind=SceneObjectKind.JOB, work_ref=WorkRef(source="job", external_id="job-b")),
        star("star-p"),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b")),
        cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-a", geometry=GEO),
        cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-p", geometry=GEO),
        cmd(SceneOp.PIN, USER, object_id="star-p"),
        upsert(BRAIN, "art-1", kind=SceneObjectKind.ARTIFACT, category="research", payload=ScenePayload(title="Recherche")),
    )


def assert_unchanged(before: SceneSnapshot, update: SceneUpdate) -> None:
    assert update.snapshot is before
    assert update.patch is None
    assert update.snapshot.revision == before.revision


# --- vocabulaire fermé ---------------------------------------------------------


def test_closed_enums_hold_exactly_the_contract_values():
    assert {kind.value for kind in SceneObjectKind} == {"agent", "job", "artifact", "attention", "window", "group"}
    assert {value.value for value in Representation} == {"point", "capsule", "window"}
    assert {value.value for value in Visibility} == {"visible", "hidden"}
    assert {value.value for value in Disposition} == {"active", "archived"}
    assert {value.value for value in PlacedBy} == {"runtime", "brain", "user", "resolver"}
    assert {value.value for value in RelationKind} == {"parent_of", "explains", "groups"}
    assert {value.value for value in SceneActor} == {"runtime", "brain", "user"}
    assert {value.value for value in SceneCommandOutcome} == {"applied", "duplicate", "rejected_authority", "invalid"}
    assert {op.value for op in SceneOp} == {
        "upsert_object", "patch_object", "set_geometry", "set_representation", "set_visibility",
        "pin", "unpin", "link", "unlink", "archive", "attach_signal",
    }
    assert set(DEFAULT_LAYERS) == set(SceneObjectKind)


def test_exec_state_mirrors_work_status_plus_unknown():
    assert {state.value for state in ExecState} == {status.value for status in WorkStatus} | {"unknown"}
    for status in WorkStatus:
        assert ExecState(status.value).value == status.value


# --- matrice d'autorité : chaque cellule --------------------------------------

EXPECTED_ALLOWED = {
    RUNTIME: {SceneOp.UPSERT_OBJECT, SceneOp.PATCH_OBJECT, SceneOp.LINK, SceneOp.UNLINK, SceneOp.ATTACH_SIGNAL},
    BRAIN: set(SceneOp) - {SceneOp.ARCHIVE, SceneOp.PIN, SceneOp.UNPIN},
    USER: set(SceneOp),
}


def matrix_command(op: SceneOp, actor: SceneActor) -> SceneCommand:
    """Une commande par opération, recevable par tout acteur qui a l'opération.

    Les cibles sont des nœuds d'exécution non épinglés et aucun champ de
    vérité ou de composition interdit n'est écrit : seule la matrice décide.
    """

    arguments = {
        SceneOp.UPSERT_OBJECT: {"object_id": "star-new", "fields": SceneObjectFields(kind=SceneObjectKind.AGENT, category="agent")},
        SceneOp.PATCH_OBJECT: {"object_id": "star-a", "fields": SceneObjectFields(payload=ScenePayload(title="Nouveau"))},
        SceneOp.SET_GEOMETRY: {"object_id": "star-a", "geometry": GEO_2},
        SceneOp.SET_REPRESENTATION: {"object_id": "star-a", "representation": Representation.CAPSULE},
        SceneOp.SET_VISIBILITY: {"object_id": "star-a", "visibility": Visibility.HIDDEN},
        SceneOp.PIN: {"object_id": "star-a"},
        SceneOp.UNPIN: {"object_id": "star-p"},
        SceneOp.LINK: {"relation": SceneRelation("rel-new", RelationKind.PARENT_OF, "star-b", "star-p")},
        SceneOp.UNLINK: {"relation_id": "rel-ab"},
        SceneOp.ARCHIVE: {"object_id": "star-b"},
        SceneOp.ATTACH_SIGNAL: {"object_id": "sig-1", "fields": SceneObjectFields(category="error"), "target_id": "star-a"},
    }[op]
    return cmd(op, actor, **arguments)


def test_authority_matrix_table_is_the_contract():
    assert {actor: set(ops) for actor, ops in ALLOWED_SCENE_OPS.items()} == EXPECTED_ALLOWED


@pytest.mark.parametrize("actor", list(SceneActor))
@pytest.mark.parametrize("op", list(SceneOp))
def test_every_authority_matrix_cell(actor, op):
    before = scene_with_stars()
    update = apply_scene_command(before, matrix_command(op, actor))
    if op in EXPECTED_ALLOWED[actor]:
        assert update.outcome is APPLIED, update.reason
        assert update.snapshot.revision == before.revision + 1
    else:
        assert update.outcome is REJECTED
        assert update.reason is SceneRefusal.OP_NOT_ALLOWED
        assert_unchanged(before, update)


# --- archivage : utilisateur seulement ----------------------------------------


@pytest.mark.parametrize("actor", [BRAIN, RUNTIME])
@pytest.mark.parametrize("object_id", ["star-a", "art-1", "absent"])
def test_archive_is_rejected_for_brain_and_runtime_whatever_the_target(actor, object_id):
    before = scene_with_stars()
    update = apply_scene_command(before, cmd(SceneOp.ARCHIVE, actor, object_id=object_id))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.OP_NOT_ALLOWED)
    assert_unchanged(before, update)
    assert all(item.disposition is Disposition.ACTIVE for item in update.snapshot.objects)


def test_user_archive_keeps_the_object_and_drops_its_relations():
    before = scene_with_stars()
    update = apply_scene_command(before, cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    assert update.outcome is APPLIED
    archived = update.snapshot.get_object("star-a")
    assert archived.disposition is Disposition.ARCHIVED
    assert archived.visibility is Visibility.VISIBLE  # caché ≠ archivé
    assert archived not in update.snapshot.active_objects
    assert update.snapshot.get_relation("rel-ab") is None
    assert [op.op for op in update.patch.ops] == [PatchOpKind.PUT_OBJECT, PatchOpKind.DELETE_RELATION]

    again = apply_scene_command(update.snapshot, cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    assert again.outcome is DUPLICATE
    for command in (
        patch(RUNTIME, "star-a", exec_state=ExecState.COMPLETED),
        cmd(SceneOp.SET_VISIBILITY, USER, object_id="star-a", visibility=Visibility.HIDDEN),
        cmd(SceneOp.LINK, USER, relation=SceneRelation("rel-x", RelationKind.GROUPS, "star-b", "star-a")),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-9", fields=SceneObjectFields(category="error"), target_id="star-a"),
    ):
        refused = apply_scene_command(update.snapshot, command)
        assert (refused.outcome, refused.reason) == (INVALID, SceneRefusal.OBJECT_ARCHIVED), command.op


def test_archive_of_an_unknown_object_is_invalid_for_the_user():
    update = apply_scene_command(scene_with_stars(), cmd(SceneOp.ARCHIVE, USER, object_id="absent"))
    assert (update.outcome, update.reason) == (INVALID, SceneRefusal.UNKNOWN_OBJECT)


# --- fin d'exécution ≠ disparition --------------------------------------------


@pytest.mark.parametrize("state", TERMINAL_EXEC_STATES)
@pytest.mark.parametrize("visibility", list(Visibility))
def test_completion_never_changes_visibility_disposition_or_composition(state, visibility):
    before = run(
        scene_with_stars(),
        cmd(SceneOp.SET_VISIBILITY, BRAIN, object_id="star-a", visibility=visibility)
        if visibility is Visibility.HIDDEN
        else cmd(SceneOp.SET_REPRESENTATION, BRAIN, object_id="star-a", representation=Representation.CAPSULE),
    )
    known = before.get_object("star-a")
    for command in (
        upsert(RUNTIME, "star-a", kind=SceneObjectKind.AGENT, category="agent", exec_state=state),
        patch(RUNTIME, "star-a", exec_state=state, payload=ScenePayload(title="Fini", summary="Résumé final.")),
    ):
        update = apply_scene_command(before, command)
        assert update.outcome in (APPLIED, DUPLICATE)
        after = update.snapshot.get_object("star-a")
        assert after.exec_state is state
        assert after.visibility is known.visibility
        assert after.disposition is Disposition.ACTIVE
        assert (after.geometry, after.representation, after.layer, after.order, after.constraints) == (
            known.geometry, known.representation, known.layer, known.order, known.constraints,
        )
        before = update.snapshot


def test_runtime_cannot_hide_or_archive_even_alongside_a_completion():
    before = scene_with_stars()
    hidden = apply_scene_command(before, patch(RUNTIME, "star-a", exec_state=ExecState.COMPLETED, visibility=Visibility.HIDDEN))
    assert (hidden.outcome, hidden.reason) == (REJECTED, SceneRefusal.RUNTIME_COMPOSITION)
    assert_unchanged(before, hidden)


# --- épingle de l'utilisateur -------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-p", geometry=GEO_2),
        cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-p", geometry=SceneGeometry(10, 20, 80, 40)),
        patch(BRAIN, "star-p", geometry=GEO_2),
        upsert(BRAIN, "star-p", kind=SceneObjectKind.AGENT, category="agent", geometry=GEO_2),
        cmd(SceneOp.SET_REPRESENTATION, BRAIN, object_id="star-p", representation=Representation.WINDOW, geometry=SceneGeometry(10, 20, 400, 300)),
        cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-p", geometry=GEO_2, placed_by=PlacedBy.RESOLVER),
        cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-p", geometry=GEO_2, placed_by=PlacedBy.RESOLVER),
    ],
    ids=["brain-move", "brain-resize", "brain-patch", "brain-upsert", "brain-representation-resize", "user-resolver", "brain-resolver"],
)
def test_brain_and_resolver_cannot_move_or_resize_a_user_pinned_object(command):
    before = scene_with_stars()
    update = apply_scene_command(before, command)
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.PINNED_BY_USER)
    assert_unchanged(before, update)


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (cmd(SceneOp.SET_GEOMETRY, RUNTIME, object_id="star-p", geometry=GEO_2), SceneRefusal.OP_NOT_ALLOWED),
        (patch(RUNTIME, "star-p", geometry=GEO_2), SceneRefusal.RUNTIME_COMPOSITION),
        (upsert(RUNTIME, "star-p", kind=SceneObjectKind.AGENT, category="agent", geometry=GEO_2), SceneRefusal.RUNTIME_COMPOSITION),
        (cmd(SceneOp.UNPIN, RUNTIME, object_id="star-p"), SceneRefusal.OP_NOT_ALLOWED),
        (cmd(SceneOp.UNPIN, BRAIN, object_id="star-p"), SceneRefusal.OP_NOT_ALLOWED),
    ],
)
def test_runtime_cannot_move_a_pinned_object_and_nobody_but_the_user_unpins(command, reason):
    before = scene_with_stars()
    update = apply_scene_command(before, command)
    assert (update.outcome, update.reason) == (REJECTED, reason)
    assert_unchanged(before, update)


def test_pinned_object_still_accepts_non_geometric_changes_and_echoed_geometry():
    before = scene_with_stars()
    echoed = apply_scene_command(before, cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-p", geometry=GEO))
    assert echoed.outcome is DUPLICATE
    reshaped = apply_scene_command(before, cmd(SceneOp.SET_REPRESENTATION, BRAIN, object_id="star-p", representation=Representation.CAPSULE))
    assert reshaped.outcome is APPLIED
    assert reshaped.snapshot.get_object("star-p").geometry == GEO
    runtime = apply_scene_command(before, patch(RUNTIME, "star-p", exec_state=ExecState.BLOCKED))
    assert runtime.outcome is APPLIED


def test_user_moves_a_pinned_object_and_it_stays_pinned():
    update = apply_scene_command(scene_with_stars(), cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-p", geometry=GEO_2))
    moved = update.snapshot.get_object("star-p")
    assert update.outcome is APPLIED
    assert moved.geometry == GEO_2
    assert moved.constraints == SceneConstraints(placed_by=PlacedBy.USER, pinned_by_user=True)
    unpinned = apply_scene_command(update.snapshot, cmd(SceneOp.UNPIN, USER, object_id="star-p"))
    assert unpinned.snapshot.get_object("star-p").constraints.pinned_by_user is False
    assert apply_scene_command(unpinned.snapshot, cmd(SceneOp.UNPIN, USER, object_id="star-p")).outcome is DUPLICATE


def test_pinning_needs_a_placed_object():
    update = apply_scene_command(scene_with_stars(), cmd(SceneOp.PIN, USER, object_id="star-b"))
    assert (update.outcome, update.reason) == (INVALID, SceneRefusal.UNPLACED)
    with pytest.raises(ValueError):
        SceneObject("x", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.USER, pinned_by_user=True))


# --- placement : auteur et AutoResolver ----------------------------------------


def test_placement_author_is_recorded_and_resolver_only_fills_the_gaps():
    before = scene_with_stars()
    assert before.get_object("star-b").geometry is None
    assert before.get_object("star-b").constraints.placed_by is PlacedBy.RUNTIME

    resolved = apply_scene_command(before, cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-b", geometry=GEO_2, placed_by=PlacedBy.RESOLVER))
    assert resolved.outcome is APPLIED
    assert resolved.snapshot.get_object("star-b").constraints.placed_by is PlacedBy.RESOLVER

    nudged = apply_scene_command(
        resolved.snapshot, cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-b", geometry=GEO, placed_by=PlacedBy.RESOLVER)
    )
    assert nudged.outcome is APPLIED

    explicit = apply_scene_command(nudged.snapshot, cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-b", geometry=GEO_2))
    assert explicit.snapshot.get_object("star-b").constraints.placed_by is PlacedBy.BRAIN
    overridden = apply_scene_command(
        explicit.snapshot, cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-b", geometry=GEO, placed_by=PlacedBy.RESOLVER)
    )
    assert (overridden.outcome, overridden.reason) == (REJECTED, SceneRefusal.EXPLICIT_PLACEMENT)


# --- représentation et identité -----------------------------------------------


@pytest.mark.parametrize("representation", [Representation.CAPSULE, Representation.WINDOW])
def test_representation_change_keeps_identity_links_and_content(representation):
    before = run(scene_with_stars(), cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-1", fields=SceneObjectFields(category="error"), target_id="star-a"))
    known = before.get_object("star-a")
    update = apply_scene_command(
        before,
        cmd(SceneOp.SET_REPRESENTATION, BRAIN, object_id="star-a", representation=representation, geometry=SceneGeometry(10, 20, 360, 240)),
    )
    assert update.outcome is APPLIED
    (op,) = update.patch.ops
    assert op.op is PatchOpKind.PUT_OBJECT and op.object.object_id == "star-a"
    after = update.snapshot.get_object("star-a")
    assert after.representation is representation
    assert dataclasses.replace(after, representation=known.representation, geometry=known.geometry, constraints=known.constraints) == known
    assert update.snapshot.relations == before.relations
    assert [item.object_id for item in update.snapshot.objects] == [item.object_id for item in before.objects]


# --- runtime : nœuds d'exécution seulement ------------------------------------


@pytest.mark.parametrize("kind", [SceneObjectKind.ARTIFACT, SceneObjectKind.WINDOW, SceneObjectKind.GROUP])
def test_runtime_cannot_create_non_execution_objects(kind):
    before = scene_with_stars()
    update = apply_scene_command(before, upsert(RUNTIME, "x-1", kind=kind, category="auto"))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_KIND)
    assert_unchanged(before, update)


@pytest.mark.parametrize(
    "command",
    [
        patch(RUNTIME, "art-1", payload=ScenePayload(title="Réécrit")),
        upsert(RUNTIME, "art-1", kind=SceneObjectKind.ARTIFACT, category="research"),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-1", fields=SceneObjectFields(category="error"), target_id="art-1"),
    ],
)
def test_runtime_cannot_touch_artifacts(command):
    before = scene_with_stars()
    update = apply_scene_command(before, command)
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_KIND)
    assert_unchanged(before, update)


@pytest.mark.parametrize(
    "command",
    [
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-x", RelationKind.EXPLAINS, "star-b", "star-a")),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-x", RelationKind.GROUPS, "star-b", "star-a")),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-x", RelationKind.PARENT_OF, "star-a", "art-1")),
    ],
)
def test_runtime_links_only_parent_of_between_execution_nodes(command):
    before = scene_with_stars()
    update = apply_scene_command(before, command)
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_RELATION)
    assert_unchanged(before, update)


def test_runtime_cannot_unlink_a_brain_relation():
    before = run(scene_with_stars(), cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-exp", RelationKind.EXPLAINS, "art-1", "star-a")))
    update = apply_scene_command(before, cmd(SceneOp.UNLINK, RUNTIME, relation_id="rel-exp"))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_RELATION)
    assert apply_scene_command(before, cmd(SceneOp.UNLINK, BRAIN, relation_id="rel-exp")).outcome is APPLIED


@pytest.mark.parametrize("field_name", ["representation", "layer", "order", "visibility", "geometry"])
def test_runtime_never_writes_composition_fields(field_name):
    value = {
        "representation": Representation.WINDOW,
        "layer": 999,
        "order": 7,
        "visibility": Visibility.HIDDEN,
        "geometry": GEO_2,
    }[field_name]
    before = scene_with_stars()
    for command in (patch(RUNTIME, "star-b", **{field_name: value}), star("star-new", **{field_name: value})):
        update = apply_scene_command(before, command)
        assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_COMPOSITION)


def test_runtime_creates_stars_and_signals_with_kind_defaults():
    before = scene_with_stars()
    assert before.get_object("star-a").layer == DEFAULT_LAYERS[SceneObjectKind.AGENT]
    update = apply_scene_command(
        before,
        cmd(
            SceneOp.ATTACH_SIGNAL,
            RUNTIME,
            object_id="sig-1",
            fields=SceneObjectFields(category="error", exec_state=ExecState.FAILED, payload=ScenePayload(title="provider_unavailable")),
            target_id="star-b",
        ),
    )
    assert update.outcome is APPLIED
    signal = update.snapshot.get_object("sig-1")
    assert (signal.kind, signal.layer, signal.constraints.placed_by) == (SceneObjectKind.ATTENTION, 300, PlacedBy.RUNTIME)
    assert update.snapshot.get_relation("sig-1") == SceneRelation("sig-1", RelationKind.EXPLAINS, "sig-1", "star-b")
    assert [op.op for op in update.patch.ops] == [PatchOpKind.PUT_OBJECT, PatchOpKind.PUT_RELATION]

    refreshed = apply_scene_command(
        update.snapshot,
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-1", fields=SceneObjectFields(payload=ScenePayload(title="timeout")), target_id="star-b"),
    )
    assert refreshed.outcome is APPLIED
    assert [op.op for op in refreshed.patch.ops] == [PatchOpKind.PUT_OBJECT]
    moved = apply_scene_command(
        update.snapshot,
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-1", fields=SceneObjectFields(category="error"), target_id="star-a"),
    )
    assert (moved.outcome, moved.reason) == (INVALID, SceneRefusal.RELATION_CONFLICT)


# --- vérité d'exécution -------------------------------------------------------


@pytest.mark.parametrize("actor", [BRAIN, USER])
@pytest.mark.parametrize(
    "fields",
    [{"exec_state": ExecState.COMPLETED}, {"work_ref": WorkRef(source="claude", external_id="other")}],
)
def test_only_runtime_writes_execution_truth(actor, fields):
    before = scene_with_stars()
    update = apply_scene_command(before, patch(actor, "star-a", **fields))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.EXECUTION_TRUTH)
    created = apply_scene_command(before, upsert(actor, "win-1", kind=SceneObjectKind.WINDOW, category="note", **fields))
    assert (created.outcome, created.reason) == (REJECTED, SceneRefusal.EXECUTION_TRUTH)
    echoed = apply_scene_command(before, patch(actor, "star-a", exec_state=ExecState.RUNNING))
    assert echoed.outcome is DUPLICATE


def test_brain_may_create_every_kind_and_compose_runtime_stars():
    before = scene_with_stars()
    snapshot = run(
        before,
        *(upsert(BRAIN, f"obj-{kind.value}", kind=kind, category="brain") for kind in SceneObjectKind),
        patch(BRAIN, "star-a", category="research", layer=150, order=3, payload=ScenePayload(title="Explorer")),
        cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-grp", RelationKind.GROUPS, "obj-group", "star-a")),
    )
    assert snapshot.revision == before.revision + len(SceneObjectKind) + 2
    assert snapshot.get_object("star-a").exec_state is ExecState.RUNNING


# --- commandes inapplicables --------------------------------------------------


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (patch(BRAIN, "absent", category="x"), SceneRefusal.UNKNOWN_OBJECT),
        (cmd(SceneOp.SET_VISIBILITY, USER, object_id="absent", visibility=Visibility.HIDDEN), SceneRefusal.UNKNOWN_OBJECT),
        (upsert(BRAIN, "new-1", category="x"), SceneRefusal.INCOMPLETE_OBJECT),
        (upsert(BRAIN, "new-1", kind=SceneObjectKind.WINDOW), SceneRefusal.INCOMPLETE_OBJECT),
        (upsert(BRAIN, "star-a", kind=SceneObjectKind.JOB, category="job"), SceneRefusal.KIND_IMMUTABLE),
        (cmd(SceneOp.ATTACH_SIGNAL, BRAIN, object_id="art-1", fields=SceneObjectFields(category="x"), target_id="star-a"), SceneRefusal.KIND_IMMUTABLE),
        (cmd(SceneOp.ATTACH_SIGNAL, BRAIN, object_id="sig-2", fields=SceneObjectFields(category="x"), target_id="absent"), SceneRefusal.UNKNOWN_OBJECT),
        (cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-x", RelationKind.EXPLAINS, "art-1", "absent")), SceneRefusal.UNKNOWN_OBJECT),
        (cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-ab", RelationKind.EXPLAINS, "art-1", "star-a")), SceneRefusal.RELATION_CONFLICT),
    ],
)
def test_well_formed_but_inapplicable_commands_are_invalid(command, reason):
    before = scene_with_stars()
    update = apply_scene_command(before, command)
    assert (update.outcome, update.reason) == (INVALID, reason)
    assert_unchanged(before, update)


def test_relation_layer_may_change_and_unlink_is_idempotent():
    before = scene_with_stars()
    relayered = apply_scene_command(before, cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b", layer=60)))
    assert relayered.outcome is APPLIED
    unlinked = apply_scene_command(relayered.snapshot, cmd(SceneOp.UNLINK, USER, relation_id="rel-ab"))
    assert unlinked.outcome is APPLIED
    assert apply_scene_command(unlinked.snapshot, cmd(SceneOp.UNLINK, USER, relation_id="rel-ab")).outcome is DUPLICATE


# --- révision -----------------------------------------------------------------


def test_revision_is_strictly_monotonic_and_patches_are_exact_deltas():
    snapshot = SceneSnapshot(scene_id="scene-1")
    commands = [
        star("star-a"),
        star("star-a"),  # doublon
        cmd(SceneOp.ARCHIVE, BRAIN, object_id="star-a"),  # refus d'autorité
        patch(BRAIN, "absent", category="x"),  # invalide
        star("star-b", kind=SceneObjectKind.JOB),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b")),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b")),  # doublon
        cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-a", geometry=GEO),
        cmd(SceneOp.PIN, USER, object_id="star-a"),
        cmd(SceneOp.PIN, USER, object_id="star-a"),  # doublon
        cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-a", geometry=GEO_2),  # épinglé
        cmd(SceneOp.ARCHIVE, USER, object_id="star-b"),
    ]
    outcomes = []
    for command in commands:
        update = apply_scene_command(snapshot, command)
        outcomes.append(update.outcome)
        if update.changed:
            assert update.snapshot.revision == snapshot.revision + 1
            assert update.patch.revision == update.snapshot.revision
            assert apply_scene_patch(snapshot, update.patch) == update.snapshot
            wire = ScenePatch.from_payload(json.loads(json.dumps(update.patch.to_payload())))
            assert apply_scene_patch(snapshot, wire) == update.snapshot
        else:
            assert_unchanged(snapshot, update)
        snapshot = update.snapshot
    assert outcomes == [
        APPLIED, DUPLICATE, REJECTED, INVALID, APPLIED, APPLIED, DUPLICATE, APPLIED, APPLIED, DUPLICATE, REJECTED, APPLIED,
    ]
    assert snapshot.revision == outcomes.count(APPLIED)


def test_patch_refuses_gaps_and_unknown_deletions():
    before = scene_with_stars()
    update = apply_scene_command(before, cmd(SceneOp.SET_VISIBILITY, BRAIN, object_id="star-a", visibility=Visibility.HIDDEN))
    with pytest.raises(ValueError):
        apply_scene_patch(update.snapshot, update.patch)  # rejoué : n'est plus la révision suivante
    with pytest.raises(ValueError):
        apply_scene_patch(before, dataclasses.replace(update.patch, revision=before.revision + 2))
    ghost = ScenePatch(revision=before.revision + 1, ops=(ScenePatchOp(PatchOpKind.DELETE_RELATION, relation_id="ghost"),))
    with pytest.raises(ValueError):
        apply_scene_patch(before, ghost)


def test_update_result_is_consistent():
    snapshot = SceneSnapshot(scene_id="scene-1")
    with pytest.raises(ValueError):
        SceneUpdate(APPLIED, snapshot)
    with pytest.raises(ValueError):
        SceneUpdate(REJECTED, snapshot)
    with pytest.raises(ValueError):
        SceneUpdate(DUPLICATE, snapshot, reason=SceneRefusal.UNPLACED)


# --- bornes et types ----------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"x": float("nan")}, ValueError),
        ({"y": float("inf")}, ValueError),
        ({"x": MAX_SCENE_COORDINATE + 1}, ValueError),
        ({"w": 0}, ValueError),
        ({"h": -5}, ValueError),
        ({"w": MAX_SCENE_EXTENT + 1}, ValueError),
        ({"x": "10"}, TypeError),
        ({"h": True}, TypeError),
    ],
)
def test_geometry_bounds(values, error):
    arguments = {"x": 0, "y": 0, "w": 10, "h": 10}
    arguments.update(values)
    with pytest.raises(error):
        SceneGeometry(**arguments)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"object_id": ""}, ValueError),
        ({"object_id": " a"}, ValueError),
        ({"object_id": "x" * (MAX_ID_CHARS + 1)}, ValueError),
        ({"category": ""}, ValueError),
        ({"category": "files/diff"}, ValueError),
        ({"category": "x" * 33}, ValueError),
        ({"layer": MAX_LAYER + 1}, ValueError),
        ({"layer": -1}, ValueError),
        ({"layer": True}, TypeError),
        ({"order": MAX_ORDER + 1}, ValueError),
        ({"order": 1.5}, TypeError),
        ({"kind": "agent"}, TypeError),
        ({"visibility": "hidden"}, TypeError),
        ({"payload": {"title": "x"}}, TypeError),
    ],
)
def test_object_bounds_and_types(overrides, error):
    values = {"object_id": "obj-1", "kind": SceneObjectKind.WINDOW, "category": "note", "constraints": SceneConstraints(PlacedBy.BRAIN)}
    values.update(overrides)
    with pytest.raises(error):
        SceneObject(**values)


def test_layer_bands_are_conventions_not_a_closed_list():
    for layer in (0, 50, 100, 120, 137, 150, 220, 300, MAX_LAYER):
        assert SceneObject("o", SceneObjectKind.WINDOW, "note", SceneConstraints(PlacedBy.BRAIN), layer=layer).layer == layer


@pytest.mark.parametrize(
    "build",
    [
        lambda: ScenePayload(title="x" * (MAX_TITLE_CHARS + 1)),
        lambda: ScenePayload(title="deux\nlignes"),
        lambda: ScenePayload(summary="x" * (MAX_PAYLOAD_SUMMARY_CHARS + 1)),
        lambda: ScenePayload(items=tuple(ScenePayloadItem(label=f"f{index}") for index in range(MAX_PAYLOAD_ITEMS + 1))),
        lambda: ScenePayload(items=tuple(ScenePayloadItem(label="x" * 160, ref="r" * 256, url="https://" + "u" * 2000) for _ in range(8))),
        lambda: ScenePayloadItem(label=""),
        lambda: ScenePayloadItem(label="lien", url="javascript:alert(1)"),
        lambda: ScenePayloadItem(label="lien", url="file:///C:/secret"),
    ],
)
def test_payload_bounds(build):
    with pytest.raises(ValueError, match=r"exceeds|at most|single printable line|required|http"):
        build()


def test_payload_byte_bound_is_explicit_and_counts_utf8():
    items = tuple(ScenePayloadItem(label="é" * 80, ref="r" * 256, url="https://example.com/" + "u" * 1000) for _ in range(12))
    with pytest.raises(ValueError, match=str(MAX_PAYLOAD_BYTES)):
        ScenePayload(summary="ligne 1\nligne 2", items=items)
    assert ScenePayload(summary="ligne 1\nligne 2", items=items[:6]).summary == "ligne 1\nligne 2"


def test_snapshot_bounds_uniqueness_and_relation_endpoints():
    agent = SceneObject("a", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.RUNTIME))
    other = dataclasses.replace(agent, object_id="b")
    link = SceneRelation("r", RelationKind.PARENT_OF, "a", "b")
    with pytest.raises(ValueError):
        SceneSnapshot("s", objects=(agent, agent))
    with pytest.raises(ValueError):
        SceneSnapshot("s", objects=(agent,), relations=(link,))
    with pytest.raises(ValueError):
        SceneSnapshot("s", objects=(agent, dataclasses.replace(other, disposition=Disposition.ARCHIVED)), relations=(link,))
    with pytest.raises(ValueError):
        SceneSnapshot("s", objects=(agent, other), relations=(link, link))
    with pytest.raises(ValueError):
        SceneSnapshot("s", revision=-1)
    with pytest.raises(TypeError):
        SceneSnapshot("s", objects=[agent])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SceneRelation("r", RelationKind.PARENT_OF, "a", "a")
    many = tuple(dataclasses.replace(agent, object_id=f"a{index}") for index in range(MAX_SCENE_OBJECTS + 1))
    with pytest.raises(ValueError):
        SceneSnapshot("s", objects=many)


def test_reducer_refuses_to_grow_past_the_bounds():
    agent = SceneObject("a0", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.RUNTIME))
    objects = tuple(dataclasses.replace(agent, object_id=f"a{index}") for index in range(MAX_SCENE_OBJECTS))
    full = SceneSnapshot("s", revision=5, objects=objects)
    update = apply_scene_command(full, star("one-more"))
    assert (update.outcome, update.reason) == (INVALID, SceneRefusal.SCENE_FULL)
    assert_unchanged(full, update)
    assert apply_scene_command(full, patch(RUNTIME, "a0", exec_state=ExecState.RUNNING)).outcome is APPLIED

    relations = tuple(
        SceneRelation(f"r{index}", RelationKind.GROUPS, "a0", f"a{1 + index % (MAX_SCENE_OBJECTS - 2)}")
        for index in range(MAX_SCENE_RELATIONS)
    )
    linked = SceneSnapshot("s", revision=5, objects=objects[:MAX_SCENE_OBJECTS - 1], relations=relations)
    extra = apply_scene_command(linked, cmd(SceneOp.LINK, USER, relation=SceneRelation("r-extra", RelationKind.GROUPS, "a1", "a2")))
    assert (extra.outcome, extra.reason) == (INVALID, SceneRefusal.RELATION_LIMIT)
    signal = apply_scene_command(linked, cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig", fields=SceneObjectFields(category="error"), target_id="a1"))
    assert (signal.outcome, signal.reason) == (INVALID, SceneRefusal.RELATION_LIMIT)
    archived = apply_scene_command(linked, cmd(SceneOp.ARCHIVE, USER, object_id="a0"))
    assert archived.outcome is APPLIED
    assert len(archived.patch.ops) == 1 + MAX_SCENE_RELATIONS == MAX_PATCH_OPS
    assert archived.snapshot.relations == ()


# --- forme des commandes ------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: SceneCommand(SceneOp.UPSERT_OBJECT, BRAIN, object_id="a"),
        lambda: SceneCommand(SceneOp.PIN, USER),
        lambda: SceneCommand(SceneOp.PIN, USER, object_id="a", geometry=GEO),
        lambda: SceneCommand(SceneOp.SET_VISIBILITY, USER, object_id="a", visibility=Visibility.HIDDEN, target_id="b"),
        lambda: SceneCommand(SceneOp.SET_GEOMETRY, BRAIN, object_id="a", geometry=GEO, placed_by=PlacedBy.BRAIN),
        lambda: SceneCommand(SceneOp.SET_GEOMETRY, USER, object_id="a", geometry=GEO, placed_by=PlacedBy.USER),
        lambda: SceneCommand(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="s", fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="x"), target_id="a"),
        lambda: SceneCommand(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="a", fields=SceneObjectFields(category="x"), target_id="a"),
        lambda: SceneCommand(SceneOp.UNLINK, USER, relation_id=""),
    ],
)
def test_malformed_commands_do_not_build(build):
    with pytest.raises(ValueError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: SceneCommand("archive", USER, object_id="a"),  # type: ignore[arg-type]
        lambda: SceneCommand(SceneOp.ARCHIVE, "user", object_id="a"),  # type: ignore[arg-type]
        lambda: SceneCommand(SceneOp.PATCH_OBJECT, BRAIN, object_id="a", fields={"layer": 3}),  # type: ignore[arg-type]
        lambda: SceneObjectFields(layer="3"),  # type: ignore[arg-type]
    ],
)
def test_commands_reject_wrong_types(build):
    with pytest.raises(TypeError):
        build()


# --- fil ----------------------------------------------------------------------


def rich_snapshot() -> SceneSnapshot:
    return run(
        scene_with_stars(),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-1", fields=SceneObjectFields(category="error", exec_state=ExecState.FAILED), target_id="star-b"),
        patch(RUNTIME, "star-a", work_ref=WorkRef(source="claude", external_id="task-a", work_id="work-1")),
        patch(
            BRAIN,
            "art-1",
            representation=Representation.WINDOW,
            geometry=SceneGeometry(-120.5, 40, 480, 320),
            layer=150,
            order=-2,
            payload=ScenePayload(
                title="Recherche",
                summary="Trois sources.\nUne contradiction.",
                items=(ScenePayloadItem(label="Doc", ref="docs/a.md"), ScenePayloadItem(label="Page", url="https://example.com/a")),
            ),
        ),
        cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-exp", RelationKind.EXPLAINS, "art-1", "star-a", layer=60)),
        upsert(USER, "grp-1", kind=SceneObjectKind.GROUP, category="castor", visibility=Visibility.HIDDEN),
        upsert(BRAIN, "old", kind=SceneObjectKind.WINDOW, category="note"),
        cmd(SceneOp.ARCHIVE, USER, object_id="old"),
    )


def test_snapshot_round_trips_through_json_with_schema_version():
    snapshot = rich_snapshot()
    wire = json.loads(json.dumps(snapshot.to_payload()))
    assert wire["schema_version"] == SCENE_SCHEMA_VERSION == 1
    assert SceneSnapshot.from_payload(wire) == snapshot


@pytest.mark.parametrize("op", list(SceneOp))
def test_every_command_round_trips_through_json(op):
    command = matrix_command(op, USER)
    wire = json.loads(json.dumps(command.to_payload()))
    assert wire["schema_version"] == 1 and wire["op"] == op.value and wire["actor"] == "user"
    assert SceneCommand.from_payload(wire) == command
    rich = cmd(
        SceneOp.UPSERT_OBJECT,
        BRAIN,
        object_id="w",
        fields=SceneObjectFields(
            kind=SceneObjectKind.WINDOW, category="note", representation=Representation.WINDOW, geometry=GEO,
            layer=220, order=1, visibility=Visibility.VISIBLE, payload=ScenePayload(title="Note"),
        ),
    )
    assert SceneCommand.from_payload(json.loads(json.dumps(rich.to_payload()))) == rich
    resolver = cmd(SceneOp.SET_GEOMETRY, USER, object_id="a", geometry=GEO, placed_by=PlacedBy.RESOLVER)
    assert SceneCommand.from_payload(json.loads(json.dumps(resolver.to_payload()))) == resolver


@pytest.mark.parametrize("version", [2, 0, None, "1", 1.0, True])
@pytest.mark.parametrize("decode", [SceneSnapshot.from_payload, SceneCommand.from_payload, ScenePatch.from_payload])
def test_decoding_refuses_unknown_or_newer_schema_versions(version, decode):
    sources = {
        SceneSnapshot.from_payload: lambda: SceneSnapshot(scene_id="s").to_payload(),
        SceneCommand.from_payload: lambda: matrix_command(SceneOp.PIN, USER).to_payload(),
        ScenePatch.from_payload: lambda: apply_scene_command(scene_with_stars(), matrix_command(SceneOp.PIN, USER)).patch.to_payload(),
    }
    payload = sources[decode]()
    if version is None:
        del payload["schema_version"]
    else:
        payload["schema_version"] = version
    with pytest.raises(UnsupportedSceneSchemaVersion):
        decode(payload)


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda p: p.update(extra=1), ValueError),
        (lambda p: p["objects"][0].update(raw={"prompt": "x"}), ValueError),
        (lambda p: p["objects"][0].pop("layer"), ValueError),
        (lambda p: p["objects"][0].update(kind="star"), ValueError),
        (lambda p: p["objects"][0].update(exec_state="exploded"), ValueError),
        (lambda p: p["objects"][0].update(layer="100"), TypeError),
        (lambda p: p["objects"][0]["constraints"].update(pinned_by_user="yes"), TypeError),
        (lambda p: p["objects"][0].update(geometry={"x": 1, "y": 2, "w": 3}), ValueError),
        (lambda p: p["relations"][0].update(kind="owns"), ValueError),
        (lambda p: p.update(objects={}), TypeError),
        (lambda p: p.update(objects=[{}] * (MAX_SCENE_OBJECTS + 1)), ValueError),
        (lambda p: p.update(relations=[{}] * (MAX_SCENE_RELATIONS + 1)), ValueError),
        (lambda p: p.update(revision=True), TypeError),
    ],
)
def test_snapshot_decoding_is_strict(mutate, error):
    payload = json.loads(json.dumps(rich_snapshot().to_payload()))
    mutate(payload)
    with pytest.raises(error):
        SceneSnapshot.from_payload(payload)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"schema_version": 1, "op": "archive", "actor": "user", "object_id": "a", "prompt": "x"}, ValueError),
        ({"schema_version": 1, "op": "destroy", "actor": "user", "object_id": "a"}, ValueError),
        ({"schema_version": 1, "op": "archive", "actor": "admin", "object_id": "a"}, ValueError),
        ({"schema_version": 1, "op": "archive", "object_id": "a"}, ValueError),
        ({"schema_version": 1, "op": "patch_object", "actor": "brain", "object_id": "a", "fields": {"disposition": "archived"}}, ValueError),
        ({"schema_version": 1, "op": "patch_object", "actor": "brain", "object_id": "a", "fields": {"constraints": {}}}, ValueError),
        ({"schema_version": 1, "op": "set_geometry", "actor": "user", "object_id": "a", "geometry": {"x": 1, "y": 2, "w": 3, "h": 4}, "placed_by": "brain"}, ValueError),
        ({"schema_version": 1, "op": "pin", "actor": "user", "object_id": 7}, TypeError),
        ({"schema_version": 1, "op": "pin", "actor": ["user"], "object_id": "a"}, TypeError),
        ([], TypeError),
    ],
)
def test_command_decoding_is_strict(payload, error):
    with pytest.raises(error):
        SceneCommand.from_payload(payload)


def test_patch_decoding_bounds_ops_before_decoding():
    payload = {"schema_version": 1, "revision": 1, "ops": [{}] * (MAX_PATCH_OPS + 1)}
    with pytest.raises(ValueError):
        ScenePatch.from_payload(payload)
    with pytest.raises(ValueError):
        ScenePatch.from_payload({"schema_version": 1, "revision": 1, "ops": []})
    with pytest.raises(ValueError):
        ScenePatchOp(PatchOpKind.PUT_OBJECT, relation_id="r")


# --- pureté et immuabilité ----------------------------------------------------


def test_scene_module_is_pure_domain():
    """Aucune E/S, aucune boucle, aucune couche d'implémentation (Slice 01)."""

    tree = ast.parse(Path(scene_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "print", "input", "exec", "eval"}, node.func.id
    assert imported <= {"__future__", "dataclasses", "enum", "json", "math", "re", "typing", "jarvis.domain.work_state"}


def test_reducer_never_mutates_its_input():
    before = rich_snapshot()
    wire = json.dumps(before.to_payload())
    for op in SceneOp:
        for actor in SceneActor:
            apply_scene_command(before, matrix_command(op, actor))
    assert json.dumps(before.to_payload()) == wire


def test_contracts_are_immutable():
    snapshot = scene_with_stars()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.revision = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.objects[0].disposition = Disposition.ARCHIVED  # type: ignore[misc]
