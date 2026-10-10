"""Hôte des capacités locales : manifeste, machine à états, installation unique, échecs typés, isolation des plugins MCP distants
(Slice 03 de jarvis-remotion-presentation-integration ; `docs/local-capabilities.md`). Faux runner : ni réseau, ni npm, ni processus."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.core.local_capability_host import LocalCapabilityHost, UnavailableRunner
from jarvis.domain import local_capabilities as lc
from jarvis.domain.local_capabilities import (
    CapabilityStatus as S, InstallStatus, LocalCapabilityError, LocalCapabilityErrorCode as C, ProcessStatus, new_manifest,
)
from jarvis.domain.mcp_plugins import McpErrorCode

PINS = {"demo-runtime": "1.2.3", "demo-player": "1.2.3"}
T0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class FakeRunner:
    """Journalise chaque appel ; chaque échec se déclenche par un attribut."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.missing: tuple[str, ...] = ()
        self.install_error: Exception | None = None
        self.installed_override: dict[str, str] | None = None
        self.verify_error: Exception | None = None
        self.start_error: Exception | None = None
        self.stop_error: Exception | None = None
        self.remove_error: Exception | None = None
        self.alive: set[str] = set()
        self.next_pid = 100

    def check_requirements(self, manifest):
        self.calls.append("check")
        return self.missing

    def install(self, manifest, runtime_dir):
        self.calls.append("install")
        assert Path(runtime_dir).is_dir()
        if self.install_error:
            raise self.install_error
        (Path(runtime_dir) / "marker.txt").write_text("x", encoding="utf-8")
        return self.installed_override if self.installed_override is not None else dict(manifest.components)

    def verify(self, manifest, runtime_dir, installed):
        self.calls.append("verify")
        if self.verify_error:
            raise self.verify_error

    def start(self, manifest, runtime_dir):
        self.calls.append("start")
        if self.start_error:
            raise self.start_error
        self.next_pid += 1
        self.alive.add(str(self.next_pid))
        return str(self.next_pid)

    def stop(self, process_ref):
        self.calls.append("stop")
        if self.stop_error:
            raise self.stop_error
        self.alive.discard(process_ref)

    def is_alive(self, process_ref):
        return process_ref in self.alive

    def remove(self, manifest, runtime_dir):
        self.calls.append("remove")
        if self.remove_error:
            raise self.remove_error


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, dict(data or {})))


def manifest(pins=None):
    return new_manifest(capability_id="demo", display_name="Demo", components=pins or PINS, requirements=[("node", "20.0.0")])


@pytest.fixture
def env(tmp_path):
    runner, sink = FakeRunner(), Sink()
    store = FileLocalCapabilityStore(tmp_path)
    host = LocalCapabilityHost(store, runner=runner, manifests={"demo": manifest()}, clock=Clock(), diagnostics=sink)
    return host, runner, store, sink, tmp_path


# ---------------------------------------------------------------- manifeste

@pytest.mark.parametrize("version", ["^1.2.3", "latest", "1.2", "~1.0.0", "*", ">=1.0.0", ""])
def test_a_manifest_refuses_anything_but_an_exact_version(version):
    with pytest.raises(LocalCapabilityError) as err:
        new_manifest(capability_id="demo", display_name="Demo", components={"a": version})
    assert err.value.code is C.INVALID


@pytest.mark.parametrize("kwargs", [
    {"capability_id": "jarvis-remotion"}, {"capability_id": "Bad Id"}, {"display_name": " "}, {"components": {}},
    {"entrypoint": "node run.js"}, {"requirements": [("python", "3.0.0")]},
])
def test_a_manifest_refuses_reserved_ids_commands_and_unknown_requirements(kwargs):
    base = dict(capability_id="demo", display_name="Demo", components={"a": "1.0.0"})
    with pytest.raises(LocalCapabilityError) as err:
        new_manifest(**{**base, **kwargs})
    assert err.value.code is C.INVALID


# ------------------------------------------------------ machine à états pure

def test_illegal_transitions_are_refused_and_the_derived_status_follows_the_axes():
    now = T0
    st = lc.initial_state("demo", now=now)
    assert lc.derive_status(st) is S.NOT_INSTALLED
    for bad in (InstallStatus.INSTALLED, InstallStatus.FAILED, InstallStatus.UNINSTALLING):
        with pytest.raises(LocalCapabilityError) as err:
            lc.transition_install(st, bad, now=now)
        assert err.value.code is C.INTERNAL_ERROR
    with pytest.raises(LocalCapabilityError):  # un processus exige une capacité installée
        lc.transition_process(st, ProcessStatus.STARTING, now=now)
    st = lc.transition_install(st, InstallStatus.INSTALLING, now=now)
    assert lc.derive_status(st) is S.INSTALLING
    st = lc.transition_install(st, InstallStatus.INSTALLED, now=now, components=PINS)
    assert lc.derive_status(st) is S.READY
    st = lc.transition_process(lc.transition_process(st, ProcessStatus.STARTING, now=now), ProcessStatus.RUNNING, now=now, process_ref="7")
    assert lc.derive_status(st) is S.RUNNING
    assert lc.derive_status(lc.with_health(st, lc.Health.UNHEALTHY, now=now, error_code=C.HEALTH_FAILED)) is S.REPAIR_NEEDED
    with pytest.raises(LocalCapabilityError):  # désactivé => pas de processus actif
        lc.with_enabled(st, False, now=now)


def test_a_corrupted_stored_state_is_refused_not_guessed():
    with pytest.raises(LocalCapabilityError) as err:
        lc.state_from_payload({"capability_id": "demo", "install_status": "bogus"})
    assert err.value.code is C.STORE_FAILED
    with pytest.raises(LocalCapabilityError):  # processus sans installation
        lc.state_from_payload({"capability_id": "demo", "install_status": "not_installed", "process_status": "running",
                               "health": "unknown", "enabled": True})


# ------------------------------------------------------------ install unique

def test_install_runs_once_and_is_idempotent(env):
    host, runner, store, sink, _ = env
    first = host.install("demo")
    assert first["status"] == "ready" and first["health"] == "healthy" and first["installed"] == PINS
    again = host.install("demo")
    assert runner.calls.count("install") == 1 and again["install_attempts"] == 1
    assert any(k == "local_capability.install.noop" for k, _, _ in sink.events)
    # un nouvel hôte sur les mêmes données ne réinstalle pas non plus
    other = LocalCapabilityHost(store, runner=runner, manifests={"demo": manifest()}, clock=Clock())
    assert other.install("demo")["install_attempts"] == 1 and runner.calls.count("install") == 1


def test_changed_pins_need_an_explicit_update_never_an_implicit_one(env):
    host, runner, *_ = env
    host.install("demo")
    host.register(manifest({"demo-runtime": "1.3.0", "demo-player": "1.3.0"}))
    assert host.status("demo")["update_required"] is True
    with pytest.raises(LocalCapabilityError) as err:
        host.install("demo")
    assert err.value.code is C.UPDATE_REQUIRED
    with pytest.raises(LocalCapabilityError) as err:
        host.start("demo")
    assert err.value.code is C.UPDATE_REQUIRED
    done = host.update("demo")
    assert done["installed"] == {"demo-runtime": "1.3.0", "demo-player": "1.3.0"} and done["update_required"] is False
    assert runner.calls.count("install") == 2


def test_update_stops_the_running_process_first(env):
    host, runner, *_ = env
    host.install("demo")
    host.start("demo")
    host.register(manifest({"demo-runtime": "2.0.0", "demo-player": "2.0.0"}))
    view = host.update("demo")
    assert view["process_status"] == "stopped" and view["status"] == "ready" and not runner.alive
    assert runner.calls.index("stop") < len(runner.calls) - 1 and runner.calls.count("install") == 2


# -------------------------------------------------------- échecs => statut typé

def test_requirement_missing_is_a_typed_failed_install_without_running_the_installer(env):
    host, runner, *_ = env
    runner.missing = ("node 18.0.0 < 20.0.0",)
    view = host.install("demo")
    assert view["status"] == "install_failed" and view["last_error_code"] == C.REQUIREMENT_MISSING.value
    assert "node" in view["last_error_detail"] and "install" not in runner.calls and view["installed"] == {}


def test_installer_failure_is_typed_logged_and_retryable(env):
    host, runner, _, sink, _ = env
    runner.install_error = RuntimeError("npm ERR! network\nsecond line")
    view = host.install("demo")
    assert view["status"] == "install_failed" and view["last_error_code"] == C.INSTALL_FAILED.value
    assert "\n" not in view["last_error_detail"]
    assert any(level == "error" and kind == "local_capability.install.failed" for kind, level, _ in sink.events)
    runner.install_error = None
    ok = host.install("demo")
    assert ok["status"] == "ready" and ok["install_attempts"] == 2 and ok["last_error_code"] is None


def test_runner_reporting_other_versions_than_the_pins_fails_the_install(env):
    host, runner, *_ = env
    runner.installed_override = {"demo-runtime": "9.9.9", "demo-player": "1.2.3"}
    assert host.install("demo")["last_error_code"] == C.INSTALL_FAILED.value


def test_default_runner_executes_nothing_and_says_so(tmp_path):
    host = LocalCapabilityHost(FileLocalCapabilityStore(tmp_path), manifests={"demo": manifest()}, clock=Clock())
    assert isinstance(host._runner, UnavailableRunner)
    view = host.install("demo")
    assert view["status"] == "install_failed" and view["last_error_code"] == C.RUNNER_UNAVAILABLE.value
    assert list((tmp_path / "local_capabilities" / "demo").glob("runtime/*")) == []


def test_unhealthy_files_give_repair_needed_then_repair_reinstalls(env):
    host, runner, *_ = env
    host.install("demo")
    runner.verify_error = LocalCapabilityError(C.HEALTH_FAILED, "bundle missing")
    view = host.check_health("demo")
    assert view["status"] == "repair_needed" and view["last_error_code"] == C.HEALTH_FAILED.value
    plain_install = runner.install

    def reinstall(manifest, runtime_dir):  # the reinstall restores the files, so the probe passes again
        runner.verify_error = None
        return plain_install(manifest, runtime_dir)

    runner.install = reinstall
    fixed = host.repair("demo")
    assert fixed["status"] == "ready" and fixed["health"] == "healthy" and runner.calls.count("install") == 2


def test_repair_of_a_healthy_capability_is_a_noop(env):
    host, runner, *_ = env
    host.install("demo")
    assert host.repair("demo")["status"] == "ready" and runner.calls.count("install") == 1


def test_repair_after_a_failed_install_retries(env):
    host, runner, *_ = env
    runner.install_error = RuntimeError("boom")
    host.install("demo")
    runner.install_error = None
    assert host.repair("demo")["status"] == "ready"


def test_operations_that_need_an_installation_refuse_without_one(env):
    host, *_ = env
    for op in (host.start, host.check_health, host.update, host.repair):
        with pytest.raises(LocalCapabilityError) as err:
            op("demo")
        assert err.value.code is C.NOT_INSTALLED
    with pytest.raises(LocalCapabilityError) as err:
        host.status("nope")
    assert err.value.code is C.UNKNOWN


# ----------------------------------------------------------------- processus

def test_start_stop_lifecycle_is_idempotent(env):
    host, runner, *_ = env
    host.install("demo")
    assert host.start("demo")["status"] == "running"
    assert host.start("demo")["status"] == "running" and runner.calls.count("start") == 1
    assert host.stop("demo")["status"] == "ready" and not runner.alive
    assert host.stop("demo")["status"] == "ready" and runner.calls.count("stop") == 1


def test_start_failure_is_a_typed_crash(env):
    host, runner, *_ = env
    host.install("demo")
    runner.start_error = RuntimeError("EADDRINUSE")
    view = host.start("demo")
    assert view["status"] == "crashed" and view["last_error_code"] == C.START_FAILED.value
    runner.start_error = None
    assert host.start("demo")["status"] == "running"


def test_a_vanished_process_is_detected_by_the_health_check(env):
    host, runner, *_ = env
    host.install("demo")
    host.start("demo")
    runner.alive.clear()
    view = host.check_health("demo")
    assert view["status"] == "crashed" and view["last_error_code"] == C.PROCESS_EXITED.value
    assert host.start("demo")["status"] == "running"


def test_a_stop_failure_is_visible_and_not_hidden_as_stopped(env):
    host, runner, *_ = env
    host.install("demo")
    host.start("demo")
    runner.stop_error = RuntimeError("access denied")
    view = host.stop("demo")
    assert view["status"] == "crashed" and view["last_error_code"] == C.STOP_FAILED.value
    runner.stop_error = None
    assert host.stop("demo")["status"] == "ready"


def test_disable_stops_the_process_and_blocks_start_enable_does_not_start(env):
    host, *_ = env
    host.install("demo")
    host.start("demo")
    assert host.disable("demo")["status"] == "disabled"
    with pytest.raises(LocalCapabilityError) as err:
        host.start("demo")
    assert err.value.code is C.DISABLED
    assert host.enable("demo")["status"] == "ready"


def test_uninstall_stops_removes_and_keeps_the_record(env):
    host, runner, _, _, root = env
    host.install("demo")
    host.start("demo")
    view = host.uninstall("demo")
    assert view["status"] == "not_installed" and view["installed"] == {} and not runner.alive
    assert host.uninstall("demo")["status"] == "not_installed" and runner.calls.count("remove") == 1
    assert (root / "local_capabilities" / "demo" / "state.json").is_file()


def test_uninstall_failure_is_typed(env):
    host, runner, *_ = env
    host.install("demo")
    runner.remove_error = RuntimeError("EBUSY")
    view = host.uninstall("demo")
    assert view["status"] == "install_failed" and view["last_error_code"] == C.UNINSTALL_FAILED.value
    runner.remove_error = None
    assert host.uninstall("demo")["status"] == "not_installed"


def test_a_second_operation_on_a_busy_capability_is_refused(env):
    host, runner, *_ = env
    seen = []

    def reenter(manifest, runtime_dir):
        try:
            host.start("demo")
        except LocalCapabilityError as exc:
            seen.append(exc.code)
        return dict(manifest.components)

    runner.install = reenter
    assert host.install("demo")["status"] == "ready" and seen == [C.BUSY]
    assert host.start("demo")["status"] == "running"  # le verrou est bien relâché


# ------------------------------------------------------------- redémarrage

def test_reconcile_marks_interrupted_installs_and_dead_processes(env):
    host, runner, store, _, _ = env
    host.install("demo")
    store.save(lc.transition_install(store.load("demo"), InstallStatus.INSTALLING, now=T0))
    [view] = host.reconcile()
    assert view["status"] == "install_failed" and view["last_error_code"] == C.INSTALL_INTERRUPTED.value
    assert host.install("demo")["status"] == "ready"  # reprise après interruption
    host.start("demo")
    runner.alive.clear()
    [view] = host.reconcile()
    assert view["status"] == "crashed" and view["last_error_code"] == C.PROCESS_EXITED.value
    assert runner.calls.count("install") == 2 and runner.calls.count("start") == 1  # reconcile n'installe ni ne lance rien


def test_a_corrupt_state_file_is_reported_not_replaced(env):
    host, runner, store, sink, root = env
    host.install("demo")
    path = root / "local_capabilities" / "demo" / "state.json"
    path.write_text("{not json", encoding="utf-8")
    other = LocalCapabilityHost(store, runner=runner, manifests={"demo": manifest()}, clock=Clock(), diagnostics=sink)
    with pytest.raises(LocalCapabilityError) as err:
        other.status("demo")
    assert err.value.code is C.STORE_FAILED
    assert other.reconcile() == [] and any(k == "local_capability.reconcile.failed" for k, _, _ in sink.events)
    assert path.read_text(encoding="utf-8") == "{not json"


# ----------------------------------------------- stockage et vue publique

def test_storage_is_under_the_data_root_and_the_view_leaks_no_path_or_secret(env):
    host, _, _, _, root = env
    view = host.install("demo")
    assert (root / "local_capabilities" / "demo" / "runtime" / "marker.txt").is_file()
    text = json.dumps(view)
    assert str(root) not in text and "credential" not in text and "endpoint" not in text
    assert view["family"] == "local_capability" and view["transport"] == "local_process"


def test_the_store_refuses_a_state_filed_under_another_id(env):
    host, _, store, _, root = env
    host.install("demo")
    other = root / "local_capabilities" / "other"
    other.mkdir()
    (other / "state.json").write_text((root / "local_capabilities" / "demo" / "state.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        store.load("other")
    assert err.value.code is C.STORE_FAILED
    assert store.list_ids() == ("demo", "other")


# ------------------------------------- aucune interférence avec les plugins MCP

def test_local_capability_codes_and_transport_never_collide_with_the_remote_plugin_contract():
    from jarvis.domain import mcp_plugins as mp
    assert mp.TRANSPORT_STREAMABLE_HTTP == "streamable_http"
    assert not {e.value for e in C} & {e.value for e in McpErrorCode}
    assert all(e.value.startswith("local_capability_") for e in C)
    with pytest.raises(LocalCapabilityError):  # l'espace `jarvis-*` reste réservé aux serveurs natifs
        new_manifest(capability_id="jarvis-x", display_name="x", components={"a": "1.0.0"})


def test_the_local_stack_imports_nothing_from_the_remote_plugin_stack():
    import jarvis.adapters.file_local_capability_store as store_mod
    import jarvis.core.local_capability_host as host_mod
    import jarvis.domain.local_capabilities as dom
    import jarvis.ports.local_capabilities as port
    forbidden = ("mcp_plugin", "credential_vault", "mcp_oauth", "remote_mcp", "mcp_endpoint", "dpapi", "sqlite_state")
    for mod in (host_mod, store_mod, dom, port):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imported += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in imported if any(f in m for f in forbidden)], (mod.__name__, imported)


# ------------------------------------------------------------ rework QA (B1, P1-P5)

def _raising_is_alive(runner):
    def boom(process_ref):
        raise OSError("probe broke")
    runner.is_alive = boom


@pytest.mark.parametrize("op", ["stop", "disable", "uninstall", "update"])
def test_an_is_alive_that_raises_never_skips_the_stop_of_a_possibly_live_child(env, op):
    host, runner, _, sink, root = env
    host.install("demo")
    host.start("demo")
    _raising_is_alive(runner)
    if op == "update":
        host.register(manifest({"demo-runtime": "2.0.0", "demo-player": "2.0.0"}))
    host_op = getattr(host, op)
    view = host_op("demo")
    assert runner.calls.count("stop") == 1, "runner.stop must be attempted when liveness is unknown"
    assert view["process_status"] == "stopped"
    assert any(k == "local_capability.runner_error" and level == "warning" for k, level, _ in sink.events)


@pytest.mark.parametrize("op", ["stop", "disable", "uninstall", "update"])
def test_when_the_forced_stop_fails_the_runtime_is_kept_and_stop_failed_is_reported(env, op):
    host, runner, _, _, root = env
    host.install("demo")
    host.start("demo")
    _raising_is_alive(runner)
    runner.stop_error = RuntimeError("access denied")
    if op == "update":
        host.register(manifest({"demo-runtime": "2.0.0", "demo-player": "2.0.0"}))
    view = getattr(host, op)("demo")
    assert view["status"] == "crashed" and view["last_error_code"] == C.STOP_FAILED.value
    assert "remove" not in runner.calls and runner.calls.count("install") == 1
    assert (root / "local_capabilities" / "demo" / "runtime" / "marker.txt").is_file()


def test_list_status_reports_a_corrupt_state_as_a_typed_entry_and_still_lists_the_healthy_ones(env):
    host, runner, store, sink, root = env
    host.register(new_manifest(capability_id="other", display_name="Other", components={"a": "1.0.0"}))
    host.install("demo")
    host.install("other")
    (root / "local_capabilities" / "demo" / "state.json").write_text("{not json", encoding="utf-8")
    entries = {e["capability_id"]: e for e in host.list_status()}
    assert entries["demo"]["status"] == "state_unreadable" and entries["demo"]["last_error_code"] == C.STORE_FAILED.value
    assert entries["other"]["status"] == "ready"
    assert any(k == "local_capability.status.failed" and level == "error" for k, level, _ in sink.events)


@pytest.mark.parametrize("raw", [
    r"ENOENT: no such file C:\Users\Clarice\.jarvis\instances\x\data\local_capabilities\demo\runtime\a.js",
    "cannot open C:/Users/Clarice/secret/file.txt now",
    "share \\\\server\\share\\dir\\f.bin failed",
    "failed at /home/clarice/.jarvis/x/runtime/y.js line 3",
])
def test_absolute_paths_never_reach_the_view_the_state_file_or_the_log(env, raw):
    host, runner, _, sink, root = env
    runner.install_error = RuntimeError(raw)
    view = host.install("demo")
    stored = (root / "local_capabilities" / "demo" / "state.json").read_text(encoding="utf-8")
    logged = json.dumps([e[2] for e in sink.events], default=str)
    for text in (json.dumps(view), stored, logged):
        for leak in ("Clarice", "C:\\", "C:/", "server", "/home/"):
            assert leak not in text, (leak, text)
    assert "<path>" in view["last_error_detail"]


def test_secrets_are_redacted_from_runner_errors(env):
    host, runner, *_ = env
    runner.install_error = RuntimeError("npm ERR! 401 Authorization: Bearer abcdef123456 token=SENTINEL-77 _authToken: sk-abcdefghijklmnop")
    detail = host.install("demo")["last_error_detail"]
    for leak in ("abcdef123456", "SENTINEL-77", "sk-abcdefghijklmnop"):
        assert leak not in detail
    assert "npm ERR!" in detail


def test_store_and_internal_failures_are_errors_not_refusals_and_logged_once(env):
    host, runner, store, sink, root = env
    host.install("demo")
    (root / "local_capabilities" / "demo" / "state.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(LocalCapabilityError):
        host.start("demo")
    ev = [e for e in sink.events if e[2].get("code") == C.STORE_FAILED.value]
    assert [(k, lvl) for k, lvl, _ in ev] == [("local_capability.start.failed", "error")]
    sink.events.clear()
    host.reconcile()
    assert [k for k, _, d in sink.events if d.get("code") == C.STORE_FAILED.value] == ["local_capability.reconcile.failed"]


def test_an_unexpected_untyped_exception_is_logged_and_becomes_a_typed_internal_error(env):
    host, _, store, sink, _ = env
    store.load = lambda cid: (_ for _ in ()).throw(KeyError("boom"))
    with pytest.raises(LocalCapabilityError) as err:
        host.install("demo")
    assert err.value.code is C.INTERNAL_ERROR
    assert any(lvl == "error" and d.get("code") == C.INTERNAL_ERROR.value for _, lvl, d in sink.events)
    with pytest.raises(LocalCapabilityError):  # the lock is released even then
        host.install("demo")


@pytest.mark.parametrize("name", ["../x", "a/../b", "a/./b", "a//b", "a..b", "/abs"])
def test_component_names_with_path_tricks_are_refused(name):
    with pytest.raises(LocalCapabilityError) as err:
        new_manifest(capability_id="demo", display_name="D", components={name: "1.0.0"})
    assert err.value.code is C.INVALID


@pytest.mark.parametrize("components", [["a"], "a", 3, None])
def test_non_mapping_components_give_a_typed_error_not_an_attribute_error(components):
    with pytest.raises(LocalCapabilityError) as err:
        new_manifest(capability_id="demo", display_name="D", components=components)
    assert err.value.code is C.INVALID


def test_malformed_requirements_give_a_typed_error():
    with pytest.raises(LocalCapabilityError) as err:
        new_manifest(capability_id="demo", display_name="D", components={"a": "1.0.0"}, requirements=[3])
    assert err.value.code is C.INVALID


@pytest.mark.parametrize("cid", ["con", "aux", "nul", "prn", "com1", "com9", "lpt1", "lpt9"])
def test_windows_reserved_device_names_are_refused_as_ids(cid, tmp_path):
    with pytest.raises(LocalCapabilityError) as err:
        new_manifest(capability_id=cid, display_name="D", components={"a": "1.0.0"})
    assert err.value.code is C.INVALID
    with pytest.raises(LocalCapabilityError):
        FileLocalCapabilityStore(tmp_path).load(cid)
    new_manifest(capability_id="com-ok", display_name="D", components={"a": "1.0.0"})


@pytest.mark.parametrize("enabled", ["false", 0, 1, None, "no"])
def test_enabled_must_be_a_real_json_boolean(enabled):
    payload = {"capability_id": "demo", "install_status": "installed", "process_status": "stopped", "health": "unknown", "enabled": enabled}
    with pytest.raises(LocalCapabilityError) as err:
        lc.state_from_payload(payload)
    assert err.value.code is C.STORE_FAILED
