"""Lanceur unique du produit installé (presentation-edition-v1 Slice 07, `docs/product-install.md` › *Launcher*).

Enfants, Job Objects, sondes HTTP et navigateur sont des doubles : ordre de démarrage, `-B`, une seule ouverture de la
page, relances bornées, arrêt propre sans orphelin, refus visibles et durables, instance unique.
"""

from __future__ import annotations

import json
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
