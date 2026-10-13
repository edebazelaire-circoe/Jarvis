"""Whole-video (master) render scope (handoff jarvis-remotion-master-project-studio-export, Slice 06; `docs/remotion-master-project.md` §10,
`docs/remotion-render.md` §3 bis). Domain (settings, resolution, identity, metadata, failure marker) and service on a real world (real
registry, Studio, prefab store and packager) with the fake render runner. The real engine: `test_presentation_render_master_real.py`.
"""

from __future__ import annotations

import asyncio
import io
import math
import struct
import wave

import pytest

from jarvis.core.presentation_render_service import PresentationRenderService
from jarvis.domain import presentation_render as D
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactRelationKind, ArtifactState
from jarvis.domain.presentation_artifacts import RenderFormat
from jarvis.domain.presentation_render import MasterTarget, RenderError, RenderErrorCode as C
from jarvis.domain.presentation_render_master import choose_master, frozen_plan
from jarvis.ports.artifacts import RelationDirection
from tests.fakes.presentation_world import SCENE_ID, PresentationWorld
from tests.fakes.remotion_render import FakeRenderRunner
from tests.fakes.remotion_scene import COMPOSITION, SCENE_TSX, scene_candidate, scene_files
from tests.unit.test_presentation_render_domain import target as scene_target

MP4 = RenderFormat.MP4
IDS = (SCENE_ID, "pss_00000000000b", "pss_00000000000c")
PREFABS = ("presentation-studio.p000000000001.s000000000001", "presentation-studio.p000000000001.s000000000002",
           "presentation-studio.p000000000001.s000000000003")


def master_target(**changes) -> MasterTarget:
    base = dict(composition_id="JarvisPresentation", width=1280, height=720, fps=30, duration_in_frames=270, engine_version="4.0.534",
                engine_lock_sha256="a" * 64, project_key="mpk_" + "1" * 24, scene_ids=IDS, audio_required=False)
    base.update(changes)
    return MasterTarget(**base)


def master(settings=None) -> D.RenderSettings:
    return D.parse_settings(MP4, {"scope": "master", **(settings or {})})


# ------------------------------------------------------------------ domain


@pytest.mark.parametrize("fmt,raw,needle", [
    (MP4, {"scope": "master", "scene_id": IDS[0]}, "scene_id does not apply"), (RenderFormat.STILL, {"scope": "master"}, "mp4 only"),
    (RenderFormat.PDF, {"scope": "master", "frames": [0]}, "mp4 only"), (MP4, {"scope": "variant"}, "scope must be"),
    (MP4, {"scope": None}, "scope must be")])
def test_invalid_scope_combinations_are_refused(fmt, raw, needle):
    with pytest.raises(RenderError) as refused:
        D.parse_settings(fmt, raw)
    assert refused.value.code is C.INVALID and needle in refused.value.detail


def test_an_explicit_scene_scope_is_normalized_and_keeps_the_scene_identity():
    absent = D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29}), scene_target())
    explicit = D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29, "scope": "scene"}), scene_target())
    assert absent == explicit and absent.settings_sha256 == explicit.settings_sha256
    assert "scope" not in absent.canonical() and absent.to_metadata()["render_scope"] == "scene"


def test_a_master_render_resolves_against_the_master_composition_with_its_own_bound():
    whole = D.resolve(MP4, master(), master_target())
    assert (whole.frame_start, whole.frame_end, whole.frames_total, whole.master) == (0, 269, 270, True)
    assert D.resolve(MP4, master(), master_target(duration_in_frames=9000)).frames_total == D.MAX_MASTER_RENDER_FRAMES == 9000
    with pytest.raises(RenderError, match="exceed the bound of 9000"):
        D.resolve(MP4, master(), master_target(duration_in_frames=9001))
    assert D.resolve(MP4, master({"frame_start": 1, "frame_end": 9000}), master_target(duration_in_frames=9100)).frames_total == 9000
    with pytest.raises(RenderError, match="outside the whole video"):
        D.resolve(MP4, master({"frame_end": 270}), master_target())
    with pytest.raises(RenderError, match="disagree"):
        D.resolve(MP4, master(), scene_target())
    with pytest.raises(RenderError, match="disagree"):
        D.resolve(MP4, D.parse_settings(MP4, None), master_target())
    assert D.MAX_RENDER_FRAMES == 3600, "the scene bound is unchanged"


def test_the_master_identity_and_metadata_name_the_project_not_a_scene():
    whole = D.resolve(MP4, master(), master_target())
    canonical = whole.canonical()
    assert canonical["scope"] == "master" and canonical["project_key"] == "mpk_" + "1" * 24 and canonical["scene_count"] == 3
    assert whole.settings_sha256 != D.resolve(MP4, master(), master_target(project_key="mpk_" + "2" * 24)).settings_sha256
    assert whole.settings_sha256 != D.resolve(MP4, master({"crf": 20}), master_target()).settings_sha256
    assert whole.settings_sha256 == D.resolve(MP4, master({"concurrency": 2}), master_target()).settings_sha256
    meta = whole.to_metadata()
    assert meta["render_scope"] == "master" and meta["render_project_key"] == "mpk_" + "1" * 24 and meta["render_scene_count"] == 3
    assert meta["render_composition"] == "JarvisPresentation" and meta["render_flat"] is True
    assert not {"render_scene_id", "render_prefab_id", "render_prefab_version", "render_source_digest"} & set(meta)
    assert len(meta) + 9 <= 32, "room for the job, drift and finish keys"


def test_the_scene_failure_marker_is_parsed_and_anything_else_is_not():
    text = "Error: jarvis_master_scene_failed:pss_00000000000b:2: boom at frame 5\n    at SceneBoundary.componentDidCatch (<path>)"
    assert D.master_scene_failure(text) == ("pss_00000000000b", 2, "boom at frame 5")  # the message line, not the stack
    one_line = "Error: jarvis_master_scene_failed:pss_00000000000b:2: boom at frame 5 at SceneBoundary.componentDidCatch (htt<path>) at x (y)"
    assert D.master_scene_failure(one_line) == ("pss_00000000000b", 2, "boom at frame 5"), "the cleaned one-line detail loses its stack too"
    assert D.master_scene_failure("render_failed: Chrome crashed") is None
    assert D.master_scene_failure("jarvis_master_scene_failed:../x:1: y") is None


# ------------------------------------------------------------------ service on a real world


def tone_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(i / 3))) for i in range(4000)))
    return buffer.getvalue()


AUDIO_TSX = SCENE_TSX.replace("import {AbsoluteFill, Img,", "import {AbsoluteFill, Audio, Img,").replace(
    '<Title text={props.title} color={props.accent} />', '<Audio src={staticFile("s1-voice.wav")} />\n      <Title text={props.title} color={props.accent} />')


class Rig:
    pass


@pytest.fixture
async def rig(tmp_path):
    r = Rig()
    r.world = await PresentationWorld().open(tmp_path, runtime={"remotion_version": "4.0.534"})
    r.runner = FakeRenderRunner(tmp_path)
    r.service = PresentationRenderService(
        artifacts=r.world.artifacts, snapshots=r.world.snapshots, packager=r.world.packager, runner=r.runner,
        installed_engine=r.runner.installed_engine, diagnostics=r.world.sink,
        new_job_id=iter(f"rj_{n:012x}" for n in range(1, 99)).__next__)
    try:
        yield r
    finally:
        await r.service.stop()
        await r.world.close()


async def deck(rig, *, fps3: int = 30, audio: bool = False) -> tuple[str, str, str]:
    """A frozen 3-scene variant: the world's scene plus two more pins (scene 2 optionally plays an `<Audio>`, scene 3 at `fps3`)."""

    w = rig.world
    pid, vid = await w.new_presentation(props={"title": "Un"})
    extra = []
    for n in (1, 2):
        files = scene_files(title_suffix=f"// scene {n}\n")
        if audio and n == 1:
            files = {**files, "src/Scene.tsx": AUDIO_TSX, "public/s1-voice.wav": tone_wav()}
        composition = COMPOSITION if n == 1 or fps3 == 30 else type(COMPOSITION)("Scene", 1280, 720, fps3, 90)
        published = await w.prefabs.save(scene_candidate(PREFABS[n], files=files, composition=composition), actor="user")
        extra.append({"scene_id": IDS[n], "prefab": {"id": PREFABS[n], "version": published.version}, "props": {"title": f"S{n}"}})
    variant = (await w.studio.get(pid)).variants[0].to_document()
    await w.studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": variant["title"],
                                           "scenes": variant["scenes"] + extra, "art_direction_id": None, "score_id": None})
    snapshot = (await w.freeze(pid, vid))["artifact_id"]
    return pid, vid, snapshot


async def finished(service, job_id, timeout=10.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        view = service.get(job_id)
        if view["state"] in ("complete", "failed", "cancelled"):
            return view
        await asyncio.sleep(0.01)
    raise AssertionError(service.get(job_id))


async def test_a_master_mp4_renders_the_whole_frozen_variant_into_one_derivative(rig):
    _, _, snapshot = await deck(rig)
    key = frozen_plan(await rig.world.packager.read_snapshot(snapshot)).project_key
    queued = await rig.service.submit(snapshot, "mp4", {"scope": "master"})
    assert (queued["scope"], queued["project_key"], queued["scene_count"], queued["scene_id"], queued["frames_total"]) == (
        "master", key, 3, None, 270)
    done = await finished(rig.service, queued["job_id"])
    assert done["state"] == "complete", done
    spec = next(call[1] for call in rig.runner.calls if call[0] == "run")
    assert spec["composition_id"] == "JarvisPresentation" and spec["entry"] == "studio-root.tsx" and spec["props"] == {}
    assert spec["composition"] == {"width": 1280, "height": 720, "fps": 30, "durationInFrames": 270} and spec["frame_range"] == [0, 269]
    files = rig.runner.files[queued["job_id"]]
    for scene_id in IDS:
        assert f"src/scenes/{scene_id}/Scene.tsx" in files
    assert {"package.json", "studio-root.tsx", "src/master/Presentation.tsx", "src/master/SceneBoundary.tsx"} <= set(files)
    assert ("verify_audio_required", "mp4") not in rig.runner.calls, "no <Audio> in this deck: no audio requirement"
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert artifact.kind is ArtifactKind.PRESENTATION_VIDEO and artifact.state is ArtifactState.COMPLETE
    meta = dict(artifact.metadata)
    assert meta["render_scope"] == "master" and meta["render_project_key"] == key and meta["render_scene_count"] == 3
    assert "render_scene_id" not in meta and len(meta) <= 32
    relations = await rig.world.artifacts.relations(snapshot, RelationDirection.DEPENDENTS)
    assert [r.artifact_id for r in relations if r.relation is ArtifactRelationKind.RENDERED_FROM] == [artifact.artifact_id]
    assert "core.presentation_render.queued" in rig.world.sink.kinds()


async def test_the_same_master_request_is_deduplicated_and_scene_exports_stay_available(rig):
    _, _, snapshot = await deck(rig)
    first = await rig.service.submit(snapshot, "mp4", {"scope": "master"})
    again = await rig.service.submit(snapshot, "mp4", {"scope": "master"})
    assert again["deduplicated"] is True and again["job_id"] == first["job_id"]
    await finished(rig.service, first["job_id"])
    later = await rig.service.submit(snapshot, "mp4", {"scope": "master"})
    assert later["deduplicated"] is True and later["artifact_id"] == first["artifact_id"] and later["scope"] == "master"
    other = await rig.service.submit(snapshot, "mp4", {"scope": "master", "crf": 20})
    assert other["deduplicated"] is False
    with pytest.raises(RenderError) as unknown:
        await rig.service.submit(snapshot, "mp4", {})
    assert unknown.value.code is C.UNKNOWN_SCENE, "a multi-scene snapshot without scene_id and without scope master: unchanged"
    scene = await rig.service.submit(snapshot, "mp4", {"scene_id": IDS[1]})
    assert scene["scene_id"] == IDS[1] and "scope" not in scene and scene["frames_total"] == 90


async def test_an_incompatible_frozen_variant_is_refused_409_with_its_reason_and_nothing_is_created(rig):
    _, _, snapshot = await deck(rig, fps3=25)
    before = (await rig.world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_VIDEO,), limit=10))).items
    with pytest.raises(RenderError) as refused:
        await rig.service.submit(snapshot, "mp4", {"scope": "master"})
    exc = refused.value
    assert exc.code is C.MASTER_INCOMPATIBLE and exc.status == 409
    assert exc.extra["reason"] == "master_fps_mismatch" and exc.extra["scene_ids"] == list(IDS) and exc.extra["detail"]
    after = (await rig.world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_VIDEO,), limit=10))).items
    assert after == before and not rig.runner.calls
    assert "core.presentation_render.master_incompatible" in rig.world.sink.kinds()
    view = await rig.service.master_readiness(snapshot)
    assert view["status"] == "incompatible" and view["reason"] == "master_fps_mismatch"


async def test_a_scene_that_throws_fails_the_job_naming_the_scene_and_its_position(rig):
    _, _, snapshot = await deck(rig)
    rig.runner.mode = "fail"
    rig.runner.fail_detail = f"Error: jarvis_master_scene_failed:{IDS[1]}:2: boom in s2 at <path>"
    queued = await rig.service.submit(snapshot, "mp4", {"scope": "master"})
    done = await finished(rig.service, queued["job_id"])
    assert done["state"] == "failed" and done["error_code"] == "presentation_render_master_scene_failed"
    assert done["error_detail"].startswith(f"scene 2 ({IDS[1]}) failed while rendering: boom in s2")
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert artifact.state is ArtifactState.FAILED and artifact.error_code == "presentation_render_master_scene_failed"


async def test_a_scene_render_failure_with_the_marker_text_keeps_its_own_code(rig):
    _, _, snapshot = await deck(rig)
    rig.runner.mode = "fail"
    rig.runner.fail_detail = f"jarvis_master_scene_failed:{IDS[1]}:2: not a master"
    done = await finished(rig.service, (await rig.service.submit(snapshot, "mp4", {"scene_id": IDS[1]}))["job_id"])
    assert done["error_code"] == "presentation_render_failed"


async def test_a_deck_with_audio_requires_an_audio_stream(rig):
    _, _, snapshot = await deck(rig, audio=True)
    assert choose_master(await rig.world.packager.read_snapshot(snapshot)).audio_required
    done = await finished(rig.service, (await rig.service.submit(snapshot, "mp4", {"scope": "master"}))["job_id"])
    assert done["state"] == "complete" and ("verify_audio_required", "mp4") in rig.runner.calls
    rig.runner.audio_missing = True
    failed = await finished(rig.service, (await rig.service.submit(snapshot, "mp4", {"scope": "master", "crf": 30}))["job_id"])
    assert failed["error_code"] == "presentation_render_output_invalid" and "audio stream" in failed["error_detail"]


async def test_the_render_reads_the_frozen_package_not_the_live_variant(rig):
    pid, vid, snapshot = await deck(rig)
    key = frozen_plan(await rig.world.packager.read_snapshot(snapshot)).project_key
    variant = (await rig.world.studio.get(pid)).variants[0].to_document()
    await rig.world.studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": variant["title"],
                                                   "scenes": list(reversed(variant["scenes"])), "art_direction_id": None, "score_id": None})
    done = await finished(rig.service, (await rig.service.submit(snapshot, "mp4", {"scope": "master"}))["job_id"])
    assert done["state"] == "complete" and done["project_key"] == key
    text = rig.runner.files[done["job_id"]]["src/master/Presentation.tsx"].decode()
    assert text.index(f"../scenes/{IDS[0]}/") < text.index(f"../scenes/{IDS[2]}/"), "the frozen order, not the live reorder"


async def test_the_master_readiness_of_a_snapshot_is_the_plan_view(rig):
    _, _, snapshot = await deck(rig)
    view = await rig.service.master_readiness(snapshot)
    assert view["status"] == "ready" and view["composition"]["duration_in_frames"] == 270 and len(view["scenes"]) == 3
    with pytest.raises(RenderError) as bad:
        await rig.service.master_readiness("jart_ps_" + "0" * 32 + "_" + "0" * 32 + "_p1_v1_a1")
    assert bad.value.code is C.SNAPSHOT_INVALID
