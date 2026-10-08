"""Le registre des epinglages du Studio, avec la VRAIE retention de la Slice 01a (jarvis-interactive-presentation-studio, Slice 06).

Prouve les conditions d'entree de `docs/prefabs.md` > *Retention of studio scene sources* : le registre couvre les documents
(Slices 02/04/05), la scene globale vivante et les retenues en vol ; un magasin enregistre un ancien pin AVANT de l'ecrire ;
le registre ferme par defaut (index absent, incomplet, scene non liee) ; il repond de memoire, sans le verrou du Studio.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from jarvis.core.presentation_studio_pins import StudioPinRegistry
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload,
    ScenePrefabRef,
)
from tests.fakes.presentation_studio_reload import GOOD_STYLE, SID, SID2, Rig, scene_body

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def rig(tmp_path):
    opened = await Rig(tmp_path).open()
    yield opened
    await opened.close()


async def window(rig: Rig, object_id: str, prefab_id: str, version: int) -> None:
    await rig.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id=object_id,
                                       fields=SceneObjectFields(
                                           kind=SceneObjectKind.WINDOW, category="note", representation=Representation.WINDOW,
                                           geometry=SceneGeometry(0, 0, 40, 24),
                                           payload=ScenePayload(title="w", prefab=ScenePrefabRef(prefab_id, version, {}, {"count": 1})))))


# ------------------------------------------------------------------ ce que le registre couvre

async def test_the_registry_answers_every_requested_id_with_the_pins_of_all_its_sources(rig):
    # documents: the two scenes pin lab.counter@1 ; a user window of the live scene pins another id ; a hold ; an extra source
    await window(rig, "user-window", "jarvis.counter", 1)
    rig.pins.add_source("extra", lambda: [("lab.counter", 7)])
    with rig.pins.hold(("lab.counter", 9)):
        answer = await rig.pins.pinned_versions(["lab.counter", "jarvis.counter", "presentation-studio.nobody"])
    assert answer == {"lab.counter": frozenset({1, 7, 9}), "jarvis.counter": frozenset({1}),
                      "presentation-studio.nobody": frozenset()}
    assert (await rig.pins.pinned_versions(["lab.counter"]))["lab.counter"] == frozenset({1, 7})     # the hold is gone


async def test_a_scenes_fallback_pin_is_covered_as_long_as_it_is_unconfirmed(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=0.2).open(host=False, show=False)
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.REPINNED
    pinned = await rig.pins.pinned_versions(["lab.counter", result.prefab.prefab_id])
    assert pinned["lab.counter"] == frozenset({1}) and pinned[result.prefab.prefab_id] == frozenset({1})
    await rig.close()


async def test_the_live_scene_pins_cover_every_frame_the_host_may_reload(rig):
    for index in range(3):
        assert (await rig.edit({"style": f"p{{color:#00000{index}}}"})).status is S.RELOADED
    stage = await rig.stage_block()
    await window(rig, "w-a", stage.prefab_id, 1)           # a second frame the host may redraw or reload
    await window(rig, "w-b", stage.prefab_id, 2)
    answer = await rig.pins.pinned_versions([stage.prefab_id])
    assert stage.version == 3 and answer[stage.prefab_id] == frozenset({1, 2, 3})


# ------------------------------------------------------------------ fermeture par defaut

async def test_the_registry_refuses_to_answer_until_its_index_is_built_and_while_it_is_incomplete(rig):
    fresh = StudioPinRegistry(diagnostics=rig.sink)
    fresh.bind_scene(rig.scene)
    with pytest.raises(RuntimeError, match="not built"):
        await fresh.pinned_versions(["lab.counter"])
    assert await fresh.rebuild(rig.variants) and (await fresh.pinned_versions(["lab.counter"]))["lab.counter"] == frozenset({1})
    fresh.mark_degraded("a variant file was unreadable")
    with pytest.raises(RuntimeError, match="incomplete"):
        await fresh.pinned_versions(["lab.counter"])
    assert rig.sink.of("core.presentation_studio.pins_degraded")[0][0] == "error"


async def test_without_a_bound_scene_the_registry_cannot_answer(rig):
    unbound = StudioPinRegistry()
    unbound.mark_ready()
    with pytest.raises(RuntimeError, match="not bound"):
        await unbound.pinned_versions(["lab.counter"])


async def test_an_unreadable_presentation_closes_the_index_instead_of_pinning_nothing(rig):
    rig.variant_file().write_text("{ not json", encoding="utf-8")
    fresh = StudioPinRegistry(diagnostics=rig.sink)
    fresh.bind_scene(rig.scene)
    assert await fresh.rebuild(rig.variants) is False and not fresh.ready
    with pytest.raises(RuntimeError):
        await fresh.pinned_versions(["lab.counter"])


async def test_a_second_source_name_is_refused(rig):
    rig.pins.add_source("extra", lambda: [])
    with pytest.raises(ValueError):
        rig.pins.add_source("extra", lambda: [])
    with pytest.raises(ValueError):
        rig.pins.add_source("undo", lambda: [])          # the Slice 08 source is already wired by the bench (as `v2_app` does)


# ------------------------------------------------------------------ enregistrer avant d'ecrire

async def test_a_store_registers_the_pin_before_the_file_is_written_and_restores_the_set_when_the_write_fails(rig, monkeypatch):
    seen: list[frozenset] = []
    real = rig.studio._store.write_variant

    def spying(presentation_id, variant_id, text):
        seen.append(rig.pins._variants[(presentation_id, variant_id)])          # what the registry knows AT write time
        raise OSError("disk full")

    monkeypatch.setattr(rig.studio._store, "write_variant", spying)
    before = rig.pins._variants[(rig.pid, rig.vid)]
    variant = await rig.variant()
    with pytest.raises(PresentationStudioError):
        await rig.studio.save_variant(rig.pid, rig.vid, {
            "expected_revision": variant.revision, "title": variant.title, "art_direction_id": None, "score_id": (await rig.variant()).score_id,
            "scenes": [scene_body(prefab=("lab.counter", 1)), scene_body(SID2, prefab=("jarvis.counter", 1), controls=[], anchors=[],
                                                                      props={}, data={"count": 1})]})
    assert seen == [frozenset({("lab.counter", 1), ("jarvis.counter", 1)})]       # registered first ...
    assert rig.pins._variants[(rig.pid, rig.vid)] == before                         # ... and put back after the failed write
    monkeypatch.setattr(rig.studio._store, "write_variant", real)


async def test_retention_racing_a_pin_write_cannot_archive_the_version_being_pinned(tmp_path):
    """The window the QA of Slice 01a named (I3): publication of version N, retention pass, then the pin of an OLD version.
    The old version is registered before the write, so a retention pass that runs while the write is in flight spares it."""

    rig = await Rig(tmp_path, mount_deadline_s=1.0).open()
    for index in range(3):
        assert (await rig.edit({"style": f"p{{color:#00000{index}}}"})).status is S.RELOADED
    source_id = (await rig.variant()).scenes[0].prefab.prefab_id
    assert source_id.startswith("presentation-studio.") and rig.versions_of(source_id) == [1, 2, 3]
    entered, release = threading.Event(), threading.Event()
    real = rig.studio._store.write_variant

    def slow_write(presentation_id, variant_id, text):
        entered.set()
        release.wait(20)
        return real(presentation_id, variant_id, text)

    rig.studio._store.write_variant = slow_write
    variant = await rig.variant()
    pin_old = asyncio.ensure_future(rig.studio.save_variant(rig.pid, rig.vid, {
        "expected_revision": variant.revision, "title": variant.title, "art_direction_id": None, "score_id": (await rig.variant()).score_id,
        "scenes": [variant.scenes[0].to_dict(), {**scene_body(SID2, prefab=(source_id, 1), controls=[], anchors=[],
                                                              props={}, data={"count": 1})}]}))
    assert await asyncio.to_thread(entered.wait, 10)                             # the write is in flight, the file not yet replaced
    rig.studio._store.write_variant = real
    # ... meanwhile 40 more publications of the same id run the retention pass (pins are read from the registry only)
    moved = []
    for index in range(40):
        await rig.prefabs.save({"manifest": {**json.loads((rig.data / "prefabs" / "lab.counter" / "1" / "manifest.json").read_text(encoding="utf-8")),
                                             "id": source_id},
                                "template": "<p>x</p>", "style": f"p{{--n:{index}}}", "behavior": "// b"}, actor="user")
    release.set()
    await pin_old
    survivors = rig.versions_of(source_id)
    assert 1 in survivors, survivors                                                # the version being pinned was spared
    archived = rig.data / "prefabs" / ".archive" / source_id
    assert archived.exists() and 2 in [int(p.name) for p in archived.iterdir()]      # retention really ran and archived others
    await rig.close()


# ------------------------------------------------------------------ la retention reelle

async def test_forty_reloads_keep_the_live_set_bounded_and_never_archive_a_pinned_or_held_version(tmp_path):
    rig = await Rig(tmp_path, quiet_s=0.01, max_wait_s=0.05, mount_deadline_s=1.0).open()
    for index in range(3):
        assert (await rig.edit({"style": f"p{{color:#00000{index}}}"})).status is S.RELOADED
    source_id = (await rig.variant()).scenes[0].prefab.prefab_id
    # pin an OLD version from the second scene (as a scene-local variant or a template will) and put a window on version 2
    variant = await rig.variant()
    await rig.studio.save_variant(rig.pid, rig.vid, {
        "expected_revision": variant.revision, "title": variant.title, "art_direction_id": None, "score_id": (await rig.variant()).score_id,
        "scenes": [variant.scenes[0].to_dict(),
                   scene_body(SID2, prefab=(source_id, 1), controls=[], anchors=[], props={}, data={"count": 1})]})
    await window(rig, "slide-copy", source_id, 2)
    for index in range(40):
        result = await rig.edit({"style": f"p{{--n:{index}}}"})
        assert result.status is S.RELOADED, (index, result.message)
    live = rig.versions_of(source_id)
    current = (await rig.variant()).scenes[0].prefab.version
    assert 1 in live and 2 in live and current in live               # pinned by scene 2, by the live window, by scene 1
    assert 3 not in live and len(live) <= 32                         # everything else old was archived: the set is bounded
    archive = rig.data / "prefabs" / ".archive" / source_id
    assert sorted(int(p.name) for p in archive.iterdir())[:2] == [3, 4]
    assert not rig.sink.of("core.prefab.retention_failed")
    # the pinned old versions are still loadable (an archived one would answer unknown_version)
    assert (await rig.prefabs.get(source_id, 1)).entry.version == 1 and (await rig.prefabs.get(source_id, 2)).entry.version == 2
    await rig.close()


async def test_while_the_index_is_not_built_nothing_is_archived_and_the_refusal_is_visible(tmp_path):
    rig = Rig(tmp_path, quiet_s=0.01, max_wait_s=0.05, mount_deadline_s=1.0)
    await rig.open()
    rig.pins._ready = False
    for index in range(36):
        assert (await rig.edit({"style": f"p{{--n:{index}}}"})).status is S.RELOADED
    source_id = (await rig.variant()).scenes[0].prefab.prefab_id
    assert len(rig.versions_of(source_id)) == 36 and not (rig.data / "prefabs" / ".archive").exists()
    assert rig.sink.of("core.prefab.retention_failed")[0][0] == "error"
    await rig.close()


@pytest.mark.filterwarnings("ignore:coroutine .*_scan_for_pins.* was never awaited:RuntimeWarning")  # the probe call is cancelled on purpose
async def test_the_registry_never_takes_the_studio_lock(rig):
    """QA-1 (the surviving M5 mutation): retention asks the registry while the Studio is mid-write; an answer that waited for
    the Studio lock would stall a variant write behind retention and retention behind the write (deadlock)."""

    registry = rig.pins
    async with rig.studio._lock:                                          # a write is in progress and holds the lock
        # the harness can see a blocked call: rebuilding the index reads the variants, so it waits for that lock
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(registry.rebuild(rig.variants), 0.3)
        # the registry's own answers are memory only: they come back at once, with the lock held
        answer = await asyncio.wait_for(registry.pinned_versions(["lab.counter", "jarvis.counter"]), 1.0)
        assert 1 in answer["lab.counter"]
        before = registry.register_variant(rig.pid, rig.vid, {("lab.counter", 1)})
        registry.restore_variant(rig.pid, rig.vid, before)
        with registry.hold(("lab.counter", 1)):
            assert registry.stats() is not None
        assert registry.ready
