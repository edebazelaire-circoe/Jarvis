"""Validateur de prefabs de `SceneService` et `apply_if` (handoff jarvis-scene-window-prefab-foundation, Slice 04).

Vrai magasin SQLite et vrai `PrefabService` sur dossiers temporaires. Contrat :
`docs/scene-model.md` › *Prefab windows*. Ce qui doit tenir :

- un bloc valide est commis ; une version inconnue, des entrées invalides ou
  aucun validateur -> `invalid/prefab_invalid` avec `detail`, révision inchangée ;
- un bloc inchangé (annotation par `patch_selection`, déplacement) n'est pas
  revalidé : la fenêtre bouge encore si sa définition a disparu ;
- le bloc survit au rechargement depuis `scene.sqlite3` ;
- `apply_if` exécute son plan sous le verrou : `None` n'écrit rien.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.prefab_service import PrefabService
from jarvis.core.scene_service import (
    PREFAB_CATALOG_UNAVAILABLE, SCENE_COMMAND_REFUSED_KIND, SCENE_PREFAB_VALIDATOR_FAILED_KIND, SceneService,
    SceneState,
)
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneCommandOutcome, SceneGeometry, SceneObjectFields,
    SceneObjectKind, SceneOp, ScenePayload, ScenePrefabRef, SceneRefusal,
)
from jarvis.domain.scene_batch import SelectionChanges
from jarvis.domain.scene_selection import SceneSelection
from jarvis.protocol import scene_wire
from jarvis.runtime.scene_view import decode_command_response
from tests.fakes.prefabs import install_version


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for k, _, data in self.events if k == kind]


class CountingValidator:
    """Enveloppe du vrai service : compte les validations."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls: list[str] = []

    async def validate_instance(self, ref):
        self.calls.append(f"{ref.prefab_id}@{ref.version}")
        return await self.inner.validate_instance(ref)


@pytest.fixture
def library(tmp_path: Path) -> tuple[Path, Path]:
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    install_version(data / LIBRARY_DIR, "test.counter")  # id custom : bibliothèque de la racine de données
    return package, data


async def started(path: Path, validator=None) -> tuple[SceneService, Recorder]:
    recorder = Recorder()
    service = SceneService(SQLiteSceneRepository(path), diagnostics=recorder, prefab_validator=validator)
    assert (await service.start()).state is SceneState.READY
    return service, recorder


def block(**changes) -> ScenePrefabRef:
    return ScenePrefabRef(**{"prefab_id": "test.counter", "version": 1, "props": {"label": "Clics"},
                             "data": {"count": 3}, **changes})


def create(object_id: str = "win-1", prefab: ScenePrefabRef | None = None, actor=SceneActor.USER) -> SceneCommand:
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=actor, object_id=object_id, fields=SceneObjectFields(
        kind=SceneObjectKind.WINDOW, category="note", representation=Representation.WINDOW,
        geometry=SceneGeometry(0, 0, 40, 24), payload=ScenePayload(title="Compteur", prefab=prefab or block())))


async def test_a_valid_block_is_committed(tmp_path, library):
    validator = CountingValidator(PrefabService(FilePrefabLibrary(*library)))
    service, _ = await started(tmp_path / "scene.sqlite3", validator)
    update = await service.apply(create())
    assert update.outcome is SceneCommandOutcome.APPLIED and update.snapshot.revision == 1
    assert (await service.snapshot()).get_object("win-1").payload.prefab == block()
    assert validator.calls == ["test.counter@1"]
    await service.close()


@pytest.mark.parametrize("bad, needle", [
    (block(version=2), "win-1: unknown_version: test.counter has no version 2"),
    (block(prefab_id="test.nothing"), "win-1: unknown_prefab: no prefab test.nothing"),
    (block(data={"count": -1}), "win-1: invalid_definition: test.counter@1: data.count"),
    (block(data={}), "win-1: invalid_definition: test.counter@1: data.count"),
    (block(props={"mode": "huge"}), "win-1: invalid_definition: test.counter@1: props.mode"),
])
async def test_an_invalid_block_is_refused_with_a_detail_and_nothing_is_committed(tmp_path, library, bad, needle):
    service, recorder = await started(tmp_path / "scene.sqlite3", PrefabService(FilePrefabLibrary(*library)))
    update = await service.apply(create(prefab=bad))
    assert update.outcome is SceneCommandOutcome.INVALID and update.reason is SceneRefusal.PREFAB_INVALID
    assert update.detail.startswith(needle) and len(update.detail) <= 300
    assert update.patch is None and update.snapshot.revision == 0
    assert (await service.snapshot()).revision == 0 and (await service.snapshot()).get_object("win-1") is None
    [logged] = recorder.of(SCENE_COMMAND_REFUSED_KIND)
    assert logged["reason"] == "prefab_invalid" and logged["detail"] == update.detail
    # Le fil HTTP porte le détail et le client du Control Center l'accepte.
    body = scene_wire.command_body(update, epoch=service.epoch)
    assert body["detail"] == update.detail and decode_command_response(body)["detail"] == update.detail
    await service.close()


async def test_without_a_validator_any_new_or_changed_block_is_refused(tmp_path):
    service, _ = await started(tmp_path / "scene.sqlite3")
    update = await service.apply(create())
    assert (update.outcome, update.reason) == (SceneCommandOutcome.INVALID, SceneRefusal.PREFAB_INVALID)
    assert update.detail == f"win-1: {PREFAB_CATALOG_UNAVAILABLE}" and update.snapshot.revision == 0
    # Une fenêtre legacy passe toujours, et son fil de réponse n'a pas de `detail`.
    legacy = SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="win-2", fields=SceneObjectFields(
        kind=SceneObjectKind.WINDOW, category="note", payload=ScenePayload(title="Note")))
    applied = await service.apply(legacy)
    assert applied.outcome is SceneCommandOutcome.APPLIED
    assert "detail" not in scene_wire.command_body(applied, epoch=service.epoch)
    await service.close()


async def test_a_validator_that_raises_refuses_closed_and_is_logged(tmp_path):
    class Broken:
        async def validate_instance(self, ref):
            raise OSError("disk gone")

    service, recorder = await started(tmp_path / "scene.sqlite3", Broken())
    update = await service.apply(create())
    assert update.reason is SceneRefusal.PREFAB_INVALID and update.detail.endswith("prefab catalog unavailable: OSError")
    [failure] = recorder.of(SCENE_PREFAB_VALIDATOR_FAILED_KIND)
    assert failure["error"] == "OSError: disk gone" and failure["prefab"] == "test.counter@1"
    await service.close()


async def test_an_unchanged_block_is_not_revalidated(tmp_path, library):
    package, data = library
    validator = CountingValidator(PrefabService(FilePrefabLibrary(package, data)))
    service, _ = await started(tmp_path / "scene.sqlite3", validator)
    await service.apply(create())
    validator.calls.clear()
    # La définition disparaît : déplacer, épingler, annoter marchent encore.
    validator.inner = type("Gone", (), {"validate_instance": staticmethod(_refuse_everything)})()
    moved = await service.apply(SceneCommand(op=SceneOp.SET_GEOMETRY, actor=SceneActor.USER, object_id="win-1",
                                             geometry=SceneGeometry(10, 10, 40, 24)))
    pinned = await service.apply(SceneCommand(op=SceneOp.PIN, actor=SceneActor.USER, object_id="win-1"))
    annotated = await service.apply(SceneCommand(
        op=SceneOp.PATCH_SELECTION, actor=SceneActor.BRAIN, selection=SceneSelection(ids=("win-1",)),
        changes=SelectionChanges(annotation="à relire")))
    assert [u.outcome for u in (moved, pinned, annotated)] == [SceneCommandOutcome.APPLIED] * 3
    current = (await service.snapshot()).get_object("win-1")
    assert current.payload.annotation == "à relire" and current.payload.prefab == block()
    assert validator.calls == []
    # Changer le bloc, lui, revalide (et la définition disparue le refuse).
    changed = await service.apply(SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.USER, object_id="win-1",
                                               fields=SceneObjectFields(payload=ScenePayload(
                                                   title="Compteur", prefab=block(data={"count": 4})))))
    assert changed.reason is SceneRefusal.PREFAB_INVALID and validator.calls == ["test.counter@1"]
    await service.close()


async def _refuse_everything(ref):
    from jarvis.ports.prefabs import InstanceValidation, PrefabStoreErrorCode
    return InstanceValidation(False, code=PrefabStoreErrorCode.UNKNOWN_PREFAB, detail="gone")


async def test_reloading_from_sqlite_keeps_the_block(tmp_path, library):
    path = tmp_path / "scene.sqlite3"
    service, _ = await started(path, PrefabService(FilePrefabLibrary(*library)))
    await service.apply(create(prefab=block(data={"count": 5, "history": [{"delta": 2, "ratio": 0.25}]})))
    await service.close()
    again, _ = await started(path)  # aucun validateur : charger ne revalide rien
    reloaded = (await again.snapshot()).get_object("win-1")
    assert reloaded.payload.prefab == block(data={"count": 5, "history": [{"delta": 2, "ratio": 0.25}]})
    await again.close()


async def test_apply_if_runs_the_plan_under_the_lock(tmp_path, library):
    service, _ = await started(tmp_path / "scene.sqlite3", PrefabService(FilePrefabLibrary(*library)))
    await service.apply(create())
    seen: list[int] = []

    def nothing(snapshot):
        seen.append(snapshot.revision)
        return None

    assert await service.apply_if(nothing) is None and seen == [1]
    assert (await service.snapshot()).revision == 1

    # Deux plans concurrents : le second voit l'écriture du premier, jamais l'état d'avant.
    def bump(snapshot):
        current = snapshot.get_object("win-1").payload
        count = current.prefab.data["count"]
        seen.append(count)
        return SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.USER, object_id="win-1",
                            fields=SceneObjectFields(payload=ScenePayload(
                                title=current.title, prefab=block(data={"count": count + 1}))))

    first, second = await asyncio.gather(service.apply_if(bump), service.apply_if(bump))
    assert seen[1:] == [3, 4] and (first.snapshot.revision, second.snapshot.revision) == (2, 3)
    assert (await service.snapshot()).get_object("win-1").payload.prefab.data == {"count": 5}

    def broken(snapshot):
        raise RuntimeError("plan failed")

    with pytest.raises(RuntimeError, match="plan failed"):
        await service.apply_if(broken)
    assert (await service.snapshot()).revision == 3
    await service.close()
