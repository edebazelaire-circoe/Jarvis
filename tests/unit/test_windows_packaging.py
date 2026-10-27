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
INTERNAL_LOCK = B.parse_lock((PACKAGING / "requirements-internal.lock").read_text(encoding="utf-8"))
INTERNAL_LOCKED = {row["name"]: row for row in INTERNAL_LOCK}


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
    """Par canal : les roues de la politique du canal = celles de ses verrous, ni plus ni moins (HD-V12-01)."""

    for channel, locked in (("production", set(LOCKED)), ("internal", set(LOCKED) | set(INTERNAL_LOCKED))):
        policy = B.channel_policy(POLICY, channel)
        assert {B.normalize(name) for name in policy["python_packages"]} == locked, channel
        assert [path.name for path in B.channel_locks(POLICY, channel)] == POLICY["channels"][channel]["locks"]
        assert {row["name"] for row in B.read_locks(B.channel_locks(POLICY, channel))} == locked
    for name, entry in POLICY["python_packages"].items():
        assert entry["status"] == "bundled" and entry["license"], name


def test_the_internal_lock_only_adds_wheels_reserved_to_the_internal_channel():
    assert set(INTERNAL_LOCKED) >= {"openwakeword", "onnxruntime"}
    assert not set(INTERNAL_LOCKED) & set(LOCKED), "une roue partagée garde la version de la production"
    for name in INTERNAL_LOCKED:
        assert POLICY["python_packages"][name]["channels"] == ["internal"], name
    reserved = {name for name, entry in POLICY["python_packages"].items() if "channels" in entry}
    assert reserved == set(INTERNAL_LOCKED)


def test_a_wheel_locked_twice_is_refused(tmp_path):
    lock = tmp_path / "a.lock"
    lock.write_text("httpx==0.28.1 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(B.BuildError, match="deux fois"):
        B.read_locks([lock, lock])


def test_production_is_the_default_channel_and_excludes_the_wake_word():
    assert B.DEFAULT_CHANNEL == "production" and POLICY["channels"]["production"]["default"] is True
    assert POLICY["channels"]["internal"]["default"] is False
    production = B.channel_policy(POLICY, "production")
    assert not {"openwakeword", "onnxruntime"} & set(production["python_packages"]) and production["models"] == {}
    assert {"openwakeword", "onnxruntime", "openwakeword-models"} <= {item["id"] for item in production["excluded"]}


def test_the_internal_channel_bundles_the_wake_word_with_its_non_commercial_warning():
    internal = B.channel_policy(POLICY, "internal")
    assert {"openwakeword", "onnxruntime"} <= set(internal["python_packages"])
    assert not {"openwakeword", "onnxruntime", "openwakeword-models"} & {item["id"] for item in internal["excluded"]}
    models = internal["models"]["openwakeword-models"]
    assert models["license"] == "CC-BY-NC-SA-4.0" and models["destination"] == "models/wake-word"
    warning = POLICY["channels"]["internal"]["warning"]
    assert "usage interne non commercial" in warning.lower() and "à remplacer avant production" in warning
    assert models["warning"] == warning and POLICY["channels"]["internal"]["decision"] == "HD-V12-01"
    assert "à remplacer avant production" in B.WAKE_MODELS_NOTICE and "by-nc-sa/4.0" in B.WAKE_MODELS_NOTICE


def test_an_unknown_channel_is_refused():
    with pytest.raises(B.BuildError, match="canal inconnu"):
        B.channel_policy(POLICY, "beta")


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


def test_pth_lists_only_package_paths_and_never_imports_site():
    lines = B.pth_content("3.14.6").splitlines()
    assert lines[:3] == ["python314.zip", ".", r"Lib\site-packages"] and lines[-1] == r"..\..\app"
    assert not any(line.startswith("import") for line in lines)  # pas de site : ni site utilisateur ni .pth
    assert all(not line.startswith(("\\", "/")) and ":" not in line for line in lines)  # relatifs au paquet


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


def test_records_of_removed_launchers_are_dropped(tmp_path):
    record = tmp_path / "httpx-0.28.1.dist-info" / "RECORD"
    record.parent.mkdir()
    record.write_text("../../bin/httpx.exe,sha256=abc,1\r\nhttpx/__init__.py,sha256=def,2\r\n", encoding="utf-8", newline="")
    B.drop_script_records(tmp_path)
    assert record.read_bytes() == b"httpx/__init__.py,sha256=def,2\r\n"


# -- reprise QA S06 -------------------------------------------------------------------------------------------------

def test_bytecode_is_compiled_in_a_single_process(tmp_path):
    argv = B.compileall_argv(tmp_path, [tmp_path / "app"])
    assert argv[argv.index("-j") + 1] == "1"  # -j 0 : bytecode différent d'un build à l'autre (QA S06, 3 jeux sur 6)
    assert argv[argv.index("--invalidation-mode") + 1] == "unchecked-hash"


@pytest.mark.parametrize("name", ["/evil.txt", r"\evil.txt", "C:/evil.txt", "C:evil.txt", r"C:\evil.txt",
                                  "top/../../outside.txt", "top/a/../../../x.txt"])
def test_zip_extraction_refuses_absolute_drive_and_parent_names(tmp_path, name):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, b"x")
    with pytest.raises(B.BuildError, match="chemin refusé"):
        B.extract_zip(archive, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "outside.txt").exists()


def test_a_build_outside_a_git_repository_names_git_and_the_prerequisites(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "REPO", tmp_path)  # une archive des sources : pas de dépôt git
    with pytest.raises(B.BuildError) as caught:
        B.git_revision("HEAD")
    message = str(caught.value)
    assert "git rev-parse" in message and "code 128" in message and "not a git repository" in message
    assert "dépôt git" in message and "Python" in message


def test_the_build_refuses_a_working_tree_that_differs_from_the_revision(tmp_path, monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        return b"packaging/windows/requirements.lock\n"

    monkeypatch.setattr(B, "git", fake_git)
    with pytest.raises(B.BuildError, match="requirements.lock"):
        B.ensure_inputs_match("a" * 40)
    assert calls == [("diff", "--name-only", "a" * 40, "--", *B.BUILD_INPUTS)]
    monkeypatch.setattr(B, "git", lambda *args: b"")
    B.ensure_inputs_match("a" * 40)


def test_the_build_checks_the_revision_before_reading_any_input(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "git_revision", lambda rev: "b" * 40)
    monkeypatch.setattr(B, "ensure_inputs_match", lambda revision: (_ for _ in ()).throw(B.BuildError("dirty")))
    monkeypatch.setattr(B, "load_json", lambda path: pytest.fail("input read before the revision check"))
    assert B.main(["build", "--out", str(tmp_path / "out"), "--cache", str(tmp_path / "cache")]) == 1
    assert not (tmp_path / "out").exists()


GOOD_PROBE = {"installed": True, "executable_in_package": True, "node_private": True, "no_site": True,
              "sys_path_outside_package": [], "excluded_importable": {"onnxruntime": False, "openwakeword": False},
              "ffmpeg": None, "path_tools": {"python": None, "node": None}, "diagnostics": {"status": "ok"},
              "wake": {"default_enabled": False, "default_provider": "porcupine"}}
GOOD_INTERNAL_WAKE = {"default_enabled": True, "default_provider": "openwakeword", "model_dir_in_package": True,
                      "models_verified": ["embedding", "hey_jarvis", "melspectrogram"], "detector": "OpenWakeWordEngine",
                      "silence_detections": [-1, -1, -1, -1, -1]}


@pytest.mark.parametrize("change, expected", [
    ({"installed": False}, "installed"), ({"executable_in_package": False}, "executable_in_package"),
    ({"node_private": False}, "node_private"), ({"no_site": False}, "no_site"),
    ({"sys_path_outside_package": ["C:/elsewhere"]}, "sys.path"),
    ({"excluded_importable": {"onnxruntime": True}}, "onnxruntime"),
    ({"ffmpeg": "C:/x/ffmpeg.exe"}, "ffmpeg"), ({"path_tools": {"node": "C:/node/node.exe"}}, "node"),
    ({"diagnostics": {"status": "degraded"}}, "degraded")])
def test_the_probe_names_every_departure_from_the_package_contract(change, expected):
    assert B.probe_problems(GOOD_PROBE) == []
    problems = B.probe_problems(GOOD_PROBE | change)
    assert len(problems) == 1 and expected in problems[0]


def fake_built_package(out: Path) -> Path:
    """Paquet minimal et cohérent : arbres, manifestes et `package_sha256` calculés comme le build."""

    from jarvis import private_runtime as PR

    for relative, content in (("app/jarvis/__init__.py", b""), ("licenses/node/LICENSE", b"MIT"),
                              ("runtime/python/python.exe", b"py"), ("runtime/node/node.exe", b"node")):
        (out / relative).parent.mkdir(parents=True, exist_ok=True)
        (out / relative).write_bytes(content)
    (out / B.THIRD_PARTY_MANIFEST).write_text("{}\n", encoding="utf-8")
    runtimes = {name: {"version": "1", "root": f"runtime/{name}", "executable": f"runtime/{name}/{name}.exe",
                       "tree_sha256": PR.tree_sha256(out / "runtime" / name)[0]} for name in ("python", "node")}
    manifest = {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
                "product": {"edition": "presentation"}, "runtimes": runtimes,
                "app": {"root": "app", "tree_sha256": PR.tree_sha256(out / "app")[0]},
                "licenses": {"root": "licenses", "tree_sha256": PR.tree_sha256(out / "licenses")[0]},
                "third_party_manifest_sha256": PR.file_sha256(out / B.THIRD_PARTY_MANIFEST), "excluded": []}
    manifest["package_sha256"] = B.package_digest(manifest)
    B.write_json(out / PR.RUNTIME_MANIFEST, manifest)
    return out


def verify(out: Path, capsys) -> tuple[int, str]:
    code = B.main(["verify", str(out)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_verify_accepts_an_intact_package(tmp_path, capsys):
    code, output = verify(fake_built_package(tmp_path / "pkg"), capsys)
    assert code == 0 and "paquet intact" in output


@pytest.mark.parametrize("tamper, expected", [
    (lambda out: (out / "app" / "jarvis" / "planted.py").write_bytes(b"x"), "app: arbre modifié"),
    (lambda out: (out / "app" / "jarvis" / "__init__.py").write_bytes(b"changed"), "app: arbre modifié"),
    (lambda out: (out / "licenses" / "node" / "LICENSE").unlink(), "licenses: arbre modifié"),
    (lambda out: (out / "third-party-manifest.json").write_text("{\"x\": 1}\n", encoding="utf-8"),
     "third-party-manifest.json modifié"),
    (lambda out: (out / "runtime" / "node" / "node.exe").write_bytes(b"other"), "node: private_runtime_integrity_failed"),
    (lambda out: (out / "runtime" / "python" / "evil.pth").write_bytes(b"x"), "python: private_runtime_integrity_failed"),
    (lambda out: (out / "planted.dll").write_bytes(b"x"), "planted.dll: fichier ou dossier inattendu"),
    (lambda out: (out / "runtime" / "ffmpeg").mkdir(), "runtime/ffmpeg: fichier ou dossier inattendu"),
])
def test_verify_reports_each_kind_of_tampering(tmp_path, capsys, tamper, expected):
    out = fake_built_package(tmp_path / "pkg")
    tamper(out)
    code, output = verify(out, capsys)
    assert code == 1 and "paquet altéré" in output and expected in output


def test_verify_detects_a_forged_package_digest(tmp_path, capsys):
    out = fake_built_package(tmp_path / "pkg")
    manifest_path = out / "runtime-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["product"]["edition"] = "full"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    code, output = verify(out, capsys)
    assert code == 1 and "package_sha256 ne correspond pas" in output


@pytest.mark.parametrize("raw", [b"\xef\xbb\xbf{}", b"{not json", b'{"schema": "jarvis.runtime-manifest", "schema_version": 1, "runtimes": {"node": "x"}}'])
def test_verify_fails_cleanly_on_an_unreadable_manifest(tmp_path, capsys, raw):
    out = fake_built_package(tmp_path / "pkg")
    (out / "runtime-manifest.json").write_bytes(raw)
    code, output = verify(out, capsys)
    assert code == 1 and "ÉCHEC" in output and "Traceback" not in output


@pytest.mark.parametrize("channel, wake, expected", [
    ("production", {"default_enabled": True}, "armé par défaut"),
    ("internal", GOOD_INTERNAL_WAKE | {"default_enabled": False}, "pas armé par défaut"),
    ("internal", GOOD_INTERNAL_WAKE | {"model_dir_in_package": False}, "pas lus dans le paquet"),
    ("internal", GOOD_INTERNAL_WAKE | {"models_verified": ["hey_jarvis"]}, "non vérifiés"),
    ("internal", GOOD_INTERNAL_WAKE | {"silence_detections": [-1, 0]}, "silence"),
    ("internal", None, "non chargé")])
def test_the_probe_checks_the_wake_word_of_each_channel(channel, wake, expected):
    assert B.probe_problems(GOOD_PROBE | {"wake": GOOD_INTERNAL_WAKE}, "internal") == []
    problems = B.probe_problems(GOOD_PROBE | {"wake": wake}, channel)
    assert any(expected in problem for problem in problems), problems


def test_the_probe_lets_the_internal_build_import_its_wake_engine_only():
    assert {"onnxruntime", "openwakeword"} <= set(B.PROBE_EXCLUDED_MODULES["production"])
    assert not {"onnxruntime", "openwakeword"} & set(B.PROBE_EXCLUDED_MODULES["internal"])
    assert set(B.PROBE_EXCLUDED_MODULES["internal"]) >= {"imageio_ffmpeg", "pvporcupine", "sherpa_onnx"}


# -- canaux : manifeste tiers, manifeste du paquet, verify (HD-V12-01) ------------------------------------------------


def _toy_policy(names: dict, models: bool = False) -> dict:
    packages = {name: {"license": "MIT", "status": "bundled", **({"channels": channels} if channels else {})}
                for name, channels in names.items()}
    return {"channels": {"production": {"locks": ["requirements.lock"]},
                         "internal": {"locks": ["requirements.lock", "requirements-internal.lock"], "warning": "W"}},
            "python_packages": packages,
            "excluded": [{"id": "openwakeword", "kind": "python-package", "reason": "NC", "channels": ["production"]}],
            "external": [], "provisioned": [],
            "models": ({"openwakeword-models": {"license": "CC-BY-NC-SA-4.0", "status": "bundled", "channels": ["internal"],
                                                "destination": "models/wake-word", "warning": "W"}} if models else {})}


TOY_LOCK = [{"name": "httpx", "version": "0.28.1", "sha256": "a" * 64},
            {"name": "openwakeword", "version": "0.6.0", "sha256": "b" * 64}]


def test_a_production_build_refuses_openwakeword_in_its_site_packages(tmp_path):
    site = fake_site(tmp_path / "site", {"httpx": "0.28.1", "openwakeword": "0.6.0"})
    policy = B.channel_policy(_toy_policy({"httpx": None, "openwakeword": ["internal"]}), "production")
    with pytest.raises(B.BuildError) as refused:
        B.third_party_manifest(site, TOY_LOCK, policy, RUNTIMES, {})
    assert "openwakeword: aucune entrée" in str(refused.value) and "openwakeword: composant exclu présent" in str(refused.value)


def test_an_internal_build_lists_its_reserved_wheels_and_models_with_their_channel(tmp_path):
    site = fake_site(tmp_path / "site", {"httpx": "0.28.1", "openwakeword": "0.6.0"})
    policy = B.channel_policy(_toy_policy({"httpx": None, "openwakeword": ["internal"]}, models=True), "internal")
    licenses = {"python-packages/openwakeword": ["licenses/python-packages/openwakeword/LICENSE"],
                "openwakeword-models": ["licenses/openwakeword-models/NOTICE.txt"]}
    models_dir = tmp_path / "models" / "wake-word"
    with pytest.raises(B.BuildError, match="modèles déclarés par la politique du canal mais non livrés"):
        B.third_party_manifest(site, TOY_LOCK, policy, RUNTIMES, licenses, models_dir)
    models_dir.mkdir(parents=True)
    with pytest.raises(B.BuildError, match="openwakeword: aucun texte de licence"):
        B.third_party_manifest(site, TOY_LOCK, policy, RUNTIMES, {}, models_dir)
    manifest = B.third_party_manifest(site, TOY_LOCK, policy, RUNTIMES, licenses, models_dir)
    assert manifest["channel"] == "internal" and manifest["warning"] == "W"
    by_id = {component["id"]: component for component in manifest["components"]}
    assert by_id["openwakeword"]["channels"] == ["internal"] and "channels" not in by_id["httpx"]
    models = [component for component in manifest["components"] if component["kind"] == "model"]
    assert sorted(component["file"] for component in models) == sorted(
        f"models/wake-word/{spec.filename}" for spec in B.WAKE_MODELS.MODELS)
    for component in models:
        spec = B.WAKE_MODELS.find_model(component["id"].split("/")[1])
        assert component["sha256"] == spec.sha256 and component["size"] == spec.size
        assert component["license"] == "CC-BY-NC-SA-4.0" and component["channels"] == ["internal"]
        assert component["license_files"] == ["licenses/openwakeword-models/NOTICE.txt"]
    assert "openwakeword" not in {item["id"] for item in manifest["excluded"]}


def test_a_production_build_refuses_models_it_does_not_declare(tmp_path):
    site = fake_site(tmp_path / "site", {"httpx": "0.28.1"})
    policy = B.channel_policy(_toy_policy({"httpx": None}, models=True), "production")
    (tmp_path / "models").mkdir()
    with pytest.raises(B.BuildError, match="modèles livrés alors que la politique du canal n'en déclare aucun"):
        B.third_party_manifest(site, TOY_LOCK[:1], policy, RUNTIMES, {}, tmp_path / "models")


def test_extra_license_files_and_the_model_notice_are_shipped(tmp_path):
    out, site = tmp_path / "pkg", tmp_path / "pkg" / "runtime" / "python" / "Lib" / "site-packages"
    for relative in ("runtime/python/LICENSE.txt", "runtime/node/LICENSE"):
        (out / relative).parent.mkdir(parents=True, exist_ok=True)
        (out / relative).write_text("L", encoding="utf-8")
    (site / "onnxruntime").mkdir(parents=True)
    (site / "onnxruntime" / "LICENSE").write_text("MIT", encoding="utf-8")
    policy = {"python_packages": {"onnxruntime": {"license_files": ["onnxruntime/LICENSE"]}},
              "models": {"openwakeword-models": {}}}
    copied = B.collect_licenses(out, site, RUNTIMES, policy)
    assert copied["python-packages/onnxruntime"] == ["licenses/python-packages/onnxruntime/onnxruntime/LICENSE"]
    notice = (out / copied["openwakeword-models"][0]).read_text(encoding="utf-8")
    assert "CC BY-NC-SA 4.0" in notice and "à remplacer avant production" in notice
    policy["python_packages"]["onnxruntime"]["license_files"].append("onnxruntime/ThirdPartyNotices.txt")
    with pytest.raises(B.BuildError, match="absents de la roue"):
        B.collect_licenses(out, site, RUNTIMES, policy)


def test_the_runtime_manifest_names_its_channel_and_tracks_the_models(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "node_npm_version", lambda node_dir: "10.0.0")
    out = fake_built_package(tmp_path / "pkg")
    production = B.runtime_manifest(out, RUNTIMES, "r" * 40, B.channel_policy(POLICY, "production"))
    assert production["product"]["channel"] == "production" and "models" not in production
    assert "channel_warning" not in production["product"]
    (out / "models" / "wake-word").mkdir(parents=True)
    (out / "models" / "wake-word" / "hey_jarvis_v0.1.onnx").write_bytes(b"m")
    internal = B.runtime_manifest(out, RUNTIMES, "r" * 40, B.channel_policy(POLICY, "internal"))
    assert internal["product"]["channel"] == "internal"
    assert "à remplacer avant production" in internal["product"]["channel_warning"]
    assert internal["models"]["root"] == "models" and internal["models"]["files"] == 1


def refresh_manifest(out: Path, **product) -> Path:
    """Recalcule les empreintes du faux paquet après une plantation : seul le contrôle de canal peut alors refuser."""

    from jarvis import private_runtime as PR

    manifest = json.loads((out / PR.RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    manifest["product"].update(product)
    for name in ("python", "node"):
        manifest["runtimes"][name]["tree_sha256"] = PR.tree_sha256(out / "runtime" / name)[0]
    manifest["third_party_manifest_sha256"] = PR.file_sha256(out / B.THIRD_PARTY_MANIFEST)
    if (out / "models").is_dir():
        manifest["models"] = {"root": "models", "tree_sha256": PR.tree_sha256(out / "models")[0]}
    manifest.pop("package_sha256", None)
    manifest["package_sha256"] = B.package_digest(manifest)
    B.write_json(out / PR.RUNTIME_MANIFEST, manifest)
    return out


def plant_model(out: Path) -> None:
    (out / "models" / "wake-word").mkdir(parents=True)
    (out / "models" / "wake-word" / "hey_jarvis_v0.1.onnx").write_bytes(b"model")


def test_verify_accepts_an_intact_internal_package_and_refuses_a_tampered_model(tmp_path, capsys):
    out = fake_built_package(tmp_path / "pkg")
    plant_model(out)
    refresh_manifest(out, channel="internal", channel_warning="Usage interne non commercial")
    code, output = verify(out, capsys)
    assert code == 0 and "canal internal" in output and "Usage interne non commercial" in output
    (out / "models" / "wake-word" / "hey_jarvis_v0.1.onnx").write_bytes(b"other")
    code, output = verify(out, capsys)
    assert code == 1 and "models: arbre modifié" in output


def test_verify_names_the_production_channel_of_a_package_without_channel(tmp_path, capsys):
    code, output = verify(fake_built_package(tmp_path / "pkg"), capsys)  # manifeste V1 : pas de `channel`
    assert code == 0 and "canal production" in output


@pytest.mark.parametrize("plant, expected", [
    (plant_model, "production: modèles livrés"),
    (lambda out: (out / "runtime" / "python" / "Lib" / "site-packages" / "openwakeword").mkdir(parents=True),
     "production: openwakeword présent"),
    (lambda out: (out / "runtime" / "python" / "Lib" / "site-packages" / "onnxruntime-1.30.0.dist-info").mkdir(parents=True),
     "production: onnxruntime présent"),
    (lambda out: (out / B.THIRD_PARTY_MANIFEST).write_text(
        json.dumps({"components": [{"id": "openwakeword", "channels": ["internal"]}]}), encoding="utf-8"),
     "production: openwakeword réservé aux canaux ['internal']"),
])
def test_verify_refuses_a_production_package_that_carries_an_internal_component(tmp_path, capsys, plant, expected):
    out = fake_built_package(tmp_path / "pkg")
    plant(out)
    (out / "runtime" / "python" / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    (out / "runtime" / "python" / "Lib" / "site-packages" / "keep.txt").write_text("x", encoding="utf-8")
    code, output = verify(refresh_manifest(out, channel="production"), capsys)
    assert code == 1 and expected in output, output
    assert "arbre modifié" not in output and "integrity_failed" not in output and "package_sha256" not in output


def test_verify_refuses_an_unknown_channel(tmp_path, capsys):
    code, output = verify(refresh_manifest(fake_built_package(tmp_path / "pkg"), channel="beta"), capsys)
    assert code == 1 and "canal inconnu 'beta'" in output


def test_a_wheel_without_licence_text_borrows_the_same_licence_from_another_wheel(tmp_path):
    out, site = tmp_path / "pkg", tmp_path / "pkg" / "runtime" / "python" / "Lib" / "site-packages"
    for relative in ("runtime/python/LICENSE.txt", "runtime/node/LICENSE"):
        (out / relative).parent.mkdir(parents=True, exist_ok=True)
        (out / relative).write_text("L", encoding="utf-8")
    fake_site(site, {"requests": "2.34.2", "flatbuffers": "25.12.19"})
    (site / "requests-2.34.2.dist-info" / "LICENSE").write_text("Apache License 2.0", encoding="utf-8")
    policy = {"python_packages": {"requests": {"license": "Apache-2.0"},
                                  "flatbuffers": {"license": "Apache-2.0", "license_text_from": "requests"}}}
    copied = B.collect_licenses(out, site, RUNTIMES, policy)
    assert copied["python-packages/flatbuffers"] == ["licenses/python-packages/flatbuffers/LICENSE",
                                                     "licenses/python-packages/flatbuffers/NOTICE.txt"]
    assert "reproduced from the requests wheel" in (out / "licenses/python-packages/flatbuffers/NOTICE.txt").read_text(encoding="utf-8")
    policy["python_packages"]["flatbuffers"]["license"] = "MIT"
    with pytest.raises(B.BuildError, match="même licence"):
        B.collect_licenses(out, site, RUNTIMES, policy)
