"""Studio Remotion, revue QA de la Slice 11 : accusé obligatoire, arrêt de la capacité, état illisible, atomicité, chemins, routes (REWORK)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket

import aiohttp
import pytest

from jarvis.adapters import remotion_studio_runner as R
from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.core.remotion_studio_service import RemotionStudioService
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain import remotion_studio as D
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C, StudioPin
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.remotion_scene import scene_candidate, scene_files
from tests.fakes.remotion_studio import FakeStudioRunner
from tests.unit.test_local_capability_host import FakeRunner
from tests.unit.test_remotion_studio import PIN, PIN2, SCENE, Stack, source_for
from tests.unit.test_remotion_studio_runner import files, make

TOKEN = "t" * 48
STUDIO = "/v1/local-capabilities/remotion/studio"
ACK = "acknowledge_unsandboxed_scene"


# ------------------------------------------------------------------ B2 : l'accusé

@pytest.mark.parametrize("call", ["open", "restart", "sync_other"])
async def test_the_service_itself_refuses_without_the_acknowledgement(call):
    stack = Stack()
    await stack.service.open(PIN, acknowledged=True)
    launches = stack.runner.calls.count("launch")
    with pytest.raises(StudioError) as caught:
        if call == "open":
            await stack.service.open(PIN)
        elif call == "restart":
            await stack.service.restart()
        else:
            await stack.service.sync(PIN2)
    assert caught.value.code is C.ACK_REQUIRED and caught.value.http_status == 400
    assert stack.runner.calls.count("launch") == launches and (await stack.service.status())["pin"] == PIN.to_dict()
    await stack.service.stop()


def test_the_body_parsers_want_exactly_true_and_nothing_else():
    assert D.parse_open({"prefab_id": SCENE, "version": 2, ACK: True}) == StudioPin(SCENE, 2)
    for bad in ({"prefab_id": SCENE, "version": 2}, {"prefab_id": SCENE, "version": 2, ACK: 1}, {"prefab_id": SCENE, "version": 2, ACK: "true"}):
        with pytest.raises(StudioError) as caught:
            D.parse_open(bad)
        assert caught.value.code is C.ACK_REQUIRED
    with pytest.raises(StudioError) as caught:
        D.parse_open({"prefab_id": SCENE, "version": 2, ACK: True, "path": "C:/x"})
    assert caught.value.code is C.INVALID
    D.parse_ack_only({ACK: True})
    for bad in ({}, {ACK: False}, {ACK: True, "x": 1}):
        with pytest.raises(StudioError):
            D.parse_ack_only(bad)


# ------------------------------------------------------------------ B2 : routes de Core

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
    from jarvis.protocol.client import LocalCoreClient
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, client, f"http://127.0.0.1:{port}", studio
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def call(base, method, path, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, base + path, headers={"Authorization": f"Bearer {TOKEN}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


async def publish(core, suffix=""):
    return await core.prefabs.save(scene_candidate(SCENE, files=scene_files(suffix)), actor="user")


@pytest.mark.parametrize("path,body", [
    ("/open", {"prefab_id": SCENE, "version": 1}),
    ("/open", {"prefab_id": SCENE, "version": 1, ACK: False}),
    ("/open", {"prefab_id": SCENE, "version": 1, ACK: "true"}),
    ("/open", {"prefab_id": SCENE, "version": 1, ACK: 1}),
    ("/restart", {}), ("/restart", {ACK: "yes"}),
    ("/sync", {"prefab_id": SCENE, "version": 1})])
async def test_without_the_explicit_acknowledgement_nothing_is_launched_or_changed(stack, path, body):
    core, client, base, studio = stack
    assert (await client.local_capability_action("remotion", "install"))["capability"]["status"] == "ready"
    publication = await publish(core)
    body = {**body, **({"version": publication.version} if "version" in body else {})}
    status, answer = await call(base, "POST", STUDIO + path, json=body)
    assert status == 400 and answer["error"]["code"] == "remotion_studio_ack_required", answer
    assert studio.calls.count("launch") == 0 and studio.calls.count("sync_work") == 0 and not studio.alive
    assert (await call(base, "GET", STUDIO))[1]["studio"]["status"] == "stopped"


async def test_a_refresh_of_the_open_scene_needs_no_new_acknowledgement_but_another_scene_does(stack):
    core, client, base, studio = stack
    await client.local_capability_action("remotion", "install")
    one = await publish(core)
    await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": one.version, ACK: True})
    assert (await call(base, "POST", STUDIO + "/sync"))[0] == 200
    two = await publish(core, "// two\n")
    status, answer = await call(base, "POST", STUDIO + "/sync", json={"prefab_id": SCENE, "version": two.version})
    assert status == 400 and answer["error"]["code"] == "remotion_studio_ack_required"
    assert (await call(base, "GET", STUDIO))[1]["studio"]["pin"]["version"] == one.version
    status, answer = await call(base, "POST", STUDIO + "/sync", json={"prefab_id": SCENE, "version": two.version, ACK: True})
    assert status == 200 and answer["studio"]["pin"]["version"] == two.version


async def test_an_unexpected_failure_is_a_coded_500_and_is_logged_durably(stack, monkeypatch):
    core, _client, base, _studio = stack

    async def boom(*_a, **_k):
        raise RuntimeError(r"secret detail C:\Users\x")
    monkeypatch.setattr(core.remotion_studio, "status", boom)
    seen = []
    monkeypatch.setattr(core.remotion_studio, "_emit", lambda kind, message, **data: seen.append((kind, data)))
    status, body = await call(base, "GET", STUDIO)
    assert status == 500 and body["error"]["code"] == "remotion_studio_internal_error" and "secret" not in json.dumps(body)
    assert seen and seen[0][0] == "route_failed" and seen[0][1]["exception_type"] == "RuntimeError"


def test_no_brain_mcp_or_agent_path_can_open_the_studio():
    """Seules les routes de Core (jeton porteur) et la carte du Control Center (confirmation) atteignent `open`."""

    root = Path(__file__).resolve().parents[2] / "jarvis"
    allowed = {"core/remotion_studio_service.py", "core/v2_app.py", "protocol/remotion_studio_routes.py", "app.py", "domain/remotion_studio.py",
               "ports/remotion_studio.py", "adapters/remotion_studio_runner.py", "runtime/remotion_studio_relay.py",
               "runtime/control_center_remotion_studio.js", "runtime/control_center.py", "runtime/control_center.html", "protocol/server.py",
               "protocol/client.py", "core/local_capability_service.py", "capabilities/remotion/studio-guard.cjs",
               # Slice 16 (render): REUSE the Studio's pure helpers (`plan_workspace`, `safe_relative`) and subclass its relay's transport; none of
               # them can open the Studio (the render has its own routes, service and process: `docs/remotion-render.md`).
               "adapters/remotion_render_runner.py", "domain/presentation_render_plan.py", "runtime/presentation_render_relay.py"}
    users = {path.relative_to(root).as_posix() for path in root.rglob("*")
             if path.suffix in {".py", ".js", ".html", ".cjs", ".mjs"}
             and any(token in path.read_text(encoding="utf-8", errors="replace") for token in ("remotion_studio", "RemotionStudio", "remotion/studio"))}
    assert users <= allowed, sorted(users - allowed)
    for path in root.rglob("*.py"):
        name = path.relative_to(root).as_posix()
        if "tool_brain" in name or "mcp" in name or name.startswith(("brain", "core/brain", "core/tool")):
            assert "remotion_studio" not in path.read_text(encoding="utf-8", errors="replace"), name


# ------------------------------------------------------------------ polish 6, 7, état illisible, chemins

async def test_a_failed_kill_before_a_capability_change_blocks_it_and_never_reports_stopped():
    stack = Stack()
    await stack.service.open(PIN, acknowledged=True)

    def stubborn(ref):
        raise StudioError(C.STOP_FAILED, "the Studio process tree is still alive after the kill")
    stack.runner.stop = stubborn
    with pytest.raises(StudioError) as caught:
        await asyncio.to_thread(stack.service.stop_for_capability_change)
    assert caught.value.code is C.STOP_FAILED
    view = await stack.service.status()
    assert view["status"] == "failed" and view["last_error_code"] == C.STOP_FAILED.value, "never a lying 'stopped'"


async def test_a_capability_change_waits_for_a_start_in_progress_then_stops_it():
    stack = Stack()
    gate = asyncio.Event()
    original = stack.provide

    async def slow(pin):
        await gate.wait()
        return await original(pin)
    stack.service._source = slow
    opening = asyncio.create_task(stack.service.open(PIN, acknowledged=True))
    await asyncio.sleep(0.05)
    changing = asyncio.create_task(asyncio.to_thread(stack.service.stop_for_capability_change))
    await asyncio.sleep(0.1)
    assert not changing.done(), "it waits for the lock held by the starting open"
    gate.set()
    await opening
    await changing
    assert not stack.runner.alive and (await stack.service.status())["stop_reason"] == "capability_change"


async def test_a_refused_studio_stop_blocks_the_capability_operation_with_a_typed_error(stack):
    from jarvis.domain.local_capabilities import LocalCapabilityError, LocalCapabilityErrorCode
    core, client, base, studio = stack
    await client.local_capability_action("remotion", "install")
    publication = await publish(core)
    await call(base, "POST", STUDIO + "/open", json={"prefab_id": SCENE, "version": publication.version, ACK: True})

    def stubborn(ref):
        raise StudioError(C.STOP_FAILED, "still alive")
    studio.stop = stubborn
    with pytest.raises(LocalCapabilityError) as caught:
        await core.local_capabilities.act("remotion", "disable")
    assert caught.value.code is LocalCapabilityErrorCode.STOP_FAILED
    assert core.local_capabilities.host.status("remotion")["status"] != "disabled"
    assert (await call(base, "GET", STUDIO))[1]["studio"]["status"] == "failed"


async def test_adoption_declares_the_new_core_as_the_parent():
    stack = Stack()
    await stack.service.open(PIN, acknowledged=True)
    saved = dict(stack.runner.state)
    stack.runner.calls.clear()
    again = RemotionStudioService(stack.runner, source_provider=stack.provide, capability_status=lambda: "ready", clock=stack.clock)
    stack.runner.state = saved
    assert (await again.reconcile())["status"] == "ready"
    assert "bind_parent" in stack.runner.calls
    await again.stop()


async def test_an_unreadable_state_is_typed_blocks_open_and_is_never_overwritten():
    stack = Stack()
    stack.runner.state = {"schema": 9}
    view = await stack.service.status()
    assert view["status"] == "failed" and view["last_error_code"] == C.STATE_UNREADABLE.value
    with pytest.raises(StudioError) as caught:
        await stack.service.open(PIN, acknowledged=True)
    assert caught.value.code is C.STATE_UNREADABLE and stack.runner.calls.count("launch") == 0
    assert stack.runner.state == {"schema": 9}, "never rewritten"
    stack.runner.state = None  # le fichier a été mis de côté
    assert (await stack.service.open(PIN, acknowledged=True))["status"] == "ready"
    await stack.service.stop()


async def test_status_never_interleaves_with_a_sync():
    stack = Stack()
    await stack.service.open(PIN, acknowledged=True)
    seen = []
    original = stack.runner.sync_work

    def slow_sync(files_):
        seen.append(stack.service._lock.locked())
        return original(files_)
    stack.runner.sync_work = slow_sync
    results = await asyncio.gather(stack.service.sync(PIN2, acknowledged=True), stack.service.status(), stack.service.status())
    assert seen == [True] and results[0]["syncs"] == 1
    await stack.service.stop()


def test_diagnostics_never_carry_a_drive_user_or_unc_path():
    samples = [r"Error at C:\Users\Clarice\AppData\x.js:1:2", "at C:/Users/Clarice/x.js", "\\\\?\\C:\\Users\\a\\b", "/c/Users/Clarice/x",
               "/Users/clarice/x.js", "file:///C:/Users/a/b.js", r"(D:\Projects\z)", "~/x/y", "\\\\server\\share\\f", "/home/bob/app.js"]
    view = D.public_view(D.StudioState(diagnostics=samples), idle_timeout_s=60, now=0)
    text = " ".join(view["diagnostics"])
    for needle in ("Clarice", "clarice", "Users", "Projects", "bob", "server", "share"):
        assert needle not in text, needle


@pytest.mark.parametrize("bad", ["../x.ts", "src/../../x", "./a", "src//a", "src/./a", "/abs.ts", "C:/x.ts", "c:x.ts", "src\\a.ts", "a/b:stream",
                                 "", "src/", "x\x00y", "a/..", "..", "."])
def test_a_work_path_that_is_not_a_plain_relative_path_is_refused_before_touching_the_disk(tmp_path, bad):
    runtime = tmp_path / "local_capabilities" / "remotion" / "runtime"
    (runtime / "node_modules" / "@remotion" / "cli").mkdir(parents=True)
    runner = make(runtime)
    with pytest.raises(StudioError) as caught:
        runner.sync_work({**files(), bad: b"x"})
    assert caught.value.code is C.SYNC_FAILED
    assert not (runtime / "studio" / "work").exists() or not any(p.name.startswith(("x", "abs")) for p in (runtime / "studio" / "work").rglob("*"))
    assert not (tmp_path / "x.ts").exists() and not (runtime.parent / "x.ts").exists()


def test_saved_edits_refuse_a_hostile_path_too(tmp_path):
    runtime = tmp_path / "local_capabilities" / "remotion" / "runtime"
    runtime.mkdir(parents=True)
    runner = make(runtime)
    runner.sync_work(files())
    for bad in ("../escape.ts", "/abs.ts", "C:/x.ts", "a\\b.ts"):
        with pytest.raises(StudioError):
            runner._save_edits((bad,))
    assert R.safe_relative("src/lib/Title.tsx") == "src/lib/Title.tsx"


def test_the_tool_cache_folder_is_wiped_at_each_launch(tmp_path):
    runtime = tmp_path / "local_capabilities" / "remotion" / "runtime"
    (runtime / "node_modules" / "@remotion" / "cli").mkdir(parents=True)
    (runtime / R.CLI_ENTRY).write_text("//", encoding="utf-8")
    runner = make(runtime, spawn=lambda *a, **k: 2_000_000_000, sleep=lambda s: None, port_chooser=lambda: 39998)
    runner.sync_work(files())
    stale = runtime / "studio" / "work" / "node_modules" / "evil" / "index.js"
    stale.parent.mkdir(parents=True)
    stale.write_text("module.exports = 1", encoding="utf-8")
    with pytest.raises(StudioError):
        runner.launch(port=None)
    assert not stale.exists() and (runtime / "studio" / "parent.json").is_file()
    parent = json.loads((runtime / "studio" / "parent.json").read_text(encoding="utf-8"))
    import os
    assert parent["pid"] == os.getpid() and parent["created"]


def test_the_source_for_helper_is_still_importable():
    assert source_for(PIN).block.composition.composition_id == "Scene" and scene_files()


async def test_reconcile_never_raises_when_the_new_parent_cannot_be_declared():
    """P1 : disque plein ou antivirus sur `parent.json` : Core démarre quand même ; le Studio adopté est arrêté, l'état est `failed`, journalisé en error."""

    stack = Stack()
    await stack.service.open(PIN, acknowledged=True)
    saved = dict(stack.runner.state)
    ref = next(iter(stack.runner.alive))

    def full_disk():
        raise OSError(28, "No space left on device")
    stack.runner.bind_parent = full_disk
    again = RemotionStudioService(stack.runner, source_provider=stack.provide, capability_status=lambda: "ready", diagnostics=stack.events, clock=stack.clock)
    stack.runner.state = saved
    view = await again.reconcile()
    assert view["status"] == "failed" and view["last_error_code"] == C.STORE_FAILED.value and ref not in stack.runner.alive
    assert any(kind == "remotion_studio.failed" and level == "error" for kind, level, _ in stack.events.events)


async def test_an_unexpected_reconcile_defect_is_logged_and_swallowed():
    stack = Stack()

    async def boom():
        raise RuntimeError("defect")
    stack.service._reconcile = boom
    view = await stack.service.reconcile()
    assert view["status"] == "stopped"
    assert any(kind == "remotion_studio.reconcile_failed" and level == "error" for kind, level, _ in stack.events.events)
