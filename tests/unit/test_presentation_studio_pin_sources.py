"""Chaque source de pins du Studio protege vraiment sa version contre la retention 01a (Slice 06, merge).

Registre REEL (`StudioPinRegistry`) branche comme `v2_app` le fait, sur un magasin qui contient : une variante vivante, une variante
ARCHIVEE (Slice 16), une entree de la pile d'annulation (Slice 08) et une lecture en cours dont la fenetre `studio-stage-<run_id>`
montre une version que plus aucun document ne nomme (Slice 12). Chaque version n'est epinglee que par UNE source ; plus de 64
versions sont ensuite publiees : la retention reelle archive les autres, jamais celle-la.
Contrat : `docs/prefabs.md` > *Entry conditions for Slice 06* ; `docs/presentation-studio.md` > *Pins and retention*.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from tests.fakes.presentation_studio_reload import GOOD_STYLE, SID, SID2, Rig, scene_body

pytestmark = pytest.mark.asyncio

SID3, SID4 = "pss_0000000000a3", "pss_0000000000a4"


async def publish(rig: Rig, source_id: str, count: int) -> None:
    manifest = json.loads((rig.data / "prefabs" / "lab.counter" / "1" / "manifest.json").read_text(encoding="utf-8"))
    for index in range(count):
        await rig.prefabs.save({"manifest": {**manifest, "id": source_id}, "template": "<p>x</p>",
                                "style": f"p{{--n:{index}}}", "behavior": "// b"}, actor="user")


async def save_scenes(rig: Rig, scenes: list) -> None:
    variant = await rig.variant()
    await rig.studio.save_variant(rig.pid, rig.vid, {"expected_revision": variant.revision, "title": variant.title,
                                                     "scenes": scenes, "art_direction_id": None, "score_id": variant.score_id})


def bodies(variant) -> list[dict]:
    return [scene.to_dict() for scene in variant.scenes]


def extra(scene_id: str, source_id: str, version: int) -> dict:
    return scene_body(scene_id, prefab=(source_id, version), controls=[], anchors=[], props={}, data={"count": 1})


async def test_a_version_pinned_by_each_single_source_is_never_archived_at_64_plus_versions(tmp_path):
    rig = await Rig(tmp_path, quiet_s=0.01, max_wait_s=0.05, mount_deadline_s=1.0).open(
        scenes=[scene_body(), scene_body(SID2, title="Milieu")])
    try:
        # v1: the scene's own source, published by a reload; a BRANCH copies the pin, then is ARCHIVED (Slice 16)
        assert (await rig.edit({"style": GOOD_STYLE})).status is S.RELOADED
        source_id = (await rig.variant()).scenes[0].prefab.prefab_id
        assert source_id.startswith("presentation-studio.") and rig.versions_of(source_id) == [1]
        branch = await rig.variants.create_branch(rig.pid, {"title": "Autre piste"})
        planned = await rig.variants.plan_archive(rig.pid, branch["node"]["variant_id"], None)
        await rig.variants.archive(rig.pid, branch["node"]["variant_id"], {"confirmation": planned["confirmation"]})
        # v2..v5 published by hand: the next reload will move the main scene past them
        await publish(rig, source_id, 4)
        assert rig.versions_of(source_id) == [1, 2, 3, 4, 5]
        assert (await rig.edit({"style": "p{color:red}"})).status is S.RELOADED                       # v6: scene 1 leaves v1
        current = (await rig.variant()).scenes[0].prefab.version
        assert current == 6
        # v2: only a LIVE variant document names it (scene 3)
        await save_scenes(rig, [*bodies(await rig.variant()), extra(SID3, source_id, 2)])
        # v3: only an UNDO entry holds it (scene 4 was added, then removed: its inverse `scene.add` carries the pin)
        await save_scenes(rig, [*bodies(await rig.variant()), extra(SID4, source_id, 3)])
        removed = await rig.edits.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit",
                                                          "basis": {"variant_revision": (await rig.variant()).revision},
                                                          "ops": [{"op": "scene.remove", "scene_id": SID4}]})
        assert removed.committed and SID4 not in [s.scene_id for s in (await rig.variant()).scenes]
        assert ("presentation-studio." in source_id) and (source_id, 3) in rig.history.pins()
        # v4: only the RUNNING PLAYBACK's stage window shows it (scene 2 pinned to v4, shown, then re-pinned to v5 in the document)
        variant = await rig.variant()
        await save_scenes(rig, [bodies(variant)[0], extra(SID2, source_id, 4), *bodies(variant)[2:]])
        if rig.playback.state.phase.value == "paused":                                               # the undo-entry edit above paused the run
            assert (await rig.playback.resume({"actor": "user"})).status.value == "applied"
        moved = await rig.playback.next({"actor": "user"})
        assert moved.status.value == "applied", moved.to_dict()
        assert (await rig.stage_block()).version == 4
        variant = await rig.variant()
        await save_scenes(rig, [bodies(variant)[0], {**bodies(variant)[1], "prefab": {"id": source_id, "version": 5}}, *bodies(variant)[2:]])
        assert (await rig.stage_block()).version == 4                                              # the window alone names v4
        names = {(s.prefab.prefab_id, s.prefab.version) for s in (await rig.variant()).scenes}
        assert (source_id, 4) not in names and (source_id, 1) not in names and (source_id, 3) not in names
        # the registry, asked directly, says who holds what BEFORE the retention pass
        started = time.monotonic()
        held = (await rig.pins.pinned_versions([source_id, "lab.counter", "presentation-studio.nobody"]))
        assert time.monotonic() - started < 1.0 and set(held) == {source_id, "lab.counter", "presentation-studio.nobody"}
        assert {1, 2, 3, 4, 5, current} <= held[source_id] and isinstance(held[source_id], frozenset)
        # now 70 more versions: the real retention pass runs on each publication
        await publish(rig, source_id, 70)
        survivors = rig.versions_of(source_id)
        for version, who in ((1, "archived variant"), (2, "live variant"), (3, "undo entry"), (4, "playback stage window"),
                             (5, "live variant (scene 2)"), (current, "live variant (scene 1)")):
            assert version in survivors, (version, who, survivors)
        archive = rig.data / "prefabs" / ".archive" / source_id
        archived = sorted(int(p.name) for p in archive.iterdir())
        assert archived and 7 in archived and 8 in archived, archived                               # unpinned ones really went
        assert not set(archived) & {1, 2, 3, 4, 5, current}
        assert len(survivors) <= 32 and not rig.sink.of("core.prefab.retention_failed")
        for version in (1, 2, 3, 4):                                                                 # and they still load
            assert (await rig.prefabs.get(source_id, version)).entry.version == version
    finally:
        await rig.close()


async def test_an_archived_variants_pin_survives_a_restart_and_a_restore_resolves(tmp_path):
    """The acceptance check of the Slice 16 merge condition: archive a variant, restart, retire old versions, restore it."""

    rig = await Rig(tmp_path, quiet_s=0.01, max_wait_s=0.05, mount_deadline_s=1.0).open()
    try:
        assert (await rig.edit({"style": GOOD_STYLE})).status is S.RELOADED
        source_id = (await rig.variant()).scenes[0].prefab.prefab_id
        branch = await rig.variants.create_branch(rig.pid, {"title": "Archivee"})
        branch_id = branch["node"]["variant_id"]
        planned = await rig.variants.plan_archive(rig.pid, branch_id, None)
        await rig.variants.archive(rig.pid, branch_id, {"confirmation": planned["confirmation"]})
        await publish(rig, source_id, 4)
        assert (await rig.edit({"style": "p{color:red}"})).status is S.RELOADED
    finally:
        await rig.close()
    again = await Rig(tmp_path, existing=True, quiet_s=0.01, max_wait_s=0.05).open()                # a restart: the index is rebuilt
    try:
        assert again.pins.ready
        held = await again.pins.pinned_versions([source_id])
        assert 1 in held[source_id]                                                                    # the ARCHIVED variant's pin
        await publish(again, source_id, 70)                                                            # retire old versions
        assert 1 in again.versions_of(source_id)
        restored = await again.variants.restore(again.pid, branch_id, None)
        scene = next(s for s in (await again.studio.get_variant(again.pid, branch_id)).scenes if s.scene_id == SID)
        assert scene.prefab.version == 1 and (await again.prefabs.get(source_id, 1)).entry.version == 1
        assert restored is not None
    finally:
        await again.close()


async def test_the_registry_stays_closed_when_a_source_cannot_answer(tmp_path):
    rig = await Rig(tmp_path).open()
    try:
        rig.pins._ready = False                                                                         # an index that is not built
        with pytest.raises(RuntimeError):
            await rig.pins.pinned_versions(["lab.counter"])
        rig.pins._ready = True

        async def broken():
            raise RuntimeError("the scene is down")

        rig.pins._scene.snapshot = broken                                                              # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="down"):
            await asyncio.wait_for(rig.pins.pinned_versions(["lab.counter"]), 5)                       # never "no pin": it raises
    finally:
        await rig.close()


async def test_an_edit_that_removes_a_scene_holds_its_pin_through_the_write_because_the_history_reserves_it_first(tmp_path):
    """Ordering with the Slice 08 reservation: `begin` (reserve) -> registry registers the NEW document (without the pin) ->
    file write -> `commit` (entry). While the write is in flight only the reservation names the pin; after it only the entry."""

    import threading

    rig = await Rig(tmp_path, quiet_s=0.01, max_wait_s=0.05, mount_deadline_s=1.0).open(show=False)
    try:
        assert (await rig.edit({"style": GOOD_STYLE})).status is S.REPINNED
        source_id = (await rig.variant()).scenes[0].prefab.prefab_id
        await publish(rig, source_id, 2)                                                        # v2, v3
        await save_scenes(rig, [*bodies(await rig.variant()), extra(SID3, source_id, 3)])
        held = await rig.pins.pinned_versions([source_id])
        assert 3 in held[source_id]                                                              # named by the document (scene 3)
        entered, release = threading.Event(), threading.Event()
        real = rig.studio._store.write_variant

        def slow(presentation_id, variant_id, text):
            entered.set()
            release.wait(20)
            return real(presentation_id, variant_id, text)

        rig.studio._store.write_variant = slow
        revision = (await rig.variant()).revision
        removal = asyncio.ensure_future(rig.edits.edit(rig.pid, rig.vid, {
            "actor": "user", "mode": "commit", "basis": {"variant_revision": revision},
            "ops": [{"op": "scene.remove", "scene_id": SID3}]}))
        assert await asyncio.to_thread(entered.wait, 10)                                        # the write is in flight
        assert (source_id, 3) in rig.history.pins()                                              # reserved BEFORE the write
        during = await rig.pins.pinned_versions([source_id])
        assert 3 in during[source_id]                                                            # nothing could archive it now
        rig.studio._store.write_variant = real
        release.set()
        assert (await removal).committed
        assert (source_id, 3) in rig.history.pins()                                              # the entry holds it now
        after = await rig.pins.pinned_versions([source_id])
        assert 3 in after[source_id] and SID3 not in [s.scene_id for s in (await rig.variant()).scenes]
    finally:
        await rig.close()
