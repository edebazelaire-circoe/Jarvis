"""Purge definitive des presentations archivees : plan (rien n'est ecrit) puis execution confirmee, sauvegarde d'abord.

Ce que l'utilisateur constate une fois la purge faite :

- `presentation_inspect` (overview, rail) ne liste plus aucune presentation archivee ;
- les presentations non archivees sont intactes (dossier, snapshots, sources de scene) ;
- les snapshots et rendus des presentations purgees, et leurs sources de scene `presentation-studio.p<12 hex>.*`, ont disparu ;
- une sauvegarde complete existe sous `<data_root>/backups/purge-presentations-<horodatage>/` (dossiers, prefabs, artefacts, copie
  coherente de `jarvis.sqlite3`) ;
- sans jeton, avec un jeton perime ou pour un autre ensemble, sans `confirmed`, ou si une presentation n'est pas archivee : rien
  n'est efface.

Vrai Core (`JarvisCoreApplication`) derriere le vrai protocole (`Core`), vrai magasin de fichiers, vrai registre d'Artifacts.
Contrat : `docs/presentation-studio.md` > *Rail des presentations* > *Purge definitive*.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from jarvis.domain.artifacts import ArtifactError
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError
from tests.unit.presentation_studio_mcp_world import open_world
from tests.unit.test_presentation_studio_routes import Core


# ------------------------------------------------------------------ outillage

async def create(core: Core, title: str) -> tuple[str, str]:
    status, made = await core.call("POST", "", json={"title": title})
    assert status == 201, made
    return made["presentation"]["presentation_id"], made["presentation"]["active_variant_id"]


async def archive(core: Core, pid: str) -> None:
    out = await core.client.presentation_studio_rail_act(pid, {"action": "archive", "actor": "user"})
    assert out["archived"] is True


async def freeze_and_render(core: Core, pid: str, vid: str) -> tuple[str, str]:
    """Un snapshot complet de la presentation et un rendu MP4 complet qui en derive (`rendered_from`)."""

    c = core.stack.core
    view = await c.presentation_studio.get(pid)
    variant = next(v for v in view.variants if v.variant_id == vid)
    began = await c.presentation_artifacts.begin_snapshot(
        pid, vid, expected_presentation_revision=view.presentation.revision, expected_variant_revision=variant.revision)
    sid = began["artifact_id"]
    spool = c.artifacts.open_spool(await c.artifacts.get(sid))
    data = b"PK-" + sid.encode()
    spool.write(data)
    spool.finalize()
    await c.presentation_artifacts.finalize_snapshot(sid, content_sha256=hashlib.sha256(data).hexdigest())
    render = await c.presentation_artifacts.begin_render(sid, "mp4")
    await c.artifacts.store_payload(render.artifact_id, b"MP4-" + sid.encode())
    return sid, render.artifact_id


def data_root(core: Core) -> Path:
    return core.stack.data_root


def source_prefab(core: Core, pid: str, scene_hex: str = "aaaaaaaaaaaa", *, archived: bool = False) -> Path:
    """Une source de scene propre a la presentation (`presentation-studio.p<12 hex>.s<12 hex>`), vivante ou retiree (`.archive`)."""

    prefab_id = f"presentation-studio.p{pid.removeprefix('pst_')[:12]}.s{scene_hex}"
    base = data_root(core) / "prefabs" / (".archive" if archived else "") / prefab_id / "1"
    base.mkdir(parents=True)
    (base / "manifest.json").write_text('{"prefab": "' + prefab_id + '"}', encoding="utf-8")
    return base.parent


def shared_prefab(core: Core) -> Path:
    base = data_root(core) / "prefabs" / "presentation-studio.rm-shared-0123abcd" / "1"
    base.mkdir(parents=True)
    (base / "manifest.json").write_text("{}", encoding="utf-8")
    return base.parent


async def plan(core: Core, **body) -> dict:
    return await core.client.presentation_studio_purge_plan(body)


async def refused(call, status: int, code: str):
    with pytest.raises(Exception) as caught:
        await call
    assert getattr(caught.value, "status", None) == status, caught.value
    assert code in str(getattr(caught.value, "code", "")) + str(caught.value)
    return caught.value


def tree(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


# ------------------------------------------------------------------ de bout en bout : route HTTP de Core

async def test_purge_end_to_end(tmp_path):
    """Every archived presentation and what came with it is removed, after a complete backup; the others stay."""
    async with Core(tmp_path) as core:
        c = core.stack.core
        a, va = await create(core, "Archivee A")
        b, _ = await create(core, "Archivee B")
        keep, vkeep = await create(core, "Gardee")
        snap_a, render_a = await freeze_and_render(core, a, va)
        snap_keep, render_keep = await freeze_and_render(core, keep, vkeep)
        prefab_a = source_prefab(core, a)
        retired_a = source_prefab(core, a, "bbbbbbbbbbbb", archived=True)
        prefab_keep = source_prefab(core, keep)
        shared = shared_prefab(core)
        folder_a = data_root(core) / "presentations" / a
        await archive(core, a)
        await archive(core, b)
        before_a = tree(folder_a)
        assert "rail.json" in before_a

        planned = await plan(core)
        rows = {r["presentation_id"]: r for r in planned["plan"]["presentations"]}
        assert set(rows) == {a, b}, "only archived presentations are planned"
        assert rows[a]["title"] == "Archivee A" and rows[a]["archived_at"]
        assert rows[a]["snapshots"] == 1 and rows[a]["renders"] == 1 and rows[a]["prefabs"] == 2
        assert rows[a]["variants"] >= 1 and rows[b]["snapshots"] == 0
        assert planned["confirmation"] and planned["expires_in_s"] > 0
        # the plan writes nothing
        assert folder_a.is_dir() and prefab_a.is_dir() and (await c.artifacts.get(snap_a)).artifact_id == snap_a

        done = await core.client.presentation_studio_purge({"confirmation": planned["confirmation"], "confirmed": True})
        assert sorted(done["purged"]) == sorted([a, b]) and done["complete"] is True
        assert done["deleted"]["presentations"] == 2 and done["deleted"]["artifacts"] == 2 and done["deleted"]["prefabs"] == 2

        # what the user sees: no archived presentation left, the kept one untouched
        rail = (await core.client.presentation_studio_rail())["presentations"]
        assert [r["presentation_id"] for r in rail] == [keep] and rail[0]["archived"] is False
        for gone in (a, b):
            status, _ = await core.call("GET", f"/{gone}")
            assert status == 404
        status, kept = await core.call("GET", f"/{keep}")
        assert status == 200 and kept["presentation"]["title"] == "Gardee"
        assert (await c.artifacts.get(snap_keep)).artifact_id == snap_keep
        assert (await c.artifacts.get(render_keep)).artifact_id == render_keep
        assert prefab_keep.is_dir(), "another presentation's scene sources stay"
        assert shared.is_dir(), "content-addressed rm-* sources are never purged"

        # derived artifacts, their folders and the purged presentation's scene sources are gone
        for artifact_id in (snap_a, render_a):
            with pytest.raises(ArtifactError):
                await c.artifacts.get(artifact_id)
            assert not (data_root(core) / "artifacts" / artifact_id).exists()
        assert not folder_a.exists() and not prefab_a.exists() and not retired_a.exists()

        # the backup is there and complete
        backup = data_root(core) / done["backup"]
        assert backup.is_dir() and backup.name.startswith("purge-presentations-") and backup.parent.name == "backups"
        assert tree(backup / "presentations" / a) == before_a
        assert (backup / "presentations" / b / "presentation.json").is_file()
        assert (backup / "prefabs" / prefab_a.name / "1" / "manifest.json").is_file()
        assert (backup / "prefabs" / ".archive" / retired_a.name / "1" / "manifest.json").is_file()
        for artifact_id in (snap_a, render_a):
            assert tree(backup / "artifacts" / artifact_id), artifact_id
        with sqlite3.connect(backup / "state" / "jarvis.sqlite3") as copy:
            saved = {row[0] for row in copy.execute("SELECT artifact_id FROM artifacts")}
        assert {snap_a, render_a} <= saved, "the database copy predates the deletion"
        manifest = json.loads((backup / "purge.json").read_text(encoding="utf-8"))
        assert sorted(manifest["presentation_ids"]) == sorted([a, b])

        # nothing left to purge
        again = await plan(core)
        assert again["plan"]["presentations"] == [] and again["confirmation"] is None


async def test_nothing_is_deleted_without_a_valid_token_and_the_users_yes(tmp_path):
    async with Core(tmp_path) as core:
        a, _ = await create(core, "A")
        await archive(core, a)
        folder = data_root(core) / "presentations" / a
        planned = await plan(core)
        token = planned["confirmation"]
        await refused(core.client.presentation_studio_purge({"confirmed": True}), 400, "presentation_studio_confirmation_required")
        await refused(core.client.presentation_studio_purge({"confirmation": token}), 400, "presentation_studio_confirmation_required")
        await refused(core.client.presentation_studio_purge({"confirmation": token, "confirmed": False}), 400,
                      "presentation_studio_confirmation_required")
        forged = token[:-4] + ("0000" if not token.endswith("0000") else "1111")
        await refused(core.client.presentation_studio_purge({"confirmation": forged, "confirmed": True}), 409,
                      "presentation_studio_confirmation_stale")
        assert folder.is_dir()
        assert not (data_root(core) / "backups").exists(), "no backup, no deletion, before a valid confirmation"


async def test_a_set_that_changed_since_the_plan_is_stale_and_nothing_is_deleted(tmp_path):
    async with Core(tmp_path) as core:
        a, _ = await create(core, "A")
        b, _ = await create(core, "B")
        await archive(core, a)
        token = (await plan(core))["confirmation"]
        await archive(core, b)  # one more archived presentation: the default set is no longer the planned one
        await refused(core.client.presentation_studio_purge({"confirmation": token, "confirmed": True}), 409,
                      "presentation_studio_confirmation_stale")
        token = (await plan(core))["confirmation"]
        await core.client.presentation_studio_rail_act(b, {"action": "restore", "actor": "user"})  # restored after the plan
        await refused(core.client.presentation_studio_purge({"confirmation": token, "confirmed": True}), 409,
                      "presentation_studio_confirmation_stale")
        for pid in (a, b):
            assert (data_root(core) / "presentations" / pid).is_dir()


async def test_an_expired_token_is_stale(tmp_path):
    async with Core(tmp_path) as core:
        a, _ = await create(core, "A")
        await archive(core, a)
        purge = core.stack.core.presentation_studio_purge
        token = (await plan(core))["confirmation"]
        later = purge._epoch() + 601
        purge._epoch = lambda: later
        await refused(core.client.presentation_studio_purge({"confirmation": token, "confirmed": True}), 409,
                      "presentation_studio_confirmation_stale")
        assert (data_root(core) / "presentations" / a).is_dir()


async def test_a_presentation_that_is_not_archived_is_never_purged(tmp_path):
    async with Core(tmp_path) as core:
        a, _ = await create(core, "Archivee")
        live, _ = await create(core, "Vivante")
        await archive(core, a)
        await refused(plan(core, presentation_ids=[live]), 409, "presentation_studio_not_archived")
        await refused(plan(core, presentation_ids=[a, live]), 409, "presentation_studio_not_archived")
        token = (await plan(core, presentation_ids=[a]))["confirmation"]
        await refused(core.client.presentation_studio_purge({"confirmation": token, "confirmed": True, "presentation_ids": [a, live]}),
                      409, "presentation_studio_not_archived")
        await refused(plan(core, presentation_ids=["pst_" + "f" * 32]), 404, "presentation_studio_unknown_presentation")
        assert (data_root(core) / "presentations" / live).is_dir()
        done = await core.client.presentation_studio_purge({"confirmation": token, "confirmed": True, "presentation_ids": [a]})
        assert done["purged"] == [a]
        assert (data_root(core) / "presentations" / live).is_dir()


async def test_the_brain_needs_confirmed_and_a_presentation_in_playback_is_refused(tmp_path):
    async with Core(tmp_path) as core:
        a, va = await create(core, "Jouee")
        await archive(core, a)
        token = (await plan(core))["confirmation"]
        await refused(core.client.presentation_studio_purge({"confirmation": token, "actor": "brain"}), 400,
                      "presentation_studio_confirmation_required")
        core.stack.core.presentation_studio_playback.running_variant = lambda: (a, va)
        await refused(core.client.presentation_studio_purge({"confirmation": token, "confirmed": True, "actor": "brain"}), 409,
                      "presentation_studio_variant_in_playback")
        assert (data_root(core) / "presentations" / a).is_dir()


async def test_a_failed_backup_deletes_nothing(tmp_path):
    async with Core(tmp_path) as core:
        a, va = await create(core, "A")
        snap, _ = await freeze_and_render(core, a, va)
        await archive(core, a)
        token = (await plan(core))["confirmation"]
        (data_root(core) / "backups").write_text("not a folder", encoding="utf-8")  # the backup cannot be written
        await refused(core.client.presentation_studio_purge({"confirmation": token, "confirmed": True}), 500,
                      "presentation_studio_storage_io")
        assert (data_root(core) / "presentations" / a).is_dir()
        assert (await core.stack.core.artifacts.get(snap)).artifact_id == snap


async def test_purge_forgets_the_in_memory_state_of_the_purged_presentation(tmp_path):
    async with Core(tmp_path) as core:
        c = core.stack.core
        a, va = await create(core, "A")
        await core.client.presentation_studio_work(a, {"event": "failure", "code": "x", "message": "boom"})
        c.studio_pins.restore_variant(a, va, frozenset({("presentation-studio.pzzz", 1)}))
        await archive(core, a)
        token = (await plan(core))["confirmation"]
        await core.client.presentation_studio_purge({"confirmation": token, "confirmed": True})
        assert a not in c.presentation_studio_rail.tracker._rows
        assert not [key for key in c.studio_pins._variants if key[0] == a]


# ------------------------------------------------------------------ domaine : jeton lie a l'ensemble exact

def test_the_purge_token_binds_the_exact_set_and_expires():
    from jarvis.domain.presentation_studio_purge import (
        PURGE_CONFIRMATION_TTL_S, PurgePlan, PurgeTarget, check_purge_confirmation, issue_purge_confirmation,
    )

    secret = b"s" * 32
    one = PurgeTarget("pst_" + "1" * 32, "Un", "2026-10-18T10:00:00.000000Z", 3, ("psv_" + "a" * 32,), (), ("jart_x",), ("p.a",))
    two = PurgeTarget("pst_" + "2" * 32, "Deux", "2026-10-18T10:00:00.000000Z", 1, (), (), (), ())
    plan = PurgePlan((one, two))
    token = issue_purge_confirmation(secret, plan, 1000)
    check_purge_confirmation(secret, plan, token, 1000 + PURGE_CONFIRMATION_TTL_S)
    for other in (PurgePlan((one,)), PurgePlan((one, two, PurgeTarget("pst_" + "3" * 32, "T", None, 1, (), (), (), ()))),
                  PurgePlan((replace(one, artifact_ids=("jart_x", "jart_y")), two)),
                  PurgePlan((replace(one, archived_at="2026-10-18T11:00:00.000000Z"), two))):
        with pytest.raises(PresentationStudioError) as stale:
            check_purge_confirmation(secret, other, token, 1000)
        assert stale.value.code is C.CONFIRMATION_STALE
    with pytest.raises(PresentationStudioError) as expired:
        check_purge_confirmation(secret, plan, token, 1001 + PURGE_CONFIRMATION_TTL_S)
    assert expired.value.code is C.CONFIRMATION_STALE
    for bad in (None, "", "psk_12", 42):
        with pytest.raises(PresentationStudioError) as missing:
            check_purge_confirmation(secret, plan, bad, 1000)
        assert missing.value.code is C.CONFIRMATION_REQUIRED
    with pytest.raises(PresentationStudioError) as other_secret:
        check_purge_confirmation(b"t" * 32, plan, token, 1000)
    assert other_secret.value.code is C.CONFIRMATION_STALE


# ------------------------------------------------------------------ magasin : effaceur sur

def test_store_removes_a_presentation_folder_but_refuses_links_inside(tmp_path):
    from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore

    store = FilePresentationStudioStore(tmp_path)
    pid = "pst_" + "1" * 32
    store.create(pid, json.dumps({"x": 1}), {"psv_" + "2" * 32: "{}"})
    copy = tmp_path / "copy"
    copied = store.copy_presentation(pid, copy)
    assert copied.files == 2 and (copy / pid / "presentation.json").is_file()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep", encoding="utf-8")
    linked = tmp_path / "presentations" / pid / "variants" / "evil"
    try:
        import _winapi
        _winapi.CreateJunction(str(outside), str(linked))
    except (ImportError, OSError):
        try:
            os.symlink(outside, linked, target_is_directory=True)
        except OSError:
            pytest.skip("cannot create a junction or a symbolic link here")
    with pytest.raises(PresentationStudioError) as caught:
        store.remove_presentation(pid)
    assert caught.value.code is C.STORAGE_IO
    assert (outside / "precious.txt").read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "presentations" / pid / "presentation.json").is_file(), "a refused removal removes nothing"
    with pytest.raises(PresentationStudioError):
        store.copy_presentation(pid, tmp_path / "copy2")
    os.rmdir(linked) if os.name == "nt" else os.unlink(linked)
    store.remove_presentation(pid)
    assert store.scan().presentation_ids == () and (outside / "precious.txt").is_file()


def test_an_interrupted_purge_is_swept_at_the_next_start(tmp_path):
    from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore

    store = FilePresentationStudioStore(tmp_path)
    pid = "pst_" + "4" * 32
    store.create(pid, "{}", {"psv_" + "5" * 32: "{}"})
    leftover = tmp_path / "presentations" / (".purging-" + "a" * 16)
    (leftover / "variants").mkdir(parents=True)
    (leftover / "variants" / "x.json").write_text("{}", encoding="utf-8")
    report = store.sweep()
    assert leftover.name in report.removed and not leftover.exists()
    assert store.scan().presentation_ids == (pid,), "a live presentation is never swept"


def test_prefab_sources_are_removed_only_if_unchanged_since_their_backup(tmp_path):
    from jarvis.adapters.file_prefab_library import FilePrefabLibrary
    from jarvis.ports.prefabs import PrefabStoreError

    library = FilePrefabLibrary(tmp_path / "package", tmp_path)
    prefab_id = "presentation-studio.p" + "6" * 12 + ".s" + "7" * 12
    version = tmp_path / "prefabs" / prefab_id / "1"
    version.mkdir(parents=True)
    (version / "manifest.json").write_text("{}", encoding="utf-8")
    assert library.list_ids("presentation-studio.p" + "6" * 12) == (prefab_id,)
    copied = library.copy_ids([prefab_id], tmp_path / "backup")
    (tmp_path / "prefabs" / prefab_id / "2").mkdir()
    (tmp_path / "prefabs" / prefab_id / "2" / "manifest.json").write_text("{}", encoding="utf-8")  # published after the backup
    with pytest.raises(PrefabStoreError):
        library.remove_ids(copied)
    assert version.is_dir(), "nothing is removed without its copy"
    with pytest.raises(PrefabStoreError):
        library.copy_ids(["jarvis.window"], tmp_path / "backup2")  # never a base or a user prefab
    copied = library.copy_ids([prefab_id], tmp_path / "backup3")
    assert library.remove_ids(copied) == (prefab_id,) and not (tmp_path / "prefabs" / prefab_id).exists()


# ------------------------------------------------------------------ outil MCP

async def test_mcp_purge_is_a_plan_then_the_users_yes_then_the_purge(tmp_path):
    core, world = await open_world(tmp_path)
    try:
        tools = world.tools
        await tools.library("archive", presentation_id=world.pid, confirmed=True)

        asked = await tools.library("purge")
        assert asked["speech"] == "say" and asked["status"] == "confirmation_required" and asked["confirmation"]
        assert "définitivement" in asked["say"] and asked["count"] == 1
        assert world.spy.named("presentation_studio_purge") == [], "the plan deletes nothing"
        assert (data_root(core) / "presentations" / world.pid).is_dir()

        with pytest.raises(PresentationToolError) as unconfirmed:
            await tools.library("purge", confirmation=asked["confirmation"])
        assert unconfirmed.value.code == "presentation_studio_confirmation_required"
        with pytest.raises(PresentationToolError) as invented:
            await tools.library("purge", confirmation="psk_1.nope", confirmed=True)
        assert invented.value.code == "presentation_studio_confirmation_required"
        assert world.spy.named("presentation_studio_purge") == []

        done = await tools.library("purge", confirmation=asked["confirmation"], confirmed=True)
        assert done["status"] == "purged" and done["purged"] == [world.pid] and done["backup"].startswith("backups/")
        assert done["speech"] == "say"
        overview = await tools.inspect("overview")
        assert not [r for r in overview["presentations"]["items"] if r.get("archived")]
        assert world.pid not in {r["presentation_id"] for r in overview["presentations"]["items"]}

        nothing = await tools.library("purge")
        assert nothing["status"] == "nothing_to_purge" and nothing.get("confirmation") is None
    finally:
        await core.__aexit__(None, None, None)


async def test_mcp_purge_of_one_live_presentation_is_refused(tmp_path):
    core, world = await open_world(tmp_path)
    try:
        with pytest.raises(PresentationToolError) as caught:
            await world.tools.library("purge", presentation_id=world.pid)
        assert caught.value.code == "presentation_studio_not_archived"
        assert (data_root(core) / "presentations" / world.pid).is_dir()
    finally:
        await core.__aexit__(None, None, None)


# ------------------------------------------------------------------ relais du Control Center (rail de droite : « Supprimer définitivement »)

async def test_the_control_center_relays_plan_and_purge_with_the_actor_forced_to_user(tmp_path):
    async with Core(tmp_path) as core:
        a, _ = await create(core, "A supprimer")
        keep, _ = await create(core, "Gardee")
        await archive(core, a)
        stack = core.stack
        # Un corps étranger est refusé ; l'acteur « brain » réclamé par la page est remplacé par `user`.
        status, bad, _ = await stack.call("POST", "/api/presentation-studio/rail/purge-plan", json={"hack": 1})
        assert status == 400 and bad["error"]["code"] == "invalid_request"
        status, planned, _ = await stack.call("POST", "/api/presentation-studio/rail/purge-plan",
                                              json={"presentation_ids": [a], "actor": "brain"})
        assert status == 200 and [r["presentation_id"] for r in planned["plan"]["presentations"]] == [a]
        status, refused_, _ = await stack.call("POST", "/api/presentation-studio/rail/purge",
                                               json={"confirmation": planned["confirmation"], "presentation_ids": [a]})
        assert status == 400 and refused_["error"]["code"] == "presentation_studio_confirmation_required"
        status, done, _ = await stack.call("POST", "/api/presentation-studio/rail/purge",
                                           json={"confirmation": planned["confirmation"], "confirmed": True,
                                                 "presentation_ids": [a], "actor": "brain"})
        assert status == 200 and done["purged"] == [a] and done["complete"] is True
        assert not (data_root(core) / "presentations" / a).exists() and (data_root(core) / "presentations" / keep).is_dir()
        # Une présentation vivante ne se purge jamais, quelle que soit la page.
        status, live, _ = await stack.call("POST", "/api/presentation-studio/rail/purge-plan", json={"presentation_ids": [keep]})
        assert status == 409 and live["error"]["code"] == "presentation_studio_not_archived"
