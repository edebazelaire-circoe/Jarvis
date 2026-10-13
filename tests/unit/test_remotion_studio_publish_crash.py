"""Publication Remotion Studio -> variante interrompue par un VRAI arrêt brutal (native-studio-playback-fix Slice 12).

Un sous-processus (une vie de Core : services neufs sur les mêmes dossiers) publie l'espace de travail ; le parent le TUE
(`Popen.kill`, TerminateProcess sous Windows : aucun nettoyage, aucun `finally`) à l'un de deux instants :

1. `during_build` : la compilation du garde tourne (rien n'est publié encore) ;
2. `after_pin` : la nouvelle version est publiée ET épinglée dans la variante, l'espace de travail n'est pas encore rebasé.

Une troisième vie relit les dossiers et vérifie : la version précédente est intacte et (1) toujours épinglée, l'espace garde ses
fichiers non publiés et la publication suivante réussit ; (2) la scène tient la nouvelle version, l'espace est encore sur l'ancienne
base, et la publication suivante le constate (« déjà publié ») et rebase sans rien publier de plus. Contrat :
`docs/presentation-studio.md` › *Remotion Studio round trip (Level 3, Slice 12)*.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from jarvis.domain.prefab import PrefabRef
from tests.fakes.remotion_edit_rig import BASE, SCENE_TSX, SID, RemotionRig
from tests.unit.test_remotion_studio_publish import EDITED, PIN, Bench, own_ids, scene_pin

pytestmark = pytest.mark.asyncio

REPO = Path(__file__).resolve().parents[2]
CHILD = r"""
import asyncio, sys
from pathlib import Path
from tests.fakes.remotion_edit_rig import RemotionRig
from tests.unit.test_remotion_studio_publish import Bench

root, runtime, point, marker = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])

async def main():
    rig = await RemotionRig(root, existing=True).open()
    bench = Bench(rig, runtime)
    if point == "during_build":
        async def hang(source):
            marker.write_text("building", encoding="utf-8")
            await asyncio.sleep(300)
        rig.fake.check_build = hang
    else:
        publisher = bench.service._publisher
        real = publisher.publish
        async def publish_then_hang(*args, **kwargs):
            result = await real(*args, **kwargs)
            marker.write_text("pinned " + result.status.value, encoding="utf-8")
            await asyncio.sleep(300)
            return result
        publisher.publish = publish_then_hang
    await bench.publish()

asyncio.run(main())
"""


async def prepare(tmp_path) -> Path:
    rig = await RemotionRig(tmp_path).open(show=False)
    runtime = tmp_path / "rt" / "local_capabilities" / "remotion" / "runtime"
    runtime.mkdir(parents=True)
    bench = Bench(rig, runtime)
    await bench.materialize()
    bench.write("src/Scene.tsx", EDITED)
    await rig.close()
    return runtime


def run_and_kill(tmp_path, runtime, point) -> tuple[str, float]:
    marker = tmp_path / f"marker-{point}"
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    started = time.monotonic()
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(tmp_path), str(runtime), point, str(marker)], cwd=REPO, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 120
        while not marker.exists():
            if child.poll() is not None:
                out, err = child.communicate()
                raise AssertionError(f"the child ended before the kill point: {err.decode(errors='replace')[-2000:]}")
            if time.monotonic() > deadline:
                raise AssertionError("the child never reached the kill point")
            time.sleep(0.05)
        child.kill()   # the real thing: TerminateProcess, no cleanup in the child
        child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
    return marker.read_text(encoding="utf-8"), time.monotonic() - started


async def test_killed_during_the_build_nothing_moved_and_the_next_publish_works(tmp_path):
    runtime = await prepare(tmp_path)
    reached, _ = run_and_kill(tmp_path, runtime, "during_build")
    assert reached == "building"
    rig = await RemotionRig(tmp_path, existing=True).open()
    try:
        bench = Bench(rig, runtime)
        assert await scene_pin(rig) == PrefabRef(BASE, 1) and own_ids(rig) == [], "nothing was published nor pinned"
        assert (await rig.source_of(PrefabRef(BASE, 1)))["src/Scene.tsx"] == SCENE_TSX, "the previous version is intact"
        assert (bench.work / "src" / "Scene.tsx").read_bytes().decode("utf-8") == EDITED
        status = await bench.service.status()
        assert status["work_copy"]["modified_files"] == ["src/Scene.tsx"] and status["pin"] == PIN.to_dict()
        outcome = (await bench.publish())["publish"]
        assert outcome["status"] in ("reloaded", "repinned", "pending_mount") and outcome["previous"] == PIN.to_dict()
        assert (await rig.source_of(await scene_pin(rig)))["src/Scene.tsx"] == EDITED
    finally:
        await rig.close()


async def test_killed_after_the_pin_before_the_rebase_the_next_publish_rebases_without_publishing_again(tmp_path):
    runtime = await prepare(tmp_path)
    reached, _ = run_and_kill(tmp_path, runtime, "after_pin")
    assert reached.startswith("pinned ")
    rig = await RemotionRig(tmp_path, existing=True).open()
    try:
        bench = Bench(rig, runtime)
        pin = await scene_pin(rig)
        assert pin.prefab_id.startswith("presentation-studio.") and (await rig.source_of(pin))["src/Scene.tsx"] == EDITED
        assert (await rig.source_of(PrefabRef(BASE, 1)))["src/Scene.tsx"] == SCENE_TSX, "the previous version is intact (rollback target)"
        status = await bench.service.status()
        assert status["pin"] == PIN.to_dict() and status["work_copy"]["unpublished"] == 1, "the kill came before the rebase"
        versions = rig.versions_of(pin.prefab_id)
        answer = await bench.publish()
        assert answer["publish"]["status"] == "already_published" and answer["publish"]["published"] == {"prefab_id": pin.prefab_id, "version": pin.version}
        assert rig.versions_of(pin.prefab_id) == versions, "no second version for the same content"
        assert answer["studio"]["pin"] == {"prefab_id": pin.prefab_id, "version": pin.version} and answer["studio"]["work_copy"]["unpublished"] == 0
        assert "remotion_studio.publish_rebased" in rig.sink.kinds()
        assert own_ids(rig) == [pin.prefab_id] and rig.fake.calls == [], "nothing was built or published by the rebase"
    finally:
        await rig.close()
