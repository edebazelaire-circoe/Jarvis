"""Stockage SQLite de la scène (handoff jarvis-constellation-scene-runtime, Slice 02).

Ce qui doit tenir :

- l'état écrit après chaque commande se relit à l'identique, ordre des tuples
  compris, y compris après fermeture et réouverture du fichier ;
- les objets archivés quittent la scène active mais restent lisibles dans
  l'historique ; les pierres tombales survivent au redémarrage et suivent la
  même éviction que le domaine ;
- une base plus récente, inconnue ou corrompue est refusée avec un code
  stable, et le fichier n'est jamais modifié ;
- une écriture est atomique : un échec ou une révision divergente ne laisse
  rien d'écrit.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters import sqlite_scene
from jarvis.adapters.sqlite_scene import MAX_HISTORY_READ, SQLiteSceneRepository
from jarvis.domain import scene as scene_domain
from jarvis.domain.scene import (
    SCENE_SCHEMA_VERSION,
    Disposition,
    ExecState,
    PatchOpKind,
    RelationKind,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneGeometry,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePatch,
    ScenePatchOp,
    ScenePayload,
    SceneRelation,
    SceneSnapshot,
    WorkRef,
    apply_scene_command,
)
from jarvis.ports.scene import SceneRepository, SceneStoreError, SceneStoreErrorCode

RUNTIME, BRAIN, USER = SceneActor.RUNTIME, SceneActor.BRAIN, SceneActor.USER


def upsert(actor: SceneActor, object_id: str, **fields) -> SceneCommand:
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=actor, object_id=object_id, fields=SceneObjectFields(**fields))


def star(object_id: str, kind: SceneObjectKind = SceneObjectKind.AGENT) -> SceneCommand:
    return upsert(RUNTIME, object_id, kind=kind, category=kind.value, exec_state=ExecState.RUNNING,
                  work_ref=WorkRef(source="claude", external_id=object_id))


def archive(object_id: str) -> SceneCommand:
    return SceneCommand(op=SceneOp.ARCHIVE, actor=USER, object_id=object_id)


def scenario() -> list[SceneCommand]:
    """Toutes les formes d'opérations de patch : put, relation, suppression, archivage."""

    return [
        star("star-a"),
        star("star-b", SceneObjectKind.JOB),
        star("star-c"),
        SceneCommand(op=SceneOp.LINK, actor=RUNTIME, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b")),
        SceneCommand(op=SceneOp.LINK, actor=RUNTIME, relation=SceneRelation("rel-bc", RelationKind.PARENT_OF, "star-b", "star-c")),
        SceneCommand(op=SceneOp.SET_GEOMETRY, actor=USER, object_id="star-a", geometry=SceneGeometry(10.5, -20.25, 40, 40)),
        SceneCommand(op=SceneOp.PIN, actor=USER, object_id="star-a"),
        upsert(BRAIN, "art-1", kind=SceneObjectKind.ARTIFACT, category="research",
               payload=ScenePayload(title="Recherche", summary="ligne 1\nligne 2 — é")),
        SceneCommand(op=SceneOp.LINK, actor=BRAIN, relation=SceneRelation("rel-art", RelationKind.EXPLAINS, "art-1", "star-c", layer=70)),
        SceneCommand(op=SceneOp.ATTACH_SIGNAL, actor=RUNTIME, object_id="sig-1", target_id="star-c",
                     fields=SceneObjectFields(category="error")),
        # Remplacement : star-a garde sa place dans l'ordre des objets.
        upsert(RUNTIME, "star-a", exec_state=ExecState.COMPLETED),
        SceneCommand(op=SceneOp.UNLINK, actor=RUNTIME, relation_id="rel-ab"),
        # Archivage : star-b quitte la scène, rel-bc tombe avec lui.
        archive("star-b"),
        SceneCommand(op=SceneOp.SET_VISIBILITY, actor=BRAIN, object_id="art-1", visibility=scene_domain.Visibility.HIDDEN),
    ]


async def commit_all(repository: SQLiteSceneRepository, snapshot: SceneSnapshot, commands) -> SceneSnapshot:
    for command in commands:
        update = apply_scene_command(snapshot, command)
        assert update.outcome is SceneCommandOutcome.APPLIED, (command, update.reason)
        await repository.commit(snapshot, update.patch, update.snapshot)
        snapshot = update.snapshot
        assert await repository.load() == snapshot
    return snapshot


async def fresh(path: Path) -> tuple[SQLiteSceneRepository, SceneSnapshot]:
    repository = SQLiteSceneRepository(path)
    await repository.initialize()
    assert await repository.load() is None
    return repository, await repository.create("scene-test")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def expect_refusal(path: Path, code: SceneStoreErrorCode, match: str) -> None:
    repository = SQLiteSceneRepository(path)
    with pytest.raises(SceneStoreError, match=match) as caught:
        await repository.initialize()
        await repository.load()
    assert caught.value.code is code
    await repository.close()


def test_repository_matches_its_port():
    for name in ("initialize", "load", "create", "commit", "archived_history", "close"):
        assert callable(getattr(SQLiteSceneRepository, name)), name
        assert name in SceneRepository.__dict__


async def test_state_round_trips_after_each_commit_and_after_reopen(tmp_path):
    path = tmp_path / "state" / "scene.sqlite3"
    repository, snapshot = await fresh(path)
    snapshot = await commit_all(repository, snapshot, scenario())
    await repository.close()

    assert [item.object_id for item in snapshot.objects] == ["star-a", "star-c", "art-1", "sig-1"]
    assert snapshot.archived_ids == ("star-b",)
    reopened = SQLiteSceneRepository(path)
    await reopened.initialize()
    loaded = await reopened.load()
    assert loaded == snapshot
    assert loaded.revision == len(scenario())
    assert loaded.get_object("star-a").geometry == SceneGeometry(10.5, -20.25, 40, 40)
    assert loaded.get_relation("rel-art").layer == 70
    # La pierre tombale survit : le domaine refuse toujours de ressusciter star-b.
    assert apply_scene_command(loaded, star("star-b", SceneObjectKind.JOB)).reason is scene_domain.SceneRefusal.OBJECT_ARCHIVED
    history = await reopened.archived_history()
    assert [(entry.object.object_id, entry.revision) for entry in history] == [("star-b", 13)]
    assert history[0].object.disposition is Disposition.ARCHIVED
    assert history[0].object.kind is SceneObjectKind.JOB
    assert await reopened.archived_history(object_id="star-a") == ()
    await reopened.close()


async def test_create_is_single_and_scene_id_is_stable(tmp_path):
    path = tmp_path / "scene.sqlite3"
    repository, snapshot = await fresh(path)
    with pytest.raises(SceneStoreError) as caught:
        await repository.create("another")
    assert caught.value.code is SceneStoreErrorCode.REVISION_CONFLICT
    await repository.close()
    reopened = SQLiteSceneRepository(path)
    await reopened.initialize()
    assert await reopened.load() == SceneSnapshot(scene_id="scene-test")
    await reopened.close()


async def test_tombstone_eviction_matches_the_domain_and_survives_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_domain, "MAX_ARCHIVED_IDS", 2)
    monkeypatch.setattr(sqlite_scene, "MAX_ARCHIVED_IDS", 2)
    path = tmp_path / "scene.sqlite3"
    repository, snapshot = await fresh(path)
    commands = [star(f"s{index}") for index in range(4)] + [archive(f"s{index}") for index in range(3)]
    # s0 oublié : son identifiant redevient libre et l'objet recréé passe en fin d'ordre.
    commands += [star("s0")]
    snapshot = await commit_all(repository, snapshot, commands)
    await repository.close()
    assert snapshot.archived_ids == ("s1", "s2")
    assert [item.object_id for item in snapshot.objects] == ["s3", "s0"]
    reopened = SQLiteSceneRepository(path)
    await reopened.initialize()
    assert await reopened.load() == snapshot
    assert [entry.object.object_id for entry in await reopened.archived_history()] == ["s2", "s1", "s0"]
    await reopened.close()


async def test_newer_schema_is_refused_and_the_file_is_left_untouched(tmp_path):
    path = tmp_path / "scene.sqlite3"
    repository, _ = await fresh(path)
    await repository.close()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schema_version SET version = 2")
    conn.close()
    before = digest(path)
    await expect_refusal(path, SceneStoreErrorCode.SCHEMA_NEWER, "schema 2 is newer than supported 1")
    assert digest(path) == before


@pytest.mark.parametrize(
    ("statement", "match"),
    [
        ("UPDATE schema_version SET version = 0", "schema 0 is unknown"),
        ("UPDATE schema_version SET version = 'one'", "schema_version is unreadable"),
        ("INSERT INTO schema_version(version) VALUES (1)", r"schema_version is unreadable \(2 rows\)"),
        ("DROP TABLE schema_version", "no schema_version: not a scene database"),
    ],
)
async def test_unknown_schema_is_refused(tmp_path, statement, match):
    path = tmp_path / "scene.sqlite3"
    repository, _ = await fresh(path)
    await repository.close()
    with sqlite3.connect(path) as conn:
        conn.execute(statement)
    conn.close()
    before = digest(path)
    await expect_refusal(path, SceneStoreErrorCode.SCHEMA_UNKNOWN, match)
    assert digest(path) == before


@pytest.mark.parametrize(("version", "code", "match"), [
    (SCENE_SCHEMA_VERSION + 1, SceneStoreErrorCode.SCHEMA_NEWER, "newer than supported"),
    (0, SceneStoreErrorCode.SCHEMA_UNKNOWN, "unknown schema 0"),
])
async def test_stored_payload_wire_version_is_checked_on_load(tmp_path, version, code, match):
    path = tmp_path / "scene.sqlite3"
    repository, _ = await fresh(path)
    await repository.close()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE scene_meta SET wire_schema_version = ?", (version,))
    conn.close()
    await expect_refusal(path, code, match)


async def test_a_file_that_is_not_a_database_is_refused_as_corrupted(tmp_path):
    path = tmp_path / "scene.sqlite3"
    path.write_bytes(b"this is not a sqlite database\x00" * 200)
    before = digest(path)
    await expect_refusal(path, SceneStoreErrorCode.CORRUPTED, "unusable: DatabaseError")
    assert digest(path) == before


@pytest.mark.parametrize(
    ("statement", "match"),
    [
        ("UPDATE scene_objects SET data = '{' WHERE object_id = 'star-a'", "scene_objects row star-a"),
        ("UPDATE scene_objects SET data = json_set(data, '$.kind', 'comet') WHERE object_id = 'star-a'", "kind must be one of"),
        ("UPDATE scene_objects SET object_id = 'other' WHERE object_id = 'star-a'", "row other holds star-a"),
        ("DELETE FROM scene_objects WHERE object_id = 'star-c'", "must link active objects"),
        ("DELETE FROM scene_meta", "rows but no scene_meta"),
        ("DROP TABLE scene_history", r"lacks tables \['scene_history'\]"),
    ],
)
async def test_invalid_stored_rows_are_refused_as_corrupted(tmp_path, statement, match):
    path = tmp_path / "scene.sqlite3"
    repository, snapshot = await fresh(path)
    await commit_all(repository, snapshot, scenario()[:10])
    await repository.close()
    with sqlite3.connect(path) as conn:
        conn.execute(statement)
    conn.close()
    await expect_refusal(path, SceneStoreErrorCode.CORRUPTED, match)


async def test_commit_refuses_a_stale_revision_and_writes_nothing(tmp_path):
    repository, snapshot = await fresh(tmp_path / "scene.sqlite3")
    first = apply_scene_command(snapshot, star("star-a"))
    await repository.commit(snapshot, first.patch, first.snapshot)
    # Même patch rejoué depuis la révision 0 : le disque est déjà en 1.
    with pytest.raises(SceneStoreError, match="holds revision 1, Core expected revision 0") as caught:
        await repository.commit(snapshot, first.patch, first.snapshot)
    assert caught.value.code is SceneStoreErrorCode.REVISION_CONFLICT
    with pytest.raises(SceneStoreError, match="does not lead from revision"):
        await repository.commit(first.snapshot, first.patch, first.snapshot)
    assert await repository.load() == first.snapshot
    await repository.close()


async def test_a_failing_op_rolls_the_whole_revision_back(tmp_path):
    repository, snapshot = await fresh(tmp_path / "scene.sqlite3")
    snapshot = await commit_all(repository, snapshot, [star("star-a")])
    new_object = apply_scene_command(snapshot, star("star-b")).snapshot.get_object("star-b")
    patch = ScenePatch(
        revision=2,
        ops=(ScenePatchOp(PatchOpKind.PUT_OBJECT, object=new_object), ScenePatchOp(PatchOpKind.DELETE_RELATION, relation_id="missing")),
    )
    with pytest.raises(SceneStoreError, match="lacks deleted relation missing") as caught:
        await repository.commit(snapshot, patch, dataclasses.replace(snapshot, revision=2))
    assert caught.value.code is SceneStoreErrorCode.REVISION_CONFLICT
    assert await repository.load() == snapshot
    # Et la connexion reste utilisable : la transaction a bien été annulée.
    snapshot = await commit_all(repository, snapshot, [star("star-b")])
    assert snapshot.revision == 2
    await repository.close()


async def test_diverged_row_counts_abort_the_commit(tmp_path):
    repository, snapshot = await fresh(tmp_path / "scene.sqlite3")
    update = apply_scene_command(snapshot, star("star-a"))
    # Un résultat qui ne correspond pas à ce que le patch écrit.
    with pytest.raises(SceneStoreError, match="diverged from Core"):
        await repository.commit(snapshot, update.patch, dataclasses.replace(update.snapshot, objects=()))
    assert await repository.load() == snapshot
    await repository.close()


async def test_closed_or_unopened_repository_is_unavailable(tmp_path):
    repository = SQLiteSceneRepository(tmp_path / "scene.sqlite3")
    with pytest.raises(SceneStoreError) as caught:
        await repository.load()
    assert caught.value.code is SceneStoreErrorCode.UNAVAILABLE
    await repository.initialize()
    await repository.close()
    await repository.close()
    with pytest.raises(SceneStoreError, match="not initialized or already closed"):
        await repository.archived_history()


async def test_history_read_is_bounded(tmp_path):
    repository, _ = await fresh(tmp_path / "scene.sqlite3")
    for limit in (0, MAX_HISTORY_READ + 1, True, "5"):
        with pytest.raises(ValueError, match="limit must be an integer"):
            await repository.archived_history(limit=limit)
    await repository.close()


async def test_unopenable_location_is_a_storage_error(tmp_path):
    blocker = tmp_path / "state"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    repository = SQLiteSceneRepository(blocker / "scene.sqlite3")
    with pytest.raises(SceneStoreError, match="cannot be opened") as caught:
        await repository.initialize()
    assert caught.value.code is SceneStoreErrorCode.STORAGE_IO


async def test_payload_columns_are_plain_json_of_the_domain_wire_form(tmp_path):
    path = tmp_path / "scene.sqlite3"
    repository, snapshot = await fresh(path)
    snapshot = await commit_all(repository, snapshot, scenario()[:1])
    await repository.close()
    with sqlite3.connect(path) as conn:
        (data,) = conn.execute("SELECT data FROM scene_objects").fetchone()
        (version,) = conn.execute("SELECT version FROM schema_version").fetchone()
    conn.close()
    assert json.loads(data) == snapshot.objects[0].to_payload()
    assert version == 1
