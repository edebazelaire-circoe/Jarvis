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

SEEDS = {"voice.self_echo", "speech.payload_integrity", "speech.stale_supersession", "voice.queue_latency"}
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

def test_the_official_catalog_loads_with_its_four_seed_diagnostics():
    catalog = load_catalog()
    assert {entry.diagnostic_id for entry in catalog.list_diagnostics()} == SEEDS
    for entry in catalog.list_diagnostics():
        assert entry.path == entry.manifest.relative_path
        assert (DEFAULT_CATALOG_ROOT / entry.path).is_file()
        virtual = entry.resources_and_cost(ProfileName.VIRTUAL)
        assert virtual.requires == frozenset() and virtual.cost.max_cost_usd == 0
        assert not virtual.available and virtual.implementation.unavailable_reason == "runner_not_registered"
        assert entry.diagnostic.assertions and any(item.blocking for item in entry.diagnostic.assertions)


def test_the_seed_stale_supersession_reuses_the_replay_fixture_scenario():
    scenario = load_catalog().describe("speech.stale_supersession").manifest.scenario
    assert scenario.scenario_id == "stale_ack_35_9s"
    assert scenario.provenance.source_path.endswith("transcript-2026-09-11.md")
    assert scenario.steps[-1].args[AT_MS] == 35_900


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
