"""Runtimes privés du paquet Windows : jamais le PATH du poste en produit installé (`docs/windows-packaging.md`).

Contrat : `jarvis/private_runtime.py`. Paquet simulé dans `tmp_path` (marqueur + faux exécutables) ; aucun vrai
paquet, aucun `%LOCALAPPDATA%` réel.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

from jarvis import private_runtime as PR
from jarvis.adapters import process_tree, screen_capture
from jarvis.adapters.node_capability_runner import NodeCapabilityRunner, NodeRuntimeSpec
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.local_capabilities import new_manifest
from jarvis.installation import PRODUCT_MARKER, marker_payload


def make_package(root: Path, *, node: bool = True, python: bool = True, manifest: dict | None = None,
                 ffmpeg: bool = False) -> PR.PackageLayout:
    app = root / PR.APP_DIR
    app.mkdir(parents=True)
    (app / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    layout = PR.PackageLayout(root)
    if node:
        layout.node_dir.mkdir(parents=True)
        layout.node_exe.write_bytes(b"node")
    if python:
        layout.python_dir.mkdir(parents=True)
        layout.python_exe.write_bytes(b"python")
    if ffmpeg:
        layout.ffmpeg_exe.parent.mkdir(parents=True)
        layout.ffmpeg_exe.write_bytes(b"ffmpeg")
    if manifest is None:
        manifest = {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
                    "product": {"edition": "presentation", "version": "0.2.0"}, "excluded": [{"id": "imageio-ffmpeg"}],
                    "runtimes": {}}
        for name, present in (("python", python), ("node", node)):
            if present:
                tree, _ = PR.tree_sha256(root / PR.RUNTIME_DIR / name)
                manifest["runtimes"][name] = {"version": "1.0.0", "root": f"runtime/{name}",
                                              "executable": f"runtime/{name}/{name}.exe", "tree_sha256": tree}
        if ffmpeg:
            manifest["runtimes"]["ffmpeg"] = {"version": "7", "root": "runtime/ffmpeg", "executable": "runtime/ffmpeg/ffmpeg.exe",
                                              "tree_sha256": PR.tree_sha256(root / "runtime" / "ffmpeg")[0]}
    if manifest is not False:
        layout.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return layout


def never(name):  # le PATH du poste : ne doit jamais être consulté pour un outil possédé par le paquet
    raise AssertionError(f"PATH consulted for {name}")


# -- identité ----------------------------------------------------------------------------------------------------

def test_a_checkout_without_marker_has_no_package_and_keeps_path_lookup(tmp_path):
    assert PR.layout_for(tmp_path) is None
    assert PR.which("node", layout=None, fallback=lambda name: f"PATH:{name}") == "PATH:node"
    assert PR.child_path("A;B", layout=None) == "A;B"
    assert "on PATH" in PR.missing_tool_hint("Node.js", layout=None)
    assert PR.diagnostics(None) == {"mode": "development", "source": "path"}


def test_this_repository_runs_as_a_development_checkout():
    assert PR.package_layout() is None  # aucun marqueur dans le dépôt : le JARVIS quotidien garde PATH et .venv


def test_the_package_is_the_parent_of_the_code_root(tmp_path):
    layout = make_package(tmp_path / "Jarvis")
    found = PR.layout_for(layout.app)
    assert found == PR.PackageLayout(tmp_path / "Jarvis")
    assert found.node_exe == tmp_path / "Jarvis" / "runtime" / "node" / "node.exe"


def test_an_unreadable_marker_refuses_instead_of_falling_back_to_path(tmp_path):
    (tmp_path / PRODUCT_MARKER).write_text("{", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        PR.layout_for(tmp_path)


# -- résolution des outils -----------------------------------------------------------------------------------------

def test_installed_node_is_the_private_one_and_never_the_path(tmp_path):
    layout = make_package(tmp_path / "Jarvis")
    assert PR.which("node", layout=layout, fallback=never) == str(layout.node_exe)
    assert PR.which("node.exe", layout=layout, fallback=never) == str(layout.node_exe)
    for name in ("npm", "npm.cmd", "npx", "py", "ffprobe"):
        assert PR.which(name, layout=layout, fallback=never) is None
    assert PR.which("python", layout=layout, fallback=never) == str(layout.python_exe)


def test_a_missing_private_node_is_absent_not_found_elsewhere(tmp_path):
    layout = make_package(tmp_path / "Jarvis", node=False)
    assert PR.which("node", layout=layout, fallback=never) is None
    assert "repair or reinstall Jarvis" in PR.missing_tool_hint("Node.js", layout=layout)


def test_external_tools_stay_on_the_path_in_the_installed_product(tmp_path):
    layout = make_package(tmp_path / "Jarvis")
    assert PR.which("claude", layout=layout, fallback=lambda name: f"PATH:{name}") == "PATH:claude"


def test_ffmpeg_only_when_the_manifest_ships_it(tmp_path):
    without = make_package(tmp_path / "a")
    assert PR.which("ffmpeg", layout=without, fallback=never) is None
    shipped = make_package(tmp_path / "b", ffmpeg=True)
    assert PR.which("ffmpeg", layout=shipped, fallback=never) == str(shipped.ffmpeg_exe)


def test_child_path_puts_the_private_node_first_once(tmp_path):
    layout = make_package(tmp_path / "Jarvis")
    head = str(layout.node_dir)
    value = PR.child_path(os.pathsep.join([r"C:\Windows", head, r"C:\Program Files\nodejs"]), layout=layout)
    parts = value.split(os.pathsep)
    assert parts[0] == head and parts.count(head) == 1 and r"C:\Program Files\nodejs" in parts


# -- branchement dans les adaptateurs ------------------------------------------------------------------------------

def test_every_node_runner_resolves_through_the_private_runtime_by_default():
    for cls in (NodeCapabilityRunner, RemotionRenderRunner, RemotionStudioRunner):
        assert inspect.signature(cls.__init__).parameters["which"].default is PR.which, cls.__name__


def test_clean_env_prepends_the_private_node_in_the_installed_product(tmp_path, monkeypatch):
    layout = make_package(tmp_path / "Jarvis")
    monkeypatch.setattr(PR, "package_layout", lambda: layout)
    env = process_tree.clean_env(environ={"Path": r"C:\Windows", "OPENAI_API_KEY": "x"})
    assert env["Path"].split(os.pathsep)[0] == str(layout.node_dir)
    assert "OPENAI_API_KEY" not in env and "PATH" not in env


def test_clean_env_is_unchanged_in_development():
    env = process_tree.clean_env(environ={"PATH": r"C:\Windows;C:\nodejs", "SECRET": "x"})
    assert env == {"PATH": r"C:\Windows;C:\nodejs"}


def test_node_runner_names_the_installation_when_its_node_is_missing(tmp_path, monkeypatch):
    layout = make_package(tmp_path / "Jarvis", node=False)
    monkeypatch.setattr(PR, "package_layout", lambda: layout)
    runner = NodeCapabilityRunner(NodeRuntimeSpec(tmp_path, "20.0.0", "9.0.0", frozenset({"win32-x64"})))
    manifest = new_manifest(capability_id="remotion", display_name="Remotion", components={"remotion": "1.0.0"},
                            requirements=[("node", "20.0.0")], entrypoint="main")
    (missing,) = runner.check_requirements(manifest)
    assert missing.startswith("node_missing:") and "repair or reinstall Jarvis" in missing


def test_screen_recording_has_no_ffmpeg_in_the_presentation_package(tmp_path, monkeypatch):
    layout = make_package(tmp_path / "Jarvis")
    monkeypatch.setattr(PR, "package_layout", lambda: layout)
    monkeypatch.delenv("JARVIS_FFMPEG_EXE", raising=False)
    assert screen_capture.find_ffmpeg() is None


# -- manifeste et diagnostic -----------------------------------------------------------------------------------------

def test_diagnostics_report_versions_without_paths(tmp_path):
    layout = make_package(tmp_path / "Jarvis")
    report = PR.diagnostics(layout)
    assert report["status"] == "ok" and report["runtimes"] == {"node": "1.0.0", "python": "1.0.0"}
    assert report["excluded"] == ["imageio-ffmpeg"] and report["edition"] == "presentation"
    assert str(tmp_path) not in json.dumps(report)


def test_diagnostics_name_a_missing_manifest_and_a_missing_runtime(tmp_path):
    assert PR.diagnostics(make_package(tmp_path / "a", manifest=False))["problems"][0]["code"] == "runtime_manifest_missing"
    layout = make_package(tmp_path / "b")
    layout.node_exe.unlink()
    report = PR.diagnostics(layout)
    assert report["status"] == "degraded"
    assert report["problems"] == [{"code": "private_runtime_missing", "component": "node", "detail": "runtime/node/node.exe absent"}]


def test_a_manifest_of_another_schema_is_invalid(tmp_path):
    layout = make_package(tmp_path / "Jarvis", manifest={"schema": "other", "schema_version": 1})
    assert PR.diagnostics(layout)["problems"][0]["code"] == "runtime_manifest_invalid"
    assert PR.verify_runtimes(layout)[0].code is PR.RuntimeProblemCode.MANIFEST_INVALID


def test_verify_detects_a_changed_runtime_file(tmp_path):
    layout = make_package(tmp_path / "Jarvis")
    assert PR.verify_runtimes(layout) == []
    (layout.node_dir / "extra.dll").write_bytes(b"planted")
    (problem,) = PR.verify_runtimes(layout)
    assert problem.code is PR.RuntimeProblemCode.INTEGRITY_FAILED and problem.component == "node"


def test_tree_digest_does_not_depend_on_the_install_folder(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name / "sub").mkdir(parents=True)
        (tmp_path / name / "sub" / "f.txt").write_bytes(b"same")
    assert PR.tree_sha256(tmp_path / "a") == PR.tree_sha256(tmp_path / "b")


# -- reprise QA S06 -------------------------------------------------------------------------------------------------

def base_manifest(**changes) -> dict:
    manifest = {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
                "product": {"edition": "presentation"}, "excluded": [],
                "runtimes": {"node": {"version": "1", "root": "runtime/node", "executable": "runtime/node/node.exe",
                                      "tree_sha256": "0" * 64}}}
    return manifest | changes


@pytest.mark.parametrize("changes", [
    {"runtimes": {"node": "x"}}, {"runtimes": ["node"]}, {"product": "p"}, {"excluded": ["a"]}, {"excluded": "a"},
    {"runtimes": {"node": {"root": "", "executable": "runtime/node/node.exe"}}},
    {"runtimes": {"node": {"root": "../outside", "executable": "runtime/node/node.exe"}}},
    {"runtimes": {"node": {"root": "C:/elsewhere", "executable": "runtime/node/node.exe"}}},
    {"runtimes": {"node": {"root": "/abs", "executable": "runtime/node/node.exe"}}},
    {"runtimes": {"node": {"root": "runtime/node", "executable": None}}}])
def test_a_manifest_of_the_wrong_shape_is_invalid_never_a_crash(tmp_path, changes):
    layout = make_package(tmp_path / "Jarvis", manifest=base_manifest(**changes))
    report = PR.diagnostics(layout)
    assert report["status"] == "invalid" and report["problems"][0]["code"] == "runtime_manifest_invalid"
    assert PR.verify_runtimes(layout)[0].code is PR.RuntimeProblemCode.MANIFEST_INVALID
    assert PR.which("node", layout=layout, fallback=never) == layout.tool("node")  # résolution inchangée, jamais le PATH


def test_runtime_reserve_names_each_problem_only_when_runtimes_are_broken(tmp_path):
    assert PR.runtime_reserve({"mode": "development", "source": "path"}) is None
    assert PR.runtime_reserve(PR.diagnostics(make_package(tmp_path / "ok"))) is None
    layout = make_package(tmp_path / "broken")
    layout.node_exe.unlink()
    reserve = PR.runtime_reserve(PR.diagnostics(layout))
    assert reserve.startswith("private runtimes degraded") and "node: private_runtime_missing" in reserve
    assert "repair or reinstall Jarvis" in reserve and str(tmp_path) not in reserve
    assert "runtime_manifest_missing" in PR.runtime_reserve(PR.diagnostics(make_package(tmp_path / "m", manifest=False)))


def _health(installation: dict | None, status: str = "ok") -> dict:
    import asyncio
    from dataclasses import dataclass
    from enum import Enum
    from types import SimpleNamespace

    from jarvis.protocol.server import LocalProtocolServer

    class State(Enum):
        READY = "ready"

    @dataclass
    class Counters:
        emitted: int = 0

    core = SimpleNamespace(
        health=SimpleNamespace(ready=True, status=status, detail=""),
        scene=SimpleNamespace(availability=SimpleNamespace(state=State.READY, code=None), capacity=None),
        conversation_events=SimpleNamespace(unreadable_rows=0, diagnostic_failures=0),
        conversation_event_emitter=SimpleNamespace(counters=Counters()),
        conversation_event_queries=SimpleNamespace(failures=0))
    server = LocalProtocolServer(core, host="127.0.0.1", port=1, token="t" * 40, installation=installation)
    return json.loads(asyncio.run(server.health(None)).body)


def test_health_is_never_ok_without_reserve_when_the_package_runtimes_are_broken(tmp_path):
    layout = make_package(tmp_path / "Jarvis")
    healthy = _health({"mode": "installed", "runtimes": PR.diagnostics(layout)})
    assert healthy["status"] == "ok" and healthy["ready"] is True
    layout.node_exe.unlink()
    broken = _health({"mode": "installed", "runtimes": PR.diagnostics(layout)})
    assert broken["status"] == "degraded" and broken["ready"] is True
    assert "node: private_runtime_missing" in broken["detail"]
    assert _health({"mode": "development", "runtimes": PR.diagnostics(None)})["status"] == "ok"
    # Un Core déjà en panne garde sa propre cause : la réserve ne la masque pas.
    assert _health({"mode": "installed", "runtimes": PR.diagnostics(layout)}, status="fail")["status"] == "fail"


def test_screen_recording_ignores_an_importable_imageio_ffmpeg_in_the_presentation_package(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    planted = tmp_path / "ffmpeg.exe"
    planted.write_bytes(b"gpl")
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", SimpleNamespace(get_ffmpeg_exe=lambda: str(planted)))
    monkeypatch.delenv("JARVIS_FFMPEG_EXE", raising=False)
    monkeypatch.setattr(PR, "package_layout", lambda: None)
    assert screen_capture.find_ffmpeg() == str(planted)  # développement : l'extra `capture` sert
    monkeypatch.setattr(PR, "package_layout", lambda: make_package(tmp_path / "Jarvis"))
    assert screen_capture.find_ffmpeg() is None  # produit installé : jamais le FFmpeg GPL d'imageio
