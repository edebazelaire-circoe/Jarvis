"""The run surface of Variants (handoff jarvis-remotion-native-studio-playback-fix, Slice 09), against the real playback service.

Proved here:
- the surface is memory only: a run creates no Board object; its id, revision, snapshot and pins are what the page and the pin
  registry read; a hot-reload re-pin is a compare-and-set (`stage_missing`, `stage_changed`, idempotent) and goes through the catalogue;
- a stage sync is BOUNDED: a `show` that never resolves pauses the run with `stage_timeout` (an actionable state: « Reprendre » retries,
  « Arrêter » stops), and a `stop` PRE-EMPTS a sync in flight instead of queueing behind the playback lock (the "stuck show" defect
  carried from Slice 07);
- the reload's `StageWindows` reads and re-pins this surface.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from jarvis.core.presentation_studio_playback import PlaybackStatus
from jarvis.core.presentation_studio_reload_stage import StageBinding, StagePatchError, StageWindows
from jarvis.core.presentation_studio_run_surface import RunSurface
from jarvis.core.presentation_studio_stage import StageError
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.scene import ScenePayload, ScenePrefabRef
from tests.unit.test_presentation_studio_playback_service import AUX_BLOCK, Rig, applied


def payload(title: str, label: str = "x") -> ScenePayload:
    return ScenePayload(title=title, prefab=ScenePrefabRef("lab.counter", 1, {"label": label}, {"count": 1}))


@pytest.fixture
async def rig(tmp_path):
    made = await Rig(tmp_path).open()
    yield made
    await made.close()


# ------------------------------------------------------------------ the surface itself

async def test_the_surface_is_memory_its_id_names_the_run_and_a_same_payload_writes_nothing(rig):
    surface = rig.stage
    assert surface.stage_object_id is None and surface.snapshot() is None
    with pytest.raises(StageError) as caught:
        await surface.show(payload("Un"))
    assert caught.value.code == "stage_not_begun"
    surface.begin("rx")
    assert surface.stage_object_id is None                                   # nothing shown yet: no surface to mount
    assert await surface.show(payload("Un")) is True
    revision = surface.revision
    assert surface.stage_object_id == "variants-run-rx" and await surface.show(payload("Un")) is False
    assert surface.revision == revision                                      # the frame's own state is not reset
    snap = surface.snapshot()
    assert snap["surface_id"] == "variants-run-rx" and snap["title"] == "Un" and snap["prefab"]["id"] == "lab.counter"
    assert snap["prefab"]["data"]["count"] == 1 and snap["overlays"] == []                # validated, defaults filled
    assert surface.pins() == {("lab.counter", 1)}
    await surface.release()
    assert surface.stage_object_id is None and surface.snapshot() is None and surface.pins() == set()
    assert await rig.objects() == []                                         # never a Board object


async def test_overlays_are_hidden_at_birth_revealed_retired_and_pinned(rig):
    surface = rig.stage
    surface.begin("rx")
    await surface.show(payload("Un"))
    overlay = await surface.stage_aux("a1", "Annexe", ScenePrefabRef("lab.counter", 1, {"label": "A"}, {"count": 2}))
    assert overlay == "variants-run-rx-a1"
    [wire] = surface.snapshot()["overlays"]
    assert (wire["overlay_id"], wire["title"], wire["visible"]) == (overlay, "Annexe", False)
    assert wire["prefab"]["id"] == "lab.counter" and wire["prefab"]["props"]["label"] == "A" and wire["prefab"]["data"]["count"] == 2
    await surface.reveal_aux(overlay)
    assert surface.snapshot()["overlays"][0]["visible"] is True
    await surface.retire([overlay, "variants-run-rx-gone"])                  # an id already gone is not a failure
    assert surface.snapshot()["overlays"] == []
    with pytest.raises(StageError) as caught:
        await surface.reveal_aux(overlay)
    assert caught.value.code == "unknown_object"


async def test_waiting_for_a_revision_wakes_on_a_change_and_times_out_otherwise():
    surface = RunSurface()
    surface.begin("rx")
    start = surface.revision
    waiter = asyncio.create_task(surface.wait_for_revision(start, timeout_s=5))
    await asyncio.sleep(0.01)
    await surface.show(payload("Un"))
    assert await waiter > start
    began = time.monotonic()
    assert await surface.wait_for_revision(surface.revision, timeout_s=0.05) == surface.revision
    assert time.monotonic() - began < 1


async def test_stage_windows_reads_and_repins_the_surface_by_compare_and_set(rig):
    surface = rig.stage
    windows = StageWindows(surface)
    surface.begin("rx")
    await surface.show(payload("Un"))
    binding = StageBinding("pst", "psv", "s1", surface.stage_object_id, "rx")
    old, new = PrefabRef("lab.counter", 1), PrefabRef("lab.counter", 2)
    assert (await windows.current(binding)).prefab_id == "lab.counter"
    windows.bind(binding)
    assert await windows.locate("pst", "psv", "s1", old) == binding
    assert await windows.locate("pst", "psv", "s1", new) is None             # another pin on screen: only re-pinned
    with pytest.raises(StagePatchError) as caught:                           # the catalogue refuses an unknown version
        await windows.repin(binding, expect=old, to=PrefabRef("lab.nothing", 1), props={}, data={})
    assert caught.value.code == "prefab_invalid"
    with pytest.raises(StagePatchError) as caught:
        await windows.repin(binding, expect=PrefabRef("lab.counter", 9), to=new, props={"label": "x"}, data={"count": 1})
    assert caught.value.code == "stage_changed"
    revision = surface.revision
    await windows.repin(binding, expect=old, to=old, props={"label": "x"}, data={"count": 1})   # already there: nothing written
    assert surface.revision == revision
    stranger = StageBinding("pst", "psv", "s1", "variants-run-other", "other")
    with pytest.raises(StagePatchError) as caught:
        await windows.repin(stranger, expect=old, to=old, props={}, data={})
    assert caught.value.code == "stage_missing"
    assert await windows.current(stranger) is None


# ------------------------------------------------------------------ the stuck show (Slice 07 finding, owner Slice 09)

class _Hanging:
    """A surface whose `show` never resolves once `hang` is set (what a stuck scene write looked like)."""

    def __init__(self, inner: RunSurface) -> None:
        self.inner, self.hang, self.entered = inner, False, asyncio.Event()

    def __getattr__(self, name):
        return getattr(self.inner, name)

    @property
    def stage_object_id(self):
        return self.inner.stage_object_id

    @property
    def revision(self):
        return self.inner.revision

    async def show(self, payload):
        if self.hang:
            self.entered.set()
            await asyncio.Event().wait()
        return await self.inner.show(payload)


async def test_a_show_that_never_resolves_pauses_the_run_with_a_bounded_actionable_problem(rig):
    hanging = _Hanging(rig.stage)
    rig.stage = hanging
    rig.build(stage_sync_timeout_s=0.2)
    applied(await rig.service.start(rig.start_body()))
    hanging.hang = True
    began = time.monotonic()
    result = await rig.run("next")
    assert time.monotonic() - began < 2                                       # bounded, never forever
    assert result.status is PlaybackStatus.STAGE_FAILED and result.reason == "stage_timeout"
    state = rig.service.where()
    assert state["phase"] == "paused" and state["problems"] == ["stage_timeout"]
    assert rig.env.sink.of("core.presentation_studio.playback_stage_sync_timeout")[0][0] == "error"
    hanging.hang = False                                                      # the cause went away: « Reprendre » retries
    state = applied(await rig.run("resume"))
    assert state["phase"] == "playing" and (await rig.stage_object()).payload.title == "Deux"


async def test_a_stop_pre_empts_a_sync_that_never_ends_instead_of_queueing_behind_the_lock(rig):
    hanging = _Hanging(rig.stage)
    rig.stage = hanging
    rig.build(stage_sync_timeout_s=60.0)                                      # the bound is far: only the pre-emption can help
    applied(await rig.service.start(rig.start_body()))
    hanging.hang = True
    stuck = asyncio.create_task(rig.run("next"))
    await asyncio.wait_for(hanging.entered.wait(), 5)
    began = time.monotonic()
    stopped = await asyncio.wait_for(rig.run("stop"), 5)
    assert time.monotonic() - began < 2
    assert stopped.status is PlaybackStatus.APPLIED and rig.service.where()["phase"] == "stopped"
    interrupted = await asyncio.wait_for(stuck, 5)
    assert interrupted.status is PlaybackStatus.STAGE_FAILED and interrupted.reason == "stage_preempted"
    assert await rig.stage_object() is None and rig.overlays() == []


async def test_the_view_names_the_surface_and_the_route_serves_its_snapshot_with_overlays(rig):
    applied(await rig.service.start(rig.start_body()))
    state = applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))
    surface = rig.service.surface()
    assert state["surface"] == {"id": surface["surface_id"], "rev": surface["revision"]}
    assert surface["run_id"] == state["run_id"] and [o["visible"] for o in surface["overlays"]] == [True]
    applied(await rig.run("stop"))
    assert rig.service.surface() is None


# ------------------------------------------------------------------ what starts the Player in Variants (no grace play any more)

async def test_an_anchorless_remotion_scene_gets_one_whole_segment_in_a_run_the_user_paces(tmp_path):
    """The Variants Player never plays by itself (no grace play, `embed=variants`): Core's order starts it. A Remotion scene without
    anchors, in a `manual` run the user paces, therefore gets one whole segment (from 0 to its last frame, then held), not "no timeline"
    as before Slice 09 (when the run stage's grace play started it)."""

    from tests.unit.test_presentation_studio_playback_service import scenes_body
    from tests.unit.test_remotion_timeline_service import COMP, Compositions
    scenes = scenes_body()
    scenes[0] = {**scenes[0], "anchors": []}                                  # S1, the first item's scene, has no anchor
    rig = await Rig(tmp_path).open(scenes=scenes)
    rig.build(timeline_source=Compositions(COMP))
    try:
        state = applied(await rig.service.start(rig.start_body("user_presenter")))
        timeline = state["timeline"]
        assert state["scope"] == "manual" and timeline["auto"] is False
        assert (timeline["anchor_id"], timeline["from_frame"], timeline["until_frame"], timeline["playing"]) == (None, 0, 299, True)
        assert "timeline_unresolved" not in state
    finally:
        await rig.close()


async def test_a_scene_whose_timeline_cannot_be_read_is_named_so_the_page_plays_it_once_unguided(tmp_path):
    from tests.unit.test_remotion_timeline_service import Compositions
    rig = await Rig(tmp_path).open()
    rig.build(timeline_source=Compositions(OSError("manifest unreadable")))
    try:
        state = applied(await rig.service.start(rig.start_body()))
        assert "timeline" not in state and state["timeline_unresolved"].startswith("pss_")
        assert "timeline_unresolved" in state["notices"]
        applied(await rig.run("stop"))
        assert "timeline_unresolved" not in rig.service.where()
    finally:
        await rig.close()
