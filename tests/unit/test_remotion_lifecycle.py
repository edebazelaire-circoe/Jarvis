"""Cycle de vie Remotion : hôte réel + magasin de fichiers + runner Node réel, avec un faux npm/node
(Slice 04 de jarvis-remotion-presentation-integration ; `docs/remotion-runtime.md`). L'installation réseau réelle est prouvée
par `scripts/remotion_install_harness.py`, pas ici."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

import pytest

from jarvis.adapters import node_capability_runner as ncr
from jarvis.adapters import process_tree
from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.adapters.node_capability_runner import NodeCapabilityRunner, NodeRuntimeSpec
from jarvis.adapters.process_tree import ProcessResult
from jarvis.core.local_capability_host import LocalCapabilityHost
from jarvis.domain.local_capabilities import LocalCapabilityError, LocalCapabilityErrorCode as C
from jarvis.domain.remotion_capability import NODE_MINIMUM, NPM_MINIMUM, REMOTION_CAPABILITY_ID as CID, SUPPORTED_PLATFORMS, remotion_manifest
from tests.unit.test_node_capability_runner import FakeNode, make_assets


REAL_SPAWN = process_tree.spawn_detached


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level))


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    node = FakeNode()
    assets = make_assets(tmp_path / "assets")
    runner = NodeCapabilityRunner(NodeRuntimeSpec(assets, NODE_MINIMUM, NPM_MINIMUM, SUPPORTED_PLATFORMS, start_timeout_s=10), execute=node,
                                  which={"node": "/fake/node", "npm": "/fake/npm", "npm.cmd": "/fake/npm.cmd"}.get, environ={"PATH": "/fake"},
                                  free_bytes=lambda _p: 10**11, windows=False)
    spawned: list[int] = []

    def fake_spawn(argv, *, cwd, env, log_path):
        """Un vrai petit processus long, plus le `worker.json` que le vrai worker Node écrirait."""

        pid = REAL_SPAWN([sys.executable, "-c", "import time; time.sleep(120)"], cwd=cwd, env=env, log_path=log_path)
        (Path(cwd) / ncr.WORKER_FILE).write_text(json.dumps({"pid": pid, "port": 1}), encoding="utf-8")
        spawned.append(pid)
        return pid

    monkeypatch.setattr(process_tree, "spawn_detached", fake_spawn)
    monkeypatch.setattr(NodeCapabilityRunner, "_get_health", staticmethod(lambda port, pid: None))
    sink = Sink()
    (tmp_path / "data").mkdir()
    store = FileLocalCapabilityStore(tmp_path / "data")
    host = LocalCapabilityHost(store, runner=runner, manifests={CID: remotion_manifest()}, diagnostics=sink)
    yield host, runner, node, tmp_path / "data", spawned, sink
    for pid in spawned:
        process_tree.kill_tree(pid)


def runtime(root: Path) -> Path:
    return root / "local_capabilities" / CID / "runtime"


def test_install_once_then_restart_of_core_finds_it_ready_and_installs_nothing(lifecycle):
    host, _runner, node, root, *_ = lifecycle
    assert host.install(CID)["status"] == "ready"
    npm_calls = sum("ci" in c["argv"] for c in node.calls)
    host2 = LocalCapabilityHost(FileLocalCapabilityStore(root), runner=host.runner, manifests={CID: remotion_manifest()})
    assert [v["status"] for v in host2.reconcile()] == ["ready"]
    assert host2.install(CID)["install_attempts"] == 1
    assert sum("ci" in c["argv"] for c in node.calls) == npm_calls == 1
    assert len(list(root.rglob("node_modules"))) == 1, "exactly one dependency tree for the whole runtime, none per presentation"


def test_concurrent_installs_run_npm_once_and_refuse_the_others_as_busy(lifecycle):
    host, runner, node, *_ = lifecycle
    gate, entered = threading.Event(), threading.Event()
    inner = node.__call__

    def slow(argv, *, cwd, env, timeout_s, on_start=None):
        if "ci" in argv:
            entered.set()
            assert gate.wait(30)
        return inner(argv, cwd=cwd, env=env, timeout_s=timeout_s, on_start=on_start)

    runner._execute = slow
    results: list[object] = []
    first = threading.Thread(target=lambda: results.append(host.install(CID)["status"]))
    first.start()
    assert entered.wait(10)
    for _ in range(3):
        with pytest.raises(LocalCapabilityError) as err:
            host.install(CID)
        assert err.value.code is C.BUSY
    gate.set()
    first.join(30)
    assert results == ["ready"] and sum("ci" in c["argv"] for c in node.calls) == 1


def test_corruption_is_detected_as_repair_needed_and_repair_restores_ready(lifecycle):
    host, _runner, node, root, *_ = lifecycle
    host.install(CID)
    (runtime(root) / "node_modules" / "remotion" / "index.js").unlink()
    broken = host.check_health(CID)
    assert broken["status"] == "repair_needed" and broken["last_error_code"] == C.HEALTH_FAILED.value
    assert broken["last_error_detail"].startswith("tree_corrupt")
    fixed = host.repair(CID)
    assert fixed["status"] == "ready" and fixed["install_attempts"] == 2
    assert (runtime(root) / "node_modules" / "remotion" / "index.js").exists()


def test_an_interrupted_install_is_reported_at_startup_and_repair_finishes_it(lifecycle):
    host, runner, node, root, *_ = lifecycle
    node.ci_result = ProcessResult(None, "", True, 900.0)  # le délai tue npm : arbre partiel laissé sur le disque
    failed = host.install(CID)
    assert failed["status"] == "install_failed" and failed["last_error_code"] == C.INSTALL_TIMEOUT.value
    half = runtime(root) / "node_modules" / "half" / "x.js"
    half.parent.mkdir(parents=True)
    half.write_text("partial", encoding="utf-8")
    # « arrêt de Core pendant npm » : l'état écrit reste `installing`
    state = host._load(CID)
    from dataclasses import replace
    from jarvis.domain.local_capabilities import InstallStatus
    host._store.save(replace(state, install_status=InstallStatus.INSTALLING, last_error_code=None, last_error_detail=""))
    restarted = LocalCapabilityHost(FileLocalCapabilityStore(root), runner=runner, manifests={CID: remotion_manifest()})
    assert restarted.status(CID)["status"] == "installing"
    [after] = restarted.reconcile()
    assert after["status"] == "install_failed" and after["last_error_code"] == C.INSTALL_INTERRUPTED.value
    node.ci_result = None
    done = restarted.repair(CID)
    assert done["status"] == "ready" and not half.exists()


def test_start_restart_stop_and_a_killed_child_are_all_visible_states(lifecycle):
    host, _runner, _node, root, spawned, _sink = lifecycle
    host.install(CID)
    running = host.start(CID)
    assert running["status"] == "running" and len(spawned) == 1
    ref = host._load(CID).process_ref
    assert process_tree.ref_alive(ref)
    assert host.start(CID)["status"] == "running" and len(spawned) == 1, "start is idempotent: no second worker"
    # Core redémarre : le même enfant est retrouvé vivant, rien n'est relancé
    host2 = LocalCapabilityHost(FileLocalCapabilityStore(root), runner=host.runner, manifests={CID: remotion_manifest()})
    assert [v["status"] for v in host2.reconcile()] == ["running"] and len(spawned) == 1
    assert host2.stop(CID)["status"] == "ready" and not process_tree.ref_alive(ref)
    assert host2.start(CID)["status"] == "running" and len(spawned) == 2
    process_tree.kill_tree(spawned[1])  # le worker meurt hors de Jarvis
    assert host2.check_health(CID)["status"] == "crashed"
    host3 = LocalCapabilityHost(FileLocalCapabilityStore(root), runner=host.runner, manifests={CID: remotion_manifest()})
    assert host3.status(CID)["status"] == "crashed"
    assert host3.start(CID)["status"] == "running" and len(spawned) == 3
    host3.stop(CID)


def test_a_worker_that_never_becomes_ready_fails_start_with_its_log_and_leaves_no_child(lifecycle, monkeypatch):
    host, runner, _node, root, spawned, _sink = lifecycle
    host.install(CID)
    runner._spec = NodeRuntimeSpec(runner._spec.assets_dir, NODE_MINIMUM, NPM_MINIMUM, SUPPORTED_PLATFORMS, start_timeout_s=1)

    def silent_spawn(argv, *, cwd, env, log_path):
        pid = REAL_SPAWN([sys.executable, "-c", "import time; time.sleep(120)"], cwd=cwd, env=env, log_path=log_path)
        spawned.append(pid)
        return pid  # jamais de worker.json

    monkeypatch.setattr(process_tree, "spawn_detached", silent_spawn)
    view = host.start(CID)
    assert view["status"] == "crashed" and view["last_error_code"] == C.START_FAILED.value and view["last_error_detail"].startswith("worker_not_ready")
    assert not process_tree.pid_exists(spawned[-1])


def test_uninstall_and_disable_never_touch_presentation_sources_or_assets(lifecycle):
    host, _runner, _node, root, spawned, _sink = lifecycle
    sources = root / "presentation" / "sources" / "deck-1"
    assets = root / "presentation" / "assets"
    sources.mkdir(parents=True)
    assets.mkdir(parents=True)
    (sources / "Deck.tsx").write_text("export const Deck = () => null;", encoding="utf-8")
    (assets / "logo.png").write_bytes(b"\x89PNG")
    snapshot = {p: p.read_bytes() for p in (root / "presentation").rglob("*") if p.is_file()}
    host.install(CID)
    host.start(CID)
    assert host.disable(CID)["status"] == "disabled"
    assert host.enable(CID)["status"] == "ready"
    assert host.start(CID)["status"] == "running"
    assert host.uninstall(CID)["status"] == "not_installed"
    assert {p: p.read_bytes() for p in (root / "presentation").rglob("*") if p.is_file()} == snapshot
    assert list(runtime(root).iterdir()) == [] and not process_tree.pid_exists(spawned[0])


def test_failures_are_logged_at_error_level_with_a_typed_code(lifecycle):
    host, _runner, node, _root, _spawned, sink = lifecycle
    node.node_version = "v18.0.0"
    view = host.install(CID)
    assert view["last_error_code"] == C.REQUIREMENT_MISSING.value and "node_too_old" in view["last_error_detail"]
    assert ("local_capability.install.failed", "error") in sink.events
