"""Slice 10: the composition layer — roots, policies, the grant, and what it does NOT do.

Contract: `docs/testlab.md` ("Native API, CLI and HTTP"). Three properties are load
bearing and each has its own test here: the work root is never the store root, building a
Test Lab touches no file, and a capability comes from the process environment and can
only be narrowed afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.testlab.composition import (
    AUDIO_ARTIFACTS_ENV,
    COMPOSITION_INVALID,
    HARDWARE_OPT_IN_ENV,
    MAX_COST_ENV,
    TESTLAB_DIR_NAME,
    WORK_DIR_NAME,
    TestLab,
    TestLabConfig,
    build_test_lab,
    display_path,
    environment_grant,
    narrow_grant,
    read_environment_grant,
)
from jarvis.testlab.devices import default_contention_detector
from jarvis.testlab.hardware.prompts import GUIDED_OPT_IN_ENV
from jarvis.testlab.live.session import LIVE_OPT_IN_ENV
from jarvis.testlab.profiles import MAX_PROFILE_COST_USD, Capability, ResourceGrant
from jarvis.testlab.retention import TestLabRetentionPolicy
from jarvis.testlab.supervisor import SETTINGS_FILE_NAME
from jarvis.testlab.validation import TestLabError


def env(**values: str) -> dict[str, str]:
    """An environment with no Jarvis opt-in set, plus whatever the test declares."""
    return {"JARVIS_RUNTIME_DIR": "./runtime", "JARVIS_DATA_ROOT": "./data", **values}


# ------------------------------------------------------------------- roots

def test_every_root_hangs_off_the_runtime_directory(tmp_path):
    config = TestLabConfig.from_environment(env(), runtime_root=tmp_path)
    assert config.root == tmp_path.resolve() / TESTLAB_DIR_NAME
    assert config.work_root == config.root / WORK_DIR_NAME
    assert config.settings_path == tmp_path.resolve() / SETTINGS_FILE_NAME
    assert config.trace_path.name == "trace.jsonl"
    assert config.state_database.parts[-2:] == ("state", "jarvis.sqlite3")


def test_the_runtime_directory_comes_from_the_environment_when_it_is_not_given(tmp_path):
    config = TestLabConfig.from_environment(env(JARVIS_RUNTIME_DIR=str(tmp_path / "rt")))
    assert config.root == (tmp_path / "rt").resolve() / TESTLAB_DIR_NAME


def test_the_work_root_may_never_be_the_store_root(tmp_path):
    """The supervisor removes every directory under its work root that no run claims."""
    with pytest.raises(TestLabError) as caught:
        TestLabConfig(root=tmp_path, work_root=tmp_path, runtime_root=tmp_path, data_root=tmp_path)
    assert caught.value.code == COMPOSITION_INVALID


def test_building_a_test_lab_creates_nothing(tmp_path):
    """Nothing until first use: a CLI that only prints help must not make directories."""
    root = tmp_path / "runtime"
    lab = build_test_lab(env(), runtime_root=root)
    assert lab.store.root == lab.config.root and lab.sweep_store.root == lab.config.root
    assert lab.bundle_store.root == lab.config.root
    assert not root.exists(), "composing a Test Lab touched the filesystem"


def test_one_store_instance_is_shared(tmp_path):
    """The Slice 07 listing cache is per instance: two would answer differently."""
    lab = build_test_lab(env(), runtime_root=tmp_path)
    assert lab.store is lab.store
    assert lab.supervisor._store is lab.store
    assert lab.sweep_runner._supervisor is lab.supervisor


def test_the_catalog_and_the_supervisor_are_built_once(tmp_path):
    lab = build_test_lab(env(), runtime_root=tmp_path)
    assert lab.catalog is lab.catalog
    assert lab.supervisor is lab.supervisor
    assert lab.supervisor.catalog is lab.catalog


# ------------------------------------------------------------------- grant

def test_the_default_grant_is_empty(tmp_path):
    """No opt-in set: exactly the `virtual` profile — free, no device, no provider, no human."""
    grant = environment_grant(env())
    assert grant.capabilities == frozenset() and grant.max_cost_usd == 0


def test_each_opt_in_grants_exactly_its_capabilities():
    assert environment_grant(env(**{LIVE_OPT_IN_ENV: "1"})).capabilities == frozenset(
        {Capability.REALTIME_PROVIDER, Capability.LLM_PROVIDER})
    assert environment_grant(env(**{HARDWARE_OPT_IN_ENV: "1"})).capabilities == frozenset(
        {Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE})
    assert environment_grant(env(**{GUIDED_OPT_IN_ENV: "1"})).capabilities == frozenset(
        {Capability.HUMAN_PRESENCE})


def test_an_opt_in_that_is_not_exactly_one_grants_nothing():
    for value in ("0", "true", "yes", "", "1 "):
        assert environment_grant(env(**{LIVE_OPT_IN_ENV: value})).capabilities == frozenset(), value


def test_the_money_budget_is_read_and_a_mistyped_one_reads_zero():
    assert environment_grant(env(**{MAX_COST_ENV: "2.5"})).max_cost_usd == 2.5
    for value in ("", "lots", "nan", "-1"):
        assert environment_grant(env(**{MAX_COST_ENV: value})).max_cost_usd == 0, value


def test_a_caller_can_only_narrow_the_grant():
    """The rule that makes the HTTP surface safe: a request body can ask for less, never more."""
    granted = ResourceGrant(frozenset({Capability.REALTIME_PROVIDER}), max_cost_usd=5, max_duration_s=100)
    asked = ResourceGrant(frozenset({Capability.REALTIME_PROVIDER, Capability.AUDIO_INPUT_DEVICE}),
                          max_cost_usd=50, max_duration_s=1000)
    narrowed = narrow_grant(granted, asked)
    assert narrowed.capabilities == frozenset({Capability.REALTIME_PROVIDER})
    assert narrowed.max_cost_usd == 5 and narrowed.max_duration_s == 100
    assert narrow_grant(granted, None) is granted


def test_narrowing_keeps_a_stricter_duration_the_caller_asked_for():
    granted = ResourceGrant(max_duration_s=None)
    assert narrow_grant(granted, ResourceGrant(max_duration_s=30)).max_duration_s == 30


def test_the_audio_artifact_opt_in_is_off_unless_asked_for(tmp_path):
    assert TestLabConfig.from_environment(env(), runtime_root=tmp_path).artifact_limits.allow_audio is False
    opted = TestLabConfig.from_environment(env(**{AUDIO_ARTIFACTS_ENV: "1"}), runtime_root=tmp_path)
    assert opted.artifact_limits.allow_audio is True


def test_retention_is_composed_and_stays_disabled_by_default(tmp_path):
    default = TestLabConfig.from_environment(env(), runtime_root=tmp_path)
    assert default.policy.maintenance.retention.enabled is False
    enabled = TestLabConfig.from_environment(env(), runtime_root=tmp_path,
                                             retention=TestLabRetentionPolicy(enabled=True, max_runs=10))
    assert enabled.policy.maintenance.retention.enabled is True
    assert enabled.policy.maintenance.retention.max_runs == 10


# -------------------------------------------------------------- contention

def test_the_native_audio_probe_is_not_composed_by_default(tmp_path):
    """Slice 09 offered it and declined to wire it: it costs a native query per reservation."""
    lab = build_test_lab(env(), runtime_root=tmp_path)
    assert lab.config.probe_audio_backend is False
    sources = [type(probe).__name__ for probe in lab.contention.probes]
    assert sources == ["LiveVoiceRuntimeProbe"]


def test_the_hardware_opt_in_adds_the_backend_probe(tmp_path):
    lab = build_test_lab(env(**{HARDWARE_OPT_IN_ENV: "1"}), runtime_root=tmp_path)
    assert lab.config.probe_audio_backend is True
    sources = [type(probe).__name__ for probe in lab.contention.probes]
    assert "AudioBackendProbe" in sources


def test_an_injected_detector_replaces_the_composed_one(tmp_path):
    detector = default_contention_detector(tmp_path / "somewhere-else")
    lab = TestLab(TestLabConfig.from_environment(env(), runtime_root=tmp_path), contention=detector)
    assert lab.contention is detector and lab.supervisor.contention is detector


def test_the_detector_reads_the_live_runtime_root_not_a_scratch(tmp_path):
    """A detector pointed at a run scratch would find no voice signal and report free."""
    lab = build_test_lab(env(), runtime_root=tmp_path)
    probe = lab.contention.probes[0]
    assert Path(probe.runtime_root) == tmp_path.resolve()


def test_the_status_document_names_every_opt_in(tmp_path):
    document = build_test_lab(env(**{LIVE_OPT_IN_ENV: "1"}), runtime_root=tmp_path).config.to_dict()
    assert document["opt_ins"] == {LIVE_OPT_IN_ENV: True, HARDWARE_OPT_IN_ENV: False, GUIDED_OPT_IN_ENV: False}
    assert document["grant"]["capabilities"] == ["llm_provider", "realtime_provider"]
    assert document["allow_audio_artifacts"] is False and document["retention_enabled"] is False


# ----------------------------------------- rework: one variable cannot break the lab

def test_a_budget_above_the_ceiling_is_clamped_instead_of_raising():
    """`ResourceGrant` refuses anything over `MAX_PROFILE_COST_USD`; reading the environment
    must not. `install_testlab_routes` runs inside `ControlCenter.__init__`, so a raise here
    would stop the whole Control Center from being constructed over a Test Lab variable."""
    grant, refusal = read_environment_grant(env(**{MAX_COST_ENV: "1e9"}))
    assert grant.max_cost_usd == MAX_PROFILE_COST_USD
    assert refusal is not None and MAX_COST_ENV in refusal and "clamped" in refusal


@pytest.mark.parametrize("value, budget", [("", 0), ("lots", 0), ("nan", 0), ("-1", 0), ("inf", 0),
                                           ("1e9", MAX_PROFILE_COST_USD), ("1001", MAX_PROFILE_COST_USD),
                                           ("1000", 1000), ("2.5", 2.5), ("0", 0)])
def test_every_budget_value_produces_a_usable_grant(value, budget):
    grant, _ = read_environment_grant(env(**{MAX_COST_ENV: value}))
    assert grant.max_cost_usd == budget


def test_an_unusable_budget_is_reported_and_never_silent():
    for value in ("lots", "nan", "-1"):
        _, refusal = read_environment_grant(env(**{MAX_COST_ENV: value}))
        assert refusal is not None and MAX_COST_ENV in refusal, value
    assert read_environment_grant(env(**{MAX_COST_ENV: "2.5"}))[1] is None


def test_the_refusal_travels_on_the_config_and_into_the_status_document(tmp_path):
    config = TestLabConfig.from_environment(env(**{MAX_COST_ENV: "1e9"}), runtime_root=tmp_path)
    assert config.grant_refusal is not None
    assert config.to_dict()["grant_refusal"] == config.grant_refusal
    assert TestLabConfig.from_environment(env(), runtime_root=tmp_path).to_dict()["grant_refusal"] is None


def test_a_mad_budget_still_builds_every_piece(tmp_path):
    lab = build_test_lab(env(**{MAX_COST_ENV: "1e9"}), runtime_root=tmp_path)
    assert lab.store is not None and lab.catalog is not None and lab.supervisor is not None


# ------------------------------------------------ rework: paths shown to a browser

def test_a_shown_path_hides_the_home_directory():
    """`/api/testlab/status` reaches a browser and an agent's stdout; the absolute form
    carries the account name."""
    inside = Path.home() / "AppData" / "Local" / "runtime"
    shown = display_path(inside)
    assert shown.startswith("~") and str(Path.home()) not in shown
    assert display_path(Path("C:/elsewhere/runtime")) == str(Path("C:/elsewhere/runtime"))


def test_the_status_document_shows_no_absolute_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    document = TestLabConfig.from_environment(env(), runtime_root=tmp_path / "rt").to_dict()
    for name in ("root", "work_root", "runtime_root", "settings_path", "trace_path"):
        assert document[name].startswith("~"), (name, document[name])
