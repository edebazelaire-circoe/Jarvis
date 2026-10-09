"""`/v1/local-capabilities/remotion/studio*` sur un vrai Core (prefabs réels, faux runner de capacité et de Studio), Slice 11."""

from __future__ import annotations

import socket

import aiohttp
import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.remotion_scene import scene_candidate, scene_files
from tests.fakes.remotion_studio import FakeStudioRunner
from tests.unit.test_local_capability_host import FakeRunner

TOKEN = "t" * 48
SCENE = "presentation-studio.p000000000001.s000000000001"
STUDIO = "/v1/local-capabilities/remotion/studio"


@pytest.fixture
async def stack(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    capability, studio = FakeRunner(), FakeStudioRunner()
    core = JarvisCoreApplication(data_root=tmp_path, local_capability_runner=capability,
                                 local_capability_store=FileLocalCapabilityStore(tmp_path.resolve()), remotion_studio_runner=studio)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, client, f"http://127.0.0.1:{port}", studio
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def call(base, method, path, *, token=TOKEN, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, base + path, headers={"Authorization": f"Bearer {token}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


async def ready_capability(client):
    assert (await client.local_capability_action("remotion", "install"))["capability"]["status"] == "ready"


async def publish(core, version_suffix=""):
    return await core.prefabs.save(scene_candidate(SCENE, files=scene_files(version_suffix)), actor="user")


async def test_get_reports_stopped_and_never_launches_anything(stack):
    _core, _client, base, studio = stack
    status, body = await call(base, "GET", STUDIO)
    assert status == 200 and body["studio"]["status"] == "stopped" and body["studio"]["url"] is None
    assert studio.calls.count("launch") == 0 and studio.calls.count("sync_work") == 0


async def test_open_serves_the_published_scene_and_close_stops_it(stack):
    core, client, base, studio = stack
    await ready_capability(client)
    publication = await publish(core)
    status, body = await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": publication.version})
    view = body["studio"]
    assert status == 200 and view["status"] == "ready" and view["url"].startswith("http://127.0.0.1:") and view["pin"]["version"] == publication.version
    assert set(studio.work) >= {"src/Scene.tsx", "studio-root.tsx", "package.json"}
    again = (await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": publication.version}))[1]["studio"]
    assert again["reused"] is True and studio.calls.count("launch") == 1
    status, closed = await call(base, "POST", STUDIO + "/close")
    assert status == 200 and closed["studio"]["status"] == "stopped" and not studio.alive


async def test_a_new_published_version_reaches_the_open_studio_through_sync(stack):
    core, client, base, studio = stack
    await ready_capability(client)
    one = await publish(core)
    await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": one.version})
    two = await publish(core, "// second version\n")
    status, body = await call(base, "POST", STUDIO + "/sync", json={"prefab_id": SCENE, "version": two.version})
    assert status == 200 and body["studio"]["pin"]["version"] == two.version and body["studio"]["syncs"] == 1
    assert studio.work["src/lib/Title.tsx"].endswith(b"// second version\n") and studio.calls.count("launch") == 1
    status, body = await call(base, "POST", STUDIO + "/sync")
    assert status == 200 and body["studio"]["syncs"] == 2


async def test_the_studio_is_refused_until_the_capability_is_ready(stack):
    core, _client, base, studio = stack
    publication = await publish(core)
    status, body = await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": publication.version})
    assert status == 409 and body["error"]["code"] == "remotion_studio_runtime_unavailable" and "not_installed" in body["error"]["message"]
    assert studio.calls.count("launch") == 0


async def test_an_unknown_or_html_version_is_a_typed_404(stack):
    core, client, base, _studio = stack
    await ready_capability(client)
    status, body = await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": 9})
    assert status == 404 and body["error"]["code"] == "remotion_studio_source_unavailable"
    status, body = await call(base, "POST", STUDIO + "/open", json={"prefab_id": "jarvis.counter", "version": 1})
    assert status == 404


@pytest.mark.parametrize("method,path,kwargs", [
    ("POST", "/open", {}), ("POST", "/open", {"json": {"prefab_id": SCENE}}), ("POST", "/open", {"json": {"prefab_id": SCENE, "version": "latest"}}),
    ("POST", "/open", {"data": b"{broken"}), ("POST", "/open", {"json": [1]}), ("POST", "/close", {"json": {"x": 1}}),
    ("POST", "/restart", {"json": {"x": 1}}), ("GET", "?x=1", {}), ("POST", "/open", {"data": b"x" * 2000}),
])
async def test_invalid_requests_are_refused_with_a_code(stack, method, path, kwargs):
    _core, _client, base, studio = stack
    status, body = await call(base, method, STUDIO + path, **kwargs)
    assert status == 400 and body["error"]["code"] == "remotion_studio_invalid"
    assert studio.calls.count("launch") == 0


async def test_every_studio_route_needs_the_core_token(stack):
    _core, _client, base, _studio = stack
    for method, path in (("GET", STUDIO), ("POST", STUDIO + "/open"), ("POST", STUDIO + "/close"), ("POST", STUDIO + "/restart"),
                         ("POST", STUDIO + "/sync")):
        status, _ = await call(base, method, path, token="wrong")
        assert status in (401, 403), (method, path, status)


async def test_a_start_failure_is_a_failed_view_over_http(stack):
    from jarvis.domain.remotion_studio import StudioError, StudioErrorCode
    core, client, base, studio = stack
    await ready_capability(client)
    publication = await publish(core)
    studio.launch_errors = [StudioError(StudioErrorCode.START_FAILED, "process_exited: boom")]
    status, body = await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": publication.version})
    assert status == 200 and body["studio"]["status"] == "failed" and body["studio"]["last_error_code"] == "remotion_studio_start_failed"
    status, body = await call(base, "POST", STUDIO + "/restart")
    assert status == 200 and body["studio"]["status"] == "ready" and body["studio"]["restarts"] == 1


async def test_uninstalling_the_capability_stops_the_studio_first_and_core_stop_leaves_no_orphan(stack):
    core, client, base, studio = stack
    await ready_capability(client)
    publication = await publish(core)
    await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": publication.version})
    assert studio.alive
    await client.local_capability_action("remotion", "uninstall")
    assert not studio.alive
    body = (await call(base, "GET", STUDIO))[1]["studio"]
    assert body["status"] == "stopped" and body["stop_reason"] == "capability_change"
    await ready_capability(client)
    await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": publication.version})
    assert studio.alive
    await core.stop()
    assert not studio.alive


async def test_a_core_without_a_studio_runner_answers_503(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    try:
        status, body = await call(f"http://127.0.0.1:{port}", "GET", STUDIO)
        assert status == 503 and body["error"]["code"] == "remotion_studio_unavailable"
    finally:
        await server.stop()
        await core.stop()
