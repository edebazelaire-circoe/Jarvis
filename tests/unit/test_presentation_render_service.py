"""Service de rendu (Remotion Slice 16) : file, états, progression, annulation, reprise, refus. Faux runner, vrai registre / Studio / paquet.

Contrat : `docs/remotion-render.md`. Le vrai moteur est éprouvé par `scripts/remotion_render_harness.py` et le test opt-in
`test_presentation_render_real.py`.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from jarvis.core.presentation_render_service import PresentationRenderService
from jarvis.domain import presentation_render as D
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactState
from jarvis.domain.presentation_render import RenderError
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.ports.artifacts import RelationDirection
from tests.fakes.presentation_world import OK_BOARDS, SCENE_ID, PresentationWorld
from tests.fakes.remotion_render import FakeInstalled, FakeRenderRunner

RENDER_KINDS = (ArtifactKind.PRESENTATION_VIDEO, ArtifactKind.PRESENTATION_STILL, ArtifactKind.PRESENTATION_PDF)


class Rig:
    pass


@pytest.fixture
async def rig(tmp_path):
    r = Rig()
    r.world = await PresentationWorld().open(tmp_path, runtime={"remotion_version": "4.0.534"})
    r.runner = FakeRenderRunner(tmp_path)
    r.status = "ready"
    r.service = PresentationRenderService(
        artifacts=r.world.artifacts, snapshots=r.world.snapshots, packager=r.world.packager, runner=r.runner,
        installed_engine=r.runner.installed_engine, capability_status=lambda: r.status, diagnostics=r.world.sink,
        new_job_id=iter(f"rj_{n:012x}" for n in range(1, 99)).__next__)
    r.pid, r.vid = await r.world.new_presentation(props={"title": "Valeur figée"})
    r.snapshot = (await r.world.freeze(r.pid, r.vid))["artifact_id"]
    try:
        yield r
    finally:
        await r.service.stop()
        await r.world.close()


async def finished(service, job_id, timeout=10.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        view = service.get(job_id)
        if view["state"] in ("complete", "failed", "cancelled"):
            return view
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish: {service.get(job_id)}")


async def derivatives(rig):
    return (await rig.world.artifacts.query(ArtifactQuery(kinds=RENDER_KINDS, limit=50))).items


# ------------------------------------------------------------------ the happy paths


async def test_an_mp4_is_rendered_from_the_frozen_snapshot_and_registered_with_its_settings(rig):
    queued = await rig.service.submit(rig.snapshot, "mp4", {"frame_start": 0, "frame_end": 29})
    assert queued["state"] in ("queued", "running") and queued["format"] == "mp4" and queued["frames_total"] == 30
    assert queued["snapshot_id"] == rig.snapshot
    pending = await rig.world.artifacts.get(queued["artifact_id"])
    assert pending.kind is ArtifactKind.PRESENTATION_VIDEO and pending.state in (ArtifactState.PENDING, ArtifactState.COMPLETE)
    done = await finished(rig.service, queued["job_id"])
    assert done["state"] == "complete" and done["percent"] == 100 and done["verified_by"] == "ffprobe"
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert artifact.state is ArtifactState.COMPLETE and artifact.width == 1280 and artifact.height == 720 and artifact.duration_ms == 2000
    assert artifact.size_bytes == done["size_bytes"] > 0
    meta = dict(artifact.metadata)
    assert meta["render_format"] == "mp4" and meta["render_fps"] == 30 and meta["render_codec"] == "h264"
    assert (meta["render_frame_start"], meta["render_frame_end"]) == (0, 29) and meta["render_flat"] is True
    assert meta["render_scene_id"] == SCENE_ID and meta["render_composition"] == "Scene" and meta["render_engine"] == "4.0.534"
    assert len(meta["render_settings_sha256"]) == 64 and len(meta["render_output_sha256"]) == 64 and meta["render_job_id"] == done["job_id"]
    assert meta["render_egress_denied"] == 3 and meta["render_browser"] == "chrome 154.0.0.0"
    assert len(meta) <= 32
    origins = await rig.world.artifacts.relations(artifact.artifact_id, RelationDirection.ORIGINS)
    assert [(r.relation.value, r.origin_artifact_id) for r in origins] == [("rendered_from", rig.snapshot)]
    path = rig.world.artifacts.payload_path(artifact)
    assert open(path, "rb").read()[4:8] == b"ftyp" and not os.path.exists(path + ".partial")
    assert ("core.presentation_render.complete" in rig.world.sink.kinds()) and ("core.presentation_render.queued" in rig.world.sink.kinds())


async def test_the_runner_receives_the_frozen_source_the_frozen_props_and_the_declared_composition(rig):
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "still", {"frame": 12}))["job_id"])
    assert done["state"] == "complete"
    files = rig.runner.files[done["job_id"]]
    assert {"src/Scene.tsx", "src/lib/Title.tsx", "public/dot.png", "studio-root.tsx", "package.json"} <= set(files)
    spec = next(c[1] for c in rig.runner.calls if c[0] == "run")
    assert spec["props"]["title"] == "Valeur figée" and spec["props"]["accent"] == "#3366ff"  # instance value over the frozen default
    assert spec["composition"] == {"width": 1280, "height": 720, "fps": 30, "durationInFrames": 90}
    assert spec["frames"] == [12] and spec["format"] == "still" and spec["composition_id"] == "Scene"
    root = files["studio-root.tsx"].decode()
    assert r"Valeur fig\u00e9e" in root  # the generated root also carries the frozen props (ASCII-escaped JSON)
    assert ("cleanup", done["job_id"]) in rig.runner.calls


async def test_a_pdf_of_page_images_is_a_flat_export_and_says_so(rig):
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "pdf", {"frames": [0, 45, 89]}))["job_id"])
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert artifact.kind is ArtifactKind.PRESENTATION_PDF and artifact.metadata["render_pages"] == 3
    assert artifact.metadata["render_frames"] == "0,45,89" and artifact.metadata["render_flat"] is True
    assert artifact.metadata["render_image_format"] == "jpeg"


async def test_progress_is_visible_while_the_render_runs_and_cancel_is_offered(rig):
    rig.runner.mode = "block"
    queued = await rig.service.submit(rig.snapshot, "mp4", {"frame_end": 59})
    await asyncio.to_thread(rig.runner.running.wait, 5)
    await asyncio.sleep(0.05)
    view = rig.service.get(queued["job_id"])
    assert view["state"] == "running" and view["phase"] == "rendering" and (view["frames_done"], view["frames_total"]) == (2, 60)
    assert view["can_cancel"] is True and view["timeout_s"] == int(D.TIMEOUT_BASE_S + 60) and view["elapsed_s"] >= 0 and view["percent"] == 3
    assert view["queue_position"] is None
    rig.runner.release()
    assert (await finished(rig.service, queued["job_id"]))["state"] == "complete"


# ------------------------------------------------------------------ concurrency 1 and the queue


async def test_only_one_render_runs_at_a_time_and_the_others_wait_in_order(rig):
    rig.runner.mode = "block"
    first = await rig.service.submit(rig.snapshot, "still")
    await asyncio.to_thread(rig.runner.running.wait, 5)
    second = await rig.service.submit(rig.snapshot, "still", {"frame": 1})
    third = await rig.service.submit(rig.snapshot, "still", {"frame": 2})
    assert rig.service.get(second["job_id"])["state"] == "queued" and rig.service.get(second["job_id"])["queue_position"] == 1
    assert rig.service.get(third["job_id"])["queue_position"] == 2
    assert [c for c in rig.runner.calls if c[0] == "run"].__len__() == 1
    rig.runner.release()
    for job in (first, second, third):
        assert (await finished(rig.service, job["job_id"]))["state"] == "complete"
    order = [c[1]["frames"] for c in rig.runner.calls if c[0] == "run"]
    assert order == [[0], [1], [2]]
    assert D.CONCURRENCY_LIMIT == 1


async def test_a_full_queue_is_refused_and_creates_nothing(rig):
    rig.runner.mode = "block"
    await rig.service.submit(rig.snapshot, "still")
    await asyncio.to_thread(rig.runner.running.wait, 5)
    for index in range(D.MAX_QUEUED):
        await rig.service.submit(rig.snapshot, "still", {"frame": index})
    before = len(await derivatives(rig))
    with pytest.raises(RenderError) as refused:
        await rig.service.submit(rig.snapshot, "still", {"frame": 50})
    assert refused.value.code is D.RenderErrorCode.QUEUE_FULL and refused.value.status == 429
    assert len(await derivatives(rig)) == before
    rig.runner.release()


# ------------------------------------------------------------------ cancel


async def test_cancelling_a_queued_job_fails_its_derivative_before_the_answer(rig):
    rig.runner.mode = "block"
    first = await rig.service.submit(rig.snapshot, "still")
    await asyncio.to_thread(rig.runner.running.wait, 5)
    waiting = await rig.service.submit(rig.snapshot, "still", {"frame": 3})
    view = await rig.service.cancel(waiting["job_id"])
    assert view["state"] == "cancelled" and view["error_code"] == "presentation_render_cancelled" and view["can_cancel"] is False
    artifact = await rig.world.artifacts.get(waiting["artifact_id"])
    assert artifact.state is ArtifactState.FAILED and artifact.error_code == "presentation_render_cancelled"  # terminal BEFORE the answer
    rig.runner.release()
    assert (await finished(rig.service, first["job_id"]))["state"] == "complete"
    assert len([c for c in rig.runner.calls if c[0] == "run"]) == 1  # the cancelled job never started


async def test_cancelling_a_running_job_stops_it_and_never_leaves_a_final_file(rig):
    rig.runner.mode = "block"
    queued = await rig.service.submit(rig.snapshot, "mp4")
    await asyncio.to_thread(rig.runner.running.wait, 5)
    view = await rig.service.cancel(queued["job_id"])
    assert view["cancel_requested"] is True and view["can_cancel"] is False
    done = await finished(rig.service, queued["job_id"])
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert done["state"] == "cancelled" and artifact.state is ArtifactState.FAILED and artifact.error_code == "presentation_render_cancelled"
    info = rig.world.artifacts.payload_info(artifact)
    assert info is None or info.final_bytes is None
    assert not any(c[0] == "verify" for c in rig.runner.calls)
    with pytest.raises(RenderError) as again:
        await rig.service.cancel(queued["job_id"])
    assert again.value.code is D.RenderErrorCode.NOT_CANCELLABLE


async def test_an_unknown_job_is_a_typed_404(rig):
    with pytest.raises(RenderError) as refused:
        rig.service.get("rj_ffffffffffff")
    assert refused.value.code is D.RenderErrorCode.UNKNOWN_JOB and refused.value.status == 404
    with pytest.raises(RenderError):
        await rig.service.cancel("rj_ffffffffffff")


# ------------------------------------------------------------------ failures are said, never partial


@pytest.mark.parametrize("code", ["presentation_render_failed", "presentation_render_timeout", "presentation_render_disk_full",
                                  "presentation_render_job_too_large", "presentation_render_crashed", "presentation_render_composition_mismatch"])
async def test_a_failed_render_fails_the_derivative_with_the_runner_code_and_keeps_no_final_file(rig, code):
    rig.runner.mode, rig.runner.fail_code, rig.runner.fail_detail = "fail", code, "Error: it broke at C:\\Users\\me\\secret\\x.js"
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "mp4"))["job_id"])
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert done["state"] == "failed" and done["error_code"] == code and artifact.state is ArtifactState.FAILED and artifact.error_code == code
    assert "C:\\Users" not in done["error_detail"] and "<path>" in done["error_detail"]
    assert done["log_tail"] == ["line one", "line two"]
    info = rig.world.artifacts.payload_info(artifact)
    assert info is None or info.final_bytes is None
    assert ("core.presentation_render.failed", "error") in [(k, lvl) for k, lvl, _ in rig.world.sink.rows]


async def test_a_prepare_failure_fails_the_job_not_the_worker(rig):
    rig.runner.mode = "prepare_fails"
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "still"))["job_id"])
    assert done["state"] == "failed" and done["error_code"] == "presentation_render_disk_low"
    rig.runner.mode = "ok"
    assert (await finished(rig.service, (await rig.service.submit(rig.snapshot, "still"))["job_id"]))["state"] == "complete"


async def test_an_output_that_does_not_verify_is_never_stored(rig):
    rig.runner.verify_error = RenderError(D.RenderErrorCode.OUTPUT_INVALID, "the video holds 59 frames, expected 60")
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "mp4"))["job_id"])
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert done["error_code"] == "presentation_render_output_invalid" and artifact.state is ArtifactState.FAILED
    info = rig.world.artifacts.payload_info(artifact)
    assert info is None or (info.final_bytes is None and not info.partial_bytes)


async def test_an_unexpected_defect_is_a_typed_failure_of_that_job_and_the_next_one_runs(rig, monkeypatch):
    original = rig.runner.prepare
    calls = {"n": 0}

    def explode(job_id, files):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ZeroDivisionError("defect")
        return original(job_id, files)

    monkeypatch.setattr(rig.runner, "prepare", explode)
    first = await finished(rig.service, (await rig.service.submit(rig.snapshot, "still"))["job_id"])
    assert first["state"] == "failed" and first["error_code"] == "presentation_render_internal_error" and "ZeroDivisionError" in first["error_detail"]
    assert ("core.presentation_render.internal_error", "error") in [(k, lvl) for k, lvl, _ in rig.world.sink.rows]
    assert (await finished(rig.service, (await rig.service.submit(rig.snapshot, "still"))["job_id"]))["state"] == "complete"


# ------------------------------------------------------------------ refused before anything exists


async def _refuse(rig, call, code):
    before = len(await derivatives(rig))
    with pytest.raises(Exception) as refused:
        await call()
    got = getattr(getattr(refused.value, "code", None), "value", None)
    assert got == code, (got, refused.value)
    assert len(await derivatives(rig)) == before  # nothing was created
    assert not [c for c in rig.runner.calls if c[0] == "run"]


async def test_unresolvable_snapshots_are_refused_and_create_no_derivative(rig):
    await _refuse(rig, lambda: rig.service.submit("jart_ps_" + "0" * 32 + "_" + "1" * 32 + "_p1_v1_a1", "mp4"), "presentation_render_snapshot_invalid")
    shot = await rig.world.artifacts.create(kind=ArtifactKind.SCREENSHOT, source="test", payload_name="s.png", mime_type="image/png")
    await _refuse(rig, lambda: rig.service.submit(shot.artifact_id, "mp4"), "presentation_render_snapshot_invalid")


async def test_a_pending_or_failed_snapshot_is_not_rendered(rig):
    pid, vid = await rig.world.new_presentation(prefab_id="presentation-studio.p000000000002.s000000000002")
    p, v = await rig.world.revisions(pid)
    begun = await rig.world.snapshots.begin_snapshot(pid, vid, expected_presentation_revision=p, expected_variant_revision=v)
    await _refuse(rig, lambda: rig.service.submit(begun["artifact_id"], "mp4"), "presentation_render_snapshot_invalid")
    await rig.world.artifacts.fail(begun["artifact_id"], error_code="package_failed")
    await _refuse(rig, lambda: rig.service.submit(begun["artifact_id"], "mp4"), "presentation_render_snapshot_invalid")


async def test_a_tampered_package_is_refused(rig):
    artifact = await rig.world.artifacts.get(rig.snapshot)
    path = rig.world.artifacts.payload_path(artifact)
    data = bytearray(open(path, "rb").read())
    data[len(data) // 2] ^= 0xFF
    open(path, "wb").write(bytes(data))
    await _refuse(rig, lambda: rig.service.submit(rig.snapshot, "still"), "presentation_render_snapshot_invalid")
    assert ("core.snapshot_packager.tampered", "error") in [(k, lvl) for k, lvl, _ in rig.world.sink.rows]


async def test_a_machine_with_another_engine_than_the_frozen_one_refuses(rig):
    other = FakeInstalled()
    other.remotion_version = "4.0.999"
    rig.runner.installed = other
    await _refuse(rig, lambda: rig.service.submit(rig.snapshot, "still"), "presentation_render_engine_mismatch")
    rig.runner.installed = None
    await _refuse(rig, lambda: rig.service.submit(rig.snapshot, "still"), "presentation_render_engine_mismatch")


async def test_a_lock_drift_is_recorded_not_refused(rig):
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "still"))["job_id"])
    artifact = await rig.world.artifacts.get(done["artifact_id"])
    assert artifact.metadata["render_engine_drift"] is True  # the fake lock differs from the test pin's lock


@pytest.mark.parametrize("settings,message", [
    ({"codec": "vp9"}, "unknown settings"), ({"frame_end": 90}, "outside the scene"), ({"frame_start": 9, "frame_end": 3}, "before"),
    ({"scale": 3}, "scale must be"), ({"crf": 5}, "crf")])
async def test_bad_settings_are_refused_with_a_reason(rig, settings, message):
    with pytest.raises(RenderError) as refused:
        await rig.service.submit(rig.snapshot, "mp4", settings)
    assert refused.value.code is D.RenderErrorCode.INVALID and message in refused.value.detail
    assert not await derivatives(rig)


async def test_a_bad_format_is_refused_by_the_studio_code(rig):
    with pytest.raises(PresentationStudioError) as refused:
        await rig.service.submit(rig.snapshot, "gif")
    assert refused.value.code.value == "presentation_studio_invalid"


async def test_a_capability_that_is_not_ready_or_a_missing_browser_is_said(rig):
    rig.status = "not_installed"
    await _refuse(rig, lambda: rig.service.submit(rig.snapshot, "still"), "presentation_render_runtime_unavailable")
    assert rig.service.availability()["ready"] is False and "not_installed" in rig.service.availability()["reason"]
    rig.status = "ready"
    rig.runner.browser = None
    await _refuse(rig, lambda: rig.service.submit(rig.snapshot, "still"), "presentation_render_browser_unavailable")
    assert "never downloaded" in rig.service.availability()["reason"]
    rig.runner.browser = None
    rig.runner.runtime_problem = "bundler_missing: run repair"
    await _refuse(rig, lambda: rig.service.submit(rig.snapshot, "still"), "presentation_render_runtime_unavailable")


async def test_an_unknown_scene_is_a_typed_404_and_the_named_one_renders(rig, monkeypatch):
    with pytest.raises(RenderError) as unknown:
        await rig.service.submit(rig.snapshot, "still", {"scene_id": "pss_999999999999"})
    assert unknown.value.code is D.RenderErrorCode.UNKNOWN_SCENE and unknown.value.status == 404
    assert (await finished(rig.service, (await rig.service.submit(rig.snapshot, "still", {"scene_id": SCENE_ID}))["job_id"]))["state"] == "complete"


# ------------------------------------------------------------------ stale source, export (freeze then render)


async def test_a_render_of_an_older_snapshot_stays_valid_after_the_source_moves_on(rig):
    view = await rig.world.studio.get(rig.pid)
    variant = view.variants[0].to_document()
    await rig.world.studio.save_variant(rig.pid, rig.vid, {"expected_revision": variant["revision"], "title": "Changé", "scenes": variant["scenes"],
                                                            "art_direction_id": None, "score_id": None})
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "still"))["job_id"])
    assert done["state"] == "complete"
    entry = next(e for e in (await rig.world.snapshots.describe_source(rig.pid))["snapshots"] if e["artifact_id"] == rig.snapshot)
    assert entry["stale"] is True and [r["state"] for r in entry["renders"]] == ["complete"]
    render = entry["renders"][0]
    assert (render["width"], render["height"], render["scene_id"], render["flat"]) == (1280, 720, SCENE_ID, True)
    assert len(render["settings_sha256"]) == 64


async def test_export_freezes_the_exact_revisions_then_renders_that_snapshot(rig):
    pid, vid = await rig.world.new_presentation(prefab_id="presentation-studio.p000000000003.s000000000003")
    p, v = await rig.world.revisions(pid)
    job = await rig.service.export(presentation_id=pid, variant_id=vid, expected_presentation_revision=p, expected_variant_revision=v,
                                   authorised_boards=OK_BOARDS, render_format="still")
    assert job["snapshot_id"].startswith("jart_ps_") and job["snapshot_replayed"] is False
    assert (await finished(rig.service, job["job_id"]))["state"] == "complete"
    again = await rig.service.export(presentation_id=pid, variant_id=vid, expected_presentation_revision=p, expected_variant_revision=v,
                                     authorised_boards=OK_BOARDS, render_format="still")
    assert again["snapshot_id"] == job["snapshot_id"] and again["snapshot_replayed"] is True  # replay-safe: the same snapshot
    await finished(rig.service, again["job_id"])


async def test_export_with_an_outdated_revision_freezes_and_renders_nothing(rig):
    p, v = await rig.world.revisions(rig.pid)
    before = (await rig.world.artifacts.query(ArtifactQuery(limit=50))).items
    with pytest.raises(PresentationStudioError) as stale:
        await rig.service.export(presentation_id=rig.pid, variant_id=rig.vid, expected_presentation_revision=p + 5, expected_variant_revision=v,
                                 authorised_boards=OK_BOARDS, render_format="mp4")
    assert stale.value.code.value == "presentation_studio_stale_revision"
    assert len((await rig.world.artifacts.query(ArtifactQuery(limit=50))).items) == len(before)


async def test_export_validates_format_and_settings_before_freezing_anything(rig):
    pid, vid = await rig.world.new_presentation(prefab_id="presentation-studio.p000000000004.s000000000004")
    p, v = await rig.world.revisions(pid)
    with pytest.raises(RenderError):
        await rig.service.export(presentation_id=pid, variant_id=vid, expected_presentation_revision=p, expected_variant_revision=v,
                                 authorised_boards=OK_BOARDS, render_format="mp4", settings={"nope": 1})
    page = await rig.world.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_SNAPSHOT,), limit=50))
    assert len(page.items) == 1  # only the fixture's snapshot


# ------------------------------------------------------------------ recovery and shutdown


async def test_reconcile_kills_an_orphan_and_fails_the_pending_derivative_without_promoting_a_partial_file(rig):
    snapshot = await rig.world.artifacts.get(rig.snapshot)
    meta = {"render_format": "mp4"}
    orphan = await rig.world.snapshots.begin_render(rig.snapshot, "mp4", metadata=meta)
    spool = rig.world.artifacts.open_spool(orphan)
    spool.write(b"half a video")  # a .partial a crashed copy left behind: never promoted
    spool.close()
    rig.runner.records_on_disk = [{"job_id": "rj_0000000000aa", "state": "running", "process_ref": "999:abc", "artifact_id": orphan.artifact_id}]
    rig.runner.alive_refs.add("999:abc")
    assert snapshot.state is ArtifactState.COMPLETE
    report = await rig.service.reconcile()
    assert report["killed"] == 1 and report["failed"] == 1 and report["partial"] == 0
    assert rig.runner.stopped == ["999:abc"] and rig.runner.swept == ["rj_0000000000aa"]
    after = await rig.world.artifacts.get(orphan.artifact_id)
    assert after.state is ArtifactState.FAILED and after.error_code == "presentation_render_interrupted"
    info = rig.world.artifacts.payload_info(after)
    assert info.final_bytes is None and info.partial_bytes == len(b"half a video")  # the evidence stays, unpromoted
    assert ("prune", D.KEEP_FINISHED * 5) in rig.runner.calls


async def test_reconcile_marks_a_complete_but_unverified_final_file_partial(rig):
    orphan = await rig.world.snapshots.begin_render(rig.snapshot, "still", metadata={})
    spool = rig.world.artifacts.open_spool(orphan)
    spool.write(b"\x89PNG....")
    spool.finalize()  # the rename was done, the registry was not updated
    report = await rig.service.reconcile()
    after = await rig.world.artifacts.get(orphan.artifact_id)
    assert report["partial"] == 1 and after.state is ArtifactState.PARTIAL and after.error_code == "artifact_recovered"


async def test_reconcile_ignores_finished_records_and_leaves_other_artifacts_alone(rig):
    rig.runner.records_on_disk = [{"job_id": "rj_0000000000bb", "state": "complete", "process_ref": "5:6"}]
    rig.runner.alive_refs.add("5:6")
    report = await rig.service.reconcile()
    assert report == {"killed": 0, "failed": 0, "partial": 0, "kept": 0} and rig.runner.stopped == []
    assert (await rig.world.artifacts.get(rig.snapshot)).state is ArtifactState.COMPLETE


async def test_the_generic_recovery_leaves_render_derivatives_to_their_owner(rig):
    orphan = await rig.world.snapshots.begin_render(rig.snapshot, "mp4", metadata={})
    report = await rig.world.artifacts.recover_pending(owned=PresentationRenderService.owns)
    assert report.owned == (orphan.artifact_id,) and (await rig.world.artifacts.get(orphan.artifact_id)).state is ArtifactState.PENDING


async def test_stopping_fails_the_waiting_jobs_and_cancels_the_running_one(rig):
    rig.runner.mode = "block"
    running = await rig.service.submit(rig.snapshot, "mp4")
    await asyncio.to_thread(rig.runner.running.wait, 5)
    waiting = await rig.service.submit(rig.snapshot, "still")
    await rig.service.stop()
    assert rig.service.get(waiting["job_id"])["error_code"] == "presentation_render_interrupted"
    assert rig.service.get(running["job_id"])["state"] in ("cancelled", "failed")
    for job in (running, waiting):
        artifact = await rig.world.artifacts.get(job["artifact_id"])
        assert artifact.state is ArtifactState.FAILED
    with pytest.raises(RenderError) as refused:
        await rig.service.submit(rig.snapshot, "still")
    assert refused.value.code is D.RenderErrorCode.UNAVAILABLE


async def test_a_shutdown_never_turns_a_completed_job_into_a_failure(rig):
    done = await finished(rig.service, (await rig.service.submit(rig.snapshot, "still"))["job_id"])
    worker = rig.service._worker
    await rig.service.stop()
    assert worker.done() and (await rig.world.artifacts.get(done["artifact_id"])).state is ArtifactState.COMPLETE


async def test_the_record_of_a_job_is_written_for_the_recovery(rig):
    queued = await rig.service.submit(rig.snapshot, "still")
    done = await finished(rig.service, queued["job_id"])
    record = rig.runner.written[queued["job_id"]]
    assert record["state"] == "complete" and record["artifact_id"] == done["artifact_id"] and record["format"] == "still"
    assert json.dumps(record)  # plain JSON, no path


async def test_only_the_last_finished_jobs_are_remembered(rig, monkeypatch):
    monkeypatch.setattr("jarvis.core.presentation_render_service.KEEP_FINISHED", 2)
    ids = []
    for frame in range(4):
        job = await rig.service.submit(rig.snapshot, "still", {"frame": frame})
        await finished(rig.service, job["job_id"])
        ids.append(job["job_id"])
    await asyncio.sleep(0.05)
    assert len(rig.service.jobs()) == 2 and rig.service.get(ids[-1])["state"] == "complete"
    with pytest.raises(RenderError):
        rig.service.get(ids[0])
