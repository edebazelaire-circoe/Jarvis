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
    DEFAULT_RELATION_LAYER,
    DEFAULT_LAYERS,
    MAX_ARCHIVED_IDS,
    MAX_ID_CHARS,
    MAX_LAYER,
    MAX_ORDER,
    MAX_PATCH_OPS,
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_ITEMS,
    MAX_PAYLOAD_SUMMARY_CHARS,
    MAX_REVISION,
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
    is_live_signal,
    is_runtime_owned_relation,
    is_runtime_reserved_id,
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
        "pin", "unpin", "link", "unlink", "archive", "archive_many", "attach_signal",
    }
    assert {op.value for op in PatchOpKind} == {"put_object", "archive_object", "put_relation", "delete_relation"}
    assert set(DEFAULT_LAYERS) == set(SceneObjectKind)


def test_exec_state_mirrors_work_status_plus_unknown():
    assert {state.value for state in ExecState} == {status.value for status in WorkStatus} | {"unknown"}
    for status in WorkStatus:
        assert ExecState(status.value).value == status.value


# --- matrice d'autorité : chaque cellule --------------------------------------

EXPECTED_ALLOWED = {
    RUNTIME: {SceneOp.UPSERT_OBJECT, SceneOp.PATCH_OBJECT, SceneOp.LINK, SceneOp.UNLINK, SceneOp.ATTACH_SIGNAL},
    BRAIN: set(SceneOp) - {SceneOp.ARCHIVE, SceneOp.ARCHIVE_MANY, SceneOp.PIN, SceneOp.UNPIN},
    USER: set(SceneOp),
}


def matrix_command(op: SceneOp, actor: SceneActor) -> SceneCommand:
    """Une commande par opération, recevable par tout acteur qui a l'opération.

    Les cibles sont des nœuds d'exécution non épinglés et aucun champ de
    vérité ou de composition interdit n'est écrit : seule la matrice décide.
    """

    arguments = {
        SceneOp.UPSERT_OBJECT: {"object_id": "sig-new", "fields": SceneObjectFields(kind=SceneObjectKind.ATTENTION, category="error")},
        SceneOp.PATCH_OBJECT: {"object_id": "star-a", "fields": SceneObjectFields(payload=ScenePayload(title="Nouveau"))},
        SceneOp.SET_GEOMETRY: {"object_id": "star-a", "geometry": GEO_2},
        SceneOp.SET_REPRESENTATION: {"object_id": "star-a", "representation": Representation.CAPSULE},
        SceneOp.SET_VISIBILITY: {"object_id": "star-a", "visibility": Visibility.HIDDEN},
        SceneOp.PIN: {"object_id": "star-a"},
        SceneOp.UNPIN: {"object_id": "star-p"},
        # Parenté entre étoiles : au runtime seul (Slice 06) ; brain/user relient un artefact.
        SceneOp.LINK: {"relation": SceneRelation("rel-new", RelationKind.PARENT_OF, "star-b", "star-p") if actor is RUNTIME
                       else SceneRelation("rel-new", RelationKind.EXPLAINS, "art-1", "star-p")},
        # `rel-ab` appartient au runtime (Slice 06) : brain/user délient un lien à eux.
        SceneOp.UNLINK: {"relation_id": "rel-ab" if actor is RUNTIME else "rel-note"},
        SceneOp.ARCHIVE: {"object_id": "star-b"},
        # Slice 08 : une étoile terminée (`star-done`, ajoutée par la cellule de matrice).
        SceneOp.ARCHIVE_MANY: {"object_ids": ("star-done",)},
        SceneOp.ATTACH_SIGNAL: {"object_id": "sig-1", "fields": SceneObjectFields(category="error"), "target_id": "star-a"},
    }[op]
    return cmd(op, actor, **arguments)


PUT_OBJECT = [PatchOpKind.PUT_OBJECT]
#: Opérations de patch attendues pour chaque cellule permise de la matrice.
MATRIX_PATCH_OPS = {
    SceneOp.UPSERT_OBJECT: PUT_OBJECT,
    SceneOp.PATCH_OBJECT: PUT_OBJECT,
    SceneOp.SET_GEOMETRY: PUT_OBJECT,
    SceneOp.SET_REPRESENTATION: PUT_OBJECT,
    SceneOp.SET_VISIBILITY: PUT_OBJECT,
    SceneOp.PIN: PUT_OBJECT,
    SceneOp.UNPIN: PUT_OBJECT,
    SceneOp.LINK: [PatchOpKind.PUT_RELATION],
    SceneOp.UNLINK: [PatchOpKind.DELETE_RELATION],
    SceneOp.ARCHIVE: [PatchOpKind.ARCHIVE_OBJECT, PatchOpKind.DELETE_RELATION],
    SceneOp.ARCHIVE_MANY: [PatchOpKind.ARCHIVE_OBJECT],
    SceneOp.ATTACH_SIGNAL: [PatchOpKind.PUT_OBJECT, PatchOpKind.PUT_RELATION],
}


def test_authority_matrix_table_is_the_contract():
    assert {actor: set(ops) for actor, ops in ALLOWED_SCENE_OPS.items()} == EXPECTED_ALLOWED


@pytest.mark.parametrize("actor", list(SceneActor))
@pytest.mark.parametrize("op", list(SceneOp))
def test_every_authority_matrix_cell(actor, op):
    before = scene_with_stars()
    if op is SceneOp.UNLINK and actor is not RUNTIME:
        before = run(before, cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-note", RelationKind.EXPLAINS, "art-1", "star-a")))
    if op is SceneOp.ARCHIVE_MANY:
        before = run(before, star("star-done", exec_state=ExecState.COMPLETED))
    update = apply_scene_command(before, matrix_command(op, actor))
    if op in EXPECTED_ALLOWED[actor]:
        assert update.outcome is APPLIED, update.reason
        assert update.snapshot.revision == before.revision + 1
        assert [item.op for item in update.patch.ops] == MATRIX_PATCH_OPS[op]
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


def test_user_archive_moves_the_object_to_history_and_leaves_a_tombstone():
    before = scene_with_stars()
    known = before.get_object("star-a")
    update = apply_scene_command(before, cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    assert update.outcome is APPLIED
    assert update.snapshot.get_object("star-a") is None
    assert update.snapshot.archived_ids == ("star-a",)
    assert update.snapshot.is_archived("star-a")
    assert update.snapshot.get_relation("rel-ab") is None
    assert all(item.disposition is Disposition.ACTIVE for item in update.snapshot.objects)
    assert [op.op for op in update.patch.ops] == [PatchOpKind.ARCHIVE_OBJECT, PatchOpKind.DELETE_RELATION]
    # Le patch porte la forme historique complète, pour le magasin.
    history = update.patch.ops[0].object
    assert history == dataclasses.replace(known, disposition=Disposition.ARCHIVED)
    assert history.visibility is Visibility.VISIBLE  # caché ≠ archivé

    again = apply_scene_command(update.snapshot, cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    assert again.outcome is DUPLICATE


@pytest.mark.parametrize(
    "command",
    [
        patch(RUNTIME, "star-a", exec_state=ExecState.COMPLETED),
        star("star-a", exec_state=ExecState.COMPLETED),  # observation tardive : pas de résurrection
        upsert(BRAIN, "star-a", kind=SceneObjectKind.WINDOW, category="note"),
        upsert(USER, "star-a", kind=SceneObjectKind.GROUP, category="castor"),
        cmd(SceneOp.SET_VISIBILITY, USER, object_id="star-a", visibility=Visibility.HIDDEN),
        cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-a", geometry=GEO_2),
        cmd(SceneOp.PIN, USER, object_id="star-a"),
        cmd(SceneOp.LINK, USER, relation=SceneRelation("rel-x", RelationKind.GROUPS, "star-b", "star-a")),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-x", RelationKind.PARENT_OF, "star-a", "star-b")),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-9", fields=SceneObjectFields(category="error"), target_id="star-a"),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="star-a", fields=SceneObjectFields(category="error"), target_id="star-b"),
    ],
)
def test_every_command_on_a_tombstoned_id_is_invalid(command):
    archived = run(scene_with_stars(), cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    update = apply_scene_command(archived, command)
    assert (update.outcome, update.reason) == (INVALID, SceneRefusal.OBJECT_ARCHIVED)
    assert_unchanged(archived, update)


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
    ],
    ids=["brain-move", "brain-resize", "brain-patch", "brain-upsert", "brain-representation-resize", "user-resolver"],
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
        SceneObject("x", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.USER, pinned_by_user=True), RUNTIME)


# --- placement : auteur et AutoResolver ----------------------------------------


def test_placement_author_is_recorded_and_resolver_only_fills_the_gaps():
    before = scene_with_stars()
    assert before.get_object("star-b").geometry is None
    assert before.get_object("star-b").constraints.placed_by is PlacedBy.RUNTIME

    resolved = apply_scene_command(before, cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-b", geometry=GEO_2, placed_by=PlacedBy.RESOLVER))
    assert resolved.outcome is APPLIED
    assert resolved.snapshot.get_object("star-b").constraints.placed_by is PlacedBy.RESOLVER

    nudged = apply_scene_command(
        resolved.snapshot, cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-b", geometry=GEO, placed_by=PlacedBy.RESOLVER)
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


@pytest.mark.parametrize("layer", [0, 60, 999, 1000])
def test_runtime_never_announces_a_relation_layer(layer):
    before = scene_with_stars()
    created = apply_scene_command(before, cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-x", RelationKind.PARENT_OF, "star-b", "star-p", layer=layer)))
    assert (created.outcome, created.reason) == (REJECTED, SceneRefusal.RUNTIME_COMPOSITION)
    assert_unchanged(before, created)
    relayered = apply_scene_command(before, cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b", layer=layer)))
    assert (relayered.outcome, relayered.reason) == (REJECTED, SceneRefusal.RUNTIME_COMPOSITION)


def test_runtime_relink_keeps_the_layer_the_brain_chose():
    before = run(scene_with_stars(), cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b", layer=77)))
    # `runtime` ne pose que la couche par défaut, qui vaut « non annoncée ».
    again = apply_scene_command(before, cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b")))
    assert again.outcome is DUPLICATE
    assert again.snapshot.get_relation("rel-ab").layer == 77
    created = apply_scene_command(before, cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-bp", RelationKind.PARENT_OF, "star-b", "star-p")))
    assert created.snapshot.get_relation("rel-bp").layer == DEFAULT_RELATION_LAYER

    signalled = run(before, cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-1", fields=SceneObjectFields(category="error"), target_id="star-a"))
    relayered = run(signalled, cmd(SceneOp.LINK, USER, relation=SceneRelation("sig-1", RelationKind.EXPLAINS, "sig-1", "star-a", layer=310)))
    for actor in (RUNTIME, BRAIN):
        refreshed = apply_scene_command(
            relayered, cmd(SceneOp.ATTACH_SIGNAL, actor, object_id="sig-1", fields=SceneObjectFields(category="error"), target_id="star-a")
        )
        assert refreshed.outcome is DUPLICATE
        assert refreshed.snapshot.get_relation("sig-1").layer == 310


# --- origine : runtime n'écrit que ce qu'il a créé ----------------------------


@pytest.mark.parametrize("author", [BRAIN, USER])
def test_runtime_cannot_rewrite_or_reuse_brain_or_user_attention(author):
    before = run(scene_with_stars(), upsert(author, "note", kind=SceneObjectKind.ATTENTION, category="todo", payload=ScenePayload(title="mine")))
    assert before.get_object("note").origin is author
    for command in (
        patch(RUNTIME, "note", payload=ScenePayload(title="runtime")),
        patch(RUNTIME, "note", category="error", work_ref=WorkRef("job", "x")),
        upsert(RUNTIME, "note", kind=SceneObjectKind.ATTENTION, category="error"),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="note", fields=SceneObjectFields(category="error"), target_id="star-a"),
    ):
        update = apply_scene_command(before, command)
        assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_ORIGIN), command.op
        assert_unchanged(before, update)
    # Le cerveau et l'utilisateur gardent leurs droits, et l'origine ne bouge pas.
    for actor in (BRAIN, USER):
        edited = apply_scene_command(before, patch(actor, "note", payload=ScenePayload(title=actor.value)))
        assert edited.outcome is APPLIED
        assert edited.snapshot.get_object("note").origin is author


def test_origin_is_set_once_at_creation_and_travels_on_the_wire():
    snapshot = run(
        scene_with_stars(),
        cmd(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="sig-r", fields=SceneObjectFields(category="error"), target_id="star-a"),
        cmd(SceneOp.ATTACH_SIGNAL, USER, object_id="sig-u", fields=SceneObjectFields(category="todo"), target_id="star-a"),
        patch(BRAIN, "sig-r", layer=310),
        patch(USER, "star-a", category="research"),
    )
    assert {item.object_id: item.origin for item in snapshot.objects} == {
        "star-a": RUNTIME, "star-b": RUNTIME, "star-p": RUNTIME, "art-1": BRAIN, "sig-r": RUNTIME, "sig-u": USER,
    }
    assert all(item["origin"] in {"runtime", "brain", "user"} for item in snapshot.to_payload()["objects"])
    assert apply_scene_command(snapshot, patch(RUNTIME, "sig-r", payload=ScenePayload(title="timeout"))).outcome is APPLIED
    with pytest.raises(ValueError, match="an execution node originates from runtime"):
        SceneObject("fake", SceneObjectKind.JOB, "job", SceneConstraints(PlacedBy.BRAIN), BRAIN)


# --- retrait des signaux runtime (Slice 04, amendement F1) --------------------


def runtime_signal(object_id: str = "sig-1", target_id: str = "star-a", state: ExecState = ExecState.FAILED) -> SceneCommand:
    return cmd(
        SceneOp.ATTACH_SIGNAL,
        RUNTIME,
        object_id=object_id,
        fields=SceneObjectFields(category="failed", exec_state=state, payload=ScenePayload(title="boom")),
        target_id=target_id,
    )


def test_runtime_retires_its_own_signal_by_unlinking_it_and_may_raise_it_again():
    raised = run(scene_with_stars(), runtime_signal())
    assert is_live_signal(raised, "sig-1")

    retired = apply_scene_command(raised, cmd(SceneOp.UNLINK, RUNTIME, relation_id="sig-1"))
    assert retired.outcome is APPLIED
    assert [op.op for op in retired.patch.ops] == [PatchOpKind.DELETE_RELATION]
    assert not is_live_signal(retired.snapshot, "sig-1")
    # L'objet reste, intact : ni archivage, ni masquage, ni géométrie.
    signal = retired.snapshot.get_object("sig-1")
    assert signal == raised.get_object("sig-1")
    assert (signal.disposition, signal.visibility, signal.geometry) == (Disposition.ACTIVE, Visibility.VISIBLE, None)
    assert retired.snapshot.archived_ids == raised.archived_ids

    resolved = apply_scene_command(retired.snapshot, patch(RUNTIME, "sig-1", exec_state=ExecState.RUNNING))
    assert resolved.outcome is APPLIED
    assert apply_scene_command(resolved.snapshot, cmd(SceneOp.UNLINK, RUNTIME, relation_id="sig-1")).outcome is DUPLICATE

    again = apply_scene_command(resolved.snapshot, runtime_signal(state=ExecState.BLOCKED))
    assert again.outcome is APPLIED
    assert is_live_signal(again.snapshot, "sig-1")
    assert [item.object_id for item in again.snapshot.objects].count("sig-1") == 1


@pytest.mark.parametrize("author", [BRAIN, USER])
def test_runtime_cannot_retire_a_brain_or_user_signal(author):
    before = run(
        scene_with_stars(),
        cmd(SceneOp.ATTACH_SIGNAL, author, object_id="note", fields=SceneObjectFields(category="todo"), target_id="star-a"),
    )
    assert is_live_signal(before, "note")
    update = apply_scene_command(before, cmd(SceneOp.UNLINK, RUNTIME, relation_id="note"))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_ORIGIN)
    assert_unchanged(before, update)
    # Leurs propres signaux restent à eux ; celui du runtime est au runtime (Slice 06).
    signalled = run(before, runtime_signal())
    for actor in (BRAIN, USER):
        assert apply_scene_command(signalled, cmd(SceneOp.UNLINK, actor, relation_id="note")).outcome is APPLIED
        refused = apply_scene_command(signalled, cmd(SceneOp.UNLINK, actor, relation_id="sig-1"))
        assert (refused.outcome, refused.reason) == (REJECTED, SceneRefusal.RUNTIME_OWNED)


def test_runtime_retires_only_a_signal_link_between_its_attention_and_its_star():
    retired = run(scene_with_stars(), runtime_signal(), cmd(SceneOp.UNLINK, RUNTIME, relation_id="sig-1"))
    cases = {
        # même identifiant que le signal, mais posé par l'utilisateur vers un artefact du cerveau
        "artifact target": SceneRelation("sig-1", RelationKind.EXPLAINS, "sig-1", "art-1"),
        # lien `explains` d'un artefact du cerveau vers une étoile, nommé comme sa source
        "artifact source": SceneRelation("art-1", RelationKind.EXPLAINS, "art-1", "star-a"),
        # lien `groups` qui porte l'identifiant de sa source : pas un lien de signal
        "groups": SceneRelation("sig-1", RelationKind.GROUPS, "sig-1", "star-a"),
    }
    for name, relation in cases.items():
        before = run(retired, cmd(SceneOp.LINK, USER, relation=relation))
        update = apply_scene_command(before, cmd(SceneOp.UNLINK, RUNTIME, relation_id=relation.relation_id))
        assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_RELATION), name
        assert_unchanged(before, update)


def test_retiring_a_signal_grants_runtime_no_archive_visibility_or_layout_right():
    raised = run(scene_with_stars(), runtime_signal())
    for command, reason in (
        (cmd(SceneOp.ARCHIVE, RUNTIME, object_id="sig-1"), SceneRefusal.OP_NOT_ALLOWED),
        (cmd(SceneOp.SET_VISIBILITY, RUNTIME, object_id="sig-1", visibility=Visibility.HIDDEN), SceneRefusal.OP_NOT_ALLOWED),
        (cmd(SceneOp.SET_GEOMETRY, RUNTIME, object_id="sig-1", geometry=GEO), SceneRefusal.OP_NOT_ALLOWED),
        (patch(RUNTIME, "sig-1", visibility=Visibility.HIDDEN), SceneRefusal.RUNTIME_COMPOSITION),
        (patch(RUNTIME, "sig-1", layer=10), SceneRefusal.RUNTIME_COMPOSITION),
        (cmd(SceneOp.UNLINK, RUNTIME, relation_id="rel-ab"), None),
    ):
        update = apply_scene_command(raised, command)
        if reason is None:
            # `parent_of` entre étoiles runtime : droit antérieur, inchangé.
            assert update.outcome is APPLIED
        else:
            assert (update.outcome, update.reason) == (REJECTED, reason), command.op
    assert ALLOWED_SCENE_OPS[RUNTIME] == EXPECTED_ALLOWED[RUNTIME]


# --- AutoResolver : commis par l'utilisateur seulement ------------------------


def test_resolver_placement_is_accepted_from_the_user_proxy_only():
    before = scene_with_stars()
    brain = apply_scene_command(before, cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="star-b", geometry=GEO, placed_by=PlacedBy.RESOLVER))
    assert (brain.outcome, brain.reason) == (REJECTED, SceneRefusal.RESOLVER_ACTOR)
    assert_unchanged(before, brain)
    unknown = apply_scene_command(before, cmd(SceneOp.SET_GEOMETRY, BRAIN, object_id="absent", geometry=GEO, placed_by=PlacedBy.RESOLVER))
    assert (unknown.outcome, unknown.reason) == (REJECTED, SceneRefusal.RESOLVER_ACTOR)
    runtime = apply_scene_command(before, cmd(SceneOp.SET_GEOMETRY, RUNTIME, object_id="star-b", geometry=GEO, placed_by=PlacedBy.RESOLVER))
    assert (runtime.outcome, runtime.reason) == (REJECTED, SceneRefusal.OP_NOT_ALLOWED)
    user = apply_scene_command(before, cmd(SceneOp.SET_GEOMETRY, USER, object_id="star-b", geometry=GEO, placed_by=PlacedBy.RESOLVER))
    assert user.outcome is APPLIED
    assert user.snapshot.get_object("star-b").constraints.placed_by is PlacedBy.RESOLVER


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


#: Création par acteur × nature : seul runtime fait naître une étoile ; runtime
#: ne crée ni artefact, ni fenêtre, ni groupe ; le signal d'attention est à
#: tous (le cerveau signale, l'utilisateur marque ce qui mérite attention).
CREATION_OUTCOMES = {
    RUNTIME: {
        SceneObjectKind.AGENT: (APPLIED, None),
        SceneObjectKind.JOB: (APPLIED, None),
        SceneObjectKind.ATTENTION: (APPLIED, None),
        SceneObjectKind.ARTIFACT: (REJECTED, SceneRefusal.RUNTIME_KIND),
        SceneObjectKind.WINDOW: (REJECTED, SceneRefusal.RUNTIME_KIND),
        SceneObjectKind.GROUP: (REJECTED, SceneRefusal.RUNTIME_KIND),
    },
    **{
        actor: {
            SceneObjectKind.AGENT: (REJECTED, SceneRefusal.EXECUTION_NODE),
            SceneObjectKind.JOB: (REJECTED, SceneRefusal.EXECUTION_NODE),
            SceneObjectKind.ATTENTION: (APPLIED, None),
            SceneObjectKind.ARTIFACT: (APPLIED, None),
            SceneObjectKind.WINDOW: (APPLIED, None),
            SceneObjectKind.GROUP: (APPLIED, None),
        }
        for actor in (BRAIN, USER)
    },
}


@pytest.mark.parametrize("kind", list(SceneObjectKind))
@pytest.mark.parametrize("actor", list(SceneActor))
def test_creation_cell_per_actor_and_kind(actor, kind):
    before = scene_with_stars()
    update = apply_scene_command(before, upsert(actor, "new-1", kind=kind, category="cat"))
    assert (update.outcome, update.reason) == CREATION_OUTCOMES[actor][kind]
    if update.changed:
        assert update.snapshot.get_object("new-1").constraints.placed_by is PlacedBy(actor.value)
        assert update.snapshot.get_object("new-1").origin is actor
    else:
        assert_unchanged(before, update)


@pytest.mark.parametrize("actor", [BRAIN, USER])
def test_brain_and_user_cannot_fabricate_a_star_by_any_creating_path(actor):
    before = scene_with_stars()
    for command in (
        upsert(actor, "fake", kind=SceneObjectKind.AGENT, category="agent", geometry=GEO),
        upsert(actor, "fake", kind=SceneObjectKind.JOB, category="job", layer=100, payload=ScenePayload(title="Faux")),
    ):
        update = apply_scene_command(before, command)
        assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.EXECUTION_NODE)
    signal = apply_scene_command(
        before, cmd(SceneOp.ATTACH_SIGNAL, actor, object_id="note-1", fields=SceneObjectFields(category="todo"), target_id="art-1")
    )
    assert signal.outcome is APPLIED
    assert signal.snapshot.get_object("note-1").kind is SceneObjectKind.ATTENTION


def test_brain_and_user_compose_existing_runtime_stars():
    before = scene_with_stars()
    snapshot = run(
        before,
        upsert(BRAIN, "grp-1", kind=SceneObjectKind.GROUP, category="castor"),
        patch(BRAIN, "star-a", category="research", layer=150, order=3, payload=ScenePayload(title="Explorer")),
        upsert(BRAIN, "star-b", kind=SceneObjectKind.JOB, category="job", representation=Representation.CAPSULE),
        cmd(SceneOp.SET_REPRESENTATION, USER, object_id="star-b", representation=Representation.WINDOW),
        cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-grp", RelationKind.GROUPS, "grp-1", "star-a")),
    )
    assert snapshot.revision == before.revision + 5
    assert snapshot.get_object("star-a").exec_state is ExecState.RUNNING
    assert snapshot.get_object("star-b").representation is Representation.WINDOW


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
    before = run(scene_with_stars(), cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-note", RelationKind.EXPLAINS, "art-1", "star-a")))
    # La couche d'un lien runtime reste de la composition, permise.
    relayered = apply_scene_command(before, cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b", layer=60)))
    assert relayered.outcome is APPLIED
    relayered = apply_scene_command(relayered.snapshot, cmd(SceneOp.LINK, USER, relation=SceneRelation("rel-note", RelationKind.EXPLAINS, "art-1", "star-a", layer=70)))
    assert relayered.outcome is APPLIED
    unlinked = apply_scene_command(relayered.snapshot, cmd(SceneOp.UNLINK, USER, relation_id="rel-note"))
    assert unlinked.outcome is APPLIED
    assert apply_scene_command(unlinked.snapshot, cmd(SceneOp.UNLINK, USER, relation_id="rel-note")).outcome is DUPLICATE


# --- topologie et signaux du runtime, identifiants réservés (Slice 06) ---------


@pytest.mark.parametrize("actor", [BRAIN, USER])
def test_brain_and_user_cannot_unlink_runtime_topology_or_signals(actor):
    before = run(scene_with_stars(), runtime_signal())
    for relation_id in ("rel-ab", "sig-1"):
        assert is_runtime_owned_relation(before, before.get_relation(relation_id))
        update = apply_scene_command(before, cmd(SceneOp.UNLINK, actor, relation_id=relation_id))
        assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_OWNED)
        assert_unchanged(before, update)
    # Le signal reste masquable par le cerveau comme par l'utilisateur.
    hidden = apply_scene_command(before, cmd(SceneOp.SET_VISIBILITY, actor, object_id="sig-1", visibility=Visibility.HIDDEN))
    assert hidden.outcome is APPLIED and is_live_signal(hidden.snapshot, "sig-1")
    # Une parenté entre deux étoiles ne se pose pas non plus : elle ne pourrait plus être retirée.
    drawn = apply_scene_command(before, cmd(SceneOp.LINK, actor, relation=SceneRelation("brain-parent", RelationKind.PARENT_OF, "star-b", "star-p")))
    assert (drawn.outcome, drawn.reason) == (REJECTED, SceneRefusal.RUNTIME_OWNED)
    assert_unchanged(before, drawn)
    # Toute autre forme reste à eux : un `parent_of` depuis un artefact, un `explains` d'artefact.
    other = run(
        before,
        cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("art-parent", RelationKind.PARENT_OF, "art-1", "star-a")),
        cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("art-1", RelationKind.EXPLAINS, "art-1", "star-a")),
    )
    for relation_id in ("art-parent", "art-1"):
        assert apply_scene_command(other, cmd(SceneOp.UNLINK, actor, relation_id=relation_id)).outcome is APPLIED
    # Le runtime garde son retrait ; l'utilisateur écarte par l'archivage, qui emporte les liens.
    assert apply_scene_command(before, cmd(SceneOp.UNLINK, RUNTIME, relation_id="sig-1")).outcome is APPLIED
    archived = run(before, cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    assert archived.get_relation("rel-ab") is None and archived.get_relation("sig-1") is None
    archived_signal = run(before, cmd(SceneOp.ARCHIVE, USER, object_id="sig-1"))
    assert archived_signal.get_relation("sig-1") is None


@pytest.mark.parametrize(
    "identifier",
    ["claude:task-1", "claude#0123456789abcdef01234567:task", "attention!claude:task-1", "attention#ab!x",
     "parent_of!claude:x", "parent_of#ab!x", "a:b"],
)
def test_runtime_reserved_ids_are_refused_to_brain_and_user(identifier):
    assert is_runtime_reserved_id(identifier)
    before = scene_with_stars()
    for actor in (BRAIN, USER):
        commands = (
            upsert(actor, identifier, kind=SceneObjectKind.ARTIFACT, category="note"),
            upsert(actor, identifier, kind=SceneObjectKind.ATTENTION, category="note"),
            cmd(SceneOp.ATTACH_SIGNAL, actor, object_id=identifier, fields=SceneObjectFields(category="note"), target_id="star-a"),
            cmd(SceneOp.LINK, actor, relation=SceneRelation(identifier, RelationKind.EXPLAINS, "art-1", "star-a")),
            cmd(SceneOp.LINK, actor, relation=SceneRelation(identifier, RelationKind.GROUPS, "art-1", "star-b", layer=70)),
        )
        for command in commands:
            update = apply_scene_command(before, command)
            assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RESERVED_ID), command
            assert_unchanged(before, update)
    # Le runtime les fabrique toujours.
    assert apply_scene_command(before, runtime_signal(object_id="attention!star-a")).outcome is APPLIED


@pytest.mark.parametrize("actor", [BRAIN, USER])
def test_brain_and_user_cannot_draw_execution_topology_but_keep_other_links(actor):
    before = run(scene_with_stars(), cmd(SceneOp.UPSERT_OBJECT, BRAIN, object_id="grp", fields=SceneObjectFields(kind=SceneObjectKind.GROUP, category="plan")))
    for source, target in (("star-a", "star-p"), ("star-p", "star-a"), ("star-b", "star-a")):
        update = apply_scene_command(before, cmd(SceneOp.LINK, actor, relation=SceneRelation("brain-p", RelationKind.PARENT_OF, source, target)))
        assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.RUNTIME_OWNED)
        assert_unchanged(before, update)
    allowed = (
        SceneRelation("r1", RelationKind.PARENT_OF, "art-1", "star-a"),
        SceneRelation("r2", RelationKind.PARENT_OF, "grp", "art-1"),
        SceneRelation("r3", RelationKind.GROUPS, "grp", "star-a"),
        SceneRelation("r4", RelationKind.EXPLAINS, "star-a", "star-b"),
        # Recomposer la parenté que le runtime a posée (couche) reste permis.
        SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b", layer=80),
    )
    for relation in allowed:
        assert apply_scene_command(before, cmd(SceneOp.LINK, actor, relation=relation)).outcome is APPLIED, relation
    # Le runtime la pose toujours.
    assert apply_scene_command(before, cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-bp", RelationKind.PARENT_OF, "star-b", "star-p"))).outcome is APPLIED


def test_ordinary_ids_are_not_reserved():
    for identifier in ("brain-artifact-0123", "brain-groups-abcd", "art-1", "attention", "parent_of", "attention-x", "note!1"):
        assert not is_runtime_reserved_id(identifier)


def test_reserved_ids_do_not_block_composing_what_the_runtime_created():
    before = run(
        SceneSnapshot(scene_id="scene-1"),
        star("claude:a"),
        star("claude:b"),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("parent_of!claude:b", RelationKind.PARENT_OF, "claude:a", "claude:b")),
        runtime_signal(object_id="attention!claude:a", target_id="claude:a"),
    )
    for actor in (BRAIN, USER):
        composed = run(
            before,
            patch(actor, "claude:a", payload=ScenePayload(title="renommée")),
            cmd(SceneOp.SET_VISIBILITY, actor, object_id="attention!claude:a", visibility=Visibility.HIDDEN),
            cmd(SceneOp.LINK, actor, relation=SceneRelation("parent_of!claude:b", RelationKind.PARENT_OF, "claude:a", "claude:b", layer=90)),
        )
        assert composed.get_relation("parent_of!claude:b").layer == 90
        # Un signal runtime retiré ne se ranime que par le runtime.
        retired = run(before, cmd(SceneOp.UNLINK, RUNTIME, relation_id="attention!claude:a"))
        revived = apply_scene_command(retired, cmd(SceneOp.ATTACH_SIGNAL, actor, object_id="attention!claude:a",
                                                   fields=SceneObjectFields(category="failed"), target_id="claude:a"))
        assert (revived.outcome, revived.reason) == (REJECTED, SceneRefusal.RESERVED_ID)


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
    with pytest.raises(ValueError, match="does not follow revision"):
        apply_scene_patch(update.snapshot, update.patch)  # rejoué : n'est plus la révision suivante
    with pytest.raises(ValueError, match="does not follow revision"):
        apply_scene_patch(before, dataclasses.replace(update.patch, revision=before.revision + 2))
    ghost = ScenePatch(revision=before.revision + 1, ops=(ScenePatchOp(PatchOpKind.DELETE_RELATION, relation_id="ghost"),))
    with pytest.raises(ValueError, match="deletes unknown relation ghost"):
        apply_scene_patch(before, ghost)

    history = dataclasses.replace(before.get_object("art-1"), object_id="ghost", disposition=Disposition.ARCHIVED)
    with pytest.raises(ValueError, match="archives unknown object ghost"):
        apply_scene_patch(before, ScenePatch(before.revision + 1, (ScenePatchOp(PatchOpKind.ARCHIVE_OBJECT, object=history),)))
    archived = run(before, cmd(SceneOp.ARCHIVE, USER, object_id="art-1"))
    resurrect = ScenePatch(archived.revision + 1, (ScenePatchOp(PatchOpKind.PUT_OBJECT, object=before.get_object("art-1")),))
    with pytest.raises(ValueError, match="rewrites archived object art-1"):
        apply_scene_patch(archived, resurrect)


def test_patch_ops_carry_the_disposition_that_matches_them():
    active = scene_with_stars().get_object("art-1")
    history = dataclasses.replace(active, disposition=Disposition.ARCHIVED)
    with pytest.raises(ValueError):
        ScenePatchOp(PatchOpKind.PUT_OBJECT, object=history)
    with pytest.raises(ValueError):
        ScenePatchOp(PatchOpKind.ARCHIVE_OBJECT, object=active)
    with pytest.raises(ValueError):
        ScenePatchOp(PatchOpKind.ARCHIVE_OBJECT, relation_id="r")
    op = ScenePatchOp(PatchOpKind.ARCHIVE_OBJECT, object=history)
    assert ScenePatchOp.from_payload(json.loads(json.dumps(op.to_payload()))) == op


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
    values = {"object_id": "obj-1", "kind": SceneObjectKind.WINDOW, "category": "note", "constraints": SceneConstraints(PlacedBy.BRAIN), "origin": BRAIN}
    values.update(overrides)
    with pytest.raises(error):
        SceneObject(**values)


def test_layer_bands_are_conventions_not_a_closed_list():
    for layer in (0, 50, 100, 120, 137, 150, 220, 300, MAX_LAYER):
        assert SceneObject("o", SceneObjectKind.WINDOW, "note", SceneConstraints(PlacedBy.BRAIN), BRAIN, layer=layer).layer == layer


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


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b[31m", "\r", "\x1f"])
def test_payload_text_rejects_control_characters(control):
    with pytest.raises(ValueError, match="summary must not contain control characters"):
        ScenePayload(summary=f"avant{control}après")
    with pytest.raises(ValueError, match="title must be a single printable line"):
        ScenePayload(title=f"titre{control}")
    with pytest.raises(ValueError, match="label must be a single printable line"):
        ScenePayloadItem(label=f"libellé{control}")


def test_summary_keeps_newlines_and_tabs():
    assert ScenePayload(summary="ligne 1\n\tpuce").summary == "ligne 1\n\tpuce"


def test_revision_is_bounded_to_a_signed_64_bit_integer():
    assert MAX_REVISION == 2**63 - 1
    assert SceneSnapshot("s", revision=MAX_REVISION).revision == MAX_REVISION
    with pytest.raises(ValueError, match="revision must be between 0 and"):
        SceneSnapshot("s", revision=MAX_REVISION + 1)
    with pytest.raises(ValueError, match="revision must be between 1 and"):
        ScenePatch(MAX_REVISION + 1, (ScenePatchOp(PatchOpKind.DELETE_RELATION, relation_id="r"),))
    exhausted = run(SceneSnapshot("s", revision=MAX_REVISION - 1), star("star-a"))
    assert exhausted.revision == MAX_REVISION
    update = apply_scene_command(exhausted, patch(RUNTIME, "star-a", exec_state=ExecState.COMPLETED))
    assert (update.outcome, update.reason) == (INVALID, SceneRefusal.REVISION_EXHAUSTED)
    assert_unchanged(exhausted, update)
    assert apply_scene_command(exhausted, star("star-a")).outcome is DUPLICATE


def test_payload_byte_bound_is_explicit_and_counts_utf8():
    items = tuple(ScenePayloadItem(label="é" * 80, ref="r" * 256, url="https://example.com/" + "u" * 1000) for _ in range(12))
    with pytest.raises(ValueError, match=str(MAX_PAYLOAD_BYTES)):
        ScenePayload(summary="ligne 1\nligne 2", items=items)
    assert ScenePayload(summary="ligne 1\nligne 2", items=items[:6]).summary == "ligne 1\nligne 2"


def test_snapshot_bounds_uniqueness_and_relation_endpoints():
    agent = SceneObject("a", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.RUNTIME), RUNTIME)
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
    # Un instantané ne tient que la scène active ; les archivés sont des
    # pierres tombales uniques, disjointes des objets, bornées.
    with pytest.raises(ValueError):
        SceneSnapshot("s", objects=(dataclasses.replace(agent, disposition=Disposition.ARCHIVED),))
    with pytest.raises(ValueError):
        SceneSnapshot("s", objects=(agent,), archived_ids=("a",))
    with pytest.raises(ValueError):
        SceneSnapshot("s", archived_ids=("x", "x"))
    with pytest.raises(ValueError):
        SceneSnapshot("s", archived_ids=(" x",))
    with pytest.raises(TypeError):
        SceneSnapshot("s", archived_ids=["x"])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SceneSnapshot("s", archived_ids=tuple(f"t{index}" for index in range(MAX_ARCHIVED_IDS + 1)))
    assert len(SceneSnapshot("s", objects=many[:MAX_SCENE_OBJECTS], archived_ids=tuple(f"t{index}" for index in range(MAX_ARCHIVED_IDS))).archived_ids) == MAX_ARCHIVED_IDS


def test_reducer_refuses_to_grow_past_the_bounds():
    agent = SceneObject("a0", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.RUNTIME), RUNTIME)
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
    assert len(archived.patch.ops) == 1 + MAX_SCENE_RELATIONS
    assert MAX_PATCH_OPS == MAX_SCENE_OBJECTS + MAX_SCENE_RELATIONS  # Slice 08 : archivage groupé
    assert archived.patch.ops[0].op is PatchOpKind.ARCHIVE_OBJECT
    assert archived.snapshot.relations == ()


def test_archiving_frees_capacity_so_a_long_lived_scene_never_fills_up():
    agent = SceneObject("a0", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.RUNTIME), RUNTIME)
    snapshot = SceneSnapshot("s", objects=tuple(dataclasses.replace(agent, object_id=f"a{index}") for index in range(MAX_SCENE_OBJECTS)))
    for turn in range(3 * MAX_SCENE_OBJECTS):
        full = apply_scene_command(snapshot, star(f"new-{turn}"))
        assert (full.outcome, full.reason) == (INVALID, SceneRefusal.SCENE_FULL)
        snapshot = run(snapshot, cmd(SceneOp.ARCHIVE, USER, object_id=snapshot.objects[0].object_id), star(f"new-{turn}"))
        assert len(snapshot.objects) == MAX_SCENE_OBJECTS
    assert len(snapshot.archived_ids) == 3 * MAX_SCENE_OBJECTS


def test_tombstones_are_bounded_and_the_oldest_drop_deterministically_on_replay():
    tombstones = tuple(f"old-{index}" for index in range(MAX_ARCHIVED_IDS))
    before = run(SceneSnapshot("s", revision=7, archived_ids=tombstones), star("star-a"))
    update = apply_scene_command(before, cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    assert update.outcome is APPLIED
    assert len(update.snapshot.archived_ids) == MAX_ARCHIVED_IDS
    assert update.snapshot.archived_ids == (*tombstones[1:], "star-a")
    # Le rejeu du patch, sur le fil, oublie exactement la même pierre tombale.
    wire = ScenePatch.from_payload(json.loads(json.dumps(update.patch.to_payload())))
    assert apply_scene_patch(before, wire) == update.snapshot
    restored = SceneSnapshot.from_payload(json.loads(json.dumps(update.snapshot.to_payload())))
    assert restored == update.snapshot

    # Risque résiduel documenté : l'identifiant oublié redevient libre.
    assert apply_scene_command(update.snapshot, star("old-0")).outcome is APPLIED
    kept = apply_scene_command(update.snapshot, star("old-1"))
    assert (kept.outcome, kept.reason) == (INVALID, SceneRefusal.OBJECT_ARCHIVED)


# --- forme des commandes ------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: SceneCommand(SceneOp.UPSERT_OBJECT, BRAIN, object_id="a"), r"upsert_object requires \['fields'\]"),
        (lambda: SceneCommand(SceneOp.PIN, USER), r"pin requires \['object_id'\]"),
        (lambda: SceneCommand(SceneOp.PIN, USER, object_id="a", geometry=GEO), r"pin does not take \['geometry'\]"),
        (lambda: SceneCommand(SceneOp.SET_VISIBILITY, USER, object_id="a", visibility=Visibility.HIDDEN, target_id="b"), r"set_visibility does not take \['target_id'\]"),
        (lambda: SceneCommand(SceneOp.SET_GEOMETRY, BRAIN, object_id="a", geometry=GEO, placed_by=PlacedBy.BRAIN), "placed_by may only announce a resolver placement"),
        (lambda: SceneCommand(SceneOp.SET_GEOMETRY, USER, object_id="a", geometry=GEO, placed_by=PlacedBy.USER), "placed_by may only announce a resolver placement"),
        (lambda: SceneCommand(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="s", fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="x"), target_id="a"), "a signal is an attention object"),
        (lambda: SceneCommand(SceneOp.ATTACH_SIGNAL, RUNTIME, object_id="a", fields=SceneObjectFields(category="x"), target_id="a"), "a signal cannot target itself"),
        (lambda: SceneCommand(SceneOp.UNLINK, USER, relation_id=""), "relation_id must be a non-empty identifier"),
    ],
)
def test_malformed_commands_do_not_build(build, message):
    with pytest.raises(ValueError, match=message):
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
    assert wire["archived_ids"] == ["old"]
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
    ("mutate", "error", "message"),
    [
        (lambda p: p.update(extra=1), ValueError, r"scene snapshot has unknown fields: \['extra'\]"),
        (lambda p: p["objects"][0].update(raw={"prompt": "x"}), ValueError, r"object has unknown fields: \['raw'\]"),
        (lambda p: p["objects"][0].pop("layer"), ValueError, r"object is missing fields: \['layer'\]"),
        (lambda p: p["objects"][0].pop("origin"), ValueError, r"object is missing fields: \['origin'\]"),
        (lambda p: p["objects"][0].update(kind="star"), ValueError, r"kind must be one of .*got 'star'"),
        (lambda p: p["objects"][0].update(exec_state="exploded"), ValueError, r"exec_state must be one of .*got 'exploded'"),
        (lambda p: p["objects"][0].update(origin="admin"), ValueError, r"origin must be one of .*got 'admin'"),
        (lambda p: p["objects"][0].update(origin="brain"), ValueError, "an execution node originates from runtime"),
        (lambda p: p["objects"][0].update(layer="100"), TypeError, "layer must be an integer"),
        (lambda p: p["objects"][0]["constraints"].update(pinned_by_user="yes"), TypeError, "pinned_by_user must be a boolean"),
        (lambda p: p["objects"][0].update(geometry={"x": 1, "y": 2, "w": 3}), ValueError, r"geometry is missing fields: \['h'\]"),
        (lambda p: p["relations"][0].update(kind="owns"), ValueError, r"kind must be one of .*got 'owns'"),
        (lambda p: p.update(objects={}), TypeError, "objects must be a list"),
        (lambda p: p.update(objects=[{}] * (MAX_SCENE_OBJECTS + 1)), ValueError, f"objects holds at most {MAX_SCENE_OBJECTS} entries"),
        (lambda p: p.update(relations=[{}] * (MAX_SCENE_RELATIONS + 1)), ValueError, f"relations holds at most {MAX_SCENE_RELATIONS} entries"),
        (lambda p: p.update(revision=True), TypeError, "revision must be an integer"),
        (lambda p: p.update(revision=-1), ValueError, "revision must be between 0 and"),
        (lambda p: p.update(revision=MAX_REVISION + 1), ValueError, "revision must be between 0 and"),
        (lambda p: p.pop("archived_ids"), ValueError, r"scene snapshot is missing fields: \['archived_ids'\]"),
        (lambda p: p.update(archived_ids="old"), TypeError, "archived_ids must be a list"),
        (lambda p: p.update(archived_ids=[7]), TypeError, r"archived_ids\[\] must be a string"),
        (lambda p: p.update(archived_ids=["old", "old"]), ValueError, "archived ids must be unique"),
        (lambda p: p.update(archived_ids=["star-a"]), ValueError, "an archived id cannot also be an active object"),
        (lambda p: p.update(archived_ids=[f"t{index}" for index in range(MAX_ARCHIVED_IDS + 1)]), ValueError, f"archived_ids holds at most {MAX_ARCHIVED_IDS} entries"),
        (lambda p: p["objects"][0].update(disposition="archived"), ValueError, "a scene snapshot holds active objects only"),
    ],
)
def test_snapshot_decoding_is_strict(mutate, error, message):
    payload = json.loads(json.dumps(rich_snapshot().to_payload()))
    mutate(payload)
    with pytest.raises(error, match=message):
        SceneSnapshot.from_payload(payload)


@pytest.mark.parametrize(
    ("payload", "error", "message"),
    [
        ({"schema_version": 1, "op": "archive", "actor": "user", "object_id": "a", "prompt": "x"}, ValueError, r"scene command has unknown fields: \['prompt'\]"),
        ({"schema_version": 1, "op": "destroy", "actor": "user", "object_id": "a"}, ValueError, r"op must be one of .*got 'destroy'"),
        ({"schema_version": 1, "op": "archive", "actor": "admin", "object_id": "a"}, ValueError, r"actor must be one of .*got 'admin'"),
        ({"schema_version": 1, "op": "archive", "object_id": "a"}, ValueError, r"scene command is missing fields: \['actor'\]"),
        ({"schema_version": 1, "op": "patch_object", "actor": "brain", "object_id": "a", "fields": {"disposition": "archived"}}, ValueError, r"fields has unknown fields: \['disposition'\]"),
        ({"schema_version": 1, "op": "patch_object", "actor": "brain", "object_id": "a", "fields": {"origin": "user"}}, ValueError, r"fields has unknown fields: \['origin'\]"),
        ({"schema_version": 1, "op": "patch_object", "actor": "brain", "object_id": "a", "fields": {"constraints": {}}}, ValueError, r"fields has unknown fields: \['constraints'\]"),
        ({"schema_version": 1, "op": "set_geometry", "actor": "user", "object_id": "a", "geometry": {"x": 1, "y": 2, "w": 3, "h": 4}, "placed_by": "brain"}, ValueError, "placed_by may only announce a resolver placement"),
        ({"schema_version": 1, "op": "pin", "actor": "user", "object_id": 7}, TypeError, "object_id must be a string"),
        ({"schema_version": 1, "op": "pin", "actor": ["user"], "object_id": "a"}, TypeError, "actor must be a string"),
        ([], TypeError, "scene command must be an object"),
    ],
)
def test_command_decoding_is_strict(payload, error, message):
    with pytest.raises(error, match=message):
        SceneCommand.from_payload(payload)


HUGE = int("9" * 400)


@pytest.mark.parametrize(
    ("decode", "payload"),
    [
        (SceneCommand.from_payload, {"schema_version": 1, "op": "set_geometry", "actor": "user", "object_id": "a", "geometry": {"x": HUGE, "y": 0, "w": 1, "h": 1}}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "set_geometry", "actor": "user", "object_id": "a", "geometry": {"x": 0, "y": 0, "w": HUGE, "h": 1}}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "patch_object", "actor": "user", "object_id": "a", "fields": {"layer": HUGE}}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "patch_object", "actor": "user", "object_id": "a", "fields": {"order": -HUGE}}),
        (SceneSnapshot.from_payload, {"schema_version": 1, "scene_id": "s", "revision": HUGE, "objects": [], "relations": [], "archived_ids": []}),
        (ScenePatch.from_payload, {"schema_version": 1, "revision": HUGE, "ops": [{"op": "delete_relation", "relation_id": "r"}]}),
        (SceneCommand.from_payload, {"schema_version": HUGE, "op": "pin", "actor": "user", "object_id": "a"}),
    ],
)
def test_hostile_numbers_raise_value_errors_only(decode, payload):
    """Un entier JSON de 400 chiffres ne fait jamais sortir `OverflowError`."""

    wire = json.loads(json.dumps(payload))
    with pytest.raises(ValueError) as caught:
        decode(wire)
    assert type(caught.value) in (ValueError, UnsupportedSceneSchemaVersion)
    assert len(str(caught.value)) < 300


MEGABYTE = "x" * 1_000_000


@pytest.mark.parametrize(
    ("decode", "payload"),
    [
        (SceneCommand.from_payload, {"schema_version": 1, "op": MEGABYTE, "actor": "user", "object_id": "a"}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "pin", "actor": MEGABYTE, "object_id": "a"}),
        (SceneCommand.from_payload, {"schema_version": [MEGABYTE]}),
        (SceneCommand.from_payload, {"schema_version": MEGABYTE}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "pin", "actor": "user", "object_id": MEGABYTE}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "pin", "actor": "user", "object_id": "a", MEGABYTE: 1}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "patch_object", "actor": "user", "object_id": "a", "fields": {"kind": MEGABYTE}}),
        (SceneCommand.from_payload, {"schema_version": 1, "op": "patch_object", "actor": "user", "object_id": "a", "fields": {"payload": {"summary": MEGABYTE}}}),
        (ScenePatch.from_payload, {"schema_version": 1, "revision": 1, "ops": [{"op": MEGABYTE, "relation_id": "r"}]}),
    ],
)
def test_error_messages_never_echo_unbounded_input(decode, payload):
    with pytest.raises((TypeError, ValueError)) as caught:
        decode(payload)
    assert len(str(caught.value)) < 300, str(caught.value)[:400]


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
    assert imported <= {"__future__", "dataclasses", "enum", "json", "math", "typing", "jarvis.domain._checks", "jarvis.domain.work_state"}


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
