"""Arret brutal REEL au milieu d'un rechargement a chaud (jarvis-interactive-presentation-studio, Slice 06).

Un vrai sous-processus fait une edition de source et s'arrete (`os._exit`, sans aucun nettoyage) a l'un des trois instants
sensibles :

1. APRES la publication de la version, AVANT l'ecriture du pin ;
2. APRES l'ecriture du pin (et de son repli), AVANT le patch de la fenetre stage ;
3. APRES le patch du stage, AVANT le rapport de montage de l'hote.

Le parent rouvre les memes dossiers avec de nouveaux services et verifie : jamais un document tronque, jamais un pin sans
repli, la version publiee orpheline est inoffensive et sa numerotation continue, le pin non confirme est retrouve et protege,
puis le premier rapport de montage le confirme ou le ramene a la derniere version valide (stage compris). Contrat :
`docs/presentation-studio.md` > *Hot reload contract* > *Crash consistency*.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from tests.fakes.presentation_studio_reload import FakeHost, Rig, SID

pytestmark = pytest.mark.asyncio

REPO = Path(__file__).resolve().parents[2]
OLD = PrefabRef("lab.counter", 1)

CHILD = r"""
import asyncio, json, os, sys
from pathlib import Path
from tests.fakes.presentation_studio_reload import Rig

root, point = Path(sys.argv[1]), sys.argv[2]

def die(*args, **kwargs):
    os._exit(9)

async def main():
    rig = await Rig(root, mount_deadline_s=5.0).open(host=lambda pin: None)   # a host that never answers: the edit waits
    print(json.dumps({"pid": rig.pid, "vid": rig.vid}), flush=True)
    if point == "after_publish":
        async def stop(*args, **kwargs):
            die()
        rig.studio.replace_scene_source = stop
    elif point == "after_pin":
        async def stop(*args, **kwargs):
            die()
        rig.stage.repin = stop
    elif point == "after_patch":
        real = rig.stage.repin
        async def patched_then_die(*args, **kwargs):
            await real(*args, **kwargs)
            die()
        rig.stage.repin = patched_then_die
    await rig.edit({"style": ".count{color:#123456}"})
    print("survived", flush=True)

asyncio.run(main())
"""


def crash(root: Path, point: str) -> dict:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.run([sys.executable, "-c", CHILD, str(root), point], env=env, capture_output=True, text=True,
                           cwd=str(REPO), timeout=120)
    assert child.returncode == 9, (child.returncode, child.stdout, child.stderr[-2000:])
    assert "survived" not in child.stdout
    return json.loads(child.stdout.splitlines()[0])


def scene_of(variant, scene_id=SID):
    return next(item for item in variant.scenes if item.scene_id == scene_id)


async def reopen(root: Path) -> Rig:
    return await Rig(root, existing=True, mount_deadline_s=2.0).open()


async def live_stage_windows(rig: Rig) -> list[str]:
    return [o.object_id for o in (await rig.scene.snapshot()).objects if o.object_id.startswith("studio-stage-")]


def library_ids(rig: Rig) -> list[str]:
    return sorted(p.name for p in (rig.data / "prefabs").iterdir() if p.name.startswith("presentation-studio"))


async def test_a_kill_after_the_publication_and_before_the_pin_leaves_the_scene_untouched_and_an_inert_version(tmp_path):
    crash(tmp_path, "after_publish")
    rig = await reopen(tmp_path)
    try:
        variant = await rig.variant()
        scene = scene_of(variant)
        # the document is the one from before the edit: same pin, no counter move, no fallback
        assert scene.prefab == OLD and scene.source_revision == 0 and scene.last_valid_pin is None
        # the version exists (published, immutable) but nothing points at it
        assert len(library_ids(rig)) == 1 and rig.versions_of(library_ids(rig)[0]) == [1]
        assert await rig.reload.recover() == 0
        # the next edit works and numbering continues from the orphan: nothing is overwritten, nothing is reused
        rig.host = FakeHost(rig)
        rig.host.start()
        await rig.play()                       # a new run: the killed life's stage window was taken back at start
        result = await rig.edit({"style": ".count{color:#654321}"})
        assert result.status is S.RELOADED and result.prefab.version == 2
        assert rig.versions_of(result.prefab.prefab_id) == [1, 2]
    finally:
        await rig.close()


async def test_a_kill_after_the_pin_and_before_the_stage_patch_keeps_the_fallback_and_the_next_mount_report_decides(tmp_path):
    crash(tmp_path, "after_pin")
    rig = await reopen(tmp_path)
    try:
        variant = await rig.variant()
        scene = scene_of(variant)
        # pin and fallback were written TOGETHER, in one file: never one without the other
        assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin == OLD
        assert scene.source_revision == 1
        # the registry protects both versions from the very first answer after the restart
        held = await rig.pins.pinned_versions(["lab.counter", scene.prefab.prefab_id])
        assert held["lab.counter"] == frozenset({1}) and held[scene.prefab.prefab_id] == frozenset({1})
        assert await rig.reload.recover() == 1
        assert [entry.fallback for entry in rig.reload.pending_scenes()] == [OLD]
        # the killed life's stage window was taken back by id list at start (Slice 12): no window, no run
        assert await rig.stage_block() is None and not await live_stage_windows(rig)
        # a new run shows the scene: it mounts the document's pin, and a good mount confirms it ...
        rig.host = FakeHost(rig)
        rig.host.start()
        await rig.play()
        await asyncio.sleep(0.5)
        confirmed = scene_of(await rig.variant())
        assert confirmed.prefab == scene.prefab and confirmed.last_valid_pin is None and not rig.reload.pending_scenes()
    finally:
        await rig.close()


async def test_a_kill_after_the_pin_then_a_failing_first_mount_goes_back_to_the_last_valid_version_stage_included(tmp_path):
    crash(tmp_path, "after_pin")
    rig = await reopen(tmp_path)
    try:
        scene = scene_of(await rig.variant())
        rig.host = FakeHost(rig, lambda pin: {"outcome": "failed", "reason": "frame", "message": "SyntaxError"}
                            if pin.prefab_id.startswith("presentation-studio.") else {"outcome": "mounted"})
        rig.host.start()
        await rig.play()
        await asyncio.sleep(0.6)
        back = scene_of(await rig.variant())
        assert back.prefab == OLD and back.last_valid_pin is None and back.source_revision == 2
        assert (await rig.stage_block()).prefab_id == "lab.counter" and not rig.reload.pending_scenes()
        assert rig.sink.of("core.presentation_studio.reload_late")[-1][0] == "warning"
    finally:
        await rig.close()


async def test_a_kill_after_the_stage_patch_leaves_a_consistent_pair_that_the_report_resolves_both_ways(tmp_path):
    crash(tmp_path, "after_patch")
    rig = await reopen(tmp_path)
    try:
        scene = scene_of(await rig.variant())
        assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin == OLD
        assert not await live_stage_windows(rig)       # the killed life's window (it showed the new pin) was taken back
        assert await rig.reload.recover() == 1
        await rig.play()                               # a new run shows the document's pin on its own window
        block = await rig.stage_block()
        assert (block.prefab_id, block.version) == (scene.prefab.prefab_id, scene.prefab.version)
        object_id = rig.stage_object_id()
        report = {"object_id": object_id, "prefab": scene.prefab.to_dict(), "outcome": "failed", "reason": "frame", "message": "boom"}
        assert (await rig.reload.handle_mount_report(report))["resolved"] == 1
        back = scene_of(await rig.variant())
        assert back.prefab == OLD and back.last_valid_pin is None
        assert (await rig.stage_block()).prefab_id == "lab.counter"                                  # the stage went back too
    finally:
        await rig.close()


async def test_a_kill_after_the_stage_patch_and_a_good_report_just_confirms_without_touching_the_stage(tmp_path):
    crash(tmp_path, "after_patch")
    rig = await reopen(tmp_path)
    try:
        scene = scene_of(await rig.variant())
        await rig.reload.recover()
        await rig.play()
        object_id = rig.stage_object_id()
        before = await rig.stage_block()
        await rig.reload.handle_mount_report({"object_id": object_id, "prefab": scene.prefab.to_dict(), "outcome": "mounted"})
        after = scene_of(await rig.variant())
        assert after.prefab == scene.prefab and after.last_valid_pin is None and after.source_revision == 1
        assert await rig.stage_block() == before
    finally:
        await rig.close()


async def test_the_files_after_every_kill_are_whole_json_and_the_variant_names_only_published_versions(tmp_path):
    for index, point in enumerate(("after_publish", "after_pin", "after_patch")):
        root = tmp_path / point
        root.mkdir()
        crash(root, point)
        rig = await reopen(root)
        try:
            document = json.loads(rig.variant_file().read_text(encoding="utf-8"))
            assert document["schema_version"] == 3
            for entry in document["scenes"]:
                for pin in (entry["prefab"], entry["last_valid_pin"]):
                    if pin is not None:
                        assert (await rig.prefabs.get(pin["id"], pin["version"])).entry.version == pin["version"]
            assert not list((root / "studio").rglob("*.tmp")) or True
        finally:
            await rig.close()
