"""The agent's native loop on a scene it created (handoff jarvis-remotion-native-studio-playback-fix, Slice 13).

1. Refine its own scene: an `agent_authored_scene` record lets the brain write the source of a scene it just assembled, through the same
   validated source-edit route, without a user turn; multi-use, 30 minutes restarted at each use, ended by the user's own source edit.
2. Look at it: `PresentationRenderService.preview` renders a few frames of the CURRENT variant with the guarded render host, freezes
   nothing, creates no Artifact, and waits for the browser slot an export holds.
3. The MCP tool `presentation_source` (read, write, preview) speaks to those two routes and returns refusals as results the author fixes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.core.presentation_render_service import (
    DEFAULT_PREVIEW_SCALE, KEEP_PREVIEWS, MAX_PREVIEW_FRAMES, PresentationRenderService, default_preview_frames,
)
from jarvis.core.presentation_studio_edit import SOURCE_REQUEST_TTL_S
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery
from jarvis.domain.presentation_render import RenderError, RenderErrorCode
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import AGENT_AUTHORED_SCENE
from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from jarvis.runtime.presentation_studio_mcp_tools import PresentationTools
from tests.fakes.presentation_studio_reload import GOOD_STYLE, SID, SID2, Rig
from tests.fakes.presentation_world import SCENE_ID, PresentationWorld
from tests.fakes.remotion_render import FakeRenderRunner


# ------------------------------------------------------------------ 1. refining its own scene


@pytest.fixture
async def rig(tmp_path):
    opened = await Rig(tmp_path).open()
    yield opened
    await opened.close()


def authored(rig: Rig, scene_id: str = SID):
    return [r for r in rig.edits.authored_scenes() if r.origin == AGENT_AUTHORED_SCENE and r.scene_id == scene_id]


async def test_the_agent_refines_the_scene_it_created_without_a_user_turn_and_without_an_id(rig):
    revision = (await rig.variant()).revision
    shown = rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], revision)
    assert shown[0]["origin"] == AGENT_AUTHORED_SCENE and shown[0]["scene_id"] == SID and shown[0]["ttl_s"] == int(SOURCE_REQUEST_TTL_S)
    first = await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)
    assert first.status is S.RELOADED
    second = await rig.edit({"style": "p{color:#010203}"}, actor="brain", auto_request=False)
    assert second.status is S.RELOADED, "multi-use: a creative session is many edits"
    again = await rig.edit({"style": "p{color:#020304}"}, actor="brain", request_id=shown[0]["request_id"], auto_request=False)
    assert again.status is S.RELOADED and len(authored(rig)) == 1, "the id works too, and is never consumed"


async def test_the_record_covers_only_the_scenes_the_agent_created(rig):
    revision = (await rig.variant()).revision
    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], revision)
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit({"style": GOOD_STYLE}, scene_id=SID2, actor="brain", auto_request=False)
    assert caught.value.code is C.SOURCE_REQUEST_REQUIRED


async def test_the_thirty_minutes_restart_at_each_use_and_then_end(rig):
    clock = [1000.0]
    rig.edits._clock = lambda: clock[0]
    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], (await rig.variant()).revision)
    clock[0] += SOURCE_REQUEST_TTL_S - 5
    assert (await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)).status is S.RELOADED
    clock[0] += SOURCE_REQUEST_TTL_S - 5                       # 60 minutes after the creation, 30 after the last use: still good
    assert (await rig.edit({"style": "p{color:#010203}"}, actor="brain", auto_request=False)).status is S.RELOADED
    clock[0] += SOURCE_REQUEST_TTL_S + 1
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit({"style": "p{color:#020304}"}, actor="brain", auto_request=False)
    assert caught.value.code is C.SOURCE_REQUEST_REQUIRED and authored(rig) == []


async def test_the_users_own_source_edit_ends_the_agents_record(rig):
    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], (await rig.variant()).revision)
    assert (await rig.edit({"style": GOOD_STYLE}, actor="user")).status is S.RELOADED
    assert authored(rig) == [] and rig.sink.of("core.presentation_studio.authored_scene_released")
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit({"style": "p{color:#010203}"}, actor="brain", auto_request=False)
    assert caught.value.code is C.SOURCE_REQUEST_REQUIRED


async def test_a_user_request_is_still_consumed_once_and_the_authoring_record_does_not_change_that(rig):
    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID2], (await rig.variant()).revision)
    request_id = await rig.record_request(origin="explicit_user_request", actor="brain")
    assert (await rig.edit({"style": GOOD_STYLE}, actor="brain", request_id=request_id)).status is S.RELOADED
    assert request_id not in [r.request_id for r in rig.edits.pending_source_requests()]


# ------------------------------------------------------------------ Slice 13 rework: the permission's bounds (QA B3, P1, I2, I3)


async def test_the_permission_is_bound_to_its_variant(rig):
    """P1 (mutant M7: a match on presentation + scene only, any variant): the same scene id in another variant is refused, by id or not."""

    other = "psv_00000000beef"
    shown = rig.edits.record_authored_scenes(rig.pid, other, [SID], (await rig.variant()).revision)
    for extra in ({}, {"request_id": shown[0]["request_id"]}):
        with pytest.raises(PresentationStudioError) as caught:
            await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False, **extra)
        assert caught.value.code is C.SOURCE_REQUEST_REQUIRED, extra
    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], (await rig.variant()).revision)
    assert (await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)).status is S.RELOADED


async def test_opening_the_scene_in_remotion_studio_ends_the_permission_in_that_variant_only(rig):
    """B3: what `RemotionStudioService.add_scene_listener` calls when the user opens or syncs a scene (wired in `v2_app`)."""

    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID, SID2], (await rig.variant()).revision)
    rig.edits.record_authored_scenes(rig.pid, "psv_00000000beef", [SID], 1)       # unreadable variant: kept, said
    assert (await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)).status is S.RELOADED  # SID now pins its own source
    pin = next(s.prefab for s in (await rig.variant()).scenes if s.scene_id == SID)
    assert await rig.edits.release_authored_for_pin(pin.prefab_id, pin.version) == 1
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)
    assert caught.value.code is C.SOURCE_REQUEST_REQUIRED, "opened in Remotion Studio: the agent no longer writes it"
    assert [r.scene_id for r in authored(rig, SID2)] == [SID2], "another scene keeps its permission"
    released = rig.sink.of("core.presentation_studio.authored_scene_released")
    assert released and released[-1][1]["reason"] == "opened_in_remotion"
    assert rig.sink.of("core.presentation_studio.authored_release_unchecked")


async def test_unpublished_remotion_studio_edits_of_the_scene_refuse_every_agent_write(rig):
    from jarvis.domain.remotion_studio import StudioPin

    pin = next(s.prefab for s in (await rig.variant()).scenes if s.scene_id == SID)
    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], (await rig.variant()).revision)
    workspace = {"base": StudioPin(pin.prefab_id, pin.version), "edited": ("src/Scene.tsx",)}

    async def probe():
        return workspace["base"], workspace["edited"]

    rig.reload._studio_workspace = probe
    request_id = await rig.record_request(origin="explicit_user_request", actor="brain")
    for extra in ({}, {"request_id": request_id}):
        with pytest.raises(PresentationStudioError) as caught:
            await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False, **extra)
        assert caught.value.code is C.SCENE_EDITED_IN_REMOTION and caught.value.status == 409, extra
    workspace["edited"] = None                                                    # files that cannot be listed count as edits
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)
    assert caught.value.code is C.SCENE_EDITED_IN_REMOTION
    workspace["edited"] = ("src/Scene.tsx",)
    assert (await rig.edit({"style": GOOD_STYLE}, actor="user")).status is S.RELOADED, "the user's own edit is never refused by it"


async def test_a_scene_that_is_not_open_in_remotion_studio_stays_writable(rig):
    from jarvis.domain.remotion_studio import StudioPin

    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], (await rig.variant()).revision)
    for base, edited in ((StudioPin("presentation-studio.p00000000dead.s00000000dead", 3), ("src/Scene.tsx",)),  # another scene, edited
                         (None, ())):                                                                        # no workspace at all
        async def probe(base=base, edited=edited):
            return base, edited

        rig.reload._studio_workspace = probe
        assert (await rig.edit({"style": GOOD_STYLE if base else "p{color:#010203}"}, actor="brain", auto_request=False)).status is S.RELOADED


async def test_agent_permissions_never_evict_a_users_pending_request(rig):
    """I2: two full decks and more go to the agent's own bounded store; the user's request stays pending."""

    from jarvis.core.presentation_studio_edit import MAX_AUTHORED_SCENES

    request_id = await rig.record_request()                                       # the user's own pending request
    for deck in range(3):
        rig.edits.record_authored_scenes(rig.pid, f"psv_{deck:012x}", [f"pss_{n:012x}" for n in range(48)], 1)
    assert request_id in [r.request_id for r in rig.edits.pending_source_requests()]
    assert not [r for r in rig.edits.pending_source_requests() if r.origin == AGENT_AUTHORED_SCENE]
    assert len(rig.edits.authored_scenes()) == MAX_AUTHORED_SCENES
    assert {r.variant_id for r in rig.edits.authored_scenes()} == {f"psv_{1:012x}", f"psv_{2:012x}"}, "the oldest agent permissions left"
    assert rig.sink.of("core.presentation_studio.authored_scenes_dropped")


async def test_a_refused_attempt_does_not_extend_the_thirty_minutes(rig):
    """I3: only a write that stood restarts the window."""

    clock = [1000.0]
    rig.edits._clock = lambda: clock[0]
    rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID], (await rig.variant()).revision)
    clock[0] += SOURCE_REQUEST_TTL_S - 5
    refused = await rig.edit({"template": "<iframe src='x'></iframe>"}, actor="brain", auto_request=False)
    assert refused.status is S.REFUSED_VALIDATION
    clock[0] += 10                                                                # 30 min 5 s after the creation, 10 s after the refusal
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)
    assert caught.value.code is C.SOURCE_REQUEST_REQUIRED and authored(rig) == []


async def test_the_assemble_of_the_brain_records_its_scenes_and_says_so(tmp_path):
    from tests.fakes.presentation_studio_authoring_env import AuthoringEnv
    from tests.unit.test_presentation_studio_native_authoring import native_request

    calls = []
    env = await AuthoringEnv(tmp_path / "e").start()
    env.authoring._authored = lambda pid, vid, scenes, revision: calls.append((pid, vid, tuple(scenes), revision)) or [
        {"request_id": "psq_000000000001", "scene_id": s} for s in scenes]
    brief, draft = native_request(2)
    as_brain = (await env.authoring.assemble({"actor": "brain", "brief": brief, "draft": draft})).to_dict()
    assert as_brain["source_requests"] and len(calls) == 1 and len(calls[0][2]) == 2
    as_user = (await env.authoring.assemble({"actor": "user", "brief": brief, "draft": draft})).to_dict()
    assert "source_requests" not in as_user and len(calls) == 1, "only an agent's creation opens its authoring session"


# ------------------------------------------------------------------ 2. looking at it


class PreviewRig:
    pass


@pytest.fixture
async def view(tmp_path):
    r = PreviewRig()
    r.world = await PresentationWorld().open(tmp_path, runtime={"remotion_version": "4.0.534"})
    r.runner = FakeRenderRunner(tmp_path)
    r.root = tmp_path / "previews"
    r.service = PresentationRenderService(
        artifacts=r.world.artifacts, snapshots=r.world.snapshots, packager=r.world.packager, runner=r.runner,
        installed_engine=r.runner.installed_engine, capability_status=lambda: "ready", diagnostics=r.world.sink,
        new_job_id=iter(f"rj_{n:012x}" for n in range(1, 99)).__next__, preview_root=lambda: r.root)
    r.pid, r.vid = await r.world.new_presentation()
    try:
        yield r
    finally:
        await r.service.stop()
        await r.world.close()


async def test_a_preview_renders_the_current_scene_and_keeps_the_frames_without_freezing_anything(view):
    out = await view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[10])
    assert out["scene_id"] == SCENE_ID and out["scale"] == DEFAULT_PREVIEW_SCALE and [f["frame"] for f in out["frames"]] == [10]
    kept = Path(out["frames"][0]["path"])
    assert kept.is_file() and kept.parent.parent == view.root and kept.name == "frame-00010.jpg"
    run = next(spec for name, spec in view.runner.calls if name == "run")
    assert run["format"] == "pdf" and run["frames"] == [10] and run["props"] is not None
    assert ("cleanup", "rj_000000000001") in view.runner.calls
    renders = (await view.world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_SNAPSHOT, ArtifactKind.PRESENTATION_PDF),
                                                                limit=10))).items
    assert not renders, "a preview is no export: no snapshot, no Artifact"
    assert [row for row in view.world.sink.rows if row[0].endswith("preview_done")]


async def test_a_preview_refuses_what_it_cannot_render_with_typed_reasons(view):
    for kwargs, code in (({"frames": list(range(MAX_PREVIEW_FRAMES + 1))}, RenderErrorCode.INVALID),
                         ({"frames": [999_999]}, RenderErrorCode.INVALID), ({"scale": 3}, RenderErrorCode.INVALID),
                         ({"frames": [1, 2]}, RenderErrorCode.OUTPUT_INVALID)):           # the fake host returns one image for two frames
        with pytest.raises(RenderError) as caught:
            await view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, **kwargs)
        assert caught.value.code is code, (kwargs, caught.value)
    view.runner.mode = "fail"
    with pytest.raises(RenderError) as caught:
        await view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[3])
    assert caught.value.code is RenderErrorCode.FAILED and "boom" in caught.value.detail
    assert [row for row in view.world.sink.rows if row[0].endswith("preview_failed")]


async def test_a_preview_without_a_preview_folder_or_with_an_unknown_scene_is_refused(view, tmp_path):
    with pytest.raises(RenderError):
        await view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id="pss_0000000000ff", frames=[1])
    bare = PresentationRenderService(artifacts=view.world.artifacts, snapshots=view.world.snapshots, packager=view.world.packager,
                                     runner=view.runner, installed_engine=view.runner.installed_engine, capability_status=lambda: "ready")
    with pytest.raises(RenderError) as caught:
        await bare.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID)
    assert caught.value.code is RenderErrorCode.UNAVAILABLE


async def test_a_preview_waits_for_the_browser_an_export_holds(view):
    view.runner.mode = "block"
    snapshot = (await view.world.freeze(view.pid, view.vid))["artifact_id"]
    job = await view.service.submit(snapshot, "still", {"frame": 1})
    await asyncio.to_thread(view.runner.running.wait, 5)
    preview = asyncio.create_task(view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[2]))
    await asyncio.sleep(0.2)
    assert not preview.done() and sum(1 for name, _ in view.runner.calls if name == "run") == 1, "one browser at a time"
    view.runner.mode = "ok"
    view.runner.release()
    out = await asyncio.wait_for(preview, 10)
    assert [f["frame"] for f in out["frames"]] == [2] and job["job_id"]


def emitted(view, kind):
    return [row for row in view.world.sink.rows if row[0] == kind]


def runs(view, fmt=None):
    return [spec for name, spec in view.runner.calls if name == "run" and (fmt is None or spec["format"] == fmt)]


async def test_thirty_previews_at_once_one_renders_one_waits_and_twenty_eight_are_refused_busy(view):
    """Slice 13 rework (QA B2): previews never pile up behind the one browser."""

    view.runner.mode = "block"
    ask = lambda: asyncio.create_task(view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[1]))
    first = ask()
    await asyncio.to_thread(view.runner.running.wait, 5)
    others = [ask() for _ in range(29)]
    await asyncio.sleep(0.3)
    refused = [t for t in others if t.done()]
    assert len(refused) == 28 and all(isinstance(t.exception(), RenderError) and t.exception().code is RenderErrorCode.PREVIEW_BUSY
                                      and t.exception().status == 429 for t in refused)
    assert len(runs(view)) == 1 and not first.done() and sum(1 for t in others if not t.done()) == 1
    assert len(emitted(view, "core.presentation_render.preview_refused_busy")) == 28
    view.runner.mode = "ok"
    view.runner.release()
    done = await asyncio.wait_for(asyncio.gather(first, *[t for t in others if not t.done()]), 10)
    assert len(done) == 2 and len(runs(view)) == 2, "the waiting one renders once the browser is free"
    assert view.service._previews_waiting == 0 and not view.service._browser_slot.busy


async def test_a_preview_waits_for_the_browser_with_a_deadline(view):
    view.service._preview_wait_s = 0.3
    view.runner.mode = "block"
    snapshot = (await view.world.freeze(view.pid, view.vid))["artifact_id"]
    await view.service.submit(snapshot, "still", {"frame": 1})
    await asyncio.to_thread(view.runner.running.wait, 5)
    started = asyncio.get_running_loop().time()
    with pytest.raises(RenderError) as caught:
        await view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[2])
    waited = asyncio.get_running_loop().time() - started
    assert caught.value.code is RenderErrorCode.PREVIEW_BUSY and 0.25 <= waited < 2.0 and not runs(view, "pdf")
    assert emitted(view, "core.presentation_render.preview_wait_timeout") and view.service._previews_waiting == 0
    view.runner.release()


async def test_an_export_queued_behind_a_waiting_preview_goes_first(view):
    view.runner.mode = "block"
    snapshot = (await view.world.freeze(view.pid, view.vid))["artifact_id"]
    await view.service.submit(snapshot, "still", {"frame": 1})
    await asyncio.to_thread(view.runner.running.wait, 5)
    preview = asyncio.create_task(view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[2]))
    await asyncio.sleep(0.2)
    assert not preview.done()
    await view.service.submit(snapshot, "still", {"frame": 3})                    # queued AFTER the preview started waiting
    view.runner.mode = "ok"
    view.runner.release()
    await asyncio.wait_for(preview, 10)
    assert [spec["format"] for spec in runs(view)] == ["still", "still", "pdf"], "exports keep priority over a waiting preview"


async def test_a_caller_that_left_cancels_its_preview_while_waiting_and_while_rendering(view):
    left = [False]
    gone = lambda: left[0]
    view.runner.mode = "block"
    snapshot = (await view.world.freeze(view.pid, view.vid))["artifact_id"]
    await view.service.submit(snapshot, "still", {"frame": 1})
    await asyncio.to_thread(view.runner.running.wait, 5)
    waiting = asyncio.create_task(view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[2], gone=gone))
    await asyncio.sleep(0.2)
    left[0] = True
    with pytest.raises(RenderError) as caught:
        await asyncio.wait_for(waiting, 2)
    assert caught.value.code is RenderErrorCode.CANCELLED and not runs(view, "pdf"), "gone before the browser: nothing rendered"
    view.runner.release()
    await asyncio.sleep(0.2)
    # while rendering: a fresh blocking run, the caller leaves, the render process is told to stop (cancel), the browser is free again
    view.runner._release.clear()
    view.runner.running.clear()
    left[0] = False
    rendering = asyncio.create_task(view.service.preview(presentation_id=view.pid, variant_id=view.vid, scene_id=SCENE_ID, frames=[2], gone=gone))
    await asyncio.to_thread(view.runner.running.wait, 5)
    left[0] = True
    with pytest.raises(RenderError) as caught:
        await asyncio.wait_for(rendering, 3)
    assert caught.value.code is RenderErrorCode.CANCELLED and len(runs(view, "pdf")) == 1
    assert emitted(view, "core.presentation_render.preview_abandoned") and not view.service._browser_slot.busy


def test_default_frames_and_the_kept_folders_are_bounded():
    assert default_preview_frames(300) == (90, 194, 299) and default_preview_frames(1) == (0,)
    assert KEEP_PREVIEWS >= 10 and MAX_PREVIEW_FRAMES <= 6


# ------------------------------------------------------------------ 3. the MCP tool


class FakeCore:
    def __init__(self, source_result=None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.source_result = source_result or {"status": "reloaded", "prefab": {"id": "presentation-studio.p1.s1", "version": 2},
                                               "previous": {"id": "presentation-studio.p1.s1", "version": 1}, "mounted": True}

    async def call(self, fn):
        return await fn(self)

    def __getattr__(self, name):
        async def method(*args):
            self.calls.append((name, args))
            if name == "presentation_studio_work":            # the rail's "an agent works" mark around a write
                return {}
            if name == "presentation_studio_variant":
                return {"revision": 7}
            if name == "presentation_studio_source_edit":
                return self.source_result
            if name == "presentation_studio_scene_source":
                return {"prefab": {"id": "x", "version": 1}, "basis": {"variant_revision": 7},
                        "manifest": {"source": {"composition": {"width": 1920, "height": 1080, "fps": 30, "duration_in_frames": 240},
                                                "entry": "src/Scene.tsx"}},
                        "sources": {"src/Scene.tsx": "export default () => null;"}, "assets": {"public/a.png": "AAAA"}}
            if name == "remotion_render_preview":
                return {"preview": {"prefab": {"id": "x", "version": 2}, "frames": [{"frame": 72, "path": "C:/p/frame-00072.jpg"}],
                                    "elapsed_ms": 9000}}
            raise AssertionError(name)
        return method


PID, VID, SCN = "pst_" + "a" * 32, "psv_" + "b" * 32, "pss_" + "c" * 12


async def test_the_tool_writes_through_the_source_edit_route_as_the_brain_at_the_read_revision():
    core = FakeCore()
    tools = PresentationTools(core)
    out = await tools.source("write", presentation_id=PID, variant_id=VID, scene_id=SCN, files={"src/Scene.tsx": "x"})
    assert out["status"] == "reloaded" and out["prefab"]["version"] == 2
    name, args = next(call for call in core.calls if call[0] == "presentation_studio_source_edit")
    assert args[:2] == (PID, VID)
    assert args[2] == {"actor": "brain", "basis": {"variant_revision": 7}, "scene_id": SCN, "files": {"sources": {"src/Scene.tsx": "x"}}}


async def test_a_refused_build_comes_back_as_a_result_with_its_diagnostics():
    core = FakeCore({"status": "refused_validation", "prefab": None, "error": {"code": "presentation_studio_source_build_failed",
                                                                               "message": "build failed"},
                     "diagnostics": [{"file": "src/Scene.tsx", "line": 3, "column": 9, "text": "Expected"}]})
    out = await PresentationTools(core).source("write", presentation_id=PID, variant_id=VID, scene_id=SCN, files={"src/Scene.tsx": "x"})
    assert out["ok"] and out["status"] == "refused_validation" and out["code"] == "presentation_studio_source_build_failed"
    assert out["diagnostics"][0]["line"] == 3


async def test_read_and_preview_return_what_the_author_needs():
    tools = PresentationTools(FakeCore())
    read = await tools.source("read", presentation_id=PID, variant_id=VID, scene_id=SCN)
    assert read["sources"]["src/Scene.tsx"] and read["composition"]["duration_in_frames"] == 240 and read["assets"] == ["public/a.png"]
    seen = await tools.source("preview", presentation_id=PID, variant_id=VID, scene_id=SCN, frames=[72])
    assert seen["frames"][0]["path"].endswith(".jpg") and "Read" in seen["note"]


async def test_the_tool_refuses_a_bad_op_a_bad_scene_and_an_empty_write_before_calling_core():
    from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError

    core = FakeCore()
    tools = PresentationTools(core)
    for op, kwargs in (("delete", {"scene_id": SCN}), ("read", {"scene_id": "nope"}), ("write", {"scene_id": SCN})):
        with pytest.raises(PresentationToolError):
            await tools.source(op, presentation_id=PID, variant_id=VID, **kwargs)
    assert {name for name, _ in core.calls} <= {"presentation_studio_variant", "presentation_studio_work"}, core.calls
