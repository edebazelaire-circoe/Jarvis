"""The replay DSL, productized: fixtures load as Test Lab scenarios (docs/testlab.md, Replay fixtures)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from jarvis.testlab.primitives import AT_MS, DEFAULT_PRIMITIVES, check_scenario
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.replay import (
    ReplayFixtureError,
    load_replay_fixture,
    load_replay_scenario,
    loads_replay_fixture,
    replay_fixture_to_scenario,
    scenario_to_replay_fixture,
)
from jarvis.testlab.scenarios import ProvenanceSourceKind, Scenario, ScenarioStep
from jarvis.testlab.validation import LIMIT_EXCEEDED, TestLabError
import tests.replay.voice_replay as shim

FIXTURES = sorted((Path(__file__).parents[1] / "fixtures" / "voice_replay").glob("*.json"))
#: Pinned so a vocabulary or contract change that silently rewrites a scenario is caught here.
FINGERPRINTS = {
    "backend_nonblocking_85_7s": "387240b006885955",
    "bus_cluster_7": "6b72601ccc934edc",
    "confirmed_interrupt_missing_item": "d7580240a28bd28a",
    "manual_close_late_results": "2291c571531f780b",
    "missing_terminal_stall": "0b2e529dfdeed65f",
    "provider_cancel_after_generation": "c6e590d3850d8877",
    "spoken_divergence": "2d3b9eafecccde74",
    "stale_ack_35_9s": "e4d784ecad07dcd9",
    "thinking_pause_wait": "6fd19ba9bc981d96",
}


def test_the_test_only_module_is_a_thin_layer_over_the_production_codec():
    assert shim.loads_replay_fixture is loads_replay_fixture
    assert shim.load_replay_fixture is load_replay_fixture
    assert shim.ReplayFixtureError is ReplayFixtureError
    assert (shim.SCHEMA, shim.SCHEMA_VERSION) == ("jarvis.voice_replay", 1)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_every_replay_fixture_loads_as_a_valid_test_lab_scenario(path):
    fixture = load_replay_fixture(path)
    scenario = replay_fixture_to_scenario(fixture)

    assert scenario.scenario_id == fixture.scenario_id
    assert [step.primitive for step in scenario.steps] == [step.kind for step in fixture.steps]
    assert [step.args[AT_MS] for step in scenario.steps] == [step.at_ms for step in fixture.steps]
    checked = check_scenario(scenario, primitives=DEFAULT_PRIMITIVES, profiles=[ProfileName.VIRTUAL])
    assert checked.end_ms == fixture.steps[-1].at_ms
    assert scenario.fingerprint()[:16] == FINGERPRINTS[fixture.scenario_id]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_provenance_is_preserved_and_the_conversion_is_reversible(path):
    fixture = load_replay_fixture(path)
    scenario = replay_fixture_to_scenario(fixture)
    provenance = scenario.provenance

    assert provenance.source_path == fixture.provenance.source_path
    assert provenance.source_kind == ProvenanceSourceKind(fixture.provenance.source_kind)
    assert provenance.origin == fixture.origin
    assert [(item.source_ref, item.fact) for item in provenance.reported] == [
        (item.source_ref, item.fact) for item in fixture.provenance.reported]
    assert scenario_to_replay_fixture(scenario) == fixture


def test_a_scenario_document_of_a_fixture_decodes_against_the_registry():
    scenario = load_replay_scenario(FIXTURES[0])
    document = json.loads(json.dumps(scenario.to_dict()))
    assert Scenario.from_dict(document, primitives=DEFAULT_PRIMITIVES).fingerprint() == scenario.fingerprint()


def test_a_scenario_title_and_description_are_optional_additions():
    scenario = load_replay_scenario(FIXTURES[0], title="Backend work stays non blocking")
    assert scenario.title == "Backend work stays non blocking"
    assert scenario_to_replay_fixture(scenario) == load_replay_fixture(FIXTURES[0])


def test_only_replay_primitives_convert_back():
    scenario = Scenario("voice.probe", (ScenarioStep("time.wait", {AT_MS: 0}),),
                        provenance=load_replay_scenario(FIXTURES[0]).provenance)
    with pytest.raises(TestLabError):
        scenario_to_replay_fixture(scenario)
    without_provenance = Scenario("voice.probe", (ScenarioStep("control.stop", {AT_MS: 0, "reason": "manual"}),))
    with pytest.raises(TestLabError):
        scenario_to_replay_fixture(without_provenance)


def document(**changes) -> dict:
    base = json.loads(FIXTURES[0].read_text(encoding="utf-8"))
    base.update(changes)
    return base


def test_the_two_documented_narrowings_are_refused_not_silently_rewritten():
    huge_epoch = document(steps=[{"at_ms": 0, "port": "scheduler", "action": "enqueue",
                                  "data": {"candidate_id": "c", "kind": "ack", "intent_epoch": 2 ** 54}}])
    with pytest.raises(TestLabError) as caught:
        replay_fixture_to_scenario(loads_replay_fixture(json.dumps(huge_epoch)))
    assert caught.value.code == LIMIT_EXCEEDED

    sub_millisecond = loads_replay_fixture(json.dumps(document(origin="2026-09-11T15:45:03.000500+02:00")))
    with pytest.raises(TestLabError):
        replay_fixture_to_scenario(sub_millisecond)


def test_the_replay_codec_still_rejects_test_lab_only_primitives():
    with pytest.raises(ReplayFixtureError) as caught:
        loads_replay_fixture(json.dumps(document(steps=[{"at_ms": 0, "port": "time", "action": "wait",
                                                         "data": {}}])))
    assert caught.value.code == "fixture_action_unknown"


def test_the_shim_clock_and_driver_stay_deterministic():
    clock = shim.ReplayClock(datetime(2026, 9, 11, 13, 43, 35, tzinfo=timezone.utc), monotonic_start=10.25)
    clock.advance_to_ms(35_900)
    assert clock.monotonic_ns() == 46_150_000_000
    with pytest.raises(ReplayFixtureError) as caught:
        clock.advance_to_ms(shim.MAX_TIMELINE_MS + 1)
    assert caught.value.code == "clock_target_invalid"
