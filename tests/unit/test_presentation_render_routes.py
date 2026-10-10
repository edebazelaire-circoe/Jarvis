"""`/v1/local-capabilities/remotion/render*` sur un vrai Core (registre, Studio, prefabs, paquet réels ; faux runners de capacité et de rendu), Slice 16."""

from __future__ import annotations

import asyncio
import json
import socket

import aiohttp
import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactKind, ArtifactState
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.presentation_render_routes import PREFIX, PresentationRenderProtocolRoutes
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.remotion_render import FakeRenderRunner
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.test_local_capability_host import FakeRunner

TOKEN = "t" * 48
SCENE = "presentation-studio.p000000000001.s000000000001"
SCENE_ID = "pss_000000000001"
JOBS = PREFIX + "/jobs"


class Stack:
    pass


async def _stack(tmp_path, *, render_runner=True):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    s = Stack()
    s.render = FakeRenderRunner(tmp_path) if render_runner else None
    s.core = JarvisCoreApplication(data_root=tmp_path, local_capability_runner=FakeRunner(),
                                   local_capability_store=FileLocalCapabilityStore(tmp_path.resolve()),
                                   remotion_render_runner=s.render)
    await s.core.start()
    s.server = LocalProtocolServer(s.core, host="127.0.0.1", port=port, token=TOKEN)
    await s.server.start()
    s.client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    s.base = f"http://127.0.0.1:{port}"
    return s


@pytest.fixture
async def stack(tmp_path):
    s = await _stack(tmp_path)
    try:
        yield s
    finally:
        await s.client.close()
        await s.server.stop()
        await s.core.stop()


async def call(base, method, path, *, token=TOKEN, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, base + path, headers={"Authorization": f"Bearer {token}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


async def ready(stack):
    assert (await stack.client.local_capability_action("remotion", "install"))["capability"]["status"] == "ready"


async def frozen(stack, suffix="1"):
    prefab = f"presentation-studio.p00000000000{suffix}.s00000000000{suffix}"
    published = await stack.core.prefabs.save(scene_candidate(prefab), actor="user")
    created = await stack.core.presentation_studio.create({"title": "Atelier"})
    pid, vid = created.presentation.presentation_id, created.presentation.active_variant_id
    variant = created.variants[0].to_document()
    await stack.core.presentation_studio.save_variant(pid, vid, {
        "expected_revision": variant["revision"], "title": variant["title"],
        "scenes": [{"scene_id": SCENE_ID, "prefab": {"id": prefab, "version": published.version}}], "art_direction_id": None, "score_id": None})
    view = await stack.core.presentation_studio.get(pid)
    revisions = (view.presentation.revision, view.variants[0].revision)
    done = await stack.core.presentation_packager.freeze(pid, vid, expected_presentation_revision=revisions[0], expected_variant_revision=revisions[1],
                                                         authorised_boards={"default"})
    return done["artifact_id"], pid, vid, revisions


async def until_done(base, job_id, timeout=10.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        status, body = await call(base, "GET", f"{JOBS}/{job_id}")
        assert status == 200
        if body["job"]["state"] in ("complete", "failed", "cancelled"):
            return body["job"]
        await asyncio.sleep(0.02)
    raise AssertionError("render did not finish")


# ------------------------------------------------------------------ wiring


async def test_core_has_a_render_service_only_with_a_runner_and_a_capability_store(tmp_path):
    bare = JarvisCoreApplication(data_root=tmp_path / "a")
    assert bare.presentation_render is None and bare.presentation_packager is not None
    no_runner = JarvisCoreApplication(data_root=tmp_path / "b", local_capability_runner=FakeRunner(),
                                      local_capability_store=FileLocalCapabilityStore((tmp_path / "b").resolve()))
    assert no_runner.presentation_render is None
    with_runner = JarvisCoreApplication(data_root=tmp_path / "c", local_capability_runner=FakeRunner(),
                                        local_capability_store=FileLocalCapabilityStore((tmp_path / "c").resolve()),
                                        remotion_render_runner=FakeRenderRunner(tmp_path))
    assert with_runner.presentation_render is not None
    assert with_runner.presentation_packager is not None and with_runner.presentation_render._packager is with_runner.presentation_packager


async def test_starting_core_reconciles_but_renders_nothing(stack):
    assert ("prune", 100) in stack.render.calls and not [c for c in stack.render.calls if c[0] in ("run", "prepare")]


async def test_a_core_without_a_render_service_answers_503(tmp_path):
    s = await _stack(tmp_path, render_runner=False)
    try:
        for method, path in (("GET", PREFIX), ("GET", JOBS), ("POST", JOBS), ("GET", JOBS + "/rj_000000000000"), ("POST", JOBS + "/rj_000000000000/cancel")):
            status, body = await call(s.base, method, path, json={"format": "mp4", "snapshot_id": "x"} if method == "POST" and path == JOBS else None)
            assert status == 503 and body["error"]["code"] == "presentation_render_unavailable", (method, path)
    finally:
        await s.client.close()
        await s.server.stop()
        await s.core.stop()


async def test_every_route_needs_the_core_token(stack):
    for method, path in (("GET", PREFIX), ("GET", JOBS), ("POST", JOBS), ("GET", JOBS + "/x"), ("POST", JOBS + "/x/cancel")):
        status, _ = await call(stack.base, method, path, token="wrong" * 10)
        assert status == 401, (method, path)


# ------------------------------------------------------------------ the happy path through HTTP


async def test_a_snapshot_is_rendered_through_the_routes_and_the_board_data_shows_the_render(stack):
    await ready(stack)
    snapshot, pid, vid, _ = await frozen(stack)
    status, body = await call(stack.base, "GET", PREFIX)
    assert status == 200 and body["render"]["ready"] is True and body["render"]["browser"] == "chrome 154.0.0.0" and body["render"]["concurrency"] == 1
    status, body = await call(stack.base, "POST", JOBS, json={"snapshot_id": snapshot, "format": "mp4", "settings": {"frame_end": 29}})
    assert status == 202 and body["job"]["state"] in ("queued", "running", "complete") and body["job"]["snapshot_id"] == snapshot
    job = await until_done(stack.base, body["job"]["job_id"])
    assert job["state"] == "complete" and job["percent"] == 100 and job["format"] == "mp4" and job["frames_total"] == 30
    status, listed = await call(stack.base, "GET", JOBS)
    assert status == 200 and [j["job_id"] for j in listed["jobs"]] == [job["job_id"]]
    derived = await stack.core.artifacts.get(job["artifact_id"])
    assert derived.kind is ArtifactKind.PRESENTATION_VIDEO and derived.state is ArtifactState.COMPLETE
    described = await stack.core.presentation_artifacts.describe_source(pid)
    renders = described["snapshots"][0]["renders"]
    assert [(r["artifact_id"], r["state"], r["width"], r["flat"]) for r in renders] == [(job["artifact_id"], "complete", 1280, True)]
    assert described["snapshots"][0]["board_ids"], "the derivative is linked to the active Board like every Artifact"


async def test_export_freezes_then_renders_in_one_request_and_a_second_request_replays_the_snapshot(stack):
    await ready(stack)
    _, pid, vid, revisions = await frozen(stack, "2")
    payload = {"format": "still", "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": revisions[0],
               "expected_variant_revision": revisions[1], "authorised_boards": ["default"], "settings": {"frame": 5}}
    status, first = await call(stack.base, "POST", JOBS, json=payload)
    assert status == 202 and first["job"]["snapshot_replayed"] is True  # the fixture already froze these exact revisions
    status, second = await call(stack.base, "POST", JOBS, json=payload)
    assert second["job"]["snapshot_id"] == first["job"]["snapshot_id"] and second["job"]["authorised_boards"] == []
    for job in (first["job"], second["job"]):
        assert (await until_done(stack.base, job["job_id"]))["state"] == "complete"


async def test_export_with_an_outdated_revision_is_a_stale_409_and_creates_nothing(stack):
    await ready(stack)
    _, pid, vid, revisions = await frozen(stack, "3")
    status, body = await call(stack.base, "POST", JOBS, json={"format": "mp4", "presentation_id": pid, "variant_id": vid,
                                                              "expected_presentation_revision": revisions[0] + 3,
                                                              "expected_variant_revision": revisions[1], "authorised_boards": ["default"]})
    assert status == 409 and body["error"]["code"] == "presentation_studio_stale_revision"
    assert stack.core.presentation_render.jobs() == []


async def test_export_without_authorised_boards_reads_no_board(stack):
    await ready(stack)
    prefab = "presentation-studio.p000000000004.s000000000004"
    from jarvis.domain.presentation_live_refs import LIVE_REFS_FORMAT, LIVE_REFS_PATH
    files = {LIVE_REFS_PATH: json.dumps({"format": LIVE_REFS_FORMAT, "refs": [{"name": "n", "ref": "board:default/memory/notes/a.md"}]})}
    from tests.fakes.remotion_scene import scene_files
    published = await stack.core.prefabs.save(scene_candidate(prefab, files={**scene_files(), **files}), actor="user")
    created = await stack.core.presentation_studio.create({"title": "Vivante"})
    pid, vid = created.presentation.presentation_id, created.presentation.active_variant_id
    variant = created.variants[0].to_document()
    await stack.core.presentation_studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": "t", "scenes": [
        {"scene_id": SCENE_ID, "prefab": {"id": prefab, "version": published.version}}], "art_direction_id": None, "score_id": None})
    view = await stack.core.presentation_studio.get(pid)
    status, body = await call(stack.base, "POST", JOBS, json={
        "format": "still", "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": view.presentation.revision,
        "expected_variant_revision": view.variants[0].revision})
    assert status in (409, 400) and body["error"]["code"] in ("live_ref_not_authorised", "live_ref_unresolved"), body
    assert stack.core.presentation_render.jobs() == []


# ------------------------------------------------------------------ cancel and refusals


async def test_cancelling_a_running_render_through_http(stack):
    await ready(stack)
    snapshot, *_ = await frozen(stack, "5")
    stack.render.mode = "block"
    _, created = await call(stack.base, "POST", JOBS, json={"snapshot_id": snapshot, "format": "mp4"})
    await asyncio.to_thread(stack.render.running.wait, 5)
    status, body = await call(stack.base, "POST", f"{JOBS}/{created['job']['job_id']}/cancel", json={})
    assert status == 200 and body["job"]["cancel_requested"] is True
    job = await until_done(stack.base, created["job"]["job_id"])
    assert job["state"] == "cancelled" and job["error_code"] == "presentation_render_cancelled"
    status, body = await call(stack.base, "POST", f"{JOBS}/{created['job']['job_id']}/cancel")
    assert status == 409 and body["error"]["code"] == "presentation_render_not_cancellable"


async def test_a_failed_render_is_a_job_view_not_an_http_error(stack):
    await ready(stack)
    snapshot, *_ = await frozen(stack, "6")
    stack.render.mode = "fail"
    _, created = await call(stack.base, "POST", JOBS, json={"snapshot_id": snapshot, "format": "mp4"})
    job = await until_done(stack.base, created["job"]["job_id"])
    assert job["state"] == "failed" and job["error_code"] == "presentation_render_failed" and job["log_tail"]
    assert (await stack.core.artifacts.get(job["artifact_id"])).state is ArtifactState.FAILED


@pytest.mark.parametrize("body,status,code", [
    ({}, 400, "presentation_render_invalid"), ({"format": 3}, 400, "presentation_render_invalid"),
    ({"format": "mp4"}, 400, "presentation_render_invalid"), ({"format": "mp4", "snapshot_id": 4}, 400, "presentation_render_invalid"),
    ({"format": "mp4", "snapshot_id": "x", "extra": 1}, 400, "presentation_render_invalid"),
    ({"format": "mp4", "snapshot_id": "x", "presentation_id": "y"}, 400, "presentation_render_invalid"),
    ({"format": "gif", "snapshot_id": "x"}, 400, "presentation_studio_invalid"),
    ({"format": "mp4", "presentation_id": "pst_x", "variant_id": "v", "expected_presentation_revision": "1", "expected_variant_revision": 1}, 400,
     "presentation_render_invalid"),
    ({"format": "mp4", "presentation_id": "p", "variant_id": "v", "expected_presentation_revision": 1, "expected_variant_revision": 1,
      "authorised_boards": "default"}, 400, "presentation_render_invalid"),
    ({"format": "mp4", "snapshot_id": "jart_ps_nope"}, 409, "presentation_render_snapshot_invalid"),
])
async def test_malformed_requests_are_refused_with_a_stable_code_and_create_nothing(stack, body, status, code):
    await ready(stack)
    got_status, answer = await call(stack.base, "POST", JOBS, json=body)
    assert (got_status, answer["error"]["code"]) == (status, code), answer
    assert stack.core.presentation_render.jobs() == [] and not stack.render.calls[-1:] == [("run", {})]


async def test_unusable_bodies_queries_and_ids_are_refused(stack):
    await ready(stack)
    assert (await call(stack.base, "POST", JOBS, data=b"{broken"))[0] == 400
    assert (await call(stack.base, "POST", JOBS, json=[1]))[0] == 400
    assert (await call(stack.base, "POST", JOBS, data=b"x" * 9000))[1]["error"]["code"] == "presentation_render_invalid"
    assert (await call(stack.base, "GET", JOBS + "?limit=3"))[1]["error"]["code"] == "presentation_render_invalid"
    status, body = await call(stack.base, "GET", JOBS + "/rj_000000000000")
    assert status == 404 and body["error"]["code"] == "presentation_render_unknown_job"
    assert (await call(stack.base, "POST", JOBS + "/rj_000000000000/cancel", json={"x": 1}))[0] == 400
    assert (await call(stack.base, "POST", JOBS + "/rj_000000000000/cancel"))[0] == 404


async def test_a_render_is_refused_until_the_capability_is_ready_and_a_browser_exists(stack):
    snapshot, *_ = await frozen(stack, "7")
    status, body = await call(stack.base, "POST", JOBS, json={"snapshot_id": snapshot, "format": "still"})
    assert status == 409 and body["error"]["code"] == "presentation_render_runtime_unavailable" and "not_installed" in body["error"]["message"]
    status, body = await call(stack.base, "GET", PREFIX)
    assert body["render"]["ready"] is False and "not_installed" in body["render"]["reason"]
    await ready(stack)
    stack.render.browser = None
    status, body = await call(stack.base, "POST", JOBS, json={"snapshot_id": snapshot, "format": "still"})
    assert status == 409 and body["error"]["code"] == "presentation_render_browser_unavailable"
    assert not [c for c in stack.render.calls if c[0] == "run"]


async def test_the_routes_do_not_collide_with_the_capability_operation_routes(stack):
    registered = {(r.method, r.path) for r in PresentationRenderProtocolRoutes(object()).routes() if r.method != "HEAD"}
    assert registered == {("GET", PREFIX), ("GET", JOBS), ("POST", JOBS), ("GET", JOBS + "/{job_id}"), ("POST", JOBS + "/{job_id}/cancel")}
    status, body = await call(stack.base, "POST", "/v1/local-capabilities/remotion/render", json={})
    assert status in (400, 404, 405) and body["error"]["code"] != "presentation_render_unavailable"  # the capability route answers, not ours
