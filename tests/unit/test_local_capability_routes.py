"""`/v1/local-capabilities*` de bout en bout sur un vrai Core avec un faux runner, et câblage du démarrage de Core
(Slice 04 de jarvis-remotion-presentation-integration ; `docs/local-capabilities.md` §7, Issue 02 point b)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
import socket
import threading
import time

import aiohttp
import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.local_capabilities import InstallStatus, LocalCapabilityErrorCode as C, initial_state, transition_install
from jarvis.domain.remotion_capability import REMOTION_CAPABILITY_ID as CID
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.unit.test_local_capability_host import Clock, FakeRunner

TOKEN = "t" * 48
ROOT = Path(__file__).resolve().parents[2]


async def _stack(tmp_path, runner, *, seed=None, store=True):
    if seed is not None:
        seed(FileLocalCapabilityStore(tmp_path))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path, local_capability_runner=runner,
                                 local_capability_store=FileLocalCapabilityStore(tmp_path.resolve()) if store else None)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    return core, server, LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN), f"http://127.0.0.1:{port}"


@pytest.fixture
async def stack(tmp_path):
    runner = FakeRunner()
    core, server, client, base = await _stack(tmp_path, runner)
    try:
        yield core, client, base, runner
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def _raw(method, url, *, token=TOKEN, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


# ------------------------------------------------- démarrage de Core : rien ne se lance tout seul

async def test_core_start_runs_nothing_and_registers_remotion_as_not_installed(stack):
    _core, client, _base, runner = stack
    assert runner.calls == [], "starting Core must not install, probe, start or stop anything"
    [cap] = (await client.list_local_capabilities())["capabilities"]
    assert (cap["capability_id"], cap["status"], cap["family"], cap["transport"]) == (CID, "not_installed", "local_capability", "local_process")


async def test_core_start_reconciles_an_interrupted_install_without_touching_the_runner(tmp_path):
    def seed(store):
        clock = Clock()
        store.save(transition_install(initial_state(CID, now=clock()), InstallStatus.INSTALLING, now=clock()))

    runner = FakeRunner()
    core, server, client, _ = await _stack(tmp_path, runner, seed=seed)
    try:
        [cap] = (await client.list_local_capabilities())["capabilities"]
        assert cap["status"] == "install_failed" and cap["last_error_code"] == C.INSTALL_INTERRUPTED.value
        assert runner.calls == []
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_a_core_without_a_runner_never_reaches_npm_and_says_so(tmp_path):
    core, server, client, _ = await _stack(tmp_path, None)
    try:
        view = (await client.local_capability_action(CID, "install"))["capability"]
        assert view["status"] == "install_failed" and view["last_error_code"] == C.RUNNER_UNAVAILABLE.value
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_a_core_without_a_store_answers_runner_unavailable_on_every_route(tmp_path):
    core, server, client, base = await _stack(tmp_path, None, store=False)
    try:
        for method, path in (("GET", "/v1/local-capabilities"), ("POST", f"/v1/local-capabilities/{CID}/install")):
            status, body = await _raw(method, base + path)
            assert (status, body["error"]["code"]) == (503, C.RUNNER_UNAVAILABLE.value)
    finally:
        await client.close()
        await server.stop()
        await core.stop()


def test_the_composition_root_injects_a_file_store_under_the_data_root(tmp_path):
    from jarvis import app
    assert isinstance(app._local_capability_store(tmp_path), FileLocalCapabilityStore)


async def test_a_background_failure_is_logged_even_if_the_client_left(tmp_path):
    events = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None):
            events.append((kind, level))

    from jarvis.core.local_capability_host import LocalCapabilityHost
    from jarvis.core.local_capability_service import LocalCapabilityService
    from jarvis.domain.remotion_capability import remotion_manifest
    host = LocalCapabilityHost(FileLocalCapabilityStore(tmp_path), runner=FakeRunner(), manifests={CID: remotion_manifest()})
    gate = threading.Event()

    def boom(capability_id):
        gate.wait(10)
        raise RuntimeError("late failure")

    host.install = boom
    service = LocalCapabilityService(host, wait_s=30, diagnostics=Sink())
    task = asyncio.create_task(service.act(CID, "install"))
    await asyncio.sleep(0.2)
    task.cancel()  # le client part avant la fin
    with pytest.raises(asyncio.CancelledError):
        await task
    gate.set()
    for _ in range(50):
        if ("local_capability.service.background_failed", "error") in events:
            break
        await asyncio.sleep(0.1)
    assert ("local_capability.service.background_failed", "error") in events


def test_the_composition_root_builds_the_real_runner_without_executing_anything(monkeypatch):
    from jarvis import app
    from jarvis.adapters import process_tree
    from jarvis.adapters.node_capability_runner import NodeCapabilityRunner

    monkeypatch.setattr(process_tree, "run_bounded", lambda *a, **k: pytest.fail("building the runner executed a process"))
    monkeypatch.setattr(process_tree, "spawn_detached", lambda *a, **k: pytest.fail("building the runner spawned a process"))
    assert isinstance(app._local_capability_runner(), NodeCapabilityRunner)


# ---------------------------------------------------------------------------------- routes

async def test_install_then_every_operation_round_trip(stack):
    _core, client, base, runner = stack
    assert (await client.local_capability_action(CID, "install"))["capability"]["status"] == "ready"
    assert (await client.local_capability_action(CID, "install"))["capability"]["install_attempts"] == 1
    assert runner.calls.count("install") == 1, "install is once-only: the second call must not reach the runner"
    assert (await client.local_capability_action(CID, "start"))["capability"]["status"] == "running"
    assert (await client.local_capability_action(CID, "health"))["capability"]["health"] == "healthy"
    assert (await client.local_capability_action(CID, "stop"))["capability"]["status"] == "ready"
    assert (await client.local_capability_action(CID, "disable"))["capability"]["status"] == "disabled"
    assert (await client.local_capability_action(CID, "enable"))["capability"]["status"] == "ready"
    assert (await client.local_capability_action(CID, "repair"))["capability"]["status"] == "ready"
    assert (await client.local_capability_action(CID, "update"))["capability"]["status"] == "ready"
    assert (await client.local_capability_action(CID, "uninstall"))["capability"]["status"] == "not_installed"
    status, body = await _raw("GET", base + f"/v1/local-capabilities/{CID}")
    assert status == 200 and body["capability"]["status"] == "not_installed"


@pytest.mark.parametrize("method, path, body, status, code", [
    ("GET", "/v1/local-capabilities/nope", None, 404, C.UNKNOWN.value),
    ("POST", "/v1/local-capabilities/nope/install", None, 404, C.UNKNOWN.value),
    ("POST", f"/v1/local-capabilities/{CID}/explode", None, 400, C.INVALID.value),
    ("POST", f"/v1/local-capabilities/{CID}/install", {"force": True}, 400, C.INVALID.value),
    ("GET", "/v1/local-capabilities?x=1", None, 400, C.INVALID.value),
    ("POST", f"/v1/local-capabilities/{CID}/start", None, 409, C.NOT_INSTALLED.value),
    ("POST", f"/v1/local-capabilities/{CID}/update", None, 409, C.NOT_INSTALLED.value),
])
async def test_refusals_carry_stable_codes_and_statuses(stack, method, path, body, status, code):
    _core, _client, base, _runner = stack
    got, payload = await _raw(method, base + path, **({"json": body} if body is not None else {}))
    assert (got, payload["error"]["code"]) == (status, code)


async def test_every_route_requires_the_core_token(stack):
    _core, _client, base, _runner = stack
    for method, path in (("GET", "/v1/local-capabilities"), ("GET", f"/v1/local-capabilities/{CID}"),
                         ("POST", f"/v1/local-capabilities/{CID}/install")):
        status, _ = await _raw(method, base + path, token="wrong")
        assert status == 401


async def test_an_operation_failure_is_the_view_not_an_http_error(stack):
    _core, client, _base, runner = stack
    runner.missing = ("node_too_old: found 18.0.0, need >= 20.0.0",)
    view = (await client.local_capability_action(CID, "install"))["capability"]
    assert view["status"] == "install_failed" and view["last_error_code"] == C.REQUIREMENT_MISSING.value
    assert "node_too_old" in view["last_error_detail"]


async def test_a_long_install_answers_202_with_the_current_state_then_finishes(stack):
    core, _client, base, runner = stack
    core.local_capabilities._wait_s = 0.2
    gate, entered = threading.Event(), threading.Event()
    original = runner.install

    def slow(manifest, runtime_dir):
        entered.set()
        assert gate.wait(30)
        return original(manifest, runtime_dir)

    runner.install = slow
    status, body = await _raw("POST", base + f"/v1/local-capabilities/{CID}/install")
    assert status == 202 and body["capability"]["status"] == "installing"
    assert entered.wait(5)
    status2, body2 = await _raw("POST", base + f"/v1/local-capabilities/{CID}/install")
    assert (status2, body2["error"]["code"]) == (409, C.BUSY.value), "a second explicit install must not start a second runtime"
    gate.set()
    deadline = time.monotonic() + 10
    current = body
    while time.monotonic() < deadline:
        _, current = await _raw("GET", base + f"/v1/local-capabilities/{CID}")
        if current["capability"]["status"] == "ready":
            break
        await asyncio.sleep(0.1)
    assert current["capability"]["status"] == "ready" and runner.calls.count("install") == 1


async def test_core_stop_cancels_the_runner_so_an_in_flight_install_does_not_outlive_core(tmp_path):
    class Cancelling(FakeRunner):
        cancelled = False

        def cancel_all(self):
            self.cancelled = True

    runner = Cancelling()
    core, server, client, _ = await _stack(tmp_path, runner)
    await client.close()
    await server.stop()
    await core.stop()
    assert runner.cancelled


# ---------------------------------------------------------------------- routes documentées

def test_every_registered_local_capability_route_is_documented():
    from jarvis.protocol.local_capability_routes import LocalCapabilityProtocolRoutes
    docs = (ROOT / "docs" / "local-capabilities.md").read_text(encoding="utf-8") + (ROOT / "docs" / "remotion-runtime.md").read_text(encoding="utf-8")
    registered = {route.path for route in LocalCapabilityProtocolRoutes(object()).routes()}
    assert registered == {"/v1/local-capabilities", "/v1/local-capabilities/{capability_id}", "/v1/local-capabilities/{capability_id}/{operation}"}
    # Le Studio Remotion optionnel (Slice 11) est un préfixe FRÈRE, documenté dans `remotion-studio.md` et gardé par son propre test.
    from jarvis.protocol.remotion_studio_routes import RemotionStudioProtocolRoutes
    sibling = {route.path for route in RemotionStudioProtocolRoutes(object()).routes()}
    # Le rendu / export (Slice 16) est un autre préfixe FRÈRE (`remotion-render.md`, test `test_presentation_render_routes.py`).
    from jarvis.protocol.presentation_render_routes import PresentationRenderProtocolRoutes
    sibling |= {route.path for route in PresentationRenderProtocolRoutes(object()).routes()}
    for path in registered:
        assert path in docs, f"{path} is registered but not quoted in docs/local-capabilities.md or docs/remotion-runtime.md"
    for quoted in set(re.findall(r"/v1/local-capabilities[A-Za-z0-9_{}/-]*", docs)):
        assert quoted in registered | sibling, f"{quoted} is documented but not registered"


def test_the_local_capability_routes_share_no_path_with_the_remote_plugin_routes():
    from jarvis.protocol.local_capability_routes import PREFIX
    assert "mcp" not in PREFIX
