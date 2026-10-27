"""Portabilité macOS par plateforme simulée (Slice 08 de jarvis-presentation-edition-v1-2, `docs/macos-portability.md`).

Aucun Mac : chaque test macOS ci-dessous tourne sous Windows avec une plateforme simulée (paramètre `platform`,
`sys`/`os` du module remplacés, fonctions du noyau injectées). Ils prouvent la CORRESPONDANCE écrite, pas le
comportement d'un vrai Mac (`HV-V12-MAC-01`). Les tests marqués `posix_only` n'ont de sens que sur un vrai noyau POSIX :
ils sont sautés sous Windows et exécutés par le job CI macOS.

Chaque test Windows fige la valeur d'AVANT la Slice 08, à l'octet.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from jarvis import data_root as D
from jarvis import installation as I
from jarvis import private_runtime as PR
from jarvis.adapters import dpapi_sealer, remotion_render_runner as RR
from jarvis.adapters.node_capability_runner import NodeCapabilityRunner, NodeRuntimeSpec
from jarvis.domain.errors import ConfigurationError
from jarvis.installation import HostPlatform
from jarvis.ports.mcp_plugins import SealerError
from jarvis.runtime import feedback_sessions, local_secrets, owned_process_tree as OPT, product_launcher as L

MAC = HostPlatform.MACOS
WIN = HostPlatform.WINDOWS
MAC_ENV = {"HOME": "/Users/alice"}
WIN_ENV = {"LOCALAPPDATA": r"C:\Users\alice\AppData\Local", "USERPROFILE": r"C:\Users\alice",
           "PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)"}
posix_only = pytest.mark.skipif(os.name == "nt", reason="real POSIX kernel needed: runs in the macOS CI job")


def posix(path: Path) -> str:
    return path.as_posix()


@pytest.fixture
def as_mac(monkeypatch):
    """`host_platform()` rend macOS : tout appel sans `platform` explicite suit la carte macOS."""

    monkeypatch.setattr(I, "host_platform", lambda sys_platform=None: MAC)


def installed_app(root: Path) -> Path:
    app = root / "pkg" / PR.APP_DIR
    app.mkdir(parents=True)
    (app / I.PRODUCT_MARKER).write_text(json.dumps(I.marker_payload()), encoding="utf-8")
    return app


# -- plateforme ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "expected"), [("win32", WIN), ("darwin", MAC), ("linux", HostPlatform.OTHER)])
def test_sys_platform_maps_to_one_platform_family(value, expected):
    assert I.host_platform(value) is expected


# -- chemins : Windows inchangé à l'octet ------------------------------------------------------------------------------

@pytest.mark.parametrize("platform", [WIN, HostPlatform.OTHER])
def test_windows_home_is_byte_identical_to_v1(platform):
    home = I.product_home(WIN_ENV, platform=platform)
    assert str(PureWindowsPath(home.root)) == r"C:\Users\alice\AppData\Local\CIRCOE\Jarvis"
    assert [str(PureWindowsPath(p)) for p in (home.data, home.runtime, home.config, home.cache, home.logs)] == [
        r"C:\Users\alice\AppData\Local\CIRCOE\Jarvis\data", r"C:\Users\alice\AppData\Local\CIRCOE\Jarvis\runtime",
        r"C:\Users\alice\AppData\Local\CIRCOE\Jarvis\config", r"C:\Users\alice\AppData\Local\CIRCOE\Jarvis\cache",
        r"C:\Users\alice\AppData\Local\CIRCOE\Jarvis\logs"]
    assert home.label == I.PRODUCT_HOME_LABEL == r"%LOCALAPPDATA%\CIRCOE\Jarvis"
    assert home.sub_label("data") == r"%LOCALAPPDATA%\CIRCOE\Jarvis\data"
    assert home == I.ProductHome(home.root)  # même valeur que l'objet de la V1


def test_windows_still_ignores_home_and_refuses_without_localappdata():
    with pytest.raises(ConfigurationError, match="LOCALAPPDATA"):
        I.product_home(MAC_ENV, platform=WIN)


def test_windows_installed_diagnostics_keep_their_v1_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "host_platform", lambda sys_platform=None: WIN)
    app = installed_app(tmp_path)
    data, runtime = D.resolve_data_root(WIN_ENV, project_root=app), D.resolve_runtime_root(WIN_ENV, project_root=app)
    block = D.installation_diagnostics(data, runtime, WIN_ENV, project_root=app)
    assert block == {"mode": "installed", "product_home": r"%LOCALAPPDATA%\CIRCOE\Jarvis",
                     "data_root": {"source": "product_home", "label": r"%LOCALAPPDATA%\CIRCOE\Jarvis\data"},
                     "runtime_root": {"source": "product_home", "label": r"%LOCALAPPDATA%\CIRCOE\Jarvis\runtime"}}


# -- chemins : carte macOS ---------------------------------------------------------------------------------------------

def test_macos_home_maps_to_application_support_with_caches_and_logs_in_library():
    home = I.product_home(MAC_ENV, platform=MAC)
    assert posix(home.root) == "/Users/alice/Library/Application Support/CIRCOE/Jarvis"
    assert posix(home.data) == "/Users/alice/Library/Application Support/CIRCOE/Jarvis/data"
    assert posix(home.runtime) == "/Users/alice/Library/Application Support/CIRCOE/Jarvis/runtime"
    assert posix(home.config) == "/Users/alice/Library/Application Support/CIRCOE/Jarvis/config"
    assert posix(home.cache) == "/Users/alice/Library/Caches/CIRCOE/Jarvis"
    assert posix(home.logs) == "/Users/alice/Library/Logs/CIRCOE/Jarvis"
    assert home.label == "~/Library/Application Support/CIRCOE/Jarvis"
    assert home.sub_label("runtime") == "~/Library/Application Support/CIRCOE/Jarvis/runtime"
    assert "alice" not in home.label


@pytest.mark.parametrize("environ", [{}, {"HOME": "  "}, {"HOME": "Users/alice"}, {"HOME": r"C:\Users\alice"},
                                     {"LOCALAPPDATA": r"C:\Users\alice\AppData\Local"}])
def test_macos_refuses_to_start_without_an_absolute_home(environ):
    with pytest.raises(ConfigurationError, match="HOME"):
        I.product_home(environ, platform=MAC)


def test_macos_installed_product_resolves_data_and_runtime_under_application_support(tmp_path, as_mac):
    app = installed_app(tmp_path)
    installation = I.detect_installation(MAC_ENV, code_root=app)
    assert installation.installed and posix(installation.home.root).endswith("Library/Application Support/CIRCOE/Jarvis")
    block = D.installation_diagnostics(installation.home.data, installation.home.runtime, MAC_ENV, project_root=app)
    assert block["product_home"] == "~/Library/Application Support/CIRCOE/Jarvis"
    assert block["data_root"] == {"source": "product_home", "label": "~/Library/Application Support/CIRCOE/Jarvis/data"}
    assert block["runtime_root"]["label"] == "~/Library/Application Support/CIRCOE/Jarvis/runtime"


def test_macos_overrides_keep_priority_like_on_windows(tmp_path, as_mac):
    app = installed_app(tmp_path)
    env = {**MAC_ENV, D.DATA_ROOT_ENV: str(tmp_path / "sbx" / "data"), D.RUNTIME_DIR_ENV: str(tmp_path / "sbx" / "rt")}
    assert D.resolve_data_root(env, project_root=app) == (tmp_path / "sbx" / "data").resolve()
    assert D.resolve_runtime_root(env, project_root=app) == (tmp_path / "sbx" / "rt").resolve()


def test_macos_feedback_label_names_the_home_without_the_user(tmp_path, monkeypatch, as_mac):
    app = installed_app(tmp_path)
    monkeypatch.setattr(I, "CODE_ROOT", app)
    label = feedback_sessions.feedback_dir_label(Path("x") / "run-1", MAC_ENV)
    assert label == "~/Library/Application Support/CIRCOE/Jarvis/data/retours-utilisateur/run-1"


def test_exports_stay_documents_jarvis_outside_the_internal_home_on_macos():
    # Export seulement : `<Documents>/Jarvis` ; la maison interne n'est jamais sous Documents.
    from jarvis.domain.document_export import EXPORT_DIR_NAME

    home = I.product_home(MAC_ENV, platform=MAC)
    documents = PurePosixPath("/Users/alice/Documents")
    assert EXPORT_DIR_NAME == "Jarvis"
    assert documents not in PurePosixPath(posix(home.root)).parents


# -- runtimes privés : disposition POSIX -------------------------------------------------------------------------------

def make_mac_package(root: Path, *, channel: str | None = None, internal_module: bool = False) -> PR.PackageLayout:
    layout = PR.PackageLayout(root, MAC)
    layout.app.mkdir(parents=True)
    (layout.app / I.PRODUCT_MARKER).write_text(json.dumps(I.marker_payload()), encoding="utf-8")
    layout.python_exe.parent.mkdir(parents=True)
    layout.python_exe.write_bytes(b"python3")
    site = layout.python_dir / "lib" / "python3.14" / "site-packages"
    site.mkdir(parents=True)
    if internal_module:
        (site / "onnxruntime").mkdir()
        (site / "onnxruntime" / "__init__.py").write_text("", encoding="utf-8")
    layout.node_exe.parent.mkdir(parents=True)
    layout.node_exe.write_bytes(b"node")
    npm = layout.node_dir / "lib" / "node_modules" / "npm" / "bin"
    npm.mkdir(parents=True)
    (npm / "npm-cli.js").write_text("// npm", encoding="utf-8")
    (root / PR.LICENSES_DIR).mkdir()
    (root / PR.LICENSES_DIR / "PSF.txt").write_text("PSF", encoding="utf-8")
    (root / PR.THIRD_PARTY_MANIFEST).write_text(json.dumps({"components": []}), encoding="utf-8")
    manifest = {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
                "product": {"edition": "presentation", "version": "0.2.0", "platform": "macos-arm64",
                            **({"channel": channel} if channel else {})},
                "excluded": [], "runtimes": {
                    "python": {"version": "3.14.6", "root": "runtime/python", "executable": "runtime/python/bin/python3",
                               "tree_sha256": PR.tree_sha256(layout.python_dir)[0]},
                    "node": {"version": "24.21.0", "root": "runtime/node", "executable": "runtime/node/bin/node",
                             "tree_sha256": PR.tree_sha256(layout.node_dir)[0]}},
                "app": {"tree_sha256": PR.tree_sha256(layout.app)[0]},
                "licenses": {"tree_sha256": PR.tree_sha256(root / PR.LICENSES_DIR)[0]},
                "third_party_manifest_sha256": PR.file_sha256(root / PR.THIRD_PARTY_MANIFEST)}
    manifest["package_sha256"] = PR.package_digest(manifest)
    layout.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return layout


def test_windows_package_layout_is_unchanged(tmp_path):
    layout = PR.PackageLayout(tmp_path, WIN)
    rel = lambda p: p.relative_to(tmp_path).as_posix()  # noqa: E731
    assert [rel(p) for p in (layout.python_exe, layout.node_exe, layout.node_bin_dir, layout.ffmpeg_exe,
                             layout.site_packages)] == [
        "runtime/python/python.exe", "runtime/node/node.exe", "runtime/node", "runtime/ffmpeg/ffmpeg.exe",
        "runtime/python/Lib/site-packages"]
    assert PR.PackageLayout(tmp_path) == PR.PackageLayout(tmp_path, I.host_platform())


def test_macos_package_layout_uses_bin_and_lib_without_exe(tmp_path):
    layout = make_mac_package(tmp_path / "Jarvis")
    rel = lambda p: p.relative_to(tmp_path / "Jarvis").as_posix()  # noqa: E731
    assert rel(layout.python_exe) == "runtime/python/bin/python3"
    assert rel(layout.node_exe) == "runtime/node/bin/node"
    assert rel(layout.ffmpeg_exe) == "runtime/ffmpeg/ffmpeg"
    assert rel(layout.site_packages) == "runtime/python/lib/python3.14/site-packages"
    assert layout.tool("node") == str(layout.node_exe) and layout.tool("python3") == str(layout.python_exe)
    assert layout.tool("npm") is None and layout.tool("ffmpeg") is None  # FFmpeg non livré : jamais le PATH
    assert PR.which("node", layout=layout, fallback=lambda name: pytest.fail("PATH consulted")) == str(layout.node_exe)
    head = PR.child_path(os.pathsep.join(["/usr/bin", "/bin"]), layout=layout).split(os.pathsep)[0]
    assert Path(head) == layout.node_dir / "bin"


def test_macos_site_packages_without_runtime_is_a_missing_path_never_a_guess(tmp_path):
    layout = PR.PackageLayout(tmp_path, MAC)
    assert not layout.site_packages.exists()
    assert layout.site_packages.relative_to(tmp_path).as_posix() == "runtime/python/lib/python3/site-packages"


def test_macos_site_packages_picks_the_highest_minor_numerically_not_alphabetically(tmp_path):
    layout = PR.PackageLayout(tmp_path, MAC)
    for minor in ("python3.9", "python3.14", "python3.x"):
        (layout.python_dir / "lib" / minor / "site-packages").mkdir(parents=True)
    assert layout.site_packages.relative_to(tmp_path).as_posix() == "runtime/python/lib/python3.14/site-packages"


def test_a_simulated_macos_package_verifies_clean_and_a_tampered_one_does_not(tmp_path):
    layout = make_mac_package(tmp_path / "Jarvis")
    manifest, problems = PR.verify_package(layout)
    assert problems == [] and manifest["product"]["platform"] == "macos-arm64"
    layout.node_exe.write_bytes(b"node, altered")
    assert any(problem.startswith("node: private_runtime_integrity_failed") for problem in PR.verify_package(layout)[1])


def test_a_macos_production_package_refuses_internal_only_modules_in_its_posix_site_packages(tmp_path):
    layout = make_mac_package(tmp_path / "Jarvis", internal_module=True)
    problems = PR.verify_package(layout)[1]
    assert any("onnxruntime" in problem and "HD-V12-01" in problem for problem in problems)


def test_npm_is_found_in_the_official_posix_node_layout(tmp_path):
    layout = make_mac_package(tmp_path / "Jarvis")
    spec = NodeRuntimeSpec(tmp_path, "18.0.0", "9.0.0", frozenset({"darwin-arm64"}))
    posix_runner = NodeCapabilityRunner(spec, which=lambda name: None, environ={}, windows=False)
    assert posix_runner._npm_argv(str(layout.node_exe)) == [
        str(layout.node_exe), str((layout.node_dir / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"))]
    # Windows : seule la disposition côte à côte compte, comme avant.
    windows_runner = NodeCapabilityRunner(spec, which=lambda name: None, environ={}, windows=True)
    assert windows_runner._npm_argv(str(layout.node_exe)) is None


# -- Chrome / Edge pour Remotion ---------------------------------------------------------------------------------------

def test_windows_browser_candidates_are_unchanged(monkeypatch):
    monkeypatch.setattr(RR, "sys", SimpleNamespace(platform="win32"))
    assert RR._browser_candidates(WIN_ENV, lambda name: None) == [
        str(Path(r"C:\Program Files") / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(r"C:\Program Files (x86)") / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(r"C:\Users\alice\AppData\Local") / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(r"C:\Program Files (x86)") / "Microsoft" / "Edge" / "Application" / "msedge.exe")]


def test_macos_browser_candidates_cover_chrome_edge_chromium_system_then_user(monkeypatch):
    monkeypatch.setattr(RR, "sys", SimpleNamespace(platform="darwin"))
    found = RR._browser_candidates(MAC_ENV, lambda name: pytest.fail("PATH consulted on macOS"))
    assert found[0] == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" in found
    assert "/Applications/Chromium.app/Contents/MacOS/Chromium" in found
    assert found[3] == "/Users/alice/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert len(found) == 6
    assert RR._browser_candidates({"JARVIS_REMOTION_RENDER_BROWSER": "/opt/c"}, lambda name: None) == ["/opt/c"]


def test_macos_without_home_only_looks_in_system_applications(monkeypatch):
    monkeypatch.setattr(RR, "sys", SimpleNamespace(platform="darwin"))
    assert all(path.startswith("/Applications/") for path in RR._browser_candidates({}, lambda name: None))


# -- secrets : refus explicite sur macOS --------------------------------------------------------------------------------

def test_macos_secret_sealer_refuses_and_says_why(monkeypatch):
    monkeypatch.setattr(dpapi_sealer, "sys", SimpleNamespace(platform="darwin"))
    sealer = dpapi_sealer.default_sealer(local_secrets.CREDENTIALS_ENTROPY)
    assert not sealer.available and "Keychain" in sealer.unavailable_reason
    with pytest.raises(SealerError, match="clear text"):
        sealer.seal(b"sk-secret")
    settings = {"credentials": [{"provider": "openai", "value": "sk-secret"}]}
    with pytest.raises(local_secrets.LocalSecretsError) as refused:
        local_secrets.seal_settings(settings, sealer)
    assert refused.value.code == local_secrets.VAULT_UNAVAILABLE
    assert settings["credentials"][0]["value"] == "sk-secret"  # rien n'est touché, rien n'est écrit en clair ailleurs


def test_windows_still_gets_dpapi(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("DPAPI exists only on Windows")
    assert isinstance(dpapi_sealer.default_sealer(), dpapi_sealer.DpapiSealer)


# -- arbre de processus : groupe POSIX -----------------------------------------------------------------------------------

class FakeKernel:
    def __init__(self):
        self.groups: dict[int, int] = {}
        self.signals: list[tuple[int, int]] = []

    def getpgid(self, pid):
        if pid not in self.groups:
            raise ProcessLookupError(pid)
        return self.groups[pid]

    def killpg(self, pgid, sig):
        if pgid not in self.groups.values():
            raise ProcessLookupError(pgid)
        self.signals.append((pgid, sig))
        if sig:
            self.groups = {pid: group for pid, group in self.groups.items() if group != pgid}


def test_a_posix_tree_kills_the_whole_group_and_reports_it_empty():
    kernel = FakeKernel()
    kernel.groups = {500: 500, 501: 500, 502: 500, 77: 77}  # 500 et ses descendants ; 77 est un étranger
    tree = OPT.OwnedProcessTree(api=OPT.PosixProcessGroupAPI(killpg=kernel.killpg, getpgid=kernel.getpgid))
    tree.attach_and_resume(500)
    assert tree.api.contains(tree.handle, 501) and not tree.api.contains(tree.handle, 77)
    assert tree.close_if_empty() is False  # le groupe vit encore
    tree.terminate()
    assert kernel.signals[-1] == (500, getattr(signal, "SIGKILL", 9))
    assert kernel.groups == {77: 77}
    assert tree.close_if_empty() is True and tree.handle is None


def test_a_posix_child_outside_its_own_group_is_refused_never_killed_by_group():
    kernel = FakeKernel()
    kernel.groups = {600: 1}  # né dans le groupe 1 (pas de start_new_session) : tuer « son » groupe tuerait le nôtre
    tree = OPT.OwnedProcessTree(api=OPT.PosixProcessGroupAPI(killpg=kernel.killpg, getpgid=kernel.getpgid))
    with pytest.raises(OSError, match="not_isolated"):
        tree.attach_and_resume(600)
    tree.terminate()
    assert kernel.signals == []


def test_a_posix_group_already_gone_is_a_clean_terminate():
    kernel = FakeKernel()
    kernel.groups = {700: 700}
    tree = OPT.OwnedProcessTree(api=OPT.PosixProcessGroupAPI(killpg=kernel.killpg, getpgid=kernel.getpgid))
    tree.attach_and_resume(700)
    kernel.groups.clear()
    tree.terminate()
    assert tree.close_if_empty() is True


def test_posix_api_without_process_groups_is_unavailable_not_a_silent_no_op(monkeypatch):
    monkeypatch.delattr(os, "killpg", raising=False)
    with pytest.raises(OSError, match="unavailable"):
        OPT.PosixProcessGroupAPI(getpgid=lambda pid: pid)


def test_spawn_arguments_per_platform(monkeypatch):
    tree = SimpleNamespace(creationflags=0x08000004)
    monkeypatch.setattr(OPT, "IS_WINDOWS", True)
    assert OPT.spawn_kwargs(tree) == {"creationflags": 0x08000004}  # l'argument exact d'avant la Slice 08
    monkeypatch.setattr(OPT, "IS_WINDOWS", False)
    assert OPT.spawn_kwargs(tree) == {"start_new_session": True}


def test_windows_tree_class_flags_are_unchanged():
    if os.name != "nt":
        pytest.skip("Windows class attributes")
    assert OPT.OwnedProcessTree.creationflags == OPT.CREATE_SUSPENDED | OPT.CREATE_NO_WINDOW
    assert OPT.OwnedProcessTree.start_new_session is False


# -- lanceur : groupe de processus et verrou d'instance ------------------------------------------------------------------

class SessionTree:
    creationflags = 0
    start_new_session = True

    def attach_and_resume(self, pid):
        self.attached = pid

    def terminate(self):
        pass

    def close_if_empty(self):
        return True


class Proc:
    pid = 4242

    def poll(self):
        return None


def test_the_launcher_starts_a_posix_child_in_its_own_session(tmp_path):
    calls = []
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    plan = L.LaunchPlan(python="/pkg/runtime/python/bin/python3", runtime_root=runtime, core_url="http://127.77.0.1:1",
                        ui_url="http://127.0.0.1:2/", token_file=runtime / "core.token",
                        roles=[L.Role("core", ("core",), True)], env={"PATH": "/usr/bin"}, start_timeout_s=1.0)
    launcher = L.Launcher(plan, log=L.LauncherLog(runtime / "launcher.log"), notify=lambda *a: None,
                          open_url=lambda url: None, spawn=lambda argv, **kw: calls.append(kw) or Proc(),
                          tree_factory=SessionTree)
    launcher.start_role(plan.roles[0])
    assert calls[0]["start_new_session"] is True
    assert calls[0]["creationflags"] == (L.CREATE_NO_WINDOW if os.name == "nt" else 0)
    plan.roles[0].log.close()


def test_the_launcher_never_passes_a_session_argument_for_a_windows_job(tmp_path):
    calls = []
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    class JobTree(SessionTree):
        creationflags = 0x4
        start_new_session = False

    plan = L.LaunchPlan(python="X:/python.exe", runtime_root=runtime, core_url="http://127.77.0.1:1",
                        ui_url="http://127.0.0.1:2/", token_file=runtime / "core.token",
                        roles=[L.Role("core", ("core",), True)], env={}, start_timeout_s=1.0)
    launcher = L.Launcher(plan, log=L.LauncherLog(runtime / "launcher.log"), notify=lambda *a: None,
                          open_url=lambda url: None, spawn=lambda argv, **kw: calls.append(kw) or Proc(),
                          tree_factory=JobTree)
    launcher.start_role(plan.roles[0])
    assert "start_new_session" not in calls[0]
    plan.roles[0].log.close()


class FakeFcntl:
    LOCK_EX, LOCK_NB = 2, 4

    def __init__(self):
        self.held = False
        self.calls = []

    def flock(self, fd, flags):
        self.calls.append(flags)
        if self.held:
            raise BlockingIOError(11, "Resource temporarily unavailable")
        self.held = True


def test_the_instance_lock_uses_a_non_blocking_exclusive_flock_on_posix(tmp_path, monkeypatch):
    fake = FakeFcntl()
    monkeypatch.setitem(sys.modules, "fcntl", fake)
    monkeypatch.setattr(L, "os", SimpleNamespace(name="posix"))
    first, second = L.InstanceLock(tmp_path / "launcher.lock"), L.InstanceLock(tmp_path / "launcher.lock")
    assert first.acquire() is True
    assert second.acquire() is False and second._handle is None  # deuxième clic : refus, poignée refermée
    assert fake.calls == [fake.LOCK_EX | fake.LOCK_NB] * 2
    first.release()
    assert first._handle is None


# -- noyau POSIX réel : job CI macOS seulement ----------------------------------------------------------------------------

@posix_only
def test_real_flock_excludes_a_second_instance_and_is_released(tmp_path):
    first, second = L.InstanceLock(tmp_path / "launcher.lock"), L.InstanceLock(tmp_path / "launcher.lock")
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


@posix_only
def test_real_process_group_kill_takes_the_grandchildren_too(tmp_path):
    tree = OPT.OwnedProcessTree()
    marker = tmp_path / "grandchild.pid"
    proc = subprocess.Popen(["/bin/sh", "-c", f"sleep 60 & echo $! > '{marker}'; wait"], **OPT.spawn_kwargs(tree))
    try:
        tree.attach_and_resume(proc.pid)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        grandchild = int(marker.read_text().strip())
        tree.terminate()
        proc.wait(timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("grandchild survived the group kill")
        assert tree.close_if_empty() is True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


# -- paquet macOS : plan et vérification (aucun paquet construit) --------------------------------------------------------

def macos_package_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "jarvis_macos_package", Path(__file__).resolve().parents[2] / "packaging" / "macos" / "macos_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_macos_runtime_pins_are_complete_and_aligned_with_windows():
    M = macos_package_module()
    assert M.pin_problems(M.load_json(M.RUNTIMES_FILE), M.load_json(M.WINDOWS_RUNTIMES_FILE)) == []
    assert M.main(["check-pins"]) == 0


def test_an_unpinned_or_misaligned_runtime_is_named():
    M = macos_package_module()
    runtimes = M.load_json(M.RUNTIMES_FILE)
    runtimes["architectures"]["x64"]["node"]["sha256"] = "to-pin"
    runtimes["architectures"]["arm64"]["python"]["version"] = "3.14.7"
    del runtimes["architectures"]["arm64"]["node"]
    problems = M.pin_problems(runtimes, M.load_json(M.WINDOWS_RUNTIMES_FILE))
    assert "x64.node.sha256: à épingler (64 caractères hexadécimaux attendus)" in problems
    assert any(p.startswith("arm64.python.version: 3.14.7") for p in problems)
    assert "arm64.node: runtime absent" in problems


@pytest.mark.parametrize("arch", ["arm64", "x64"])
def test_the_bundle_plan_keeps_user_state_outside_the_bundle_and_claims_no_support(arch):
    M = macos_package_module()
    plan = M.bundle_plan(arch, M.load_json(M.RUNTIMES_FILE))
    assert plan["launcher"]["argv"][0] == "../Resources/package/runtime/python/bin/python3"
    assert plan["runtimes"]["node"]["executable"] == "Jarvis.app/Contents/Resources/package/runtime/node/bin/node"
    assert plan["code_root"].endswith("/package/app")
    assert plan["supported"] is False and plan["support_gate"] == "HV-V12-MAC-01"
    assert "Application Support" in plan["user_state"] and plan["exports"].startswith("~/Documents/Jarvis")
    with pytest.raises(ValueError):
        M.bundle_plan("universal", M.load_json(M.RUNTIMES_FILE))


def test_info_plist_and_entitlements_declare_microphone_and_runtime_needs():
    import plistlib

    M = macos_package_module()
    info = plistlib.loads(M.INFO_PLIST.read_bytes())
    assert info["CFBundleIdentifier"] == "com.circoe.jarvis" and info["CFBundleExecutable"] == "jarvis-launcher"
    assert info["NSMicrophoneUsageDescription"] and info["LSMinimumSystemVersion"] == "13.5"
    entitlements = plistlib.loads(M.ENTITLEMENTS.read_bytes())
    assert entitlements["com.apple.security.device.audio-input"] is True
    assert entitlements["com.apple.security.cs.allow-jit"] is True
    assert "com.apple.security.app-sandbox" not in entitlements


def test_macos_verify_accepts_a_clean_tree_and_names_windows_leftovers(tmp_path):
    M = macos_package_module()
    layout = make_mac_package(tmp_path / "Jarvis")
    assert M.verify(layout.install_root)[1] == []
    assert M.main(["verify", str(layout.install_root)]) == 0
    (layout.site_packages / "pywin32-311.dist-info").mkdir()
    (layout.node_dir / "bin" / "npm.cmd").write_text("@echo off", encoding="utf-8")
    problems = M.verify(layout.install_root)[1]
    assert "pywin32: module réservé à Windows dans un paquet macOS" in problems
    assert "runtime/node/bin/npm.cmd: fichier Windows dans un paquet macOS" in problems
    assert any(p.startswith("node: private_runtime_integrity_failed") for p in problems)  # l'arbre a changé aussi
    assert M.main(["verify", str(layout.install_root)]) == 1


def test_the_platform_policy_names_every_platform_conditional_dependency_of_the_lock():
    M = macos_package_module()
    policy = M.load_json(M.POLICY_FILE)
    lock = (Path(M.REPO) / "packaging" / "windows" / "requirements.lock").read_text(encoding="utf-8")
    for package in policy["windows_only_packages"]:
        assert f"\n{package}==" in lock  # présent dans le verrou Windows, donc à exclure du verrou macOS
    assert {"pyobjc-framework-quartz", "pyobjc-framework-applicationservices"} <= set(policy["macos_only_packages"])
    assert all(entry["status"] == "to-lock" for entry in policy["macos_only_packages"].values())


# -- CLI Claude et smoke de Core -----------------------------------------------------------------------------------------

def test_claude_cli_known_locations_per_platform():
    from jarvis.runtime import brain_cli

    windows = brain_cli.known_locations({"USERPROFILE": "U", "APPDATA": "A", "LOCALAPPDATA": "L"}, platform="win32")
    assert windows == [Path("U") / ".local" / "bin" / "claude.exe", Path("A") / "npm" / "claude.cmd",
                       Path("L") / "Microsoft" / "WinGet" / "Links" / "claude.exe"]
    mac = brain_cli.known_locations({"HOME": "/Users/alice", "USERPROFILE": "U"}, platform="darwin")
    assert [p.as_posix() for p in mac] == ["/Users/alice/.local/bin/claude", "/opt/homebrew/bin/claude",
                                           "/usr/local/bin/claude"]
    assert [p.as_posix() for p in brain_cli.known_locations({}, platform="darwin")] == [
        "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]


def core_smoke_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "jarvis_core_smoke", Path(__file__).resolve().parents[2] / "scripts" / "core_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_core_smoke_sandbox_drops_provider_keys_and_moves_every_root(tmp_path, monkeypatch):
    S = core_smoke_module()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    env = S.sandbox_env(tmp_path, "127.0.0.1", 63653)
    assert "OPENAI_API_KEY" not in env and "ANTHROPIC_API_KEY" not in env
    for key in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "JARVIS_DATA_ROOT", "JARVIS_RUNTIME_DIR"):
        assert Path(env[key]).is_relative_to(tmp_path), key
    assert (env["JARVIS_CORE_HOST"], env["JARVIS_CORE_PORT"], env["JARVIS_UI_PORT"]) == ("127.0.0.1", "63653", "63654")
    assert env["JARVIS_VISUALIZER_ENABLED"] == env["JARVIS_OPEN_BROWSER"] == env["JARVIS_LAUNCH_VOICE"] == "0"


def test_core_smoke_refuses_a_folder_that_already_has_content(tmp_path, capsys):
    S = core_smoke_module()
    (tmp_path / "state").mkdir()
    assert S.main(["--work", str(tmp_path)]) == 2
    assert "not empty" in capsys.readouterr().err


# -- sites de lancement des CLI : arguments de l'arbre possédé, par plateforme ---------------------------------------------

from tests.unit.test_back_brain_worker import harness, job, until  # noqa: E402,F401 - fixture `harness` réutilisée


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("windows", [True, False])
async def test_owned_cli_sites_pass_the_tree_spawn_arguments_of_their_platform(harness, monkeypatch, provider, windows):
    """`claude_local` et `codex_local` passent `spawn_kwargs(tree)` : supprimer l'argument, ou le figer sur une seule
    plateforme, est vu ici (Windows : `creationflags` exact d'avant la Slice 08 ; POSIX : session propre)."""

    monkeypatch.setattr(OPT, "IS_WINDOWS", windows)
    worker = harness.worker(provider)

    class Progress:
        async def emit(self, job_id, value):
            pass

    running = asyncio.create_task(worker.execute_with_progress(job(), Progress()))
    try:
        await until(lambda: harness.calls)
        _argv, kwargs = harness.calls[0]
        if windows:
            assert kwargs["creationflags"] == 0x08000004 and "start_new_session" not in kwargs
        else:
            assert kwargs["start_new_session"] is True and "creationflags" not in kwargs
        assert harness.trees and harness.trees[0].pid is not None  # l'enfant est rattaché à SON arbre
    finally:
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)
