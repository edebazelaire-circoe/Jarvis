"""Outils de la release (presentation-edition-v1 Slice 10, `docs/release.md`) : vérificateur, porte des tests et liste
datée des échecs connus, identité d'un candidat, build sans cache utilisateur."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jarvis import private_runtime as PR
from jarvis.domain import agent_capabilities as AC
from jarvis.domain.product_edition import ProductEdition
from scripts import release_info as RI
from scripts import release_test_gate as G
from scripts import verify_release as V
from tests.unit.test_product_setup import make_package

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------- vérificateur statique


def test_the_repository_passes_the_static_release_gates():
    assert V.execution_primitive_findings(ROOT) == []
    assert V.product_release_findings(ROOT) == []
    assert V.artifact_info_findings(ROOT) == []


def _fake_root(tmp_path: Path) -> Path:
    for relative in V.SUBPROCESS_RUN_REVIEWED:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("import subprocess\nsubprocess.run(['x'])\n", encoding="utf-8")
    return tmp_path


def test_a_new_subprocess_run_or_any_shell_is_a_finding(tmp_path):
    root = _fake_root(tmp_path)
    assert V.execution_primitive_findings(root) == []
    (root / "jarvis" / "new_tool.py").write_text("import subprocess\nsubprocess.run(['git'])\n", encoding="utf-8")
    (root / "jarvis" / "bad.py").write_text("import os\nos.system('dir')\n", encoding="utf-8")
    (root / "jarvis" / "adapters" / "process_tree.py").write_text("subprocess.run('x', shell=True)\n", encoding="utf-8")
    found = V.execution_primitive_findings(root)
    assert any("jarvis/new_tool.py" in f and "not in the reviewed list" in f for f in found)
    assert any("os.system(" in f and "jarvis/bad.py" in f for f in found)
    assert any("shell=True" in f and "process_tree.py" in f for f in found)
    (root / "jarvis" / "runtime" / "brain_cli.py").write_text("# no subprocess any more\n", encoding="utf-8")
    assert any("stale entry jarvis/runtime/brain_cli.py" in f for f in V.execution_primitive_findings(root))


def test_a_forbidden_capability_coming_back_fails_the_release(monkeypatch):
    leaky = replace(AC.PRESENTATION_CAPABILITIES, native_tools=(*AC.CONFINED_NATIVE_TOOLS, "Bash"), chrome=True)
    monkeypatch.setattr(AC, "AGENT_CAPABILITY_POLICIES", {ProductEdition.FULL: AC.UNCONFINED, ProductEdition.PRESENTATION: leaky})
    found = V.product_release_findings(ROOT)
    assert any("forbidden native tools ['Bash']" in f for f in found)
    assert any("--chrome" in f for f in found)


def test_a_package_runtime_resolved_on_the_path_fails_the_release(monkeypatch):
    monkeypatch.setattr(PR, "OWNED_TOOLS", PR.OWNED_TOOLS - {"node", "node.exe"})
    found = V.product_release_findings(ROOT)
    assert "node is not owned by the package (private_runtime.OWNED_TOOLS)" in found
    assert any("resolves node outside its package: PATH:node" in f for f in found)


def test_an_excluded_wheel_back_in_the_lock_fails_the_release(tmp_path):
    (tmp_path / "packaging" / "windows").mkdir(parents=True)
    lock = (ROOT / "packaging" / "windows" / "requirements.lock").read_text(encoding="utf-8")
    (tmp_path / "packaging" / "windows" / "requirements.lock").write_text(
        lock + "onnxruntime==1.0 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")
    assert any("onnxruntime is back" in f for f in V.product_release_findings(tmp_path))


def test_artifact_info_must_follow_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "ARTIFACT_INFO.json").write_text(json.dumps({"version": "0.1.0-rc1"}), encoding="utf-8")
    found = V.artifact_info_findings(tmp_path)
    assert any("'0.1.0-rc1' differs from pyproject '9.9.9'" in f for f in found)
    assert any("does not point at the generated release info" in f for f in found)


# ---------------------------------------------------------------------- liste datée des échecs connus


def test_every_known_failure_names_an_existing_test_and_is_dated():
    known = G.load_known()
    assert known, "the list is read, never empty by accident"
    for nodeid, entry in known.items():
        path, _, name = nodeid.partition("::")
        source = (ROOT / path).read_text(encoding="utf-8")
        assert f"def {name.split('[')[0]}(" in source, nodeid
        assert entry.review_by >= date(2026, 10, 27), nodeid


def test_the_known_failure_file_refuses_a_global_ignore_or_an_incomplete_entry(tmp_path):
    bad = tmp_path / "k.json"
    for failures, message in (([{"nodeid": "tests/*", "kind": "ignore", "since": "2026-10-27", "review_by": "2027-01-01",
                                  "issue": "x", "reason": "y"}], "a le type"),
                              ([{"nodeid": "tests/a.py::t", "kind": "failing"}], "incomplète")):
        bad.write_text(json.dumps({"schema": G.KNOWN_SCHEMA, "schema_version": 1, "failures": failures}), encoding="utf-8")
        with pytest.raises(G.GateError, match=message):
            G.load_known(bad)


def _result(**phases_by_id):
    return {"exitstatus": 1, "tests": {nodeid.replace("__", "::"): phases for nodeid, phases in phases_by_id.items()}}


def test_the_gate_judges_unknown_known_stale_expired_and_intermittent_failures():
    known = {"a.py::known": G.Known("a.py::known", "failing", date(2027, 1, 1), "I-1"),
             "a.py::fixed": G.Known("a.py::fixed", "failing", date(2027, 1, 1), "I-2"),
             "a.py::flaky": G.Known("a.py::flaky", "intermittent", date(2027, 1, 1), "I-3"),
             "a.py::flaky_dead": G.Known("a.py::flaky_dead", "intermittent", date(2027, 1, 1), "I-4"),
             "a.py::old": G.Known("a.py::old", "failing", date(2026, 1, 1), "I-5")}
    result = _result(**{"a.py__known": {"call": "failed"}, "a.py__fixed": {"call": "passed"},
                        "a.py__flaky": {"call": "failed"}, "a.py__flaky_dead": {"setup": "failed"},
                        "a.py__new": {"teardown": "failed", "call": "passed"}, "a.py__ok": {"call": "passed"}})
    verdict = G.judge(result, known, today=date(2026, 10, 27), rerun=lambda nodeid: nodeid == "a.py::flaky")
    assert verdict.known_failed == ["a.py::known"] and verdict.tolerated == ["a.py::flaky"]
    assert verdict.unknown == ["a.py::flaky_dead (intermittent listé, mais échoue aussi seul)", "a.py::new"]
    assert verdict.stale == ["a.py::fixed"] and verdict.expired == ["a.py::old (review_by 2026-01-01, I-5)"]
    assert not verdict.green
    clean = G.judge(_result(**{"a.py__known": {"call": "failed"}}), {"a.py::known": known["a.py::known"]},
                    today=date(2026, 10, 27), rerun=lambda nodeid: False)
    assert clean.green and clean.failed == 1


def test_a_pytest_crash_is_a_red_gate_never_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3))
    result = G.run_pytest(["tests/unit/x.py"], tmp_path / "never-written.json")
    assert G.failed_ids(result) == {"<pytest>"}
    assert not G.judge(result, {}, today=date(2026, 10, 27), rerun=lambda n: True).green


def test_suites_cover_every_test_file_once_and_shards_partition_them():
    unit, browser, everything = G.suite_files("unit"), G.suite_files("browser"), G.suite_files("all")
    assert not set(unit) & set(browser) and sorted(unit + browser) == everything
    assert set(G.suite_files("release")) <= set(unit) and "tests/unit/test_release_tooling.py" in G.suite_files("release")
    parts = [G.shard(everything, f"{k}/4") for k in range(1, 5)]
    assert sorted(sum(parts, [])) == everything and all(parts)
    halves = [G.shard(parts[2], f"{k}/2") for k in (1, 2)]  # `--shard 3/4 --shard K/2` : les moitiés d'une part
    assert sorted(halves[0] + halves[1]) == sorted(parts[2]) and not set(halves[0]) & set(halves[1])
    for bad in ("0/4", "5/4", "x"):
        with pytest.raises(G.GateError):
            G.shard(everything, bad)


def test_the_gate_plugin_records_every_phase_and_collection_errors(tmp_path):
    sample = tmp_path / "test_sample.py"
    sample.write_text("import pytest\n\ndef test_ok():\n    pass\n\ndef test_ko():\n    assert False\n\n"
                      "@pytest.fixture\ndef broken():\n    raise RuntimeError('setup')\n\ndef test_setup(broken):\n    pass\n",
                      encoding="utf-8")
    (tmp_path / "test_import.py").write_text("import not_a_module_anywhere\n", encoding="utf-8")

    def outcomes(target: Path) -> dict:
        report = tmp_path / f"{target.stem}.json"
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p",
                        "scripts.release_test_gate_plugin", "--rootdir", str(tmp_path), str(target)],
                       cwd=ROOT, env={**os.environ, "JARVIS_TEST_GATE_REPORT": str(report)}, capture_output=True, check=False)
        tests = json.loads(report.read_text(encoding="utf-8"))["tests"]
        return {nodeid.rsplit("::", 1)[-1] if "::" in nodeid else Path(nodeid).name: phases for nodeid, phases in tests.items()}

    by_name = outcomes(sample)
    assert by_name["test_ok"]["call"] == "passed" and by_name["test_ko"]["call"] == "failed"
    assert by_name["test_setup"]["setup"] == "failed"
    # Une erreur d'import arrête la session de pytest : elle reste un échec écrit, donc une porte rouge.
    assert outcomes(tmp_path / "test_import.py")["test_import.py"]["collect"] == "failed"


# ---------------------------------------------------------------------- identité d'un candidat


def _installer(path: Path, payload: bytes, stub: bytes = b"MZ-stub") -> Path:
    path.write_bytes(stub + payload + b"JVSETUP1" + len(stub).to_bytes(8, "little") + len(payload).to_bytes(8, "little"))
    return path


def _verdict(path: Path, green: bool = True) -> Path:
    path.write_text(json.dumps({"green": green, "suite": "release", "passed": 3, "failed": 0, "known_failures_seen": [],
                                "intermittent_tolerated": []}), encoding="utf-8")
    return path


def test_release_info_names_a_verified_package_its_installer_and_its_inputs(tmp_path):
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    package = make_package(tmp_path / "pkg")
    manifest = json.loads((package / PR.RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    manifest["product"]["source_revision"] = head
    manifest.pop("package_sha256")
    manifest["package_sha256"] = PR.package_digest(manifest)
    (package / PR.RUNTIME_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    installer = _installer(tmp_path / "JARVIS-Setup.exe", b"PK-zip-payload")
    info = RI.build(package, installer, gate_reports=[_verdict(tmp_path / "gate.json")], smoke_report=None)
    assert info["source_revision"] == head and info["package_sha256"] == manifest["package_sha256"]
    assert info["installer"]["payload_sha256"] == hashlib.sha256(b"PK-zip-payload").hexdigest()
    assert info["installer"]["sha256"] == hashlib.sha256(installer.read_bytes()).hexdigest() and info["installer"]["signed"] is False
    assert set(info["build_inputs_sha256"]) == set(RI.BUILD_INPUTS)
    assert info["artifact_name"] == f"jarvis-0.2.0-{head[:12]}-{info['installer']['sha256'][:12]}"
    assert info["verdicts"]["gate.json"]["passed"] == 3
    # Refus : paquet altéré, installeur sans remorque, verdict rouge, identité déjà écrite.
    with pytest.raises(RI.ReleaseInfoError, match="vert"):
        RI.build(package, installer, gate_reports=[_verdict(tmp_path / "red.json", green=False)], smoke_report=None)
    (tmp_path / "plain.exe").write_bytes(b"MZ" * 40)
    with pytest.raises(RI.ReleaseInfoError, match="remorque"):
        RI.build(package, tmp_path / "plain.exe", gate_reports=[], smoke_report=None)
    (package / "runtime" / "node" / "node.exe").write_bytes(b"tampered")
    with pytest.raises(RI.ReleaseInfoError, match="paquet altéré"):
        RI.build(package, installer, gate_reports=[], smoke_report=None)
    out = tmp_path / "release-info.json"
    out.write_text("{}", encoding="utf-8")
    assert RI.main(["--package", str(package), "--installer", str(installer), "--out", str(out)]) == 1


def test_the_build_never_writes_the_user_pip_cache(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_build_package_s10", ROOT / "packaging" / "windows" / "build_package.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    calls = []
    monkeypatch.setattr(builder.subprocess, "run", lambda argv, **kwargs: calls.append(argv))
    monkeypatch.setattr(builder, "install_pywin32_dlls", lambda site: None)
    builder.install_wheels(tmp_path / "out", builder.load_json(builder.RUNTIMES_FILE), tmp_path / "cache")
    assert [argv[3] for argv in calls] == ["download", "install"]
    assert all("--no-cache-dir" in argv for argv in calls)
