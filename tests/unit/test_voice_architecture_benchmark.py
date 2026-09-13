from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.runtime.voice_architecture_benchmark import (
    BenchmarkEvidenceRun,
    BenchmarkSuiteError,
    default_suite_path,
    load_benchmark_suite,
    required_evidence_nodes,
    run_cross_architecture_benchmark,
)
from jarvis.runtime.voice_metrics import COUNT_KEYS, LATENCY_KEYS
from scripts import benchmark_voice_architectures as cli


def complete_evidence(suite):  # noqa: ANN001
    nodes = required_evidence_nodes(suite)
    return BenchmarkEvidenceRun(("python", "-m", "pytest", *nodes), 0, frozenset(nodes))


def test_common_suite_is_strict_complete_and_traceable():
    suite = load_benchmark_suite(default_suite_path())
    assert suite.suite_id == "voice-common-v1"
    assert len(suite.scenarios) == 14
    assert len({item.scenario_id for item in suite.scenarios}) == 14
    assert len(suite.suite_fingerprint) == 64
    assert suite.provenance.evidence_kind == "constructed_offline_contract"
    assert any("not latency measurements" in gap for gap in suite.provenance.gaps)
    assert {item.action for item in suite.scenarios} == {
        "quiet_ambient", "short_confirmation", "direct_question", "pause_mid_sentence",
        "long_monologue", "late_correction", "long_backend_work",
        "backend_result_after_topic_shift", "user_interruption", "background_noise",
        "output_stall_reconnect", "mode_switch", "manual_stop", "spoken_divergence",
    }
    assert set(suite.representative_e2e) == {"simple", "front_brain", "duplex"}
    assert len(required_evidence_nodes(suite)) == 16
    assert suite.migration_evidence == (
        "tests/unit/test_voice_architecture_config.py::test_migration_maps_simple_projection_without_reinterpreting_execution",
        "tests/unit/test_app.py::test_operational_architecture_provenance_matches_the_runtime",
    )
    assert all(node.startswith("tests/") and "live_openai" not in node
               for node in required_evidence_nodes(suite))


@pytest.mark.parametrize("mutate,code", [
    (lambda value: value.update(extra=True), "benchmark_suite_shape_invalid"),
    (lambda value: value.update(schema_version=True), "benchmark_suite_version_unsupported"),
    (lambda value: value["scenarios"][0].update(action="unknown"), "benchmark_suite_action_unknown"),
    (lambda value: value["scenarios"][0].update(expected_invariant="one_useful_output"), "benchmark_suite_invariant_invalid"),
    (lambda value: value["scenarios"][0]["params"].update(duration_ms=-1), "benchmark_suite_params_invalid"),
    (lambda value: value["scenarios"].append(dict(value["scenarios"][0])), "benchmark_suite_scenario_duplicate"),
    (lambda value: value["representative_e2e"].update(duplex=[]), "benchmark_suite_representative_mapping_invalid"),
    (lambda value: value.update(migration_evidence=[]), "benchmark_suite_migration_mapping_invalid"),
    (lambda value: value["scenarios"][0]["evidence"]["shared"].append(
        "tests/integration/test_live_openai.py::test_live"), "benchmark_suite_evidence_unsafe"),
    (lambda value: value["representative_e2e"]["simple"].__setitem__(
        0, "tests/integration/test_simple_front_brain_composition.py::test_explicit_conversation_is_direct_while_optional_luna_is_blocked[gpt-realtime-2.1-simple]"),
     "benchmark_suite_evidence_unsafe"),
    (lambda value: value.update(migration_evidence=[
        "tests/unit/test_reflex_gate.py::test_wait_controls"]),
     "benchmark_suite_migration_mapping_invalid"),
    (lambda value: value["representative_e2e"].update(
        simple=value["representative_e2e"]["duplex"],
        duplex=value["representative_e2e"]["simple"]),
     "benchmark_suite_representative_mapping_invalid"),
    (lambda value: value["scenarios"][6]["evidence"].update(shared=[
        "tests/unit/test_reflex_gate.py::test_wait_controls"]),
     "benchmark_suite_scenario_mapping_invalid"),
    (lambda value: value["scenarios"][0]["params"].update(duration_ms=1),
     "benchmark_suite_scenario_mapping_invalid"),
    (lambda value: value["scenarios"][3]["params"].update(pause_ms=1),
     "benchmark_suite_scenario_mapping_invalid"),
    (lambda value: value["scenarios"][9]["params"].update(candidate_count=1),
     "benchmark_suite_scenario_mapping_invalid"),
])
def test_suite_rejects_malformed_self_redefined_or_unsafe_contract(tmp_path, mutate, code):  # noqa: ANN001
    value = json.loads(default_suite_path().read_text(encoding="utf-8"))
    mutate(value)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(BenchmarkSuiteError) as caught:
        load_benchmark_suite(path)
    assert caught.value.code == code


def test_suite_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema": "a", "schema": "b"}', encoding="utf-8")
    with pytest.raises(BenchmarkSuiteError) as caught:
        load_benchmark_suite(path)
    assert caught.value.code == "benchmark_suite_duplicate_field"


@pytest.mark.parametrize("evidence,code", [
    (BenchmarkEvidenceRun(("pytest",), 1, frozenset()), "benchmark_evidence_failed"),
    (BenchmarkEvidenceRun(("pytest",), 0, frozenset()), "benchmark_evidence_incomplete"),
])
def test_report_refuses_failed_or_incomplete_production_evidence(tmp_path, evidence, code):  # noqa: ANN001
    with pytest.raises(BenchmarkSuiteError) as caught:
        run_cross_architecture_benchmark(
            suite_path=default_suite_path(), output_root=tmp_path, evidence_run=evidence)
    assert caught.value.code == code
    assert not (tmp_path / "benchmarks").exists()


def test_offline_run_uses_identical_suite_and_unavailable_live_metrics(tmp_path):
    suite = load_benchmark_suite(default_suite_path())
    report, path = run_cross_architecture_benchmark(
        suite_path=default_suite_path(), output_root=tmp_path, evidence_run=complete_evidence(suite))
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert report["evidence_scope"] == {
        "shared_deterministic_policy_contract": "available",
        "production_seam_pytest": "available",
        "configuration_scope": "explicit_only",
        "compatibility_projection_samples": "excluded_from_architecture_comparison",
        "migration_compatibility_evidence": "verified_separately",
        "live_run": "not_run_no_authorization",
        "provider_session": "unavailable",
        "microphone": "unavailable",
        "speaker": "unavailable",
        "live_latency": "unavailable",
        "provider_usage": "unavailable",
        "cost": "unavailable",
        "backend_model": "unavailable",
        "ranking": "unavailable",
        "reason": "offline fake adapters cannot measure provider, acoustic, latency, usage, cost, or conversational quality",
    }
    assert report["metric_interpretation"]["scripted_clock_values_are_performance_measurements"] is False
    modes = report["architectures"]
    assert [item["architecture"] for item in modes] == ["simple", "front_brain", "duplex"]
    scenario_ids = report["suite"]["scenario_ids"]
    assert all([row["scenario_id"] for row in item["scenarios"]] == scenario_ids for item in modes)
    assert all(item["representative_e2e"]["outcome"] == "architecture_specific_pass" for item in modes)
    assert all(item["representative_e2e"]["evidence_node_ids"] == list(suite.representative_e2e[item["architecture"]])
               for item in modes)
    assert report["migration_evidence"] == {
        "outcome": "pass",
        "evidence_kind": "production_seam_pytest",
        "evidence_node_ids": list(suite.migration_evidence),
        "compatibility_projection": "verified",
        "operational_architecture_provenance": ["legacy", "continuous_brain", "simple"],
    }
    outcomes = {item["architecture"]: {row["scenario_id"]: row["outcome"] for row in item["scenarios"]}
                for item in modes}
    assert all(values["quiet-ambient"] == values["long-monologue"] == "not_run"
               for values in outcomes.values())
    assert outcomes["simple"]["direct-question"] == outcomes["front_brain"]["direct-question"] == "architecture_specific_pass"
    assert outcomes["duplex"]["direct-question"] == "not_run"
    assert all(values["short-confirmation"] == values["manual-stop"] == "shared_contract_evidence"
               for values in outcomes.values())
    assert all(
        row["evidence_kind"] == "shared_contract_evidence"
        for item in modes for row in item["scenarios"]
        if row["outcome"] == "shared_contract_evidence"
    )
    assert [sum(value == "architecture_specific_pass" for value in outcomes[mode].values())
            for mode in ("simple", "front_brain", "duplex")] == [1, 1, 0]
    assert all(sum(value == "shared_contract_evidence" for value in values.values()) == 11
               for values in outcomes.values())
    assert len({item["configuration_id"] for item in modes}) == 3
    assert all(len(item["configuration_id"]) == len(item["configuration_fingerprint"]) == 64 for item in modes)
    assert all(len(item["component_fingerprint"]) == 64 for item in modes)
    assert all(item["configuration"]["compatibility"] is None for item in modes)
    assert all(item["configuration_readiness"] == {
        "outcome": "pass", "evidence_kind": "production_composition_resolution",
        "explicit": True, "compatibility": False,
    } for item in modes)
    assert all(item["test_environment"] == {"provider_transport": "controlled_fake",
                                            "microphone": "controlled_fake", "speaker": "controlled_fake"}
               for item in modes)
    assert [[component["model_id"] for component in item["components"]] for item in modes] == [
        ["gpt-realtime-2.1-mini"],
        ["gpt-realtime-2.1-mini", "gpt-5.6-luna"],
        ["gpt-live-1"],
    ]
    for item in modes:
        assert item["scenario_suite_fingerprint"] == report["suite"]["fingerprint"]
        assert all(len(prompt["static_fingerprint"]) == 64 and prompt["application"] == "saved"
                   for prompt in item["prompt_applications"])
        session = item["task18_session_report"]
        assert session["schema"] == "jarvis.voice_benchmark.session"
        assert tuple(session["latency_metrics"]) == LATENCY_KEYS
        assert tuple(session["event_counts"]) == COUNT_KEYS
        assert all(metric["count"] == 0 and metric["mean_ms"] is None
                   for metric in session["latency_metrics"].values())
        assert set(session["event_counts"].values()) == {0}
        assert session["provider_usage_seconds"] is None and session["cost_estimate"] is None
        assert len(session["annotations"]) == len(scenario_ids)
        annotations = {annotation["name"]: annotation["outcome"] for annotation in session["annotations"]}
        assert annotations["short-confirmation"] == annotations["manual-stop"] == "uncertain"
        assert annotations["direct-question"] == (
            "pass" if item["architecture"] in {"simple", "front_brain"} else "uncertain")
    assert len(list((tmp_path / "benchmarks" / "voice-sessions").glob("*.json"))) == 3
    assert len(list((tmp_path / "benchmarks" / "voice-sessions").glob("*.txt"))) == 3
    readable = path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "live_latency=unavailable" in readable
    assert "/14" not in readable and "shared_contract_evidence=11" in readable


def test_report_is_repeatable_and_observable_without_private_content(tmp_path):
    suite = load_benchmark_suite(default_suite_path())
    evidence = complete_evidence(suite)
    first, first_path = run_cross_architecture_benchmark(
        suite_path=default_suite_path(), output_root=tmp_path, evidence_run=evidence)
    second, second_path = run_cross_architecture_benchmark(
        suite_path=default_suite_path(), output_root=tmp_path, evidence_run=evidence)
    assert first == second and first_path == second_path
    trace = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [item["kind"] for item in trace].count("voice.benchmark.run_started") == 2
    assert [item["kind"] for item in trace].count("voice.benchmark.architecture_completed") == 6
    assert [item["kind"] for item in trace].count("voice.benchmark.run_completed") == 2
    assert all(item["data"].get("run_id") == first["run_id"] for item in trace)
    completed = [item for item in trace if item["kind"] == "voice.benchmark.architecture_completed"]
    assert all(item["data"]["failed_count"] == 0 for item in completed)
    assert [item["data"]["unavailable_count"] for item in completed[:3]] == [2, 2, 3]
    assert [item["data"]["architecture_specific_pass_count"] for item in completed[:3]] == [1, 1, 0]
    assert all(item["data"]["shared_contract_evidence_count"] == 11 for item in completed)
    assert "No provider session was opened" not in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")


def test_cli_runs_exact_allowlisted_evidence_before_writing_report(tmp_path, monkeypatch, capsys):
    captured = {}

    def run(command, **kwargs):  # noqa: ANN001
        captured["command"], captured["kwargs"] = command, kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(["--output-root", str(tmp_path)]) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.is_file()
    suite = load_benchmark_suite(default_suite_path())
    assert set(required_evidence_nodes(suite)).issubset(captured["command"])
    assert "tests/integration/test_live_openai.py" not in " ".join(captured["command"])
    assert captured["kwargs"] == {"cwd": cli.ROOT, "check": False}


def test_cli_failure_never_writes_a_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=7))
    assert cli.main(["--output-root", str(tmp_path)]) == 7
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "benchmarks").exists()
