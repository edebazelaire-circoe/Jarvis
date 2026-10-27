"""Lanceur unique du produit installé (presentation-edition-v1 Slice 07, `docs/product-install.md` › *Launcher*).

Enfants, Job Objects, sondes HTTP et navigateur sont des doubles : ordre de démarrage, `-B`, une seule ouverture de la
page, relances bornées, arrêt propre sans orphelin, refus visibles et durables, instance unique.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jarvis.runtime import product_launcher as L


class FakeProcess:
    next_pid = 1000

    def __init__(self, argv, exit_after_polls: int | None = None, code: int = 1) -> None:
        FakeProcess.next_pid += 1
        self.pid = FakeProcess.next_pid
        self.argv = argv
        self.returncode = None
        self._polls = 0
        self._exit_after = exit_after_polls
        self._code = code
        self.terminated = False

    def poll(self):
        self._polls += 1
        if self.returncode is None and self._exit_after is not None and self._polls > self._exit_after:
            self.returncode = self._code
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class FakeTree:
    creationflags = 0x4
    made: list["FakeTree"] = []

    def __init__(self) -> None:
        self.attached = None
        self.terminated = False
        FakeTree.made.append(self)

    def attach_and_resume(self, pid):
        self.attached = pid

    def terminate(self):
        self.terminated = True

    def close_if_empty(self):
        return True


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def plan(tmp_path: Path, *, voice: bool = True) -> L.LaunchPlan:
    roles = [L.Role("core", ("core",), True), L.Role("ui", ("control-center",), True, {"JARVIS_OPEN_BROWSER": "0"})]
    if voice:
        roles.append(L.Role("voice", ("voice",), False))
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "core.token").write_text("tok", encoding="utf-8")
    return L.LaunchPlan(python="X:/pkg/runtime/python/pythonw.exe", runtime_root=runtime, core_url="http://127.77.0.1:40653",
                        ui_url="http://127.0.0.1:40654/", token_file=runtime / "core.token", roles=roles,
                        env={"PATH": "C:/Windows"}, start_timeout_s=30.0)


def launcher(tmp_path, *, behaviours=None, probe=None, stop_after: float | None = None, voice=True):
    FakeTree.made = []
    clock = Clock()
    spawned: list[FakeProcess] = []
    notices: list[str] = []
    opened: list[str] = []
    behaviours = dict(behaviours or {})

    def spawn(argv, **kwargs):
        role = argv[-1]
        options = behaviours.get(role)
        if isinstance(options, list):
            options = options.pop(0) if options else None
        process = FakeProcess(argv, **(options or {}))
        process.kwargs = kwargs
        spawned.append(process)
        return process

    p = plan(tmp_path, voice=voice)

    def sleep(seconds):
        clock.sleep(seconds)
        if stop_after is not None and clock.now >= stop_after:
            (p.runtime_root / L.STOP_FILE).write_text("now", encoding="utf-8")

    log = L.LauncherLog(p.runtime_root / "logs" / "launcher.log")
    instance = L.Launcher(p, log=log, notify=lambda title, text: notices.append(text), open_url=opened.append,
                          spawn=spawn, tree_factory=FakeTree, clock=clock, sleep=sleep,
                          probe=probe or (lambda url, headers=None: (True, b"{}")))
    return instance, spawned, notices, opened


def events(tmp_path: Path) -> list[dict]:
    path = tmp_path / "runtime" / "logs" / "launcher.log"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_core_then_control_center_then_voice_each_with_dash_b_contained_and_the_page_opened_once(tmp_path):
    instance, spawned, notices, opened = launcher(tmp_path, stop_after=2.0)
    assert instance.run() == 0
    assert [p.argv[-1] for p in spawned] == ["core", "control-center", "voice"]
    for process in spawned:
        assert process.argv[:4] == ["X:/pkg/runtime/python/pythonw.exe", "-B", "-m", "jarvis"]
        assert process.kwargs["creationflags"] & 0x4  # suspendu jusqu'à son entrée dans le Job
    assert spawned[1].kwargs["env"]["JARVIS_OPEN_BROWSER"] == "0"
    assert [tree.attached for tree in FakeTree.made] == [p.pid for p in spawned]
    assert opened == ["http://127.0.0.1:40654/"] and notices == []
    # Arrêt : Control Center et Voix d'abord, Core en dernier ; chaque Job fermé ; état publié effacé.
    stopped = [row["data"]["role"] for row in events(tmp_path) if row["kind"] == "child_stopped"]
    assert stopped == ["ui", "voice", "core"] and all(tree.terminated for tree in FakeTree.made)
    assert not (tmp_path / "runtime" / L.STATE_FILE).exists() and not (tmp_path / "runtime" / L.STOP_FILE).exists()


def test_core_health_is_read_with_its_token(tmp_path):
    seen = []

    def probe(url, headers=None):
        seen.append((url, headers))
        return True, b"{}"

    instance, *_ = launcher(tmp_path, probe=probe, stop_after=1.0)
    instance.run()
    assert seen[0] == ("http://127.77.0.1:40653/v1/health", {"Authorization": "Bearer tok"})
    assert seen[1][0] == "http://127.0.0.1:40654/api/status"


def test_a_core_that_dies_at_start_is_said_visibly_and_durably_with_the_port_cause(tmp_path):
    instance, spawned, notices, opened = launcher(tmp_path, behaviours={"core": {"exit_after_polls": 0}},
                                                  probe=lambda url, headers=None: (False, OSError("refused")))
    (tmp_path / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtime" / "logs" / "core.log").write_text(
        "RuntimeError: Jarvis Core cannot bind 127.77.0.1:40653: [Errno 10048] in use\n", encoding="utf-8")
    assert instance.run() == 1
    assert len(notices) == 1 and "port" in notices[0] and "launcher.log" in notices[0]
    failed = [row for row in events(tmp_path) if row["kind"] == "failed"][0]
    assert failed["level"] == "error" and failed["data"]["code"] == "child_exited"
    assert opened == [] and [p.argv[-1] for p in spawned] == ["core"]


def test_a_start_that_never_answers_times_out_with_a_deadline(tmp_path):
    instance, spawned, notices, _ = launcher(tmp_path, probe=lambda url, headers=None: (False, OSError("refused")))
    assert instance.run() == 1
    assert "30 secondes" in notices[0] and spawned[0].terminated


def test_an_essential_child_is_restarted_then_a_crash_loop_stops_everything(tmp_path):
    # Le Control Center meurt après sa mise en route, puis à chaque relance : relances bornées, puis arrêt complet.
    crash = {"exit_after_polls": 1}
    instance, spawned, notices, _ = launcher(tmp_path, voice=False,
                                             behaviours={"control-center": [{"exit_after_polls": 2}, crash, crash, crash]})
    assert instance.run() == 1
    assert len([p for p in spawned if p.argv[-1] == "control-center"]) == 1 + L.MAX_RESTARTS
    assert "redémarrait sans cesse" in notices[0]
    assert all(p.returncode is not None for p in spawned)


def test_the_voice_is_abandoned_after_its_restarts_without_stopping_jarvis(tmp_path):
    crash = {"exit_after_polls": 0}
    instance, spawned, notices, _ = launcher(tmp_path, behaviours={"voice": [crash] * 10}, stop_after=5.0)
    assert instance.run() == 0 and notices == []
    assert len([p for p in spawned if p.argv[-1] == "voice"]) == 1 + L.MAX_RESTARTS
    assert any(row["kind"] == "child_abandoned" for row in events(tmp_path))


def test_one_instance_per_home_and_a_second_click_reopens_the_page(tmp_path):
    runtime = tmp_path / "runtime"
    first = L.InstanceLock(runtime / L.LOCK_FILE)
    assert first.acquire()
    second = L.InstanceLock(runtime / L.LOCK_FILE)
    assert not second.acquire()
    (runtime / L.STATE_FILE).write_text(json.dumps({"ui_url": "http://127.0.0.1:40654/"}), encoding="utf-8")
    opened = []
    assert L.reopen_running(runtime, open_url=opened.append) and opened == ["http://127.0.0.1:40654/"]
    (runtime / L.STATE_FILE).write_text(json.dumps({"ui_url": "https://evil.example/"}), encoding="utf-8")
    assert not L.reopen_running(runtime, open_url=opened.append)
    first.release()
    assert second.acquire()
    second.release()


def test_a_refusal_before_any_home_is_shown_and_written_to_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(L.tempfile, "gettempdir", lambda: str(tmp_path))

    def broken(environ=None):
        from jarvis.domain.errors import ConfigurationError

        raise ConfigurationError("produit installé : LOCALAPPDATA absent, maison du produit introuvable")

    monkeypatch.setattr(L, "detect_installation", broken)
    notices = []
    assert L.main(notify=lambda title, text: notices.append(text)) == 1
    assert "LOCALAPPDATA absent" in notices[0]
    row = json.loads((tmp_path / L.FALLBACK_LOG).read_text(encoding="utf-8").splitlines()[-1])
    assert row["kind"] == "launcher.refused" and row["exception_type"] == "ConfigurationError"


def test_ensure_home_creates_the_three_folders_of_the_installed_product(tmp_path):
    from jarvis.installation import Installation, InstallMode, ProductHome

    home = ProductHome(tmp_path / "CIRCOE" / "Jarvis")
    assert sorted(L.ensure_home(Installation(InstallMode.INSTALLED, tmp_path, home))) == ["config", "data", "runtime"]
    assert L.ensure_home(Installation(InstallMode.INSTALLED, tmp_path, home)) == []
    assert L.ensure_home(Installation(InstallMode.DEVELOPMENT, tmp_path)) == []


@pytest.mark.parametrize("value", ["0", "off", "false"])
def test_voice_can_be_left_out(monkeypatch, value, tmp_path):
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "data"))
    built = L.plan_from_environment({"JARVIS_LAUNCH_VOICE": value, "JARVIS_UI_PORT": "40654", "JARVIS_OPEN_BROWSER": "0"})
    assert [role.name for role in built.roles] == ["core", "ui"] and built.open_browser is False
    assert built.ui_url == "http://127.0.0.1:40654/"


class CleanProcess(FakeProcess):
    """Un rôle qui lit la demande d'arrêt propre (`JARVIS_STOP_REQUEST_FILE`) et sort de lui-même."""

    def poll(self):
        stop = ((getattr(self, "kwargs", {}) or {}).get("env") or {}).get("JARVIS_STOP_REQUEST_FILE")
        if self.returncode is None and stop and Path(stop).exists():
            self.returncode = 0
        return super().poll()


def test_quit_asks_core_and_control_center_to_stop_cleanly_before_any_terminate(tmp_path):
    """Revue m6 : « Quitter JARVIS » était un `TerminateProcess` immédiat de Core et du Control Center."""

    instance, spawned, notices, _ = launcher(tmp_path, stop_after=2.0)
    original = instance.spawn

    def spawn(argv, **kwargs):
        process = original(argv, **kwargs)
        if argv[-1] in ("core", "control-center"):
            process.__class__ = CleanProcess
        return process

    instance.spawn = spawn
    assert instance.run() == 0 and notices == []
    by_role = {p.argv[-1]: p for p in spawned}
    assert by_role["core"].kwargs["env"]["JARVIS_STOP_REQUEST_FILE"].endswith("stop-core.request")
    assert by_role["control-center"].kwargs["env"]["JARVIS_STOP_REQUEST_FILE"].endswith("stop-ui.request")
    assert "JARVIS_STOP_REQUEST_FILE" not in by_role["voice"].kwargs["env"]
    assert not by_role["core"].terminated and not by_role["control-center"].terminated
    assert by_role["voice"].terminated  # la Voix ne lit pas la demande : arrêtée comme avant
    clean = [row["data"]["role"] for row in events(tmp_path) if row["kind"] == "child_stopped_cleanly"]
    assert clean == ["ui", "core"]
    assert not list((tmp_path / "runtime").glob("stop-*.request"))


def test_a_role_that_ignores_the_stop_request_is_terminated_after_the_grace_delay(tmp_path):
    instance, spawned, notices, _ = launcher(tmp_path, stop_after=2.0, voice=False)
    assert instance.run() == 0
    assert all(p.terminated for p in spawned)
    timeouts = [row for row in events(tmp_path) if row["kind"] == "child_stop_timeout"]
    assert [row["data"]["role"] for row in timeouts] == ["ui", "core"] and timeouts[0]["level"] == "warning"


def test_a_stale_stop_request_never_stops_the_next_launch(tmp_path):
    instance, spawned, _notices, _ = launcher(tmp_path, stop_after=2.0, voice=False)
    (tmp_path / "runtime" / "stop-core.request").write_text("old", encoding="utf-8")
    instance.start_role(instance.plan.roles[0])
    assert not (tmp_path / "runtime" / "stop-core.request").exists()


def test_launch_refuses_a_development_checkout_instead_of_using_its_ports(tmp_path, monkeypatch):
    """Revue m5 / QA runtime m4 : sans marqueur, `launch` démarrait sur les ports du JARVIS de développement."""

    from jarvis.installation import Installation, InstallMode

    monkeypatch.setattr(L.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(L, "detect_installation", lambda environ=None: Installation(InstallMode.DEVELOPMENT, tmp_path))
    monkeypatch.setattr(L, "plan_from_environment", lambda environ=None: pytest.fail("no plan without a marker"))
    notices = []
    assert L.main(notify=lambda title, text: notices.append(text)) == 1
    assert "n'est pas un JARVIS installé" in notices[0] and "menu Démarrer" in notices[0]
    row = json.loads((tmp_path / L.FALLBACK_LOG).read_text(encoding="utf-8").splitlines()[-1])
    assert row["code"] == "not_installed_product"


def test_run_until_stop_requested_returns_on_the_request_and_cancels_the_main_wait(tmp_path):
    import asyncio

    from jarvis.runtime.stop_request import run_until_stop_requested

    stop = tmp_path / "stop.request"
    cancelled = []

    async def forever():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def scenario():
        asyncio.get_running_loop().call_later(0.1, lambda: stop.write_text("now", encoding="utf-8"))
        return await run_until_stop_requested(forever(), stop, poll_s=0.02)

    assert asyncio.run(scenario()) is True and cancelled == [True]

    async def finishes():
        return 7

    assert asyncio.run(run_until_stop_requested(finishes(), stop.with_name("never"), poll_s=0.02)) is False

    async def fails():
        raise RuntimeError("core died")

    with pytest.raises(RuntimeError, match="core died"):
        asyncio.run(run_until_stop_requested(fails(), None))


# ---------------------------------------------------------------------- identité publiée (S10, I-009 point 2)


def test_the_published_state_carries_the_launcher_identity_with_its_creation_time(tmp_path):
    from jarvis.adapters import process_tree

    instance, _spawned, _notices, _opened = launcher(tmp_path, stop_after=None)
    instance.write_state()
    state = json.loads((tmp_path / "runtime" / L.STATE_FILE).read_text(encoding="utf-8"))
    assert state["pid"] == os.getpid()
    assert state["process_ref"] == process_tree.make_process_ref(os.getpid()) != ""
    assert L.launcher_alive(state, pid_alive=lambda pid: False) is True  # vérifié par la vraie heure de création


def test_a_reused_pid_is_never_taken_for_a_running_launcher(tmp_path):
    from jarvis.adapters import process_tree

    mine = process_tree.make_process_ref(os.getpid())
    pid, started = process_tree.parse_process_ref(mine)
    reused = {"pid": pid, "process_ref": f"{pid}:{int(started) - 1}"}  # même PID, autre processus (heure différente)
    assert L.launcher_alive(reused, pid_alive=lambda _pid: True) is False
    # État écrit avant la Slice 10, ou référence illisible / d'un autre PID : le PID seul fait foi (défaut sûr).
    assert L.launcher_alive({"pid": 77}, pid_alive=lambda p: p == 77) is True
    assert L.launcher_alive({"pid": 77, "process_ref": "garbage"}, pid_alive=lambda p: p == 77) is True
    assert L.launcher_alive({"pid": 77, "process_ref": "78:123"}, pid_alive=lambda p: p == 77) is True
    for bad in (None, [], {"pid": "77"}, {"pid": True}, {"pid": 0}, {}):
        assert L.launcher_alive(bad, pid_alive=lambda _pid: True) is False
