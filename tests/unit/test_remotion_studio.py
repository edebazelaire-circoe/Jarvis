"""Studio Remotion optionnel : domaine pur et service (faux runner), Slice 11. Contrat : `docs/remotion-studio.md`."""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.remotion_studio_service import RemotionStudioService
from jarvis.domain import remotion_studio as D
from jarvis.domain.prefab import parse_candidate
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C, StudioPin
from tests.fakes.remotion_scene import scene_candidate, scene_files
from tests.fakes.remotion_studio import FakeStudioRunner

SCENE = "presentation-studio.p000000000001.s000000000001"
OTHER = "presentation-studio.p000000000001.s000000000002"
PIN, PIN2, PIN_OTHER = StudioPin(SCENE, 1), StudioPin(SCENE, 2), StudioPin(OTHER, 1)


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, dict(data or {})))

    def kinds(self):
        return [kind for kind, _, _ in self.events]


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def source_for(pin):
    suffix = f"// {pin.prefab_id[-4:]} v{pin.version}\n"
    return parse_candidate(scene_candidate(pin.prefab_id, files=scene_files(suffix))).remotion_source()


class Stack:
    def __init__(self, **options):
        self.runner = FakeStudioRunner(port=options.pop("port", None))
        self.clock = Clock()
        self.events = Recorder()
        self.capability = options.pop("capability", "ready")
        self.unknown: set[StudioPin] = set()
        self.service = RemotionStudioService(self.runner, source_provider=self.provide, capability_status=lambda: self.capability,
                                             diagnostics=self.events, clock=self.clock, **options)

    async def provide(self, pin):
        if pin in self.unknown:
            raise StudioError(C.SOURCE_UNAVAILABLE, "unknown version")
        return source_for(pin), {"title": "Bonjour"}


@pytest.fixture
def stack():
    return Stack()


# ------------------------------------------------------------------ domaine

def test_workspace_is_exactly_the_scene_source_plus_two_generated_files():
    source = source_for(PIN)
    files = D.plan_workspace(source, {"title": "A"})
    assert set(files) == set(source.files) | {D.WORK_ROOT_FILE, D.WORK_PACKAGE}
    assert all(files[path] == data for path, data in source.files.items()), "scene bytes are untouched"
    root = files[D.WORK_ROOT_FILE].decode()
    assert 'import Scene from "./src/Scene"' in root and 'id="Scene"' in root and "durationInFrames={90}" in root
    assert '{"title": "A"}' in root
    assert not any("node_modules" in path or path.endswith("remotion.config.ts") for path in files)
    assert b"jarvis-studio-scene" in files[D.WORK_PACKAGE]


def test_workspace_digest_changes_with_the_source():
    assert D.workspace_digest(D.plan_workspace(source_for(PIN))) != D.workspace_digest(D.plan_workspace(source_for(PIN2)))


@pytest.mark.parametrize("raw", [None, {}, {"prefab_id": SCENE}, {"prefab_id": SCENE, "version": 0}, {"prefab_id": SCENE, "version": True},
                                 {"prefab_id": SCENE, "version": "latest"}, {"prefab_id": "../x", "version": 1},
                                 {"prefab_id": SCENE, "version": 1, "path": "C:/x"}])
def test_a_pin_names_one_exact_version_and_nothing_else(raw):
    with pytest.raises(StudioError) as caught:
        D.parse_pin(raw)
    assert caught.value.code is C.INVALID


def test_idle_timeout_and_port_bounds():
    assert D.parse_idle_timeout(60) == 60.0
    for bad in (59, 90_000, "x", None):
        with pytest.raises(StudioError):
            D.parse_idle_timeout(bad)
    assert D.valid_port(1024) and not D.valid_port(80) and not D.valid_port(True) and not D.valid_port(70000)


def test_the_view_has_no_disk_path_no_secret_and_a_loopback_url_only_when_ready():
    state = D.StudioState(status=D.StudioStatus.READY, pin=PIN, port=41001, ready_at=5.0, last_activity_at=5.0,
                          diagnostics=[r"error at C:\Users\bob\x.tsx token=abc"])
    view = D.public_view(state, idle_timeout_s=100, now=10.0)
    assert view["url"] == "http://127.0.0.1:41001/" and view["idle_in_s"] == 95.0
    text = repr(view)
    assert "Users" not in text and "abc" not in text and "process_ref" not in view
    state.status = D.StudioStatus.STOPPED
    assert D.public_view(state, idle_timeout_s=100, now=10.0)["url"] is None


def test_state_payload_round_trips_and_refuses_an_unknown_schema():
    state = D.StudioState(status=D.StudioStatus.READY, pin=PIN, port=41001, process_ref="1:2", launch_id="x", syncs=2, restarts=1)
    again = D.StudioState.from_payload(state.to_payload())
    assert (again.status, again.pin, again.port, again.process_ref, again.syncs, again.restarts) == (state.status, PIN, 41001, "1:2", 2, 1)
    with pytest.raises(ValueError):
        D.StudioState.from_payload({"schema": 9})


# ------------------------------------------------------------------ service : jamais forcé

async def test_nothing_starts_without_an_explicit_open(stack):
    view = await stack.service.status()
    await stack.service.reconcile()
    await stack.service.stop()
    assert view["status"] == "stopped" and view["url"] is None
    assert "launch" not in stack.runner.calls and "sync_work" not in stack.runner.calls


async def test_open_materialises_then_launches_one_studio_and_reports_a_loopback_url(stack):
    view = await stack.service.open(PIN)
    assert view["status"] == "ready" and view["url"].startswith("http://127.0.0.1:") and view["pin"] == PIN.to_dict()
    assert stack.runner.calls.index("sync_work") < stack.runner.calls.index("launch")
    assert stack.runner.launches == [None], "random free port by default"
    assert view["composition"]["id"] == "Scene" and view["source_digest"]
    assert "remotion_studio.ready" in stack.events.kinds()
    await stack.service.stop()


async def test_a_second_open_on_the_same_scene_reuses_the_live_host(stack):
    first = await stack.service.open(PIN)
    again = await stack.service.open(PIN)
    assert again["reused"] is True and again["url"] == first["url"]
    assert stack.runner.calls.count("launch") == 1
    await stack.service.stop()


async def test_opening_another_scene_switches_in_place_never_a_second_studio(stack):
    first = await stack.service.open(PIN)
    other = await stack.service.open(PIN_OTHER)
    assert stack.runner.calls.count("launch") == 1 and other["url"] == first["url"]
    assert other["pin"] == PIN_OTHER.to_dict() and other["syncs"] == 1
    assert any(path.startswith("src/") for path in stack.runner.work)
    await stack.service.stop()


async def test_sync_refreshes_the_work_copy_for_hot_reload_without_a_new_process(stack):
    await stack.service.open(PIN)
    before = (await stack.service.status())["source_digest"]
    view = await stack.service.sync(PIN2)
    assert view["source_digest"] != before and view["pin"] == PIN2.to_dict() and view["syncs"] == 1 and view["status"] == "ready"
    assert stack.runner.calls.count("launch") == 1
    same = await stack.service.sync()
    assert same["syncs"] == 2 and same["source_digest"] == view["source_digest"]
    await stack.service.stop()


async def test_sync_when_closed_is_a_typed_refusal(stack):
    with pytest.raises(StudioError) as caught:
        await stack.service.sync()
    assert caught.value.code is C.NOT_RUNNING


async def test_a_sync_failure_is_reported_and_keeps_the_studio_up(stack):
    await stack.service.open(PIN)
    stack.runner.sync_error = StudioError(C.SYNC_FAILED, "disk full")
    with pytest.raises(StudioError) as caught:
        await stack.service.sync(PIN2)
    assert caught.value.code is C.SYNC_FAILED
    view = await stack.service.status()
    assert view["status"] == "ready" and view["pin"] == PIN.to_dict() and any("disk full" in line for line in view["diagnostics"])
    await stack.service.stop()


# ------------------------------------------------------------------ préconditions : aucune trace laissée

async def test_a_capability_that_is_not_ready_is_refused_before_anything_is_written(stack):
    stack.capability = "not_installed"
    with pytest.raises(StudioError) as caught:
        await stack.service.open(PIN)
    assert caught.value.code is C.RUNTIME_UNAVAILABLE and "not_installed" in caught.value.detail
    assert stack.runner.calls.count("launch") == 0 and stack.runner.calls.count("sync_work") == 0
    assert (await stack.service.status())["status"] == "stopped"


async def test_a_runner_that_cannot_run_node_says_why(stack):
    stack.runner.ready_reason = "node_missing: Node.js is no longer on PATH"
    with pytest.raises(StudioError) as caught:
        await stack.service.open(PIN)
    assert caught.value.code is C.RUNTIME_UNAVAILABLE and "node_missing" in caught.value.detail


async def test_an_unreadable_source_is_refused_and_leaves_the_state_stopped(stack):
    stack.unknown.add(PIN)
    with pytest.raises(StudioError) as caught:
        await stack.service.open(PIN)
    assert caught.value.code is C.SOURCE_UNAVAILABLE and caught.value.http_status == 404
    assert stack.runner.calls.count("launch") == 0 and (await stack.service.status())["status"] == "stopped"


async def test_a_provider_failure_keeps_its_real_cause(stack):
    class Boom(Exception):
        code = C.INVALID

    async def provide(pin):
        raise Boom("tampered version")
    stack.service._source = provide
    with pytest.raises(StudioError) as caught:
        await stack.service.open(PIN)
    assert caught.value.code is C.SOURCE_UNAVAILABLE and "tampered version" in caught.value.detail


# ------------------------------------------------------------------ échecs de démarrage, ports

async def test_a_start_failure_is_a_failed_view_with_the_log_not_an_http_error(stack):
    stack.runner.launch_errors = [StudioError(C.START_FAILED, "process_exited: boom")]
    stack.runner.log = ["Error: Cannot find module x"]
    view = await stack.service.open(PIN)
    assert view["status"] == "failed" and view["last_error_code"] == C.START_FAILED.value and view["url"] is None
    assert view["diagnostics"] == ["Error: Cannot find module x"]
    recovered = await stack.service.open(PIN)
    assert recovered["status"] == "ready" and recovered["last_error_code"] is None
    await stack.service.stop()


async def test_a_random_port_collision_is_retried_once_with_another_port(stack):
    stack.runner.launch_errors = [StudioError(C.PORT_UNAVAILABLE, "in use")]
    view = await stack.service.open(PIN)
    assert view["status"] == "ready" and stack.runner.launches == [None, None]
    assert "remotion_studio.port_retry" in stack.events.kinds()
    await stack.service.stop()


async def test_a_configured_port_is_never_silently_replaced():
    stack = Stack(port=45555)
    stack.runner.launch_errors = [StudioError(C.PORT_UNAVAILABLE, "port 45555 is already in use")]
    view = await stack.service.open(PIN)
    assert view["status"] == "failed" and view["last_error_code"] == C.PORT_UNAVAILABLE.value and view["port_mode"] == "configured"
    assert stack.runner.launches == [45555]
    ok = await stack.service.open(PIN)
    assert ok["status"] == "ready" and ok["port"] == 45555
    await stack.service.stop()


# ------------------------------------------------------------------ fermeture, redémarrage, disparition

async def test_close_stops_the_process_tree_and_keeps_the_work_recorded(stack):
    await stack.service.open(PIN)
    ref = next(iter(stack.runner.alive))
    stack.runner.saved = ("src/Scene.tsx",)
    view = await stack.service.close()
    assert view["status"] == "stopped" and view["url"] is None and stack.runner.stopped == [ref] and not stack.runner.alive
    assert view["work_copy"]["edits_saved"] == 1 and view["pin"] == PIN.to_dict(), "the last scene is remembered for restart"
    assert (await stack.service.close())["status"] == "stopped", "close is idempotent"


async def test_restart_stops_then_starts_on_the_same_scene(stack):
    await stack.service.open(PIN)
    old = set(stack.runner.alive)
    view = await stack.service.restart()
    assert view["status"] == "ready" and view["restarts"] == 1 and view["pin"] == PIN.to_dict()
    assert stack.runner.stopped and old.isdisjoint(stack.runner.alive) and len(stack.runner.alive) == 1
    await stack.service.stop()


async def test_restart_without_a_previous_scene_is_a_typed_refusal(stack):
    with pytest.raises(StudioError) as caught:
        await stack.service.restart()
    assert caught.value.code is C.NOT_RUNNING


async def test_a_vanished_process_becomes_failed_and_open_recovers(stack):
    await stack.service.open(PIN)
    stack.runner.alive.clear()
    view = await stack.service.status()
    assert view["status"] == "failed" and view["last_error_code"] == C.PROCESS_EXITED.value and view["url"] is None
    again = await stack.service.open(PIN)
    assert again["status"] == "ready"
    await stack.service.stop()


async def test_a_live_process_that_does_not_answer_is_killed_and_restarted(stack):
    await stack.service.open(PIN)
    first = set(stack.runner.alive)
    stack.runner.healthy = False
    view = await stack.service.open(PIN)
    assert stack.runner.stopped and first.isdisjoint(stack.runner.alive), "the unresponsive one was killed first"
    assert stack.runner.calls.count("launch") == 2 and view["status"] == "ready"
    await stack.service.stop()


# ------------------------------------------------------------------ inactivité

async def test_idle_timeout_stops_the_studio_and_says_why():
    stack = Stack(idle_timeout_s=120)
    await stack.service.open(PIN)
    stack.clock.now += 100
    await stack.service.tick()
    assert (await stack.service.status())["status"] == "ready"
    stack.clock.now += 30
    await stack.service.tick()
    view = await stack.service.status()
    assert view["status"] == "stopped" and view["stop_reason"] == "idle_timeout" and not stack.runner.alive
    assert "remotion_studio.idle_timeout" in stack.events.kinds()


async def test_activity_and_open_viewers_keep_the_studio_alive():
    stack = Stack(idle_timeout_s=120)
    await stack.service.open(PIN)
    stack.clock.now += 500
    stack.runner.activity_data = {"ws_open": 1, "last_ms": (stack.clock.now - 400) * 1000}
    await stack.service.tick()
    assert (await stack.service.status())["status"] == "ready", "a browser tab with an open socket is not idle"
    stack.runner.activity_data = {"ws_open": 0, "last_ms": (stack.clock.now - 10) * 1000}
    await stack.service.tick()
    assert (await stack.service.status())["status"] == "ready", "recent requests keep it alive"
    await stack.service.stop()


async def test_the_watch_task_runs_ticks_and_dies_with_the_studio():
    stack = Stack(idle_timeout_s=60, tick_s=0.01)
    await stack.service.open(PIN)
    stack.clock.now += 120
    for _ in range(100):
        await asyncio.sleep(0.01)
        if (await stack.service.status())["status"] == "stopped":
            break
    assert (await stack.service.status())["stop_reason"] == "idle_timeout"
    await asyncio.sleep(0.02)
    assert stack.service._watch is None


# ------------------------------------------------------------------ Core : démarrage, arrêt, changement de capacité

async def test_core_stop_never_leaves_an_orphan(stack):
    await stack.service.open(PIN)
    await stack.service.stop()
    assert not stack.runner.alive and (await stack.service.status())["stop_reason"] == "core_stopped"


async def test_reconcile_adopts_a_live_studio_and_fails_a_vanished_one():
    stack = Stack()
    await stack.service.open(PIN)
    saved = dict(stack.runner.state)
    ref = next(iter(stack.runner.alive))
    again = RemotionStudioService(stack.runner, source_provider=stack.provide, capability_status=lambda: "ready",
                                  diagnostics=stack.events, clock=stack.clock)
    view = await again.reconcile()
    assert view["status"] == "ready" and "remotion_studio.adopted" in stack.events.kinds()
    stack.runner.alive.clear()
    stack.runner.state = saved
    view = await RemotionStudioService(stack.runner, source_provider=stack.provide, capability_status=lambda: "ready",
                                       clock=stack.clock).reconcile()
    assert view["status"] == "failed" and view["last_error_code"] == C.PROCESS_EXITED.value and ref not in stack.runner.alive
    await again.stop()


async def test_an_unreadable_state_file_starts_stopped_and_is_reported():
    stack = Stack()
    stack.runner.state = {"schema": 9}
    assert (await stack.service.status())["status"] == "stopped"
    assert "remotion_studio.state_unreadable" in stack.events.kinds()


async def test_a_capability_change_stops_the_studio_first(stack):
    await stack.service.open(PIN)
    await asyncio.to_thread(stack.service.stop_for_capability_change)
    assert not stack.runner.alive
    assert (await stack.service.status())["stop_reason"] == "capability_change"


async def test_a_second_operation_while_one_runs_is_busy(stack):
    gate = asyncio.Event()
    original = stack.provide

    async def slow(pin):
        await gate.wait()
        return await original(pin)
    stack.service._source = slow
    task = asyncio.create_task(stack.service.open(PIN))
    await asyncio.sleep(0.05)
    with pytest.raises(StudioError) as caught:
        await stack.service.open(PIN2)
    assert caught.value.code is C.BUSY
    gate.set()
    assert (await task)["status"] == "ready"
    await stack.service.stop()


async def test_work_edited_outside_jarvis_is_reported_and_saved_before_a_sync(stack):
    await stack.service.open(PIN)
    stack.runner.modified = ("src/Scene.tsx",)
    assert (await stack.service.status())["work_copy"]["modified_files"] == ["src/Scene.tsx"]
    stack.runner.edits_on_sync = ("src/Scene.tsx",)
    view = await stack.service.sync(PIN2)
    assert view["work_copy"]["edits_saved"] == 1 and any("saved aside" in line for line in view["diagnostics"])
    await stack.service.stop()
