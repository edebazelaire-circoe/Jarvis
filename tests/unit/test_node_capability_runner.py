"""Runner réel des capacités Node : exigences, installation `npm ci`, intégrité, santé, retrait, échecs typés
(Slice 04 de jarvis-remotion-presentation-integration ; `docs/remotion-runtime.md`). Faux npm/node : ni réseau ni processus."""

from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from jarvis.adapters import node_capability_runner as ncr
from jarvis.adapters import process_tree
from jarvis.adapters.node_capability_runner import NodeCapabilityRunner, NodeRuntimeSpec, classify_npm_failure
from jarvis.adapters.process_tree import ProcessResult
from jarvis.domain.local_capabilities import LocalCapabilityError, LocalCapabilityErrorCode as C
from jarvis.domain.remotion_capability import NODE_MINIMUM, NPM_MINIMUM, SUPPORTED_PLATFORMS, REMOTION_COMPONENTS, remotion_manifest

PLATFORM = "win32-x64"
MANIFEST = remotion_manifest()


def make_assets(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "package.json").write_text(json.dumps({"name": "x", "dependencies": dict(REMOTION_COMPONENTS)}), encoding="utf-8")
    packages = {"": {"dependencies": dict(REMOTION_COMPONENTS)}}
    for name, version in REMOTION_COMPONENTS.items():
        packages[f"node_modules/{name}"] = {"version": version, "integrity": "sha512-x"}
    packages["node_modules/native-win"] = {"version": "1.0.0", "os": ["win32"], "cpu": ["x64"], "optional": True}
    packages["node_modules/native-linux"] = {"version": "1.0.0", "os": ["linux"], "cpu": ["x64"], "optional": True}
    packages["node_modules/native-musl"] = {"version": "1.0.0", "os": ["linux"], "cpu": ["x64"], "libc": ["musl"], "optional": True}
    packages["node_modules/wasm-helper"] = {"version": "2.0.0", "optional": True}
    (path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": packages}), encoding="utf-8")
    (path / "runtime-host.mjs").write_text("// fake\n", encoding="utf-8")
    return path


class FakeNode:
    """Imite node + npm : même interface que `process_tree.run_bounded`, journalise chaque appel."""

    def __init__(self) -> None:
        self.node_version = "v24.18.0"
        self.npm_version = "12.0.1"
        self.platform = PLATFORM
        self.calls: list[dict] = []
        self.ci_result: ProcessResult | None = None  # force l'issue de `npm ci`
        self.ci_writes = True
        self.probe_result = ProcessResult(0, '{"ok":true}', False, 0.1)
        self.started_pids: list[int] = []
        self.skip_wasm = True

    def __call__(self, argv, *, cwd, env, timeout_s, on_start=None):
        self.calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env), "timeout_s": timeout_s})
        if on_start:
            on_start(4242)
            self.started_pids.append(4242)
        joined = " ".join(argv)
        if "process.version" in joined:
            return ProcessResult(0, f"{self.node_version} {self.platform}\n", False, 0.0)
        if "process.platform" in joined:
            return ProcessResult(0, f"{self.platform}\n", False, 0.0)
        if argv[-1] == "--version":
            return ProcessResult(0, f"{self.npm_version}\n", False, 0.0)
        if "ci" in argv:
            if self.ci_result is not None:
                return self.ci_result
            if self.ci_writes:
                self.write_tree(Path(cwd))
            return ProcessResult(0, "added 297 packages", False, 5.0)
        if "--probe" in argv:
            return self.probe_result
        raise AssertionError(f"unexpected call {argv}")

    def write_tree(self, runtime: Path) -> None:
        lock = json.loads((runtime / "package-lock.json").read_text(encoding="utf-8"))["packages"]
        for key, entry in lock.items():
            if not key or (entry.get("os") and "win32" not in entry["os"]):
                continue
            if self.skip_wasm and key.endswith("wasm-helper"):
                continue
            target = runtime / key
            target.mkdir(parents=True, exist_ok=True)
            (target / "package.json").write_text(json.dumps({"name": key, "version": entry["version"]}), encoding="utf-8")
            (target / "index.js").write_text("module.exports = 1; // " + "x" * 100, encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    assets = make_assets(tmp_path / "assets")
    runtime = tmp_path / "data" / "local_capabilities" / "remotion" / "runtime"
    runtime.mkdir(parents=True)
    node = FakeNode()
    which = {"node": "/fake/bin/node", "npm": "/fake/bin/npm", "npm.cmd": "/fake/bin/npm.cmd"}.get
    runner = NodeCapabilityRunner(NodeRuntimeSpec(assets, NODE_MINIMUM, NPM_MINIMUM, SUPPORTED_PLATFORMS), execute=node, which=which,
                                  environ={"PATH": "/fake", "JARVIS_TOKEN": "secret-token", "OPENAI_API_KEY": "sk-abc"},
                                  free_bytes=lambda _p: 10_000_000_000, windows=False)
    return runner, node, runtime, assets, tmp_path


def installed(env):
    runner, _node, runtime, *_ = env
    return runner.install(MANIFEST, runtime)


# ------------------------------------------------------------------------ exigences

def test_requirements_are_met_on_a_supported_machine(env):
    runner, *_ = env
    assert runner.check_requirements(MANIFEST) == ()


def test_node_missing_is_a_typed_requirement_and_runs_nothing(env):
    runner, node, *_ = env
    runner._which = lambda name: None
    [line] = runner.check_requirements(MANIFEST)
    assert line.startswith("node_missing:") and node.calls == []


@pytest.mark.parametrize("version, token", [("v18.19.0", "node_too_old"), ("v19.9.9", "node_too_old")])
def test_node_too_old_is_typed_with_found_and_needed(env, version, token):
    runner, node, *_ = env
    node.node_version = version
    [line] = runner.check_requirements(MANIFEST)
    assert line.startswith(token + ":") and version.lstrip("v") in line and NODE_MINIMUM in line


def test_node_without_a_version_answer_is_unusable(env):
    runner, node, *_ = env
    node.node_version = "garbage"
    assert runner.check_requirements(MANIFEST)[0].startswith("node_unusable:")


def test_unsupported_platform_is_typed(env):
    runner, node, *_ = env
    node.platform = "win32-arm64"
    [line] = runner.check_requirements(MANIFEST)
    assert line.startswith("platform_unsupported:") and "win32-arm64" in line


def test_npm_missing_and_npm_too_old_are_typed(env):
    runner, node, *_ = env
    node.npm_version = "8.19.4"
    assert runner.check_requirements(MANIFEST)[0].startswith("npm_too_old:")
    runner._which = {"node": "/fake/bin/node"}.get
    assert runner.check_requirements(MANIFEST)[0].startswith("npm_missing:")


def test_several_unmet_requirements_are_all_reported(env):
    runner, node, *_ = env
    node.node_version, node.npm_version, node.platform = "v16.0.0", "7.0.0", "linux-ia32"
    tokens = [line.split(":")[0] for line in runner.check_requirements(MANIFEST)]
    assert tokens == ["node_too_old", "platform_unsupported", "npm_too_old"]


# ---------------------------------------------------------------------- installation

def test_install_runs_npm_ci_from_the_shipped_lock_inside_the_runtime_dir_only(env):
    runner, node, runtime, assets, tmp_path = env
    before = {p for p in tmp_path.rglob("*")}
    result = installed(env)
    assert result == dict(MANIFEST.components)
    ci = next(c for c in node.calls if "ci" in c["argv"])
    assert ci["cwd"] == runtime and "--ignore-scripts" in ci["argv"] and "-g" not in ci["argv"] and "--global" not in ci["argv"]
    assert (runtime / "package-lock.json").read_bytes() == (assets / "package-lock.json").read_bytes()
    new = {p for p in tmp_path.rglob("*")} - before
    assert all(runtime in p.parents or p == runtime for p in new), [str(p) for p in new if runtime not in p.parents]
    assert not (runtime / "node_modules" / "native-linux").exists()  # un binaire d'une autre plate-forme n'est pas attendu


def test_install_isolates_npm_config_cache_and_secrets(env):
    runner, node, runtime, *_ = env
    installed(env)
    env_used = next(c for c in node.calls if "ci" in c["argv"])["env"]
    assert env_used["npm_config_cache"] == str(runtime / ".npm-cache")
    assert env_used["npm_config_userconfig"].startswith(str(runtime)) and env_used["npm_config_globalconfig"].startswith(str(runtime))
    assert env_used["npm_config_registry"] == "https://registry.npmjs.org/" and env_used["npm_config_ignore_scripts"] == "true"
    assert "JARVIS_TOKEN" not in env_used and "OPENAI_API_KEY" not in env_used and env_used["PATH"] == "/fake"


def test_install_writes_a_record_with_lock_hash_and_fingerprint(env):
    runner, _node, runtime, assets, _ = env
    installed(env)
    record = json.loads((runtime / ncr.RECORD_FILE).read_text(encoding="utf-8"))
    assert record["installed"] == dict(MANIFEST.components) and record["platform"] == PLATFORM
    assert record["lock_sha256"] == ncr.sha256_file(assets / "package-lock.json") and len(record["fingerprint"]) == 64


def test_install_refuses_a_runtime_dir_that_is_not_the_capability_runtime(env, tmp_path):
    runner, *_ = env
    for bad in (tmp_path / "elsewhere", tmp_path / "data" / "local_capabilities" / "other" / "runtime"):
        bad.mkdir(parents=True, exist_ok=True)
        with pytest.raises(LocalCapabilityError) as err:
            runner.install(MANIFEST, bad)
        assert err.value.code is C.INSTALL_FAILED


def test_install_refuses_when_the_shipped_package_json_disagrees_with_the_manifest(env):
    runner, _node, runtime, assets, _ = env
    (assets / "package.json").write_text(json.dumps({"dependencies": {"remotion": "4.0.1"}}), encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is C.INSTALL_FAILED and err.value.detail.startswith("manifest_mismatch")


def test_install_fails_typed_when_the_tree_lacks_a_locked_package(env):
    runner, node, runtime, *_ = env
    node.ci_writes = False
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is C.HEALTH_FAILED and err.value.detail.startswith("tree_corrupt")


def test_install_cleans_a_partial_tree_left_by_an_interrupted_run(env):
    runner, _node, runtime, *_ = env
    stale = runtime / "node_modules" / "half-written" / "x.js"
    stale.parent.mkdir(parents=True)
    stale.write_text("partial", encoding="utf-8")
    installed(env)
    assert not stale.exists()


@pytest.mark.parametrize("output, code, token", [
    ("npm error code ENOTFOUND\nnpm error getaddrinfo ENOTFOUND registry.npmjs.org", C.INSTALL_OFFLINE, "offline"),
    ("npm error code ECONNREFUSED", C.INSTALL_OFFLINE, "offline"),
    ("npm error network timeout", C.INSTALL_OFFLINE, "offline"),
    ("npm error code EACCES\nnpm error syscall mkdir", C.INSTALL_PERMISSION_DENIED, "permission_denied"),
    ("npm error code EPERM operation not permitted", C.INSTALL_PERMISSION_DENIED, "permission_denied"),
    ("npm error code EBUSY resource busy or locked", C.INSTALL_PERMISSION_DENIED, "file_locked"),
    ("npm error code ENOSPC no space left on device", C.INSTALL_DISK_FULL, "disk_full"),
    ("npm error code EINTEGRITY\nnpm error sha512-aaa integrity checksum failed", C.INSTALL_INTEGRITY_FAILED, "integrity_failed"),
    ("npm error code E404 not found", C.INSTALL_FAILED, "registry_refused"),
    ("npm error something odd", C.INSTALL_FAILED, "npm_failed"),
])
def test_npm_failures_become_typed_codes(env, output, code, token):
    assert classify_npm_failure(output) == (code, token)
    runner, node, runtime, *_ = env
    node.ci_result = ProcessResult(1, output, False, 1.0)
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is code and err.value.detail.startswith(token + ":")


def test_a_timeout_is_typed_and_names_the_limit(env):
    runner, node, runtime, *_ = env
    node.ci_result = ProcessResult(None, "partial", True, 900.0)
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is C.INSTALL_TIMEOUT and "900" in err.value.detail and "process tree was killed" in err.value.detail


def test_npm_that_cannot_launch_is_typed(env):
    runner, node, runtime, *_ = env
    node.ci_result = ProcessResult(None, "FileNotFoundError: npm", False, 0.0, started=False)
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is C.INSTALL_FAILED and err.value.detail.startswith("npm_unlaunchable")


def test_install_refuses_a_read_only_runtime_dir_with_a_permission_code(env, monkeypatch):
    runner, _node, runtime, *_ = env
    real = Path.write_text

    def deny(self, *a, **k):
        if self.name.startswith(".write-probe"):
            raise PermissionError(13, "denied")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", deny)
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is C.INSTALL_PERMISSION_DENIED and err.value.detail.startswith("permission_denied")


def test_install_refuses_when_the_disk_is_too_small_before_downloading(env):
    runner, node, runtime, *_ = env
    runner._free_bytes = lambda _p: 100_000_000
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is C.INSTALL_DISK_FULL and not any("ci" in c["argv"] for c in node.calls)


def test_a_long_windows_runtime_path_is_refused_with_advice(env, tmp_path, monkeypatch):
    runner, *_ = env
    runner._windows = True
    monkeypatch.setattr(NodeCapabilityRunner, "_windows_long_paths", staticmethod(lambda: False))
    long_runtime = tmp_path / ("d" * 90) / "local_capabilities" / "remotion" / "runtime"
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, long_runtime)
    assert err.value.detail.startswith("path_too_long")


# --------------------------------------------------------------------------- verrou

def test_a_live_install_lock_makes_the_second_install_busy(env):
    runner, _node, runtime, *_ = env
    (runtime / ncr.LOCK_FILE).write_text(json.dumps({"ref": process_tree.make_process_ref(__import__("os").getpid()), "at": time.time()}), encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert err.value.code is C.BUSY


@pytest.mark.parametrize("content", [
    json.dumps({"ref": "999999:1", "at": time.time()}),          # processus disparu
    json.dumps({"ref": "1:1", "at": 0}),                          # trop vieux
    "not json",                                                   # illisible
])
def test_a_stale_install_lock_is_taken_over(env, content):
    runner, _node, runtime, *_ = env
    (runtime / ncr.LOCK_FILE).write_text(content, encoding="utf-8")
    assert installed(env) == dict(MANIFEST.components)
    assert not (runtime / ncr.LOCK_FILE).exists()  # relâché à la fin


def test_the_lock_is_released_after_a_failed_install(env):
    runner, node, runtime, *_ = env
    node.ci_result = ProcessResult(1, "boom", False, 0.1)
    with pytest.raises(LocalCapabilityError):
        runner.install(MANIFEST, runtime)
    assert not (runtime / ncr.LOCK_FILE).exists()


# ----------------------------------------------------------------------------- santé

def healthy(env):
    runner, _node, runtime, *_ = env
    inst = installed(env)
    runner.verify(MANIFEST, runtime, inst)
    return inst


def test_verify_passes_on_a_fresh_install_and_runs_the_node_probe(env):
    runner, node, runtime, *_ = env
    healthy(env)
    assert any("--probe" in c["argv"] and c["cwd"] == runtime for c in node.calls)


def test_verify_detects_a_deleted_file_in_a_pinned_package(env):
    runner, _node, runtime, *_ = env
    inst = healthy(env)
    (runtime / "node_modules" / "remotion" / "index.js").unlink()
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, inst)
    assert err.value.code is C.HEALTH_FAILED and err.value.detail.startswith("tree_corrupt")


def test_verify_detects_a_truncated_file(env):
    runner, _node, runtime, *_ = env
    inst = healthy(env)
    (runtime / "node_modules" / "react" / "index.js").write_text("", encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, inst)
    assert err.value.detail.startswith("tree_corrupt")


def test_verify_detects_a_missing_or_wrong_version_dependency_and_names_it(env):
    runner, _node, runtime, *_ = env
    inst = healthy(env)
    pkg = runtime / "node_modules" / "native-win" / "package.json"
    pkg.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, inst)
    assert "native-win@1.0.0" in err.value.detail and "found 9.9.9" in err.value.detail


def test_verify_tolerates_an_unconstrained_optional_dependency_npm_omitted(env):
    healthy(env)  # `wasm-helper` n'a jamais été écrit par le faux npm, comme le vrai l'omet pour les aides wasm


def test_verify_detects_a_lock_changed_on_disk_or_in_the_shipped_files(env):
    runner, _node, runtime, assets, _ = env
    inst = healthy(env)
    (assets / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {"": {}}}), encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, inst)
    assert err.value.detail.startswith("shipped_files_changed") and "package-lock.json" in err.value.detail


@pytest.mark.parametrize("name", ["runtime-host.mjs", "package.json", "package-lock.json"])
def test_verify_detects_any_shipped_file_changed_in_the_runtime_copy_or_in_the_shipped_assets(env, name):
    runner, _node, runtime, assets, _ = env
    inst = healthy(env)
    (runtime / name).write_text((runtime / name).read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, inst)
    assert err.value.code is C.HEALTH_FAILED and err.value.detail.startswith("shipped_files_changed") and name in err.value.detail
    runtime_ok = installed(env)  # repair path: a new install re-syncs the copies
    runner.verify(MANIFEST, runtime, runtime_ok)
    (assets / "runtime-host.mjs").write_text("// new worker", encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err2:
        runner.verify(MANIFEST, runtime, runtime_ok)
    assert "runtime-host.mjs" in err2.value.detail
    installed(env)
    runner.verify(MANIFEST, runtime, runtime_ok)


def _health_server(pid_answer):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "pid": pid_answer}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_worker_health_ignores_environment_proxies_and_requires_our_pid(monkeypatch):
    server = _health_server(4321)
    try:
        for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
            monkeypatch.setenv(var, "http://127.0.0.1:9")  # proxy mort : un client qui le suit échouerait
        NodeCapabilityRunner._get_health(server.server_port, 4321)
        with pytest.raises(LocalCapabilityError) as err:
            NodeCapabilityRunner._get_health(server.server_port, 9999)  # un autre programme sur ce port
        assert err.value.code is C.START_FAILED and err.value.detail.startswith("worker_unhealthy")
    finally:
        server.shutdown()


def test_start_refuses_a_worker_whose_identity_cannot_be_read_and_kills_it(env, monkeypatch):
    runner, _node, runtime, *_ = env
    healthy(env)
    killed = []
    def spawn(*a, **k):
        (runtime / ncr.WORKER_FILE).write_text(json.dumps({"pid": 77, "port": 1}), encoding="utf-8")
        return 77

    monkeypatch.setattr(process_tree, "spawn_detached", spawn)
    monkeypatch.setattr(NodeCapabilityRunner, "_get_health", staticmethod(lambda port, pid: None))
    monkeypatch.setattr(process_tree, "make_process_ref", lambda pid: "")
    monkeypatch.setattr(process_tree, "kill_tree", lambda pid: killed.append(pid) or True)
    with pytest.raises(LocalCapabilityError) as err:
        runner.start(MANIFEST, runtime)
    assert err.value.detail.startswith("process_identity_unavailable") and killed == [77]


def test_start_rotates_an_oversized_worker_log(env, monkeypatch):
    runner, _node, runtime, *_ = env
    (runtime / ncr.WORKER_LOG).write_bytes(b"x" * (ncr.WORKER_LOG_MAX_BYTES + 1))
    monkeypatch.setattr(process_tree, "spawn_detached", lambda *a, **k: 5)
    monkeypatch.setattr(process_tree, "pid_exists", lambda pid: False)
    with pytest.raises(LocalCapabilityError):
        runner.start(MANIFEST, runtime)
    assert (runtime / (ncr.WORKER_LOG + ".1")).exists() and not (runtime / ncr.WORKER_LOG).exists()


def test_verify_reports_a_missing_record_and_version_mismatch(env):
    runner, _node, runtime, *_ = env
    inst = healthy(env)
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, {**inst, "remotion": "4.0.1"})
    assert err.value.detail.startswith("version_mismatch")
    (runtime / ncr.RECORD_FILE).unlink()
    with pytest.raises(LocalCapabilityError) as err2:
        runner.verify(MANIFEST, runtime, inst)
    assert err2.value.detail.startswith("record_missing")


def test_verify_reports_a_failing_or_hanging_probe_with_its_output(env):
    runner, node, runtime, *_ = env
    inst = healthy(env)
    node.probe_result = ProcessResult(2, "probe_failed: Cannot find module 'x'", False, 0.2)
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, inst)
    assert err.value.code is C.HEALTH_FAILED and "Cannot find module" in err.value.detail
    node.probe_result = ProcessResult(None, "", True, 90.0)
    with pytest.raises(LocalCapabilityError) as err2:
        runner.verify(MANIFEST, runtime, inst)
    assert err2.value.detail.startswith("probe_timeout")


def test_verify_reports_node_that_vanished(env):
    runner, _node, runtime, *_ = env
    inst = healthy(env)
    runner._which = lambda name: None
    with pytest.raises(LocalCapabilityError) as err:
        runner.verify(MANIFEST, runtime, inst)
    assert err.value.detail.startswith("node_missing")


# ------------------------------------------------------------------------------ retrait

def test_remove_empties_only_the_runtime_dir_and_never_a_sibling_presentation_tree(env):
    runner, _node, runtime, _assets, tmp_path = env
    installed(env)
    sources = tmp_path / "data" / "presentation" / "sources" / "deck-1"
    sources.mkdir(parents=True)
    (sources / "Deck.tsx").write_text("export const Deck = () => null;", encoding="utf-8")
    (runtime.parent / "state.json").write_text("{}", encoding="utf-8")
    runner.remove(MANIFEST, runtime)
    assert list(runtime.iterdir()) == []
    assert (sources / "Deck.tsx").read_text(encoding="utf-8").startswith("export") and (runtime.parent / "state.json").exists()


def test_remove_refuses_a_directory_that_is_not_the_runtime_dir(env, tmp_path):
    runner, *_ = env
    other = tmp_path / "precious"
    other.mkdir()
    (other / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(LocalCapabilityError) as err:
        runner.remove(MANIFEST, other)
    assert err.value.code is C.UNINSTALL_FAILED and (other / "keep.txt").exists()


def test_remove_does_not_follow_a_link_out_of_the_runtime_dir(env, tmp_path):
    runner, _node, runtime, *_ = env
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    try:
        (runtime / "link").symlink_to(outside, target_is_directory=True)
    except OSError:  # Windows sans droit de lien symbolique : une jonction n'en demande pas
        import subprocess
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(runtime / "link"), str(outside)], capture_output=True)
        if made.returncode != 0:
            pytest.skip("neither symlinks nor junctions can be created here")
    runner.remove(MANIFEST, runtime)
    assert (outside / "keep.txt").exists() and not (runtime / "link").exists()


def test_remove_of_a_missing_runtime_dir_is_a_no_op(env, tmp_path):
    runner, *_ = env
    runner.remove(MANIFEST, tmp_path / "d2" / "local_capabilities" / "remotion" / "runtime")


def test_removal_retries_a_delete_pending_folder_but_not_other_errors(monkeypatch):
    """Slice 05 : sous Windows `rmdir` répond « répertoire non vide » (WinError 145) tant qu'une poignée traîne sur un enfant
    déjà supprimé ; la suppression réessaie. Une autre erreur n'est jamais réessayée."""

    import errno as errno_module
    monkeypatch.setattr(ncr.time, "sleep", lambda _: None)
    calls = []

    def pending_then_ok():
        calls.append(1)
        if len(calls) < 3:
            error = OSError(errno_module.ENOTEMPTY, "directory not empty")
            error.winerror = 145
            raise error

    ncr._retry(pending_then_ok)
    assert len(calls) == 3
    other = []

    def broken():
        other.append(1)
        raise OSError(errno_module.EIO, "disk")

    with pytest.raises(OSError):
        ncr._retry(broken)
    assert len(other) == 1


@pytest.mark.skipif(not ncr.os.name == "nt", reason="the 260-character limit is a Windows one")
def test_removal_reaches_files_beyond_the_260_character_windows_limit(tmp_path):
    """Slice 05 : le cache de npm range des fichiers à nom de 124 caractères ; `uninstall` doit les supprimer même quand le chemin
    complet dépasse 260 caractères (sinon « répertoire non vide » et un environnement impossible à retirer)."""

    runtime = tmp_path / "local_capabilities" / "remotion" / "runtime"
    deep = runtime / ".npm-cache" / "_cacache" / "content-v2" / "sha512" / "00" / "d8"
    extended = ncr._extended(deep)
    ncr.os.makedirs(extended)
    name = "f" * 124
    with open(str(extended) + chr(92) + name, "wb") as stream:
        stream.write(b"x")
    assert len(str(deep)) + 1 + len(name) > 260
    ncr._remove_tree(runtime / ".npm-cache")
    assert not ncr.os.path.exists(ncr._extended(runtime / ".npm-cache"))
    assert ncr._extended(Path("C:/x")) == Path(ncr.EXTENDED_PREFIX + "C:" + chr(92) + "x")
    assert ncr._extended(Path(ncr.EXTENDED_PREFIX + "C:" + chr(92) + "x")) == Path(ncr.EXTENDED_PREFIX + "C:" + chr(92) + "x")


# ------------------------------------------------------------------------ arrêt de Core

def test_cancel_all_kills_every_tracked_process_tree_and_marks_the_install_cancelled(env, monkeypatch):
    runner, node, runtime, *_ = env
    killed: list[int] = []
    monkeypatch.setattr(process_tree, "kill_tree", lambda pid: killed.append(pid) or True)

    def execute(argv, *, cwd, env, timeout_s, on_start=None):
        if "ci" in argv:
            on_start(777)
            runner.cancel_all()  # Core s'arrête pendant npm
            return ProcessResult(1, "killed", False, 0.1)
        return node(argv, cwd=cwd, env=env, timeout_s=timeout_s, on_start=on_start)

    runner._execute = execute
    with pytest.raises(LocalCapabilityError) as err:
        runner.install(MANIFEST, runtime)
    assert killed == [777] and err.value.detail.startswith("cancelled")
    assert runner._active == set()


# ------------------------------------------------------------- les fichiers livrés eux-mêmes

SHIPPED = Path(ncr.__file__).resolve().parents[1] / "capabilities" / "remotion"


def test_the_shipped_package_json_lock_and_manifest_agree():
    package = json.loads((SHIPPED / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((SHIPPED / "package-lock.json").read_text(encoding="utf-8"))
    assert package["dependencies"] == dict(REMOTION_COMPONENTS) == dict(MANIFEST.components)
    assert lock["packages"][""]["dependencies"] == dict(REMOTION_COMPONENTS)
    for name, version in REMOTION_COMPONENTS.items():
        assert lock["packages"][f"node_modules/{name}"]["version"] == version


def test_every_locked_package_has_an_integrity_hash_and_comes_from_the_official_registry():
    lock = json.loads((SHIPPED / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    assert len(lock) > 100
    for key, entry in lock.items():
        if not key:
            continue
        assert entry.get("integrity", "").startswith("sha512-"), key
        assert entry.get("resolved", "").startswith("https://registry.npmjs.org/"), key


def test_the_required_node_covers_the_highest_engine_of_the_lock():
    lock = json.loads((SHIPPED / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    needed = (0, 0, 0)
    for key, entry in lock.items():
        engine = (entry.get("engines") or {}).get("node") if isinstance(entry.get("engines"), dict) else None
        found = ncr.parse_version(engine.split("||")[0]) if engine and ">=" in engine.split("||")[0] and "||" not in engine else None
        if found:
            needed = max(needed, found)
    assert needed <= ncr.parse_version(NODE_MINIMUM)


def test_the_lock_covers_the_native_binaries_of_every_supported_platform():
    lock = json.loads((SHIPPED / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    have = {(os_, cpu) for key, entry in lock.items() if key.startswith("node_modules/@remotion/compositor-")
            for os_ in entry.get("os", []) for cpu in entry.get("cpu", [])}
    for platform in SUPPORTED_PLATFORMS:
        os_, _, cpu = platform.partition("-")
        assert (os_, cpu) in have, platform


def test_the_worker_script_binds_loopback_only_and_reads_no_secret():
    script = (SHIPPED / "runtime-host.mjs").read_text(encoding="utf-8")
    # Slice 05: the compile mode names the string key `process.env.NODE_ENV` once, as an esbuild `define` replaced in the
    # compiled bundle; it never reads the environment. Any other mention is still a failure.
    script = script.replace('"process.env.NODE_ENV"', "")
    assert '"127.0.0.1"' in script and "process.env" not in script and "0.0.0.0" not in script
