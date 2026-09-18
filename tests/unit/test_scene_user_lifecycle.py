"""Cycle de vie utilisateur de la scène (handoff jarvis-constellation-scene-runtime, Slice 08).

Amendement PM (capacité) prouvé ici, sur le réducteur pur puis avec la
projection runtime réelle :

- **cascade** : l'archivage utilisateur d'une étoile emporte ses signaux
  runtime (vivant, retiré, ou de même travail Core) dans le même patch et la
  même révision ; aucun signal du cerveau ou de l'utilisateur n'est emporté ;
- **`archive_many`** : utilisateur seulement (op absente pour cerveau et
  runtime), liste explicite bornée, chaque identifiant revalidé (étoile
  terminée, son signal, ou signal orphelin), tout ou rien, une révision ;
- **pas de résurrection** : ni une mise à jour de travail, ni une
  réconciliation ne ramènent une étoile ou son signal archivés ;
- **rattrapage** : l'archivage groupé libère des places que la projection
  saturée reprend sans nouvel événement de travail.
"""

from __future__ import annotations

import json

import pytest

from jarvis.core.scene_projector import signal_object_id
from jarvis.core.scene_service import SCENE_COMMAND_REFUSED_KIND
from jarvis.domain.scene import (
    ALLOWED_SCENE_OPS,
    MAX_ARCHIVE_MANY_IDS,
    MAX_ARCHIVED_IDS,
    MAX_PATCH_OPS,
    MAX_SCENE_OBJECTS,
    MAX_SCENE_RELATIONS,
    PatchOpKind,
    RelationKind,
    SceneCommand,
    SceneConstraints,
    SceneObject,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePatch,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    TERMINAL_EXEC_STATES,
    PlacedBy,
    ExecState,
    WorkRef,
    apply_scene_command,
    apply_scene_patch,
    bulk_archivable,
    runtime_signals_of,
    signal_owners,
)
from jarvis.domain.work_state import WorkStatus
from tests.unit.test_scene_contracts import (
    APPLIED,
    BRAIN,
    DUPLICATE,
    INVALID,
    REJECTED,
    RUNTIME,
    USER,
    assert_unchanged,
    cmd,
    run,
    star,
    upsert,
)
from tests.unit.test_scene_projector import Stack, ids, nearly_full, obs, settled, until_true


def ref(external_id: str, source: str = "claude") -> WorkRef:
    return WorkRef(source=source, external_id=external_id)


def signal(object_id: str, target_id: str, work: WorkRef | None, *, actor=RUNTIME, category: str = "failed") -> SceneCommand:
    return cmd(
        SceneOp.ATTACH_SIGNAL, actor, object_id=object_id, target_id=target_id,
        fields=SceneObjectFields(category=category, **({"exec_state": ExecState.FAILED, "work_ref": work} if actor is RUNTIME else {})),
    )


def unlink(relation_id: str) -> SceneCommand:
    return cmd(SceneOp.UNLINK, RUNTIME, relation_id=relation_id)


def many(*object_ids: str, actor=USER) -> SceneCommand:
    return cmd(SceneOp.ARCHIVE_MANY, actor, object_ids=tuple(object_ids))


def lifecycle_scene() -> SceneSnapshot:
    """Étoiles de chaque état, signaux vivant / retiré / orphelin, objets du cerveau et de l'utilisateur.

    - `claude:failed` échoué, signal vivant `attention!claude:failed` ;
    - `claude:interrupted` interrompu, signal **retiré** (lien délié, même travail) ;
    - `claude:done` terminé, `job:cancelled` annulé ;
    - `claude:running`, `claude:pending`, `claude:blocked` (signal vivant), `claude:unknown` ;
    - `claude:gone` échoué puis archivé : la cascade a emporté `attention!claude:gone` ;
    - `note` : attention du cerveau reliée par `explains` à `claude:failed` ;
    - `mine` : attention de l'utilisateur ; `art` : artefact du cerveau, relié par
      `explains` à `claude:running` (Slice 07 : un artefact relié n'est jamais pris) ;
    - `rel-parent` : `parent_of` runtime `claude:done` → `claude:failed`.
    """

    base = SceneSnapshot(scene_id="scene-08")
    return run(
        base,
        star("claude:failed", exec_state=ExecState.FAILED, work_ref=ref("failed")),
        signal("attention!claude:failed", "claude:failed", ref("failed")),
        star("claude:interrupted", exec_state=ExecState.INTERRUPTED, work_ref=ref("interrupted")),
        signal("attention!claude:interrupted", "claude:interrupted", ref("interrupted"), category="interrupted"),
        unlink("attention!claude:interrupted"),
        star("claude:done", exec_state=ExecState.COMPLETED, work_ref=ref("done")),
        star("job:cancelled", kind=SceneObjectKind.JOB, exec_state=ExecState.CANCELLED, work_ref=ref("cancelled", "job")),
        star("claude:running", work_ref=ref("running")),
        star("claude:pending", exec_state=ExecState.PENDING, work_ref=ref("pending")),
        star("claude:blocked", exec_state=ExecState.BLOCKED, work_ref=ref("blocked")),
        signal("attention!claude:blocked", "claude:blocked", ref("blocked"), category="blocked"),
        star("claude:unknown", exec_state=ExecState.UNKNOWN, work_ref=ref("unknown")),
        star("claude:gone", exec_state=ExecState.FAILED, work_ref=ref("gone")),
        signal("attention!claude:gone", "claude:gone", ref("gone")),
        cmd(SceneOp.ARCHIVE, USER, object_id="claude:gone"),  # avant Slice 08 le signal restait : ici la cascade l'emporte
        upsert(BRAIN, "note", kind=SceneObjectKind.ATTENTION, category="note"),
        cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("note-explains", RelationKind.EXPLAINS, "note", "claude:failed")),
        upsert(USER, "mine", kind=SceneObjectKind.ATTENTION, category="note"),
        upsert(BRAIN, "art", kind=SceneObjectKind.ARTIFACT, category="research"),
        cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("art-explains", RelationKind.EXPLAINS, "art", "claude:running")),
        cmd(SceneOp.LINK, RUNTIME, relation=SceneRelation("rel-parent", RelationKind.PARENT_OF, "claude:done", "claude:failed")),
    )


def with_orphan(snapshot: SceneSnapshot) -> SceneSnapshot:
    """Signal runtime orphelin, comme une scène d'avant Slice 08 le laisse après un archivage d'étoile."""

    orphan = SceneObject(
        "attention!claude:old", SceneObjectKind.ATTENTION, "failed", SceneConstraints(PlacedBy.RUNTIME), RUNTIME,
        exec_state=ExecState.FAILED, work_ref=ref("old"),
    )
    return SceneSnapshot(
        scene_id=snapshot.scene_id, revision=snapshot.revision, objects=(*snapshot.objects, orphan),
        relations=snapshot.relations, archived_ids=(*snapshot.archived_ids, "claude:old"),
    )


# --- cascade ------------------------------------------------------------------


def test_archiving_a_star_takes_its_live_signal_in_the_same_revision_signal_first():
    before = lifecycle_scene()
    update = apply_scene_command(before, cmd(SceneOp.ARCHIVE, USER, object_id="claude:failed"))
    assert update.outcome is APPLIED
    after = update.snapshot
    assert after.revision == before.revision + 1
    assert [op.op for op in update.patch.ops] == [PatchOpKind.ARCHIVE_OBJECT] * 2 + [PatchOpKind.DELETE_RELATION] * 3
    assert [op.object.object_id for op in update.patch.ops[:2]] == ["attention!claude:failed", "claude:failed"]
    # Pierre tombale de l'étoile la plus récente : la dernière oubliée.
    assert after.archived_ids[-2:] == ("attention!claude:failed", "claude:failed")
    assert {op.relation_id for op in update.patch.ops[2:]} == {"attention!claude:failed", "note-explains", "rel-parent"}
    # Le signal du cerveau n'est pas un signal runtime : il reste, sans lien.
    assert after.get_object("note") is not None
    assert apply_scene_patch(before, ScenePatch.from_payload(json.loads(json.dumps(update.patch.to_payload())))) == after


def test_archiving_a_star_takes_its_retired_signal_found_by_work_ref():
    before = lifecycle_scene()
    assert before.get_relation("attention!claude:interrupted") is None  # retiré : plus de lien
    update = apply_scene_command(before, cmd(SceneOp.ARCHIVE, USER, object_id="claude:interrupted"))
    assert update.outcome is APPLIED
    assert [op.object.object_id for op in update.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT] == [
        "attention!claude:interrupted", "claude:interrupted",
    ]


def test_the_pre_slice08_leak_is_gone_archiving_a_star_leaves_no_orphan_signal():
    scene = lifecycle_scene()
    assert scene.is_archived("claude:gone") and scene.is_archived("attention!claude:gone")
    owners = signal_owners(scene)
    assert all(owner is not None for owner in owners.values()), owners


def test_a_live_signal_is_matched_by_its_link_even_with_another_work_ref():
    scene = run(
        SceneSnapshot(scene_id="s"),
        star("claude:a", exec_state=ExecState.FAILED, work_ref=ref("a")),
        signal("sig-a", "claude:a", ref("elsewhere")),
    )
    assert runtime_signals_of(scene, "claude:a") == ("sig-a",)
    update = apply_scene_command(scene, cmd(SceneOp.ARCHIVE, USER, object_id="claude:a"))
    assert update.snapshot.objects == ()


def test_brain_and_user_attention_are_never_cascaded_and_a_signal_archive_keeps_its_star():
    scene = run(
        lifecycle_scene(),
        signal("brain-sig", "claude:done", None, actor=BRAIN, category="note"),
        signal("user-sig", "claude:done", None, actor=USER, category="note"),
    )
    assert runtime_signals_of(scene, "claude:done") == ()
    done = apply_scene_command(scene, cmd(SceneOp.ARCHIVE, USER, object_id="claude:done"))
    assert [op.object.object_id for op in done.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT] == ["claude:done"]
    assert done.snapshot.get_object("brain-sig") is not None and done.snapshot.get_object("user-sig") is not None
    only_signal = apply_scene_command(scene, cmd(SceneOp.ARCHIVE, USER, object_id="attention!claude:failed"))
    assert [op.object.object_id for op in only_signal.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT] == ["attention!claude:failed"]
    assert only_signal.snapshot.get_object("claude:failed") is not None
    # Non-étoiles : aucune cascade, même pour un objet d'id runtime.
    assert runtime_signals_of(scene, "art") == () and runtime_signals_of(scene, "absent") == ()


@pytest.mark.parametrize("actor", [BRAIN, RUNTIME])
def test_the_cascade_gives_brain_and_runtime_no_archive_right(actor):
    before = lifecycle_scene()
    update = apply_scene_command(before, cmd(SceneOp.ARCHIVE, actor, object_id="claude:failed"))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.OP_NOT_ALLOWED)
    assert_unchanged(before, update)


# --- archive_many : autorité --------------------------------------------------


def test_archive_many_is_a_user_only_op_in_the_matrix():
    assert SceneOp.ARCHIVE_MANY in ALLOWED_SCENE_OPS[USER]
    assert SceneOp.ARCHIVE_MANY not in ALLOWED_SCENE_OPS[BRAIN]
    assert SceneOp.ARCHIVE_MANY not in ALLOWED_SCENE_OPS[RUNTIME]


@pytest.mark.parametrize("actor", [BRAIN, RUNTIME])
@pytest.mark.parametrize("object_ids", [("claude:done",), ("absent",), ("art", "claude:running")])
def test_archive_many_is_refused_to_brain_and_runtime_whatever_the_ids(actor, object_ids):
    before = lifecycle_scene()
    update = apply_scene_command(before, many(*object_ids, actor=actor))
    assert (update.outcome, update.reason) == (REJECTED, SceneRefusal.OP_NOT_ALLOWED)
    assert_unchanged(before, update)


# --- archive_many : règle ------------------------------------------------------


def test_bulk_archive_takes_every_terminal_star_with_its_signals_in_one_revision():
    before = with_orphan(lifecycle_scene())
    selection = ("claude:failed", "claude:interrupted", "claude:done", "job:cancelled", "attention!claude:old")
    update = apply_scene_command(before, many(*selection))
    assert update.outcome is APPLIED, update.reason
    assert update.snapshot.revision == before.revision + 1
    archived = [op.object.object_id for op in update.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT]
    assert archived == [
        "attention!claude:failed", "claude:failed", "attention!claude:interrupted", "claude:interrupted",
        "claude:done", "job:cancelled", "attention!claude:old",
    ]
    remaining = ids(update.snapshot)
    assert remaining == {"claude:running", "claude:pending", "claude:blocked", "attention!claude:blocked", "claude:unknown", "note", "mine", "art"}
    assert set(update.snapshot.relations) == {update.snapshot.get_relation("attention!claude:blocked"),
                                              update.snapshot.get_relation("art-explains")}
    assert all(owner is not None for owner in signal_owners(update.snapshot).values())
    assert apply_scene_patch(before, ScenePatch.from_payload(json.loads(json.dumps(update.patch.to_payload())))) == update.snapshot


def test_signals_listed_with_their_star_are_accepted_and_archived_once():
    before = lifecycle_scene()
    update = apply_scene_command(before, many("attention!claude:failed", "claude:failed"))
    assert update.outcome is APPLIED
    archived = [op.object.object_id for op in update.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT]
    assert sorted(archived) == ["attention!claude:failed", "claude:failed"]


@pytest.mark.parametrize(
    "selection",
    [
        ("claude:done", "claude:running"),  # travail en cours
        ("claude:pending",),
        ("claude:blocked",),
        ("claude:unknown",),  # état inconnu : pas terminé
        ("attention!claude:blocked",),  # signal d'un travail bloqué
        ("attention!claude:failed",),  # signal sans son étoile dans la sélection
        ("claude:done", "art"),  # artefact du cerveau encore relié (Slice 07)
        ("claude:done", "note"),  # attention du cerveau
        ("mine",),  # attention de l'utilisateur
    ],
)
def test_one_non_archivable_id_refuses_the_whole_selection(selection):
    before = lifecycle_scene()
    update = apply_scene_command(before, many(*selection))
    assert (update.outcome, update.reason) == (INVALID, SceneRefusal.NOT_BULK_ARCHIVABLE)
    assert_unchanged(before, update)


def test_an_unknown_id_refuses_the_whole_selection_and_archived_ids_are_skipped():
    before = lifecycle_scene()
    unknown = apply_scene_command(before, many("claude:done", "never-seen"))
    assert (unknown.outcome, unknown.reason) == (INVALID, SceneRefusal.UNKNOWN_OBJECT)
    assert_unchanged(before, unknown)
    # Un autre onglet a déjà archivé `claude:done` : le reste s'applique, le déjà-archivé ne compte pas.
    raced = run(before, cmd(SceneOp.ARCHIVE, USER, object_id="claude:done"))
    update = apply_scene_command(raced, many("claude:done", "job:cancelled"))
    assert update.outcome is APPLIED
    assert [op.object.object_id for op in update.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT] == ["job:cancelled"]
    again = apply_scene_command(update.snapshot, many("claude:done", "job:cancelled"))
    assert again.outcome is DUPLICATE and again.patch is None


def test_the_rule_is_the_public_bulk_archivable_helper():
    scene = with_orphan(lifecycle_scene())
    owners = signal_owners(scene)
    assert owners["attention!claude:old"] is None
    assert owners["attention!claude:interrupted"] == "claude:interrupted"
    expected = {"claude:failed", "claude:interrupted", "claude:done", "job:cancelled", "attention!claude:old"}
    stars = frozenset({"claude:failed", "claude:interrupted"})
    assert {item.object_id for item in scene.objects if bulk_archivable(scene, item.object_id)} == expected
    assert bulk_archivable(scene, "attention!claude:failed", stars) and not bulk_archivable(scene, "attention!claude:failed")
    assert not bulk_archivable(scene, "absent")
    assert set(TERMINAL_EXEC_STATES) == {ExecState(status.value) for status in WorkStatus if status.is_terminal}


# --- archive_many : bornes et fil ----------------------------------------------


def test_archive_many_command_bounds_and_wire():
    with pytest.raises(ValueError, match="between 1 and"):
        SceneCommand(op=SceneOp.ARCHIVE_MANY, actor=USER, object_ids=())
    with pytest.raises(ValueError, match="between 1 and"):
        SceneCommand(op=SceneOp.ARCHIVE_MANY, actor=USER, object_ids=tuple(f"id-{index}" for index in range(MAX_ARCHIVE_MANY_IDS + 1)))
    with pytest.raises(ValueError, match="unique"):
        many("a", "a")
    with pytest.raises(TypeError, match="tuple"):
        SceneCommand(op=SceneOp.ARCHIVE_MANY, actor=USER, object_ids=["a"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="object_ids"):
        many("x" * 129)
    with pytest.raises(ValueError, match="does not take"):
        SceneCommand(op=SceneOp.ARCHIVE, actor=USER, object_id="a", object_ids=("a",))
    with pytest.raises(ValueError, match="requires"):
        SceneCommand(op=SceneOp.ARCHIVE_MANY, actor=USER, object_id="a")
    command = many(*(f"claude:{index}" for index in range(MAX_ARCHIVE_MANY_IDS)))
    wire = json.loads(json.dumps(command.to_payload()))
    assert wire["object_ids"][0] == "claude:0" and len(wire["object_ids"]) == MAX_ARCHIVE_MANY_IDS
    assert SceneCommand.from_payload(wire) == command
    # Liste trop longue refusée avant de décoder quoi que ce soit.
    hostile = {**wire, "object_ids": [{"not": "an id"}] * (MAX_ARCHIVE_MANY_IDS + 1)}
    with pytest.raises(ValueError, match=f"at most {MAX_ARCHIVE_MANY_IDS}"):
        SceneCommand.from_payload(hostile)
    with pytest.raises(TypeError, match="list"):
        SceneCommand.from_payload({**wire, "object_ids": "claude:0"})
    # Une commande d'avant Slice 08 se décode toujours à l'identique.
    old = {"schema_version": 1, "op": "archive", "actor": "user", "object_id": "claude:done"}
    assert SceneCommand.from_payload(old).to_payload() == old


def test_a_full_scene_bulk_archive_fits_one_patch_and_replays_exactly():
    objects = tuple(
        SceneObject(f"claude:{index}", SceneObjectKind.AGENT, "agent", SceneConstraints(PlacedBy.RUNTIME), RUNTIME,
                    exec_state=ExecState.COMPLETED, work_ref=ref(str(index)))
        for index in range(MAX_SCENE_OBJECTS)
    )
    relations = tuple(
        SceneRelation(f"r{index}", RelationKind.PARENT_OF, "claude:0", f"claude:{1 + index % (MAX_SCENE_OBJECTS - 1)}")
        for index in range(MAX_SCENE_RELATIONS)
    )
    full = SceneSnapshot("s", revision=9, objects=objects, relations=relations)
    update = apply_scene_command(full, many(*(item.object_id for item in objects)))
    assert update.outcome is APPLIED
    assert len(update.patch.ops) == MAX_SCENE_OBJECTS + MAX_SCENE_RELATIONS == MAX_PATCH_OPS
    assert update.snapshot.objects == () and len(update.snapshot.archived_ids) == MAX_SCENE_OBJECTS
    assert apply_scene_patch(full, ScenePatch.from_payload(json.loads(json.dumps(update.patch.to_payload())))) == update.snapshot


def test_bulk_archive_keeps_tombstone_eviction_deterministic():
    old = tuple(f"old-{index}" for index in range(MAX_ARCHIVED_IDS))
    scene = run(
        SceneSnapshot("s", archived_ids=old),
        star("claude:a", exec_state=ExecState.FAILED, work_ref=ref("a")),
        signal("attention!claude:a", "claude:a", ref("a")),
    )
    update = apply_scene_command(scene, many("claude:a"))
    assert update.snapshot.archived_ids[-2:] == ("attention!claude:a", "claude:a")
    assert len(update.snapshot.archived_ids) == MAX_ARCHIVED_IDS and "old-0" not in update.snapshot.archived_ids


# --- avec la projection runtime réelle ------------------------------------------


async def test_an_archived_failed_star_and_its_signal_never_resurrect_after_more_work_updates():
    async with Stack() as stack:
        await stack.observe(obs("a"), obs("a", WorkStatus.FAILED, at=1, error_class="boom", summary="raté"))
        before = await stack.snapshot()
        assert signal_object_id("claude:a") in ids(before)
        update = await stack.scene.apply(cmd(SceneOp.ARCHIVE, USER, object_id="claude:a"))
        assert update.changed
        archived = await stack.snapshot()
        assert archived.objects == () and archived.relations == ()
        assert archived.archived_ids == (signal_object_id("claude:a"), "claude:a")
        # Un producteur rejoue : mise à jour, nouveau signal, réconciliation complète.
        await stack.observe(obs("a", WorkStatus.FAILED, at=2, error_class="again", summary="encore"))
        assert await stack.projector._reconcile("test")
        await settled(stack.projector)
        assert await stack.snapshot() == archived
    assert stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == []


async def test_bulk_archive_from_a_saturated_scene_lets_deferred_stars_catch_up():
    async with Stack(repository=nearly_full(4), work_max_items=2) as stack:
        for index in range(2):
            await stack.observe(obs(f"done{index}"), obs(f"done{index}", WorkStatus.FAILED, at=1, error_class="boom"))
        full = await stack.snapshot()
        assert len(full.objects) == MAX_SCENE_OBJECTS  # 510 artefacts, 2 étoiles échouées et leurs 2 signaux
        for index in range(3):
            await stack.observe(obs(f"late{index}"), obs(f"late{index}", WorkStatus.COMPLETED, at=1))
        assert stack.projector.pending_count >= 3
        # Slice 07 : les 508 artefacts de remplissage, jamais reliés, sont des orphelins archivables à part.
        assert all(bulk_archivable(full, item.object_id) for item in full.objects if item.kind is SceneObjectKind.ARTIFACT)
        selection = [item.object_id for item in full.objects
                     if item.kind is not SceneObjectKind.ARTIFACT and bulk_archivable(full, item.object_id)]
        assert sorted(selection) == ["claude:done0", "claude:done1"]
        update = await stack.scene.apply(many(*selection))
        assert update.changed and update.snapshot.revision == full.revision + 1

        async def caught_up() -> bool:
            return stack.projector.pending_count == 0

        await until_true(caught_up)
        await settled(stack.projector)
        after = await stack.snapshot()
    assert {"claude:late0", "claude:late1", "claude:late2"} <= ids(after)
    assert not {"claude:done0", "claude:done1"} & ids(after)
    assert stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == []


async def test_a_bulk_archive_is_one_durable_sqlite_commit_with_every_object_in_history(tmp_path):
    from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
    from tests.unit.test_scene_service import started

    path = tmp_path / "scene.sqlite3"
    service, _, _ = await started(SQLiteSceneRepository(path))
    try:
        for command in (
            star("claude:a", exec_state=ExecState.FAILED, work_ref=ref("a")),
            signal("attention!claude:a", "claude:a", ref("a")),
            star("job:b", kind=SceneObjectKind.JOB, exec_state=ExecState.COMPLETED, work_ref=ref("b", "job")),
        ):
            assert (await service.apply(command)).changed
        update = await service.apply(many("claude:a", "job:b"))
        assert update.changed
        expected = update.snapshot
    finally:
        await service.close()
    again, _, _ = await started(SQLiteSceneRepository(path))
    try:
        assert await again.snapshot() == expected
        history = await again.archived_history()
        assert {(entry.object.object_id, entry.revision) for entry in history} == {
            ("attention!claude:a", expected.revision), ("claude:a", expected.revision), ("job:b", expected.revision),
        }
    finally:
        await again.close()
