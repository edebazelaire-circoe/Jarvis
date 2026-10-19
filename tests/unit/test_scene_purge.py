"""Purge définitive des objets archivés de la scène (demande de l'utilisateur du 2026-10-18).

Ce que l'utilisateur doit constater, et ce que ces tests mesurent :

- après la purge, la scène ne compte plus d'objets archivés (`archived_ids`
  vide), ou seulement ceux que le runtime suit encore ; les pierres tombales
  et l'historique purgés ont quitté `scene.sqlite3` ;
- les objets actifs, épinglés compris, et leurs liens restent intacts, et la
  commande de scène suivante réussit (le contrôle de comptage du commit ne
  voit aucune divergence) ;
- une étoile runtime encore suivie garde sa pierre tombale : elle ne
  ressuscite pas quand son travail se manifeste de nouveau ;
- une sauvegarde cohérente est écrite **d'abord**, lisible, avec les données
  d'avant ; si elle échoue, rien n'est effacé ;
- un jeton absent, périmé ou qui ne décrit plus l'état n'efface rien ;
- après un redémarrage de Core sur la même base, le compte reste à zéro ;
- les lecteurs de la scène (transport, page) se resynchronisent sans erreur.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.scene_service import SceneService, SceneState
from jarvis.domain.scene import (
    ExecState,
    RelationKind,
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
    WorkRef,
)
from jarvis.domain.scene_purge import PURGE_CONFIRMATION_TTL_S, ScenePurgeCode, ScenePurgeError
from jarvis.domain.work_state import WorkStatus
from tests.unit.test_scene_projector import Stack, obs, settled

USER, BRAIN, RUNTIME = SceneActor.USER, SceneActor.BRAIN, SceneActor.RUNTIME
ARCHIVED = ("arch-0", "arch-1", "arch-2", "arch-3", "claude:run-a")


def note(object_id: str, actor: SceneActor = BRAIN, **fields) -> SceneCommand:
    values = {"kind": SceneObjectKind.ARTIFACT, "category": "research", "payload": ScenePayload(title=f"Note {object_id}"),
              **fields}
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=actor, object_id=object_id, fields=SceneObjectFields(**values))


def runtime_star(object_id: str) -> SceneCommand:
    source, external_id = object_id.split(":", 1)
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=RUNTIME, object_id=object_id, fields=SceneObjectFields(
        kind=SceneObjectKind.AGENT, category="agent", exec_state=ExecState.COMPLETED,
        work_ref=WorkRef(source=source, external_id=external_id)))


def archive(object_id: str) -> SceneCommand:
    return SceneCommand(op=SceneOp.ARCHIVE, actor=USER, object_id=object_id)


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


async def populated(tmp_path: Path, *, retained: frozenset[str] | None = None, clock: Clock | None = None):
    """Une scène vivante : une note épinglée, une note reliée à elle, quatre notes et une étoile archivées."""

    path = tmp_path / "state" / "scene.sqlite3"
    retention = None
    if retained is not None:
        async def retention() -> frozenset[str]:
            return retained

    options = {"clock": clock} if clock is not None else {}
    service = SceneService(SQLiteSceneRepository(path, scene_id_factory=lambda: "scene-purge"),
                           archive_retention=retention, **options)
    assert (await service.start()).state is SceneState.READY
    commands = [
        note("pinned", USER),
        SceneCommand(op=SceneOp.SET_GEOMETRY, actor=USER, object_id="pinned", geometry=SceneGeometry(10, 20, 40, 30)),
        SceneCommand(op=SceneOp.PIN, actor=USER, object_id="pinned"),
        note("kept-note"),
        SceneCommand(op=SceneOp.LINK, actor=BRAIN,
                     relation=SceneRelation("rel-explains", RelationKind.EXPLAINS, "kept-note", "pinned")),
        *(note(object_id) for object_id in ARCHIVED[:4]),
        runtime_star("claude:run-a"),
        *(archive(object_id) for object_id in ARCHIVED),
    ]
    for command in commands:
        update = await service.apply(command)
        assert update.outcome is SceneCommandOutcome.APPLIED, (command, update.reason)
    return service, path


def rows(path: Path) -> dict[str, int]:
    """Lignes réellement sur disque (lecture seule, à côté de la connexion de Core)."""

    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("scene_objects", "scene_relations", "scene_tombstones", "scene_history")}
        counts["revision"] = conn.execute("SELECT revision FROM scene_meta").fetchone()[0]
        return counts
    finally:
        conn.close()


def backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.purge-*.bak"))


# ------------------------------------------------------------------ plan


async def test_the_plan_writes_nothing_and_says_what_would_go(tmp_path):
    service, path = await populated(tmp_path)
    before = rows(path)

    offer = await service.plan_archive_purge(actor=USER)

    assert offer.plan.purge_ids == ARCHIVED
    assert offer.plan.history_rows == len(ARCHIVED)
    assert offer.plan.kept_ids == () and offer.plan.kept_history_rows == 0
    assert offer.confirmation and offer.confirmation.startswith("spg_")
    assert offer.expires_at == pytest.approx(offer.issued_at + PURGE_CONFIRMATION_TTL_S, abs=1)
    payload = offer.to_payload(epoch=service.epoch)
    assert payload["purgeable"] == {"archived_ids": 5, "history_rows": 5}
    assert payload["kept"]["archived_ids"] == 0
    # Rien n'a bougé : ni la base, ni la révision, ni une sauvegarde.
    assert rows(path) == before
    assert (await service.snapshot()).archived_ids == ARCHIVED
    assert backups(path) == []
    await service.close()


async def test_an_empty_archive_gives_no_confirmation(tmp_path):
    service = SceneService(SQLiteSceneRepository(tmp_path / "scene.sqlite3"))
    await service.start()
    offer = await service.plan_archive_purge(actor=BRAIN)
    assert offer.plan.purge_ids == () and offer.plan.history_rows == 0
    assert offer.confirmation is None
    await service.close()


# ------------------------------------------------------------------ exécution


async def test_the_purge_empties_the_archive_and_keeps_the_live_scene(tmp_path):
    service, path = await populated(tmp_path)
    live = await service.snapshot()
    before = rows(path)

    offer = await service.plan_archive_purge(actor=USER)
    result = await service.purge_archived(confirmation=offer.confirmation, actor=USER)

    after = await service.snapshot()
    # Ce que scene_inspect rapporte : archived = 0.
    assert after.archived_ids == ()
    # Objets actifs (l'épinglé compris) et liens strictement intacts.
    assert after.objects == live.objects and after.relations == live.relations
    assert after.get_object("pinned").constraints.pinned_by_user is True
    assert after.revision == live.revision + 1
    assert result.revision == after.revision
    assert (result.purged_ids, result.history_rows, result.kept_ids) == (5, 5, ())
    on_disk = rows(path)
    assert on_disk == {"scene_objects": before["scene_objects"], "scene_relations": before["scene_relations"],
                       "scene_tombstones": 0, "scene_history": 0, "revision": after.revision}

    # Sauvegarde écrite d'abord, à côté de la base, lisible, avec les données d'avant.
    (backup,) = backups(path)
    assert Path(result.backup_path) == backup
    assert rows(backup) == before

    # La commande suivante passe : aucune divergence au contrôle de comptage.
    update = await service.apply(note("after-purge"))
    assert update.outcome is SceneCommandOutcome.APPLIED
    # Un id purgé est libre de nouveau, et l'archivage reprend normalement.
    assert (await service.apply(note("arch-0"))).outcome is SceneCommandOutcome.APPLIED
    assert (await service.apply(archive("arch-0"))).outcome is SceneCommandOutcome.APPLIED
    assert service.availability.state is SceneState.READY
    assert (await service.snapshot()).archived_ids == ("arch-0",)
    await service.close()


async def test_after_a_core_restart_the_archive_stays_empty(tmp_path):
    service, path = await populated(tmp_path)
    offer = await service.plan_archive_purge(actor=USER)
    result = await service.purge_archived(confirmation=offer.confirmation, actor=USER)
    await service.close()

    again = SceneService(SQLiteSceneRepository(path))
    assert (await again.start()).state is SceneState.READY
    reloaded = await again.snapshot()
    assert reloaded.archived_ids == ()
    assert reloaded.revision == result.revision
    assert await again.archived_history(limit=1000) == ()
    assert (await again.apply(note("next"))).outcome is SceneCommandOutcome.APPLIED
    await again.close()


async def test_ids_the_runtime_still_tracks_keep_their_tombstone(tmp_path):
    service, path = await populated(tmp_path, retained=frozenset({"claude:run-a", "claude:not-archived"}))

    offer = await service.plan_archive_purge(actor=BRAIN)
    assert offer.plan.purge_ids == ARCHIVED[:4]
    assert offer.plan.kept_ids == ("claude:run-a",)
    assert (offer.plan.history_rows, offer.plan.kept_history_rows) == (4, 1)
    assert offer.to_payload(epoch=service.epoch)["kept"]["reason"]

    result = await service.purge_archived(confirmation=offer.confirmation, actor=BRAIN)

    assert (await service.snapshot()).archived_ids == ("claude:run-a",)
    assert result.kept_ids == ("claude:run-a",)
    assert rows(path)["scene_tombstones"] == 1 and rows(path)["scene_history"] == 1
    # La pierre tombale gardée refuse toujours la résurrection de l'étoile.
    refused = await service.apply(runtime_star("claude:run-a"))
    assert refused.reason is SceneRefusal.OBJECT_ARCHIVED
    await service.close()


async def test_the_purge_forces_readers_to_resync_instead_of_missing_a_revision(tmp_path):
    service, _ = await populated(tmp_path)
    before = (await service.snapshot()).revision
    waiter = asyncio.ensure_future(service.wait_for_revision(before, timeout_s=10))
    await asyncio.sleep(0)

    offer = await service.plan_archive_purge(actor=USER)
    await service.purge_archived(confirmation=offer.confirmation, actor=USER)

    # Réveil immédiat des attentes, révision suivante.
    assert await asyncio.wait_for(waiter, 2) == before + 1
    # Un lecteur à l'ancienne révision relit l'instantané (aucun patch ne décrit la purge).
    window = await service.patches_since(before)
    assert window.resync_required is True and window.patches == () and window.revision == before + 1
    # Un lecteur à jour ne voit rien de neuf, puis le patch suivant normalement.
    assert (await service.patches_since(before + 1)).resync_required is False
    await service.apply(note("next"))
    window = await service.patches_since(before + 1)
    assert window.resync_required is False and [patch.revision for patch in window.patches] == [before + 2]
    await service.close()


# ------------------------------------------------------------------ refus : rien n'est effacé


async def test_without_a_valid_confirmation_nothing_is_deleted(tmp_path):
    service, path = await populated(tmp_path)
    before = rows(path)
    for token in (None, "", "garbage", "spg_1.abc"):
        with pytest.raises(ScenePurgeError) as caught:
            await service.purge_archived(confirmation=token, actor=USER)
        assert caught.value.code is ScenePurgeCode.CONFIRMATION_REQUIRED
    assert rows(path) == before and backups(path) == []
    await service.close()


async def test_a_token_that_no_longer_describes_the_archive_deletes_nothing(tmp_path):
    service, path = await populated(tmp_path)
    offer = await service.plan_archive_purge(actor=USER)
    # Entre le plan et la confirmation, un autre objet est archivé.
    await service.apply(note("late"))
    await service.apply(archive("late"))
    before = rows(path)

    with pytest.raises(ScenePurgeError) as caught:
        await service.purge_archived(confirmation=offer.confirmation, actor=USER)

    assert caught.value.code is ScenePurgeCode.CONFIRMATION_STALE
    assert rows(path) == before and backups(path) == []
    assert len((await service.snapshot()).archived_ids) == 6
    await service.close()


async def test_an_expired_token_deletes_nothing(tmp_path):
    clock = Clock()
    service, path = await populated(tmp_path, clock=clock)
    offer = await service.plan_archive_purge(actor=USER)
    before = rows(path)
    clock.now += PURGE_CONFIRMATION_TTL_S + 1

    with pytest.raises(ScenePurgeError) as caught:
        await service.purge_archived(confirmation=offer.confirmation, actor=USER)

    assert caught.value.code is ScenePurgeCode.CONFIRMATION_STALE
    assert rows(path) == before and backups(path) == []
    await service.close()


async def test_a_token_from_another_core_life_is_stale(tmp_path):
    service, path = await populated(tmp_path)
    offer = await service.plan_archive_purge(actor=USER)
    await service.close()
    again = SceneService(SQLiteSceneRepository(path))
    await again.start()
    with pytest.raises(ScenePurgeError) as caught:
        await again.purge_archived(confirmation=offer.confirmation, actor=USER)
    assert caught.value.code is ScenePurgeCode.CONFIRMATION_STALE
    assert len((await again.snapshot()).archived_ids) == 5
    await again.close()


async def test_if_the_backup_fails_nothing_is_deleted(tmp_path, monkeypatch):
    service, path = await populated(tmp_path)
    offer = await service.plan_archive_purge(actor=USER)
    before = rows(path)

    def broken(self, conn, target):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr(SQLiteSceneRepository, "_write_backup", broken)
    with pytest.raises(ScenePurgeError) as caught:
        await service.purge_archived(confirmation=offer.confirmation, actor=USER)

    assert caught.value.code is ScenePurgeCode.BACKUP_FAILED
    assert rows(path) == before
    assert not list(path.parent.glob("*.partial")) and backups(path) == []
    # La scène reste servie et la commande suivante passe.
    assert service.availability.state is SceneState.READY
    assert (await service.apply(note("next"))).outcome is SceneCommandOutcome.APPLIED
    await service.close()


async def test_the_runtime_actor_cannot_purge(tmp_path):
    service, path = await populated(tmp_path)
    with pytest.raises(PermissionError):
        await service.plan_archive_purge(actor=RUNTIME)
    await service.close()


# ------------------------------------------------------------------ projection runtime


async def test_a_star_whose_work_is_still_tracked_never_resurrects(tmp_path):
    clock = Clock(100.0)
    stack = Stack(repository=SQLiteSceneRepository(tmp_path / "scene.sqlite3"), restart_grace_s=30, monotonic=clock)
    async with stack:
        stack.scene.attach_archive_retention(stack.projector.retained_archive_ids)
        await stack.observe(obs("a"), obs("b", WorkStatus.COMPLETED, at=1))
        await stack.scene.apply(note("brain-note"))
        for object_id in ("claude:a", "claude:b", "brain-note"):
            assert (await stack.scene.apply(archive(object_id))).changed

        # Juste après le démarrage, les producteurs n'ont pas encore tout redit : refus, rien d'effacé.
        with pytest.raises(ScenePurgeError) as caught:
            await stack.scene.plan_archive_purge(actor=USER)
        assert caught.value.code is ScenePurgeCode.RUNTIME_SETTLING
        assert caught.value.retry_after_s == pytest.approx(30, abs=1)

        clock.now += 31
        offer = await stack.scene.plan_archive_purge(actor=USER)
        assert offer.plan.purge_ids == ("brain-note",)
        assert set(offer.plan.kept_ids) == {"claude:a", "claude:b"}
        await stack.scene.purge_archived(confirmation=offer.confirmation, actor=USER)

        skipped = stack.projector.stats.skipped_archived
        await stack.observe(obs("a", at=2, summary="toujours là"), obs("a", WorkStatus.FAILED, at=3, error_class="boom"))
        assert await stack.projector._reconcile("test")
        await settled(stack.projector)
        snapshot = await stack.snapshot()
        assert snapshot.get_object("claude:a") is None and snapshot.is_archived("claude:a")
        assert snapshot.get_object("claude:b") is None
        assert stack.projector.stats.skipped_archived > skipped
        assert stack.scene.availability.state is SceneState.READY


# ------------------------------------------------------------------ page du Control Center


async def test_the_page_client_resyncs_to_an_empty_archive(tmp_path, scene_logic):
    """Le client pur de la page (`control_center_scene.js`) suit la purge sans erreur ni divergence."""

    from jarvis.protocol import scene_wire
    from jarvis.runtime.scene_view import decode_patches_response
    import json

    service, _ = await populated(tmp_path)
    epoch = service.epoch
    held = json.loads(scene_wire.snapshot_body(await service.snapshot(), epoch))
    offer = await service.plan_archive_purge(actor=USER)
    await service.purge_archived(confirmation=offer.confirmation, actor=USER)
    # Ce que Core rend au long-poll de la page, validé comme par le proxy du Control Center.
    window = await service.patches_since(held["revision"], scene_id=held["scene_id"])
    patches = decode_patches_response(json.loads(scene_wire.patch_window_body(window, epoch=epoch, after=held["revision"])),
                                      after=held["revision"])
    fresh = json.loads(scene_wire.snapshot_body(await service.snapshot(), epoch))
    await service.close()

    result = scene_logic(
        """
        const s0=S.fromSnapshot(D.held);if(!s0.ok)return {error:s0.reason};
        const r=S.applyPatchResponse(s0.state,D.patches);
        const accepted=S.acceptSnapshot(s0.state,D.fresh);
        const s1=S.fromSnapshot(D.fresh);
        const t=S.toSnapshot(s1.state);
        return {before:s0.state.archived_ids.size,action:r.action,reason:r.reason,accepted,ok:s1.ok,
                archived:t.archived_ids.length,objects:t.objects.length,relations:t.relations.length};
        """,
        {"held": held, "patches": patches, "fresh": fresh},
    )
    assert result == {"before": 5, "action": "resync", "reason": "resync_required", "accepted": True, "ok": True,
                      "archived": 0, "objects": len(fresh["snapshot"]["objects"]),
                      "relations": len(fresh["snapshot"]["relations"])}


async def test_purged_text_is_gone_from_the_database_files_but_kept_in_the_backup(tmp_path):
    """« Vraiment supprimé » : le texte des objets purgés ne reste ni dans la base ni dans son `-wal`."""

    service, path = await populated(tmp_path)
    marker = b"Note arch-2"
    assert any(marker in candidate.read_bytes() for candidate in (path, path.with_name(path.name + "-wal"))
               if candidate.exists())
    offer = await service.plan_archive_purge(actor=USER)
    result = await service.purge_archived(confirmation=offer.confirmation, actor=USER)

    for candidate in (path, path.with_name(path.name + "-wal")):
        if candidate.exists():
            assert marker not in candidate.read_bytes(), candidate.name
    assert marker in Path(result.backup_path).read_bytes()
    await service.close()
