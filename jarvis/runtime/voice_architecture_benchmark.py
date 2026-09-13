"""Deterministic, offline cross-architecture voice benchmark tooling.

This module records results from exact pytest nodes that exercise real JARVIS
seams with controlled transports/devices. Fixture clock values must never be
presented as provider, device, latency, usage, or cost evidence. No production
runtime imports this module; the CLI and its tests are its only entry points.

Observability contract:
- ``voice.benchmark.run_started``: one info event per accepted suite/run ID;
- ``voice.benchmark.architecture_completed``: one info event per architecture;
- ``voice.benchmark.run_completed``: one info event after atomic reports exist.
All events correlate by ``run_id`` and contain fingerprints/counts only. Suite
validation fails with a stable ``BenchmarkSuiteError.code`` before execution.
No temporary debug probes or fallback behavior are used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from types import MappingProxyType
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.prompt_registry import PromptTarget, fingerprint
from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig,
    FrontBrainVoiceConfig,
    SimpleVoiceConfig,
    VoiceArchitectureId,
    VoiceModeConfig,
    VoiceModelRef,
)
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.prompt_catalog import default_prompt_registry
from jarvis.runtime.prompt_runtime import prompt_evidence
from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings
from jarvis.runtime.voice_capabilities import default_voice_registry
from jarvis.runtime.voice_composition import VoiceComposition, resolve_voice_composition
from jarvis.runtime.voice_metrics import COUNT_KEYS, LATENCY_KEYS, VoiceSessionMetricRecorder


SUITE_SCHEMA = "jarvis.voice_benchmark.cross_architecture_suite"
SUITE_SCHEMA_VERSION = 1
REPORT_SCHEMA = "jarvis.voice_benchmark.cross_architecture"
REPORT_SCHEMA_VERSION = 1
MAX_SUITE_BYTES = 64 * 1024
MAX_SCENARIOS = 64
MAX_SCRIPTED_DURATION_MS = 7 * 24 * 60 * 60 * 1000
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,119}\Z")


class BenchmarkSuiteError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BenchmarkProvenance:
    source_path: str
    evidence_kind: str
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    scenario_id: str
    action: str
    params: dict[str, object]
    expected_invariant: str
    shared_evidence: tuple[str, ...]
    architecture_evidence: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class BenchmarkSuite:
    suite_id: str
    origin: datetime
    provenance: BenchmarkProvenance
    scenarios: tuple[BenchmarkScenario, ...]
    representative_e2e: dict[str, tuple[str, ...]]
    migration_evidence: tuple[str, ...]
    suite_fingerprint: str


@dataclass(frozen=True, slots=True)
class BenchmarkEvidenceRun:
    command: tuple[str, ...]
    exit_code: int
    passed_nodes: frozenset[str]

    def __post_init__(self) -> None:
        if (not isinstance(self.command, tuple) or not self.command
                or any(not isinstance(item, str) or not item or len(item) > 512
                       or any(ord(char) < 32 for char in item) for item in self.command)
                or type(self.exit_code) is not int
                or not isinstance(self.passed_nodes, frozenset)
                or any(not isinstance(item, str) for item in self.passed_nodes)):
            raise BenchmarkSuiteError("benchmark_evidence_invalid", "evidence run metadata is invalid")


_ACTION_CONTRACTS: dict[str, tuple[dict[str, tuple[str, int, int]], str]] = {
    "quiet_ambient": ({"duration_ms": ("int", 0, MAX_SCRIPTED_DURATION_MS)}, "no_speech_or_work"),
    "short_confirmation": ({}, "silent_completion"),
    "direct_question": ({}, "one_useful_output"),
    "pause_mid_sentence": ({"pause_ms": ("int", 0, MAX_SCRIPTED_DURATION_MS)}, "no_precommit_effect"),
    "long_monologue": ({"fragment_count": ("int", 2, 256)}, "single_committed_turn"),
    "late_correction": ({"revision_count": ("int", 2, 32)}, "latest_revision_only"),
    "long_backend_work": ({"duration_ms": ("int", 1, MAX_SCRIPTED_DURATION_MS),
                           "later_turns": ("int", 1, 32)}, "conversation_nonblocking"),
    "backend_result_after_topic_shift": ({}, "result_deferred_not_spoken"),
    "user_interruption": ({}, "local_output_stopped"),
    "background_noise": ({"candidate_count": ("int", 1, 256)}, "no_false_interruption"),
    "output_stall_reconnect": ({}, "queue_recovers"),
    "mode_switch": ({}, "active_work_preserved"),
    "manual_stop": ({}, "session_closed_usage_unknown"),
    "spoken_divergence": ({}, "heard_text_authoritative"),
}

_ARCHITECTURES = tuple(item.value for item in VoiceArchitectureId)
_WAIT_NODE = "tests/unit/test_reflex_gate.py::test_wait_controls"
_SIMPLE_E2E_NODE = "tests/integration/test_simple_front_brain_composition.py::test_explicit_conversation_is_direct_while_optional_luna_is_blocked[gpt-realtime-2.1-mini-simple]"
_FRONT_E2E_NODE = "tests/integration/test_simple_front_brain_composition.py::test_explicit_conversation_is_direct_while_optional_luna_is_blocked[gpt-realtime-2.1-mini-front_brain]"
_DUPLEX_E2E_NODE = "tests/integration/test_live_duplex_session.py::test_first_live_deltas_drive_restricted_job_without_blocking_second_turn"
_PAUSE_NODE = "tests/integration/test_voice_replay_regressions.py::test_thinking_pause_wait_stays_silent_on_the_full_voice_stack"
_BACKEND_NODE = "tests/integration/test_voice_replay_regressions.py::test_backend_85_7s_does_not_block_later_turn_admission_on_full_stack"
_DIVERGENCE_NODE = "tests/integration/test_voice_replay_safety_regressions.py::test_spoken_divergence_preserves_intended_generated_and_heard_evidence"
_NOISE_NODE = "tests/integration/test_voice_replay_safety_regressions.py::test_bus_cluster_seven_rejections_never_stop_duck_cancel_or_submit_work"
_INTERRUPT_NODE = "tests/integration/test_voice_replay_safety_regressions.py::test_confirmed_interrupt_without_provider_item_never_invents_heard_words"
_CANCEL_NODE = "tests/integration/test_voice_replay_safety_regressions.py::test_late_provider_cancel_rejection_keeps_local_stop_and_drops_late_pcm"
_STALL_NODE = "tests/integration/test_voice_replay_safety_regressions.py::test_missing_terminal_recovers_at_replay_deadline_and_next_output_speaks"
_MANUAL_STOP_NODE = "tests/integration/test_voice_replay_safety_regressions.py::test_manual_close_retains_late_core_results_without_speech_and_reports_once"
_CORRECTION_NODE = "tests/unit/test_v2_intent_revision.py::test_late_uncertain_confirmation_preserves_latest_confirmed_intent"
_SWITCH_NODE = "tests/unit/test_voice_switch.py::test_simple_front_duplex_simple_sequence_keeps_conversation_and_work"
_MIGRATION_NODE = "tests/unit/test_voice_architecture_config.py::test_migration_maps_simple_projection_without_reinterpreting_execution"
_PROVENANCE_NODE = "tests/unit/test_app.py::test_operational_architecture_provenance_matches_the_runtime"

_NO_ARCHITECTURE_EVIDENCE = tuple((architecture, ()) for architecture in _ARCHITECTURES)
_EXPECTED_REPRESENTATIVE_EVIDENCE = MappingProxyType({
    "simple": (_SIMPLE_E2E_NODE,),
    "front_brain": (_FRONT_E2E_NODE,),
    "duplex": (_DUPLEX_E2E_NODE,),
})
_EXPECTED_MIGRATION_EVIDENCE = (_MIGRATION_NODE, _PROVENANCE_NODE)
_EXPECTED_SCENARIOS = MappingProxyType({
    "quiet-ambient": ("quiet_ambient", (("duration_ms", 5000),), "no_speech_or_work",
                      (), _NO_ARCHITECTURE_EVIDENCE),
    "short-confirmation": ("short_confirmation", (), "silent_completion",
                           (_WAIT_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "direct-question": ("direct_question", (), "one_useful_output", (), (
        ("simple", (_SIMPLE_E2E_NODE,)), ("front_brain", (_FRONT_E2E_NODE,)), ("duplex", ()),
    )),
    "pause-mid-sentence": ("pause_mid_sentence", (("pause_ms", 2900),), "no_precommit_effect",
                           (_PAUSE_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "long-monologue": ("long_monologue", (("fragment_count", 32),), "single_committed_turn",
                       (), _NO_ARCHITECTURE_EVIDENCE),
    "late-correction": ("late_correction", (("revision_count", 3),), "latest_revision_only",
                        (_CORRECTION_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "long-backend-work": ("long_backend_work", (("duration_ms", 85700), ("later_turns", 2)),
                          "conversation_nonblocking", (_BACKEND_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "backend-result-after-topic-shift": ("backend_result_after_topic_shift", (),
                                         "result_deferred_not_spoken", (_BACKEND_NODE,),
                                         _NO_ARCHITECTURE_EVIDENCE),
    "user-interruption": ("user_interruption", (), "local_output_stopped",
                          (_INTERRUPT_NODE, _CANCEL_NODE), _NO_ARCHITECTURE_EVIDENCE),
    "background-noise": ("background_noise", (("candidate_count", 7),), "no_false_interruption",
                         (_NOISE_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "output-stall-reconnect": ("output_stall_reconnect", (), "queue_recovers",
                               (_STALL_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "mode-switch": ("mode_switch", (), "active_work_preserved",
                    (_SWITCH_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "manual-stop": ("manual_stop", (), "session_closed_usage_unknown",
                    (_MANUAL_STOP_NODE,), _NO_ARCHITECTURE_EVIDENCE),
    "spoken-divergence": ("spoken_divergence", (), "heard_text_authoritative",
                          (_DIVERGENCE_NODE,), _NO_ARCHITECTURE_EVIDENCE),
})
_ALLOWED_EVIDENCE_NODES = frozenset({
    *_EXPECTED_MIGRATION_EVIDENCE,
    *(node for nodes in _EXPECTED_REPRESENTATIVE_EVIDENCE.values() for node in nodes),
    *(node for _action, _params, _invariant, shared, by_architecture in _EXPECTED_SCENARIOS.values()
      for nodes in (shared, *(nodes for _architecture, nodes in by_architecture)) for node in nodes),
})


def default_suite_path() -> Path:
    return Path(__file__).resolve().parents[2] / "benchmarks" / "voice" / "common_suite_v1.json"


def load_benchmark_suite(path: Path) -> BenchmarkSuite:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BenchmarkSuiteError("benchmark_suite_unreadable", str(path)) from exc
    if len(raw) > MAX_SUITE_BYTES:
        raise BenchmarkSuiteError("benchmark_suite_too_large", f"suite exceeds {MAX_SUITE_BYTES} bytes")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkSuiteError("benchmark_suite_json_invalid", "suite must be valid UTF-8 JSON") from exc
    values = _shape(value, {"schema", "schema_version", "suite_id", "origin", "provenance",
                            "scenarios", "representative_e2e", "migration_evidence"}, "suite")
    if values["schema"] != SUITE_SCHEMA or type(values["schema_version"]) is not int or values["schema_version"] != SUITE_SCHEMA_VERSION:
        raise BenchmarkSuiteError("benchmark_suite_version_unsupported", "expected cross-architecture suite schema version 1")
    suite_id = _identifier(values["suite_id"], "suite_id")
    origin = _aware_datetime(values["origin"])
    provenance = _decode_provenance(values["provenance"])
    rows = values["scenarios"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SCENARIOS:
        raise BenchmarkSuiteError("benchmark_suite_scenario_bound", f"scenarios must contain 1..{MAX_SCENARIOS} entries")
    scenarios = tuple(_decode_scenario(row, index) for index, row in enumerate(rows))
    identifiers = [item.scenario_id for item in scenarios]
    if len(set(identifiers)) != len(identifiers):
        raise BenchmarkSuiteError("benchmark_suite_scenario_duplicate", "scenario IDs must be unique")
    if tuple(identifiers) != tuple(_EXPECTED_SCENARIOS):
        raise BenchmarkSuiteError("benchmark_suite_scenario_set_invalid", "suite v1 scenario IDs/order are frozen")
    for scenario in scenarios:
        expected = _EXPECTED_SCENARIOS[scenario.scenario_id]
        actual = (
            scenario.action,
            tuple(sorted(scenario.params.items())),
            scenario.expected_invariant,
            scenario.shared_evidence,
            tuple((architecture, scenario.architecture_evidence[architecture])
                  for architecture in _ARCHITECTURES),
        )
        if actual != expected:
            raise BenchmarkSuiteError(
                "benchmark_suite_scenario_mapping_invalid",
                f"suite v1 mapping is frozen for {scenario.scenario_id}",
            )
    representative = _decode_architecture_evidence(values["representative_e2e"], "representative_e2e")
    if representative != _EXPECTED_REPRESENTATIVE_EVIDENCE:
        raise BenchmarkSuiteError("benchmark_suite_representative_mapping_invalid",
                                  "suite v1 representative E2E mapping is frozen")
    migration = _decode_evidence_nodes(values["migration_evidence"], "migration_evidence")
    if migration != _EXPECTED_MIGRATION_EVIDENCE:
        raise BenchmarkSuiteError("benchmark_suite_migration_mapping_invalid",
                                  "suite v1 migration evidence is frozen")
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return BenchmarkSuite(suite_id, origin, provenance, scenarios, representative, migration,
                          hashlib.sha256(canonical).hexdigest())


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkSuiteError("benchmark_suite_duplicate_field", key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise BenchmarkSuiteError("benchmark_suite_nonfinite", value)


def _shape(value: object, expected: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkSuiteError("benchmark_suite_shape_invalid", f"{where} must be an object")
    actual = set(value)
    if actual != expected:
        raise BenchmarkSuiteError(
            "benchmark_suite_shape_invalid",
            f"{where}: missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}",
        )
    return value


def _identifier(value: object, where: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise BenchmarkSuiteError("benchmark_suite_identifier_invalid", where)
    return value


def _bounded_text(value: object, where: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > maximum:
        raise BenchmarkSuiteError("benchmark_suite_text_invalid", where)
    return value


def _aware_datetime(value: object) -> datetime:
    text = _bounded_text(value, "origin", maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkSuiteError("benchmark_suite_origin_invalid", "origin must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BenchmarkSuiteError("benchmark_suite_origin_invalid", "origin must include a UTC offset")
    return parsed


def _decode_provenance(value: object) -> BenchmarkProvenance:
    values = _shape(value, {"source_path", "evidence_kind", "gaps"}, "provenance")
    source_path = _bounded_text(values["source_path"], "provenance.source_path")
    source = Path(source_path)
    if source.is_absolute() or ".." in source.parts or "\\" in source_path:
        raise BenchmarkSuiteError("benchmark_suite_provenance_invalid", "source_path must be repo-relative POSIX")
    if values["evidence_kind"] != "constructed_offline_contract":
        raise BenchmarkSuiteError("benchmark_suite_provenance_invalid", "evidence_kind must remain explicit")
    gaps = values["gaps"]
    if not isinstance(gaps, list) or not gaps or len(gaps) > 16:
        raise BenchmarkSuiteError("benchmark_suite_provenance_invalid", "gaps must be a non-empty bounded array")
    return BenchmarkProvenance(source_path, values["evidence_kind"],
                               tuple(_bounded_text(item, f"provenance.gaps[{index}]") for index, item in enumerate(gaps)))


def _decode_scenario(value: object, index: int) -> BenchmarkScenario:
    values = _shape(value, {"scenario_id", "action", "params", "expected_invariant", "evidence"},
                    f"scenarios[{index}]")
    scenario_id = _identifier(values["scenario_id"], f"scenarios[{index}].scenario_id")
    action = _identifier(values["action"], f"scenarios[{index}].action")
    if action not in _ACTION_CONTRACTS:
        raise BenchmarkSuiteError("benchmark_suite_action_unknown", action)
    params = values["params"]
    contract, invariant = _ACTION_CONTRACTS[action]
    if not isinstance(params, dict) or set(params) != set(contract):
        raise BenchmarkSuiteError("benchmark_suite_params_invalid", f"{scenario_id} has invalid parameters")
    validated: dict[str, object] = {}
    for key, (kind, minimum, maximum) in contract.items():
        item = params[key]
        if kind == "int" and (type(item) is not int or not minimum <= item <= maximum):
            raise BenchmarkSuiteError("benchmark_suite_params_invalid", f"{scenario_id}.{key} is outside bounds")
        validated[key] = item
    if values["expected_invariant"] != invariant:
        raise BenchmarkSuiteError("benchmark_suite_invariant_invalid", f"{scenario_id} changes the contract for {action}")
    evidence = _shape(values["evidence"], {"shared", "by_architecture"},
                      f"scenarios[{index}].evidence")
    shared = _decode_evidence_nodes(evidence["shared"], f"scenarios[{index}].evidence.shared")
    by_architecture = _decode_architecture_evidence(
        evidence["by_architecture"], f"scenarios[{index}].evidence.by_architecture")
    return BenchmarkScenario(scenario_id, action, validated, invariant, shared, by_architecture)


def _decode_architecture_evidence(value: object, where: str) -> dict[str, tuple[str, ...]]:
    values = _shape(value, set(_ARCHITECTURES), where)
    return {architecture: _decode_evidence_nodes(values[architecture], f"{where}.{architecture}")
            for architecture in _ARCHITECTURES}


def _decode_evidence_nodes(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise BenchmarkSuiteError("benchmark_suite_evidence_invalid", f"{where} must be a bounded array")
    result: list[str] = []
    for index, item in enumerate(value):
        node = _bounded_text(item, f"{where}[{index}]", maximum=512)
        if node not in _ALLOWED_EVIDENCE_NODES:
            raise BenchmarkSuiteError("benchmark_suite_evidence_unsafe", node)
        result.append(node)
    if len(set(result)) != len(result):
        raise BenchmarkSuiteError("benchmark_suite_evidence_invalid", f"{where} contains duplicate nodes")
    return tuple(result)


class _FixedClock:
    def __init__(self, origin: datetime) -> None:
        self.origin = origin

    @staticmethod
    def monotonic() -> float:
        return 0.0

    def now(self) -> datetime:
        return self.origin


def _configurations() -> tuple[VoiceModeConfig, ...]:
    realtime_mini = VoiceModelRef("openai", "gpt-realtime-2.1-mini")
    return (
        SimpleVoiceConfig(realtime_mini),
        FrontBrainVoiceConfig(realtime_mini, VoiceModelRef("openai", "gpt-5.6-luna"), True, "low"),
        DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"), True, 60.0),
    )


def _prompt_applications(config: VoiceModeConfig) -> list[dict[str, object]]:
    registry = default_prompt_registry()
    provider = (config.reflex_model.provider_id if isinstance(config, FrontBrainVoiceConfig)
                else config.conversation_model.provider_id)
    targets = [PromptTarget("conversation", config.architecture.value, provider, None, "explicit", "session")]
    if isinstance(config, FrontBrainVoiceConfig):
        targets.append(PromptTarget("analysis", "front_brain", config.analysis_model.provider_id,
                                    None, "explicit", "hint"))
    return [prompt_evidence(registry.resolve(target), application="saved") for target in targets]


def _components(config: VoiceModeConfig) -> list[dict[str, str]]:
    surface = config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model
    result = [{"role": "surface", "provider_id": surface.provider_id, "model_id": surface.model_id}]
    if isinstance(config, FrontBrainVoiceConfig):
        result.append({"role": "analysis", "provider_id": config.analysis_model.provider_id,
                       "model_id": config.analysis_model.model_id})
    return result


def required_evidence_nodes(suite: BenchmarkSuite) -> tuple[str, ...]:
    nodes = {node for values in suite.representative_e2e.values() for node in values}
    nodes.update(suite.migration_evidence)
    for scenario in suite.scenarios:
        nodes.update(scenario.shared_evidence)
        for values in scenario.architecture_evidence.values():
            nodes.update(values)
    return tuple(sorted(nodes))


def _validate_evidence_run(suite: BenchmarkSuite, evidence: BenchmarkEvidenceRun) -> None:
    required = frozenset(required_evidence_nodes(suite))
    if evidence.exit_code != 0:
        raise BenchmarkSuiteError("benchmark_evidence_failed", f"pytest exited with {evidence.exit_code}")
    if evidence.passed_nodes != required:
        missing = sorted(required - evidence.passed_nodes)
        extra = sorted(evidence.passed_nodes - required)
        raise BenchmarkSuiteError("benchmark_evidence_incomplete", f"missing={missing}, extra={extra}")
    if any(node not in _ALLOWED_EVIDENCE_NODES for node in evidence.passed_nodes):
        raise BenchmarkSuiteError("benchmark_evidence_unsafe", "evidence contains a non-allowlisted node")


def _scenario_result(scenario: BenchmarkScenario, architecture: str,
                     evidence: BenchmarkEvidenceRun) -> dict[str, object]:
    architecture_nodes = scenario.architecture_evidence[architecture]
    nodes = tuple(dict.fromkeys((*scenario.shared_evidence, *architecture_nodes)))
    if architecture_nodes and all(node in evidence.passed_nodes for node in nodes):
        outcome = "architecture_specific_pass"
        evidence_kind = "production_seam_pytest"
    elif scenario.shared_evidence and all(node in evidence.passed_nodes for node in scenario.shared_evidence):
        outcome = "shared_contract_evidence"
        evidence_kind = "shared_contract_evidence"
    elif not nodes:
        outcome = "not_run"
        evidence_kind = "unavailable"
    else:
        outcome = "fail"
        evidence_kind = "production_seam_pytest"
    return {
        "scenario_id": scenario.scenario_id,
        "action": scenario.action,
        "expected_invariant": scenario.expected_invariant,
        "outcome": outcome,
        "evidence_kind": evidence_kind,
        "scripted_parameters": dict(scenario.params),
        "evidence_node_ids": list(nodes),
    }


def _session_report(output_root: Path, suite: BenchmarkSuite, composition: VoiceComposition,
                    applications: list[dict[str, object]], scenarios: list[dict[str, object]]) -> dict[str, object]:
    config = composition.selection.config
    surface = config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model
    clock = _FixedClock(suite.origin)
    recorder = VoiceSessionMetricRecorder(
        runtime_root=output_root,
        journal=SimpleNamespace(),
        architecture=config.architecture.value,
        provider_id=surface.provider_id,
        model_id=surface.model_id,
        configuration_id=composition.configuration_id,
        components=_components(config),
        clock=clock.monotonic,
        wall_clock=clock.now,
    )
    session_id = f"offline-{config.architecture.value}-{suite.suite_fingerprint[:12]}"
    recorder.start(conversation_id=f"offline-{suite.suite_id}", session_id=session_id)
    recorder.identify_frontend(session_id=session_id, prompt_applications=applications)
    for item in scenarios:
        outcome = str(item["outcome"])
        annotation = "pass" if outcome == "architecture_specific_pass" else "fail" if outcome == "fail" else "uncertain"
        recorder.annotate(str(item["scenario_id"]), outcome=annotation,
                          note="controlled production-seam evidence; no provider or device measurement")
    return recorder.finish(status="stopped")


def run_cross_architecture_benchmark(*, suite_path: Path, output_root: Path,
                                     evidence_run: BenchmarkEvidenceRun) -> tuple[dict[str, object], Path]:
    suite = load_benchmark_suite(suite_path)
    _validate_evidence_run(suite, evidence_run)
    output_root = Path(output_root)
    journal = RuntimeJournal(output_root)
    run_id = f"offline-{suite.suite_id}-{suite.suite_fingerprint[:12]}"
    journal.emit("voice.benchmark.run_started", "Offline voice benchmark started",
                 data={"run_id": run_id, "suite_fingerprint": suite.suite_fingerprint,
                       "scenario_count": len(suite.scenarios)})
    registry = default_voice_registry()
    results: list[dict[str, object]] = []
    for config in _configurations():
        registry.validate(config, require_ready=True)
        settings = VoiceArchitectureSettings(config).to_dict()
        composition = resolve_voice_composition({"voice_architecture": settings}, environ={})
        applications = _prompt_applications(config)
        scenarios = [_scenario_result(item, config.architecture.value, evidence_run)
                     for item in suite.scenarios]
        components = _components(config)
        session_report = _session_report(output_root, suite, composition, applications, scenarios)
        results.append({
            "architecture": config.architecture.value,
            "test_environment": {"provider_transport": "controlled_fake",
                                 "microphone": "controlled_fake", "speaker": "controlled_fake"},
            "configuration": settings,
            "configuration_id": composition.configuration_id,
            "configuration_fingerprint": fingerprint(settings),
            "configuration_readiness": {
                "outcome": "pass",
                "evidence_kind": "production_composition_resolution",
                "explicit": True,
                "compatibility": False,
            },
            "components": components,
            "component_fingerprint": fingerprint(components),
            "prompt_applications": applications,
            "scenario_suite_fingerprint": suite.suite_fingerprint,
            "scenarios": scenarios,
            "representative_e2e": {
                "outcome": "architecture_specific_pass",
                "evidence_kind": "production_seam_pytest",
                "evidence_node_ids": list(suite.representative_e2e[config.architecture.value]),
            },
            "task18_session_report": session_report,
        })
        journal.emit("voice.benchmark.architecture_completed", "Offline architecture benchmark completed",
                     data={"run_id": run_id, "architecture": config.architecture.value,
                           "configuration_id": composition.configuration_id,
                           "scenario_count": len(scenarios),
                           "failed_count": sum(item["outcome"] == "fail" for item in scenarios),
                           "architecture_specific_pass_count": sum(
                               item["outcome"] == "architecture_specific_pass" for item in scenarios),
                           "shared_contract_evidence_count": sum(
                               item["outcome"] == "shared_contract_evidence" for item in scenarios),
                           "unavailable_count": sum(item["outcome"] == "not_run" for item in scenarios)})
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "origin": suite.origin.isoformat(),
        "suite": {
            "schema": SUITE_SCHEMA,
            "schema_version": SUITE_SCHEMA_VERSION,
            "suite_id": suite.suite_id,
            "fingerprint": suite.suite_fingerprint,
            "scenario_ids": [item.scenario_id for item in suite.scenarios],
            "provenance": {**asdict(suite.provenance), "gaps": list(suite.provenance.gaps)},
        },
        "evidence_scope": {
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
        },
        "evidence_run": {"command": list(evidence_run.command), "exit_code": evidence_run.exit_code,
                         "passed_node_ids": sorted(evidence_run.passed_nodes)},
        "migration_evidence": {
            "outcome": "pass",
            "evidence_kind": "production_seam_pytest",
            "evidence_node_ids": list(suite.migration_evidence),
            "compatibility_projection": "verified",
            "operational_architecture_provenance": ["legacy", "continuous_brain", "simple"],
        },
        "metric_interpretation": {
            "task18_schema": "emitted_per_architecture",
            "latency_keys": list(LATENCY_KEYS),
            "count_keys": list(COUNT_KEYS),
            "scripted_clock_values_are_performance_measurements": False,
            "zero_event_counts_are_live_passes": False,
        },
        "architectures": results,
    }
    root = output_root / "benchmarks" / "voice-cross-architecture"
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{suite.suite_id}-{suite.suite_fingerprint[:12]}"
    report_path = root / f"{stem}.json"
    text_path = root / f"{stem}.txt"
    lines = [
        f"Offline cross-architecture benchmark {run_id}",
        f"suite_fingerprint={suite.suite_fingerprint}",
        f"scenarios={len(suite.scenarios)} architectures={len(results)}",
        "evidence=controlled_production_seams",
        "live_latency=unavailable provider_usage=unavailable cost=unavailable ranking=unavailable",
        *[f"{item['architecture']}: architecture_specific_pass={sum(row['outcome'] == 'architecture_specific_pass' for row in item['scenarios'])} "
          f"shared_contract_evidence={sum(row['outcome'] == 'shared_contract_evidence' for row in item['scenarios'])} "
          f"not_run={sum(row['outcome'] == 'not_run' for row in item['scenarios'])} "
          f"fail={sum(row['outcome'] == 'fail' for row in item['scenarios'])}"
          for item in results],
    ]
    json_tmp = report_path.with_suffix(".json.tmp")
    text_tmp = text_path.with_suffix(".txt.tmp")
    try:
        json_tmp.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        text_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        replace_with_retry(text_tmp, text_path)
        replace_with_retry(json_tmp, report_path)
    finally:
        json_tmp.unlink(missing_ok=True)
        text_tmp.unlink(missing_ok=True)
    journal.emit("voice.benchmark.run_completed", "Offline voice benchmark completed",
                 data={"run_id": run_id, "suite_fingerprint": suite.suite_fingerprint,
                       "architecture_count": len(results), "report": report_path.name})
    return report, report_path
