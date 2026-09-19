"""Conformance tests for the official diagnostic catalog (docs/testlab.md, Catalog and Manifests)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jarvis.testlab.catalog import Catalog, DEFAULT_CATALOG_ROOT, LOCK_FILE_NAME, load_catalog
from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    ParameterSpec,
    ParameterType,
    ScoreContract,
    resolve_parameters,
)
from jarvis.testlab.implementations import (
    ImplementationRegistry,
    default_implementations,
    registered,
    reserved,
)
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.manifests import (
    CATALOG_DUPLICATE,
    CATALOG_FINGERPRINT_DRIFT,
    CATALOG_HISTORY_GAP,
    CATALOG_IMPLEMENTATION_PROFILE_MISMATCH,
    CATALOG_IMPLEMENTATION_UNKNOWN,
    CATALOG_JSON_INVALID,
    CATALOG_LOCK_INVALID,
    CATALOG_LOCK_ORPHAN,
    CATALOG_NOT_FOUND,
    CATALOG_PATH_INVALID,
    CATALOG_PRIMITIVE_UNKNOWN,
    CATALOG_PRIMITIVE_UNSUPPORTED,
    CATALOG_READ_FAILED,
    CATALOG_SCENARIO_INVALID,
    CATALOG_SCHEMA_INVALID,
    CATALOG_UNLOCKED,
    CatalogError,
    CatalogLock,
    DiagnosticManifest,
    build_lock,
    decode_manifest_text,
    lock_entry_for,
    render_manifest,
)
from jarvis.testlab.primitives import AT_MS
from jarvis.testlab.profiles import Capability, CostBounds, ProfileName, ProfileSpec
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.validation import FORBIDDEN_CODE, FORBIDDEN_PRIVATE_DATA
from tests.fakes.testlab import queued_run

#: The four `virtual` seeds. Every one of them runs with no device, no provider and no human.
SEEDS = {"voice.self_echo", "speech.payload_integrity", "speech.stale_supersession", "voice.queue_latency"}
#: The whole published catalog. `voice.barge_in_response` (Slice 12) is `hardware:guided`
#: ONLY: it asks a person to interrupt Jarvis, which no virtual profile can stand in for.
PUBLISHED = SEEDS | {"voice.barge_in_response", "barehands.input_quality"}
IMPLEMENTATION = "testlab.scenario.virtual"


def spec(version: int = 1, diagnostic_id: str = "voice.probe", **changes) -> DiagnosticSpec:
    profile = ProfileSpec(ProfileName.VIRTUAL, IMPLEMENTATION, CostBounds(60, 0))
    values = dict(
        diagnostic_id=diagnostic_id,
        version=version,
        title="Probe",
        domain=diagnostic_id.split(".", 1)[0],
        profiles={profile.name: profile},
        metrics=(MetricSpec("probe.count", MetricUnit.COUNT, MetricDirection.LOWER_BETTER),),
        assertions=(AssertionSpec("none_seen", "probe.count", Comparator.EQ, 0, True),),
        score=ScoreContract(),
        parameters=(ParameterSpec("turns", ParameterType.INT, 3, minimum=1, maximum=20),),
        description="Probe diagnostic.",
    )
    values.update(changes)
    return DiagnosticSpec(**values)


def manifest(version: int = 1, **changes) -> DiagnosticManifest:
    scenario = changes.pop("scenario", None)
    allowlist = changes.pop("override_allowlist", ())
    return DiagnosticManifest(spec(version, **changes), allowlist, scenario)


def write_catalog(root: Path, manifests=(), lock: CatalogLock | None = None,
                  documents: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for item in manifests:
        path = root / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_manifest(item), encoding="utf-8")
    for name, text in (documents or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / LOCK_FILE_NAME).write_text((lock if lock is not None else build_lock(manifests)).render(),
                                       encoding="utf-8")
    return root


def load(root: Path, **options) -> Catalog:
    options.setdefault("implementations", default_implementations())
    return load_catalog(root, **options)


def failure(root: Path, **options) -> CatalogError:
    with pytest.raises(CatalogError) as caught:
        load(root, **options)
    return caught.value


# ------------------------------------------------------------- seed catalog

def test_the_official_catalog_loads_with_its_published_diagnostics():
    catalog = load_catalog()
    assert {entry.diagnostic_id for entry in catalog.list_diagnostics()} == PUBLISHED
    for entry in catalog.list_diagnostics():
        assert entry.path == entry.manifest.relative_path
        assert (DEFAULT_CATALOG_ROOT / entry.path).is_file()
        assert entry.diagnostic.assertions and any(item.blocking for item in entry.diagnostic.assertions)
        if entry.diagnostic_id not in SEEDS:
            continue
        virtual = entry.resources_and_cost(ProfileName.VIRTUAL)
        assert virtual.requires == frozenset() and virtual.cost.max_cost_usd == 0


def test_the_seed_virtual_profiles_are_available_to_a_supervisor_and_its_workers():
    """Slice 06 registered the four seed runners, so the catalog a run resolves says `available`.

    `default_implementations()` is the DECLARATION view: it holds the reviewed names and,
    for the profiles no Slice has implemented yet, the reason they cannot run.
    `catalog_implementations()` is the EXECUTION view a supervisor and its workers share.
    Both are asserted here so the docs, the tests and the code cannot drift apart.
    """
    declared = load_catalog(implementations=default_implementations())
    executed = load_catalog(implementations=catalog_implementations())
    for entry in (item for item in executed.list_diagnostics() if item.diagnostic_id in SEEDS):
        virtual = entry.resources_and_cost(ProfileName.VIRTUAL)
        assert virtual.available, entry.diagnostic_id
        assert virtual.implementation.unavailable_reason is None
        assert virtual.implementation.name.endswith(".virtual")
    for entry in (item for item in declared.list_diagnostics() if item.diagnostic_id in SEEDS):
        virtual = entry.resources_and_cost(ProfileName.VIRTUAL)
        assert not virtual.available
        assert virtual.implementation.unavailable_reason == "runner_not_registered"


def test_the_seed_stale_supersession_reuses_the_replay_fixture_scenario():
    """v1 and v2 ARE the converted fixture; v3 keeps its provenance and extends its timeline."""
    catalog = load_catalog()
    for version in (1, 2):
        scenario = catalog.describe("speech.stale_supersession", version).manifest.scenario
        assert scenario.scenario_id == "stale_ack_35_9s"
        assert scenario.provenance.source_path.endswith("transcript-2026-09-11.md")
        assert scenario.steps[-1].args[AT_MS] == 35_900
    latest = catalog.describe("speech.stale_supersession").manifest.scenario
    assert latest.scenario_id == "stale_ack_and_late_answer_35_9s"
    assert latest.provenance.source_path.endswith("transcript-2026-09-11.md")
    # The incident's own release is still there, with the late answer of the past intent after it.
    assert [step.args[AT_MS] for step in latest.steps if step.primitive == "device.release"] == [35_900]


def test_the_seed_payload_integrity_measures_the_harness_not_the_divergence_signal():
    entry = load_catalog().describe("speech.payload_integrity")
    assert "speech.payload_mismatch_count" in entry.diagnostic.metric_index
    assert "diverg" not in " ".join(entry.diagnostic.metric_index)


def test_the_published_lock_matches_the_published_manifests():
    catalog = load_catalog()
    lock = CatalogLock.decode_text((DEFAULT_CATALOG_ROOT / LOCK_FILE_NAME).read_text(encoding="utf-8"))
    assert {entry.key for entry in lock.entries} == {(item.diagnostic_id, item.version) for item in catalog.entries}
    assert all(lock.get(item.diagnostic_id, item.version).manifest_fingerprint == item.manifest_fingerprint
               for item in catalog.entries)


# ------------------------------------------------------------------- lookup

def test_describe_defaults_to_the_latest_version_and_history_keeps_every_version(tmp_path):
    root = write_catalog(tmp_path / "catalog", (manifest(1), manifest(2), manifest(3)))
    catalog = load(root)
    assert catalog.describe("voice.probe").version == 3
    assert catalog.describe("voice.probe", 2).version == 2
    assert [entry.version for entry in catalog.history("voice.probe")] == [1, 2, 3]
    assert [entry.version for entry in catalog.list_diagnostics()] == [3]
    for missing in (lambda: catalog.describe("voice.probe", 9), lambda: catalog.describe("voice.absent"),
                    lambda: catalog.history("voice.absent")):
        with pytest.raises(CatalogError) as caught:
            missing()
        assert caught.value.code == CATALOG_NOT_FOUND


def test_resources_and_cost_reports_requirements_availability_and_cost(tmp_path):
    live = ProfileSpec(ProfileName.LIVE, "testlab.scenario.live", CostBounds(300, 0.5),
                       frozenset({Capability.REALTIME_PROVIDER}))
    virtual = ProfileSpec(ProfileName.VIRTUAL, IMPLEMENTATION, CostBounds(60, 0))
    root = write_catalog(tmp_path / "catalog", (manifest(profiles={virtual.name: virtual, live.name: live}),))
    catalog = load(root)
    reported = catalog.resources_and_cost("voice.probe", ProfileName.LIVE).to_dict()
    assert reported["requires"] == ["realtime_provider"] and reported["cost"]["max_cost_usd"] == 0.5
    assert reported["availability"] == "unavailable"
    with pytest.raises(CatalogError) as caught:
        catalog.resources_and_cost("voice.probe", ProfileName.AUDIO)
    assert caught.value.code == CATALOG_NOT_FOUND


def test_a_registered_implementation_is_reported_available(tmp_path):
    registry = ImplementationRegistry((registered(IMPLEMENTATION, ProfileName.VIRTUAL, lambda: object()),))
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    entry = load(root, implementations=registry).describe("voice.probe")
    assert entry.resources_and_cost(ProfileName.VIRTUAL).available


def test_loading_reports_the_expected_path_through_the_diagnostic_sink(tmp_path):
    emitted = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None):
            emitted.append((kind, level, data))

    load(write_catalog(tmp_path / "catalog", (manifest(1), manifest(2))), sink=Sink())
    assert emitted == [("testlab.catalog.loaded", "info",
                        {"root": str(tmp_path / "catalog"), "diagnostics": 1, "versions": 2})]


def test_a_stored_run_is_checked_against_the_version_it_was_judged_by(tmp_path):
    root = write_catalog(tmp_path / "catalog", (manifest(1), manifest(2)))
    catalog = load(root)
    declaration = catalog.describe("voice.probe", 1).diagnostic
    run = queued_run(declaration, diagnostic_version=1, diagnostic_fingerprint=declaration.fingerprint(),
                     parameters=resolve_parameters(declaration.parameters, {}))
    catalog.check_run(run)


# ------------------------------------------------------------- failure modes

def test_unreadable_lock_and_unreadable_manifest_are_typed(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    assert failure(root).code == CATALOG_READ_FAILED
    write_catalog(root, (manifest(),))
    (root / "voice" / "probe.v1.json").write_bytes(b"\xff\xfe\x00")
    assert failure(root).code == CATALOG_READ_FAILED


@pytest.mark.parametrize("text", ["{", '{"schema": "jarvis.testlab.manifest", "schema": 1}', '{"a": NaN}'])
def test_malformed_manifest_json_is_rejected(tmp_path, text):
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    (root / "voice" / "probe.v1.json").write_text(text, encoding="utf-8")
    assert failure(root).code == CATALOG_JSON_INVALID


@pytest.mark.parametrize("mutate", [
    lambda document: document.update(schema="jarvis.testlab.other"),
    lambda document: document.update(surprise=True),
    lambda document: document.pop("override_allowlist"),
    lambda document: document["diagnostic"].update(version=7),
    lambda document: document["diagnostic"]["metrics"].append({"name": "x", "unit": "parsecs",
                                                               "direction": "lower_better", "description": None}),
    lambda document: document["diagnostic"]["assertions"].append(
        {"assertion_id": "orphan", "metric": "absent.metric", "comparator": "eq", "threshold": 0,
         "blocking": True, "description": None}),
])
def test_schema_and_contract_violations_are_rejected(tmp_path, mutate):
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    document = json.loads((root / "voice" / "probe.v1.json").read_text(encoding="utf-8"))
    mutate(document)
    (root / "voice" / "probe.v1.json").write_text(json.dumps(document), encoding="utf-8")
    assert failure(root).code in (CATALOG_SCHEMA_INVALID, CATALOG_PATH_INVALID)


def test_a_manifest_must_live_at_the_path_its_identity_dictates(tmp_path):
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    (root / "voice" / "probe.v1.json").rename(root / "voice" / "renamed.v1.json")
    assert failure(root).code == CATALOG_PATH_INVALID


@pytest.mark.parametrize("name", ["stray.txt", "voice/probe.json", "voice/probe.v1.txt",
                                  "voice/nested/probe.v1.json"])
def test_unexpected_files_under_the_catalog_root_fail_loudly(tmp_path, name):
    root = write_catalog(tmp_path / "catalog", (manifest(),), documents={name: "{}"})
    assert failure(root).code == CATALOG_PATH_INVALID


@pytest.mark.parametrize("where", ["root", "domain"])
def test_a_link_into_the_catalog_root_is_refused(tmp_path, where):
    """A Windows junction is not a symlink: without the `_fs.is_link` check the loader would read
    manifests from outside the catalog root."""
    outside = tmp_path / "outside" / "voice"
    outside.mkdir(parents=True)
    (outside / "probe.v1.json").write_text(render_manifest(manifest()), encoding="utf-8")
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    (root / "voice" / "probe.v1.json").unlink()
    link = root / "voice" if where == "domain" else root / "linked"
    if where == "domain":
        link.rmdir()
    target = outside if where == "domain" else outside.parent
    if os.name == "nt":
        import _winapi  # a junction needs no privilege, and `Path.is_symlink()` is False for one

        _winapi.CreateJunction(str(target), str(link))
        assert not link.is_symlink() and link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)
    assert failure(root).code == CATALOG_PATH_INVALID


def test_a_duplicate_version_is_refused():
    with pytest.raises(CatalogError) as caught:
        Catalog.build(((manifest().relative_path, manifest()), (manifest().relative_path, manifest())),
                      build_lock((manifest(),)), implementations=default_implementations())
    assert caught.value.code == CATALOG_DUPLICATE


def test_version_history_has_no_hole(tmp_path):
    root = write_catalog(tmp_path / "catalog", (manifest(1), manifest(3)))
    assert failure(root).code == CATALOG_HISTORY_GAP


def test_editing_a_published_manifest_without_a_version_bump_is_drift(tmp_path):
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    path = root / "voice" / "probe.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["diagnostic"]["assertions"][0]["threshold"] = 2
    path.write_text(json.dumps(document), encoding="utf-8")
    assert failure(root).code == CATALOG_FINGERPRINT_DRIFT


def test_a_wording_edit_is_not_drift(tmp_path):
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    path = root / "voice" / "probe.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["diagnostic"]["title"] = "Probe, reworded"
    document["diagnostic"]["description"] = "Clearer sentence."
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load(root).describe("voice.probe").diagnostic.title == "Probe, reworded"


def test_an_unlocked_manifest_and_an_orphan_lock_entry_both_fail(tmp_path):
    root = write_catalog(tmp_path / "catalog", (manifest(),), lock=CatalogLock())
    assert failure(root).code == CATALOG_UNLOCKED
    root = write_catalog(tmp_path / "orphan", (manifest(1),), lock=build_lock((manifest(1), manifest(2))))
    assert failure(root).code == CATALOG_LOCK_ORPHAN


@pytest.mark.parametrize("text", ["{", '{"schema": "jarvis.testlab.catalog_lock", "schema_version": 1}'])
def test_a_malformed_lock_is_rejected(tmp_path, text):
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    (root / LOCK_FILE_NAME).write_text(text, encoding="utf-8")
    assert failure(root).code == CATALOG_LOCK_INVALID


def test_the_lock_refuses_to_republish_a_version():
    lock = build_lock((manifest(),))
    with pytest.raises(CatalogError) as caught:
        lock.with_entry(lock_entry_for(manifest()))
    assert caught.value.code == CATALOG_LOCK_INVALID
    assert len(lock.with_entry(lock_entry_for(manifest(2))).entries) == 2


# ------------------------------------------------- implementations and primitives

def test_an_unknown_or_mismatched_implementation_is_rejected_at_load_time(tmp_path):
    unknown = ProfileSpec(ProfileName.VIRTUAL, "jarvis.runtime.app", CostBounds(60, 0))
    root = write_catalog(tmp_path / "unknown", (manifest(profiles={unknown.name: unknown}),))
    assert failure(root).code == CATALOG_IMPLEMENTATION_UNKNOWN
    mismatched = ProfileSpec(ProfileName.VIRTUAL, "testlab.scenario.audio", CostBounds(60, 0))
    root = write_catalog(tmp_path / "mismatch", (manifest(profiles={mismatched.name: mismatched}),))
    assert failure(root).code == CATALOG_IMPLEMENTATION_PROFILE_MISMATCH


def test_a_reserved_implementation_is_declared_unavailable_not_missing():
    registry = ImplementationRegistry((reserved("testlab.scenario.virtual", ProfileName.VIRTUAL,
                                                "runner_not_registered", "Slice 06 registers it."),))
    entry = registry.get("testlab.scenario.virtual")
    assert entry.availability == "unavailable" and entry.to_dict()["unavailable_reason"] == "runner_not_registered"


def test_a_scenario_primitive_must_be_registered_and_supported_by_every_declared_profile(tmp_path):
    scenario = Scenario("voice.probe_script", (ScenarioStep("control.checkpoint", {AT_MS: 0, "checkpoint_id": "a"}),))
    root = write_catalog(tmp_path / "ok", (manifest(scenario=scenario),))
    assert load(root).describe("voice.probe").manifest.scenario is not None

    document = json.loads((root / "voice" / "probe.v1.json").read_text(encoding="utf-8"))
    document["scenario"]["steps"][0]["primitive"] = "shell.run"
    (root / "voice" / "probe.v1.json").write_text(json.dumps(document), encoding="utf-8")
    assert failure(root).code == CATALOG_PRIMITIVE_UNKNOWN

    live = ProfileSpec(ProfileName.LIVE, "testlab.scenario.live", CostBounds(300, 0.5),
                       frozenset({Capability.REALTIME_PROVIDER}))
    virtual_only = Scenario("voice.probe_script",
                            (ScenarioStep("user.turn", {AT_MS: 0, "turn_id": "t", "content_tag": "c"}),))
    root = write_catalog(tmp_path / "profile", (manifest(scenario=virtual_only, profiles={live.name: live}),))
    assert failure(root).code == CATALOG_PRIMITIVE_UNSUPPORTED


def test_a_scenario_timeline_must_fit_a_non_virtual_profile_budget(tmp_path):
    live = ProfileSpec(ProfileName.LIVE, "testlab.scenario.live", CostBounds(5, 0.5),
                       frozenset({Capability.REALTIME_PROVIDER}))
    long_scenario = Scenario("voice.probe_script", (ScenarioStep("time.wait", {AT_MS: 60_000}),))
    root = write_catalog(tmp_path / "budget", (manifest(scenario=long_scenario, profiles={live.name: live}),))
    assert failure(root).code == CATALOG_SCENARIO_INVALID


def test_a_scenario_override_must_name_a_declared_parameter_or_an_allowlisted_setting(tmp_path):
    allowed = ParameterSpec("speech.stale_ttl_ms", ParameterType.INT, 60000, minimum=0, maximum=600000)
    scenario = Scenario("voice.probe_script", (
        ScenarioStep("parameter.override", {AT_MS: 0, "parameter": "speech.stale_ttl_ms", "value": 1000}),
        ScenarioStep("time.wait", {AT_MS: 10})))
    root = write_catalog(tmp_path / "ok", (manifest(scenario=scenario, override_allowlist=(allowed,)),))
    assert load(root).describe("voice.probe").manifest.override_allowlist[0].name == "speech.stale_ttl_ms"
    root = write_catalog(tmp_path / "undeclared", (manifest(scenario=scenario),))
    assert failure(root).code == CATALOG_SCENARIO_INVALID


# ------------------------------------------------------- no code from a manifest

@pytest.mark.parametrize("mutate", [
    lambda document: document.update(command="rm -rf /"),
    lambda document: document.update(hook_script="import os"),
    lambda document: document["diagnostic"].update(description="__import__('os').system('x')"),
])
def test_a_manifest_can_never_carry_code(tmp_path, mutate):
    root = write_catalog(tmp_path / "catalog", (manifest(),))
    document = json.loads((root / "voice" / "probe.v1.json").read_text(encoding="utf-8"))
    mutate(document)
    (root / "voice" / "probe.v1.json").write_text(json.dumps(document), encoding="utf-8")
    assert failure(root).code == CATALOG_SCHEMA_INVALID


@pytest.mark.parametrize(("key", "cause"), [("api_key", FORBIDDEN_PRIVATE_DATA), ("python_code", FORBIDDEN_CODE)])
def test_manifest_decoding_keeps_the_private_and_code_causes(key, cause):
    document = json.loads(render_manifest(manifest()))
    document[key] = "x"
    with pytest.raises(CatalogError) as caught:
        DiagnosticManifest.from_dict(document)
    assert caught.value.code == CATALOG_SCHEMA_INVALID and caught.value.cause_code == cause


def test_manifest_text_round_trips_with_a_stable_fingerprint():
    original = manifest()
    decoded = decode_manifest_text(render_manifest(original))
    assert decoded.to_dict() == original.to_dict()
    assert decoded.fingerprint() == original.fingerprint()
    assert decoded.fingerprint() != manifest(2).fingerprint()


# ---------------------------------- the shipped speech.stale_supersession v2 and v3

def test_the_shipped_catalog_publishes_both_versions_of_stale_supersession():
    """v2 adds the expectation metrics and one blocking assertion; v1 keeps its history slot."""
    catalog = load_catalog(implementations=catalog_implementations())
    versions = catalog.versions("speech.stale_supersession")
    assert versions == (1, 2, 3)
    assert catalog.describe("speech.stale_supersession").version == 3  # no version means the latest
    v1, v2 = (catalog.describe("speech.stale_supersession", version).diagnostic for version in (1, 2))
    assert [metric.name for metric in v2.metrics] == [metric.name for metric in v1.metrics] + [
        "scenario.expectations_declared", "scenario.expectations_failed_count"]
    assert [item.assertion_id for item in v2.assertions] == [item.assertion_id for item in v1.assertions] + [
        "scenario_expectations_met"]
    blocking = v2.assertion_index["scenario_expectations_met"]
    assert (blocking.metric, blocking.comparator.value, blocking.threshold, blocking.blocking) == (
        "scenario.expectations_failed_count", "eq", 0, True)
    # Everything else is the same declaration: same profiles, parameters and scenario.
    assert v2.profiles.keys() == v1.profiles.keys()
    assert v2.parameters == v1.parameters
    entries = {entry.version: entry for entry in catalog.history("speech.stale_supersession")}
    assert entries[1].manifest.scenario == entries[2].manifest.scenario


def test_v3_of_stale_supersession_adds_the_carried_over_half_without_touching_v2():
    """The 2026-09-19 decision: a stale ANSWER is carried over, a stale acknowledgement is not.

    v3 adds one measurement and one blocking assertion for the half that was missing, and
    a scenario that states both halves as `expect.*` steps. v2 is untouched, scenario
    included: a run judged by it measured a situation where only the transient case occurs.
    """
    catalog = load_catalog(implementations=catalog_implementations())
    v2, v3 = (catalog.describe("speech.stale_supersession", version).diagnostic for version in (2, 3))
    assert [metric.name for metric in v3.metrics] == [
        "speech.superseded_count", "speech.stale_delivered_count", "speech.carried_over_delivered_count",
        "speech.latest_intent_delivered", "speech.stale_wait_ms",
        "scenario.expectations_declared", "scenario.expectations_failed_count"]
    assert {metric.name for metric in v3.metrics} - {metric.name for metric in v2.metrics} == {
        "speech.carried_over_delivered_count"}
    carried = v3.metric_index["speech.carried_over_delivered_count"]
    assert (carried.unit.value, carried.direction.value) == ("count", "higher_better")
    assert [item.assertion_id for item in v3.assertions] == [
        "no_stale_delivery", "carried_over_answer_spoken", "latest_intent_wins", "scenario_expectations_met"]
    blocking = v3.assertion_index["carried_over_answer_spoken"]
    assert (blocking.metric, blocking.comparator.value, blocking.threshold, blocking.blocking) == (
        "speech.carried_over_delivered_count", "ge", 1, True)
    assert v3.profiles.keys() == v2.profiles.keys() and v3.parameters == v2.parameters

    # The scenario is what changed semantically, which is why this is a new version and not prose.
    entries = {entry.version: entry for entry in catalog.history("speech.stale_supersession")}
    scenario = entries[3].manifest.scenario
    assert scenario != entries[2].manifest.scenario
    enqueued = {step.args["candidate_id"]: step.args for step in scenario.steps
                if step.primitive == "scheduler.enqueue"}
    assert enqueued["old-ack"]["kind"] == "ack" and enqueued["old-ack"]["intent_epoch"] == 1
    assert enqueued["old-result"]["kind"] == "result" and enqueued["old-result"]["intent_epoch"] == 1
    assert enqueued["new-result"]["intent_epoch"] == 2
    # Both halves of the rule are stated by the scenario itself, not only by the assertions.
    expected = {(step.args["metric"], step.args["comparator"], step.args["threshold"])
                for step in scenario.steps if step.primitive == "expect.metric"}
    assert expected == {("speech.carried_over_delivered_count", "ge", 1),
                        ("speech.stale_delivered_count", "eq", 0)}


def test_a_stored_v1_run_still_validates_against_v1_after_v2_is_published():
    """Publishing a version never invalidates the runs judged by an earlier one."""
    from jarvis.testlab.identity import format_run_id
    from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun
    from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0

    catalog = load_catalog(implementations=catalog_implementations())
    v1 = catalog.describe("speech.stale_supersession", 1).diagnostic
    v2 = catalog.describe("speech.stale_supersession", 2).diagnostic
    run = TestRun(run_id=format_run_id(T0, NONCE), diagnostic_id=v1.diagnostic_id, diagnostic_version=1,
                  profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED, created_at=T0,
                  code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                  diagnostic_fingerprint=v1.fingerprint(),
                  parameters=resolve_parameters(v1.parameters, {}), environment=ENVIRONMENT)
    catalog.check_run(run)  # the declaration it was judged by is still in the history
    assert run.diagnostic_fingerprint == v1.fingerprint() != v2.fingerprint()
    # And the run is NOT silently re-judged by v2: the fingerprints differ, so it would be refused.
    from jarvis.testlab.runs import check_run_against_spec
    from jarvis.testlab.validation import TestLabError

    with pytest.raises(TestLabError, match="diagnostic_id/diagnostic_version"):
        check_run_against_spec(run, v2)

    # Publishing v3 changes neither: the run stays judged by the declaration it named, and
    # v3's extra measurement is not retroactively expected of it.
    v3 = catalog.describe("speech.stale_supersession", 3).diagnostic
    catalog.check_run(run)
    assert run.diagnostic_fingerprint not in {v2.fingerprint(), v3.fingerprint()}
    assert "speech.carried_over_delivered_count" not in v1.metric_index
    with pytest.raises(TestLabError, match="diagnostic_id/diagnostic_version"):
        check_run_against_spec(run, v3)
