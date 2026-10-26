"""Paquet Windows de l'édition presentation : verrou, politique de licences, runtimes épinglés (`docs/windows-packaging.md`).

Conformité des entrées versionnées (`packaging/windows/`) et des fonctions pures du build ; aucun téléchargement, aucun
vrai build (celui-ci est prouvé en runtime, LOG de la Slice 06).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging" / "windows"


def load_builder():
    spec = importlib.util.spec_from_file_location("jarvis_build_package", PACKAGING / "build_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = load_builder()
RUNTIMES = json.loads((PACKAGING / "runtimes.json").read_text(encoding="utf-8"))
POLICY = json.loads((PACKAGING / "third_party_policy.json").read_text(encoding="utf-8"))
LOCK = B.parse_lock((PACKAGING / "requirements.lock").read_text(encoding="utf-8"))
LOCKED = {row["name"]: row for row in LOCK}


def top_level_pins() -> dict[str, str]:
    pins = {}
    for line in (PACKAGING / "requirements.in").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, version = line.split("==")
            pins[B.normalize(name)] = version
    return pins


# -- verrou ---------------------------------------------------------------------------------------------------------

def test_every_locked_wheel_has_an_exact_version_and_a_sha256():
    assert len(LOCK) >= 50
    assert len(LOCKED) == len(LOCK), "un nom verrouillé deux fois"
    for row in LOCK:
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) and row["version"]


def test_top_level_pins_are_locked_at_the_same_version():
    for name, version in top_level_pins().items():
        assert LOCKED[name]["version"] == version, name


def test_the_lock_covers_the_base_dependencies_of_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    base = re.search(r"dependencies = \[(.*?)\]", text, re.S)[1]
    for name in re.findall(r'"([A-Za-z0-9_.-]+)', base):
        assert B.normalize(name) in LOCKED, name


def test_lock_rendering_round_trips():
    assert B.parse_lock(B.render_lock(LOCK)) == sorted(LOCK, key=lambda r: r["name"])


def test_a_lock_line_without_hash_is_refused():
    with pytest.raises(B.BuildError):
        B.parse_lock("httpx==0.28.1\n")


# -- politique de licences ---------------------------------------------------------------------------------------------

def test_every_locked_wheel_has_a_policy_entry_and_nothing_else():
    declared = {B.normalize(name) for name in POLICY["python_packages"]}
    assert declared == set(LOCKED)
    for name, entry in POLICY["python_packages"].items():
        assert entry["status"] == "bundled" and entry["license"], name


@pytest.mark.parametrize("excluded", ["openwakeword", "onnxruntime", "imageio-ffmpeg", "pvporcupine", "sherpa-onnx"])
def test_license_gated_components_are_not_in_the_presentation_lock(excluded):
    assert excluded not in LOCKED
    assert excluded in {item["id"] for item in POLICY["excluded"]}


def test_agpl_and_non_commercial_components_are_excluded_with_a_human_decision():
    by_id = {item["id"]: item for item in POLICY["excluded"]}
    for name, decision in (("barehands", "HV-PACKAGE-06"), ("ai-visualizer", "HV-PACKAGE-06"),
                           ("openwakeword-models", "HV-PACKAGE-04"), ("imageio-ffmpeg", "HV-PACKAGE-03")):
        assert by_id[name]["decision"] == decision


def test_copyleft_wheels_carry_a_distribution_note():
    for name, entry in POLICY["python_packages"].items():
        if re.search(r"GPL|MPL", entry["license"]):
            assert entry.get("notes"), name


def test_external_and_provisioned_dependencies_are_declared():
    assert {item["id"] for item in POLICY["external"]} >= {"claude-code-cli", "chrome-or-edge"}
    assert {item["id"] for item in POLICY["provisioned"]} == {"remotion-npm-packages"}


def test_the_human_decisions_named_by_the_policy_exist_in_the_slice():
    validation = json.loads((ROOT / "tasks" / "jarvis-presentation-edition-v1" / "slices" / "06-windows-private-runtime-packaging"
                             / "human-validation.json").read_text(encoding="utf-8"))
    ids = {check["id"] for check in validation["checks"]}
    named = {item.get("decision") for group in ("excluded", "external", "provisioned") for item in POLICY[group]}
    assert named - {None} <= ids


# -- runtimes épinglés ------------------------------------------------------------------------------------------------

def test_runtimes_are_pinned_to_official_sources_with_sha256():
    hosts = {"python": "https://www.python.org/ftp/python/", "node": "https://nodejs.org/dist/"}
    for name, entry in RUNTIMES["runtimes"].items():
        assert entry["url"].startswith(hosts[name]) and entry["version"] in entry["url"], name
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), name
        assert entry["license"] and entry["license_file"]


def test_the_python_runtime_matches_the_locked_wheels_abi():
    short, abi = B.python_tag(RUNTIMES["runtimes"]["python"]["version"])
    assert (short, abi) == ("3.14", "cp314")
    assert B.pip_target_args(RUNTIMES)[-2:] == ["--only-binary", ":all:"]


def test_the_node_runtime_satisfies_the_remotion_minimum():
    from jarvis.domain.remotion_capability import NODE_MINIMUM
    pinned = tuple(int(p) for p in RUNTIMES["runtimes"]["node"]["version"].split("."))
    assert pinned >= tuple(int(p) for p in NODE_MINIMUM.split("."))


def test_pth_puts_the_app_on_the_path_and_imports_site():
    assert B.pth_content("3.14.6") == "python314.zip\n.\n..\\..\\app\nimport site\n"


# -- fonctions du build -------------------------------------------------------------------------------------------------

def test_a_corrupt_cached_archive_is_removed_and_refused(tmp_path):
    entry = {"url": "https://example.invalid/runtime.zip", "sha256": "0" * 64}
    (tmp_path / "runtime.zip").write_bytes(b"tampered")
    with pytest.raises(B.BuildError, match="SHA-256"):
        B.fetch_verified(entry, tmp_path)
    assert not (tmp_path / "runtime.zip").exists()


def test_zip_extraction_refuses_escaping_paths(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("top/../../outside.txt", b"x")
    with pytest.raises(B.BuildError):
        B.extract_zip(archive, tmp_path / "out", strip_components=1)
    assert not (tmp_path / "outside.txt").exists()


def test_zip_extraction_strips_the_top_folder(tmp_path):
    archive = tmp_path / "node.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("node-v1-win-x64/node.exe", b"n")
        bundle.writestr("node-v1-win-x64/node_modules/npm/bin/npm-cli.js", b"c")
    B.extract_zip(archive, tmp_path / "out", strip_components=1)
    assert (tmp_path / "out" / "node.exe").read_bytes() == b"n"


def fake_site(root: Path, names: dict[str, str]) -> Path:
    for name, version in names.items():
        info = root / f"{name.replace('-', '_')}-{version}.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nLicense-Expression: MIT\n",
                                       encoding="utf-8")
    return root


def test_third_party_manifest_refuses_a_wheel_without_policy(tmp_path):
    site = fake_site(tmp_path / "site", {"httpx": "0.28.1", "mystery": "1.0"})
    lock = [{"name": "httpx", "version": "0.28.1", "sha256": "a" * 64}, {"name": "mystery", "version": "1.0", "sha256": "b" * 64}]
    policy = {"python_packages": {"httpx": {"license": "BSD-3-Clause", "status": "bundled"}}, "excluded": [], "external": [],
              "provisioned": []}
    with pytest.raises(B.BuildError, match="mystery: aucune entrée"):
        B.third_party_manifest(site, lock, policy, RUNTIMES, {})


def test_third_party_manifest_refuses_an_excluded_component(tmp_path):
    site = fake_site(tmp_path / "site", {"imageio-ffmpeg": "0.6.0"})
    lock = [{"name": "imageio-ffmpeg", "version": "0.6.0", "sha256": "a" * 64}]
    policy = {"python_packages": {"imageio-ffmpeg": {"license": "BSD-2-Clause", "status": "bundled"}},
              "excluded": [{"id": "imageio-ffmpeg", "kind": "python-package", "reason": "GPL"}], "external": [], "provisioned": []}
    with pytest.raises(B.BuildError, match="exclu présent"):
        B.third_party_manifest(site, lock, policy, RUNTIMES, {})


def test_third_party_manifest_lists_runtimes_and_wheels(tmp_path):
    site = fake_site(tmp_path / "site", {"httpx": "0.28.1"})
    lock = [{"name": "httpx", "version": "0.28.1", "sha256": "a" * 64}]
    policy = {"python_packages": {"httpx": {"license": "BSD-3-Clause", "status": "bundled"}}, "excluded": [],
              "external": [], "provisioned": []}
    manifest = B.third_party_manifest(site, lock, policy, RUNTIMES, {"python": ["licenses/python/LICENSE.txt"]})
    ids = [(c["kind"], c["id"]) for c in manifest["components"]]
    assert ids == [("runtime", "node"), ("runtime", "python"), ("python-package", "httpx")]
    assert manifest["components"][2]["sha256"] == "a" * 64


def test_the_probe_environment_has_only_windows_on_its_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("PYTHONPATH", r"C:\elsewhere")
    env = B.probe_env(tmp_path)
    assert env["PATH"].lower().split(";") == [r"c:\windows\system32", r"c:\windows", r"c:\windows\system32\wbem"]
    assert "PYTHONPATH" not in env


def test_the_package_digest_ignores_key_order():
    assert B.package_digest({"a": 1, "b": [1, 2]}) == B.package_digest({"b": [1, 2], "a": 1})


def test_the_build_refuses_an_output_inside_the_repository(tmp_path):
    assert B.main(["build", "--out", str(ROOT / "build-out-test"), "--cache", str(tmp_path)]) == 1
    assert not (ROOT / "build-out-test").exists()
