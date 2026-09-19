"""Conformance tests for the Test Lab primitive vocabulary (docs/testlab.md, Scenario primitives)."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from jarvis.testlab.diagnostics import ParameterSpec, ParameterType
from jarvis.testlab.primitives import (
    ALL_PROFILES,
    AT_MS,
    DEFAULT_PRIMITIVES,
    MAX_SPEECH_TEXT_CHARS,
    MAX_TIMELINE_MS,
    PRIMITIVE_ARGS_INVALID,
    PRIMITIVE_PROFILE_UNSUPPORTED,
    PRIMITIVE_UNKNOWN,
    SCENARIO_TIMELINE_INVALID,
    ArgRule,
    PrimitiveArgError,
    PrimitiveError,
    PrimitiveRegistry,
    PrimitiveSpec,
    ScenarioContext,
    check_scenario,
    missing_handlers,
)
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.validation import (
    FORBIDDEN_CODE,
    FORBIDDEN_PRIVATE_DATA,
    PARAMETER_INVALID,
    REFERENCE_INVALID,
    ForbiddenCodeError,
    TestLabError,
    TestLabRedactionError,
)
from tests.fakes.testlab import self_echo_spec

REPLAY_ACTIONS = {
    "user.turn", "brain.hold", "brain.ready", "brain.release", "scheduler.enqueue", "provider.output_started",
    "provider.transcript_final", "provider.output_done", "provider.cancel_rejected", "provider.session_closed",
    "owner.candidate", "owner.rejected", "owner.confirmed", "device.output_busy", "device.consume",
    "device.release", "control.stop", "control.checkpoint",
}


def scenario(*steps: tuple[str, dict], scenario_id: str = "voice.probe") -> Scenario:
    return Scenario(scenario_id, tuple(ScenarioStep(primitive, args) for primitive, args in steps))


def step(primitive: str, **args) -> Scenario:
    return scenario((primitive, {AT_MS: 0, **args}))


def refused(primitive: str, **args) -> TestLabError:
    with pytest.raises(TestLabError) as caught:
        check_scenario(step(primitive, **args))
    return caught.value


# ------------------------------------------------------------- the registry

def test_registry_is_a_superset_of_the_replay_dsl_with_identical_action_names():
    assert set(DEFAULT_PRIMITIVES.replay_actions()) == REPLAY_ACTIONS
    assert REPLAY_ACTIONS < set(DEFAULT_PRIMITIVES)
    assert {"user.speech", "user.interrupt", "time.wait", "audio.inject", "parameter.override", "expect.event",
            "expect.metric", "expect.assertion"} <= set(DEFAULT_PRIMITIVES)


def test_registry_is_the_collection_scenarios_decode_against():
    document = step("control.checkpoint", checkpoint_id="settled").to_dict()
    assert Scenario.from_dict(document, primitives=DEFAULT_PRIMITIVES).steps[0].primitive == "control.checkpoint"
    with pytest.raises(TestLabError) as caught:
        Scenario.from_dict(scenario(("python.exec", {AT_MS: 0})).to_dict(), primitives=DEFAULT_PRIMITIVES)
    assert caught.value.code == REFERENCE_INVALID


def test_every_primitive_declares_a_family_arguments_and_profiles():
    for spec in DEFAULT_PRIMITIVES.specs:
        assert spec.name.startswith(f"{spec.family.value}.")
        assert spec.profiles and spec.profiles <= ALL_PROFILES
        assert AT_MS not in (*spec.required, *spec.optional)
        assert spec.to_dict()["arguments"]["common"] == [AT_MS]


def test_registry_refuses_duplicates_and_malformed_specs():
    spec = DEFAULT_PRIMITIVES.get("time.wait")
    with pytest.raises(TestLabError):
        PrimitiveRegistry((spec, spec))
    with pytest.raises(TestLabError):
        PrimitiveSpec("time.wait", spec.family, ("unknown_argument",), (), frozenset({ProfileName.VIRTUAL}), "x")
    with pytest.raises(TestLabError):
        PrimitiveSpec("wait", spec.family, (), (), frozenset({ProfileName.VIRTUAL}), "x")


def test_unknown_primitive_is_named_by_its_own_code():
    with pytest.raises(PrimitiveError) as caught:
        check_scenario(scenario(("shell.run", {AT_MS: 0})))
    assert caught.value.code == PRIMITIVE_UNKNOWN


# ----------------------------------------------------------- argument rules

@pytest.mark.parametrize(("args", "rule"), [
    ({"turn_id": "t-1"}, ArgRule.FIELDS),                      # content_tag missing
    ({"turn_id": "t-1", "content_tag": "c", "extra": 1}, ArgRule.FIELDS),
    ({"turn_id": "", "content_tag": "c"}, ArgRule.NOT_TEXT),
    ({"turn_id": "x" * 129, "content_tag": "c"}, ArgRule.TOO_LONG),
    ({"turn_id": "unsafe id", "content_tag": "c"}, ArgRule.INVALID),
    ({"turn_id": 12, "content_tag": "c"}, ArgRule.NOT_TEXT),
    ({"turn_id": "t-1", "content_tag": "c", "addressing": "maybe"}, ArgRule.INVALID),
])
def test_identifier_and_choice_arguments_report_the_failed_rule(args, rule):
    error = refused("user.turn", **args)
    assert error.code == PRIMITIVE_ARGS_INVALID and error.rule is rule


def test_identifier_and_choice_arguments_accept_the_declared_shapes():
    check_scenario(step("user.turn", turn_id="turn.1:a-b", content_tag="tag_1", addressing="uncertain"))
    check_scenario(step("owner.confirmed", candidate_id="c1", played_ms=0, provider_item_id=None))


@pytest.mark.parametrize("value", [True, -1, 1.5, "1", MAX_TIMELINE_MS + 1])
def test_integer_arguments_reject_booleans_floats_and_out_of_range(value):
    assert refused("device.consume", output_id="out", played_ms=value).rule is ArgRule.INVALID


def test_boolean_argument_rejects_an_integer():
    assert refused("device.release", output_id="out", provider_still_active=1).rule is ArgRule.INVALID


def test_output_busy_needs_an_output_or_a_playback():
    assert refused("device.output_busy").rule is ArgRule.FIELDS
    check_scenario(step("device.output_busy", playback_id="local"))


def test_expected_event_counts_must_be_ordered_and_named_by_the_event_vocabulary():
    check_scenario(step("expect.event", event="mouth.speech.started", count_min=1, count_max=2))
    assert refused("expect.event", event="mouth.speech.started", count_min=3, count_max=2).rule is ArgRule.INVALID
    assert refused("expect.event", event="mouth.speech.invented").rule is ArgRule.INVALID


@pytest.mark.parametrize(("audio_ref", "ok"), [
    ("bonjour-jarvis.wav", True), ("clips/echo.wav", True), ("../secret.wav", False), ("/abs/clip.wav", False),
    ("clip.mp3", False), ("clip.wav.exe", False),
])
def test_audio_injection_takes_a_bounded_fixture_reference_never_bytes(audio_ref, ok):
    if ok:
        check_scenario(step("audio.inject", audio_ref=audio_ref), profiles=[ProfileName.AUDIO])
    else:
        assert refused("audio.inject", audio_ref=audio_ref).rule is ArgRule.INVALID
    with pytest.raises(TestLabRedactionError):
        check_scenario(step("audio.inject", audio_ref=b"RIFF"))


def test_audio_gain_is_bounded():
    check_scenario(step("audio.inject", audio_ref="clip.wav", gain_db=-6), profiles=[ProfileName.AUDIO])
    assert refused("audio.inject", audio_ref="clip.wav", gain_db=99).rule is ArgRule.INVALID


# ------------------------------------------------------- user speech privacy

def test_user_speech_text_is_bounded_single_line_authored_input():
    check_scenario(step("user.speech", turn_id="t1", text="Jarvis, quelle heure est-il ?"))
    assert refused("user.speech", turn_id="t1", text="x" * (MAX_SPEECH_TEXT_CHARS + 1)).rule is ArgRule.TOO_LONG
    assert refused("user.speech", turn_id="t1", text="line\nline").rule is ArgRule.INVALID


@pytest.mark.parametrize("text", ["ecris a webmaster@circoe.com", "ouvre https://user:pass@host/x"])
def test_user_speech_text_refuses_identifying_data(text):
    with pytest.raises(TestLabRedactionError) as caught:
        check_scenario(step("user.speech", turn_id="t1", text=text))
    assert caught.value.code == FORBIDDEN_PRIVATE_DATA


# ---------------------------------------------------------------- timeline

def test_timeline_is_required_non_decreasing_and_bounded():
    assert check_scenario(scenario(("time.wait", {AT_MS: 0}), ("time.wait", {AT_MS: 35900}))).end_ms == 35900
    with pytest.raises(PrimitiveArgError) as missing:
        check_scenario(scenario(("time.wait", {})))
    assert missing.value.rule is ArgRule.FIELDS
    for steps in (((AT_MS, 10), (AT_MS, 9)),):
        with pytest.raises(PrimitiveError) as backwards:
            check_scenario(scenario(("time.wait", {AT_MS: steps[0][1]}), ("time.wait", {AT_MS: steps[1][1]})))
        assert backwards.value.code == SCENARIO_TIMELINE_INVALID
    with pytest.raises(PrimitiveError) as too_far:
        check_scenario(scenario(("time.wait", {AT_MS: MAX_TIMELINE_MS + 1})))
    assert too_far.value.code == SCENARIO_TIMELINE_INVALID


# ------------------------------------------------------------ profile rules

def test_a_scenario_is_validated_against_the_chosen_profile():
    checked = check_scenario(step("control.checkpoint", checkpoint_id="settled"))
    assert checked.supported_profiles == ALL_PROFILES
    assert check_scenario(step("user.turn", turn_id="t", content_tag="c")).supported_profiles == {
        ProfileName.VIRTUAL}
    with pytest.raises(PrimitiveError) as caught:
        check_scenario(step("user.turn", turn_id="t", content_tag="c"), profiles=[ProfileName.LIVE])
    assert caught.value.code == PRIMITIVE_PROFILE_UNSUPPORTED


def test_audio_injection_is_not_a_virtual_primitive():
    with pytest.raises(PrimitiveError) as caught:
        check_scenario(step("audio.inject", audio_ref="clip.wav"), profiles=[ProfileName.VIRTUAL])
    assert caught.value.code == PRIMITIVE_PROFILE_UNSUPPORTED


def test_missing_handlers_lists_what_a_runner_must_implement():
    covered = DEFAULT_PRIMITIVES.for_profile(ProfileName.VIRTUAL)
    assert missing_handlers(DEFAULT_PRIMITIVES, ProfileName.VIRTUAL, covered) == ()
    assert "time.wait" in missing_handlers(DEFAULT_PRIMITIVES, ProfileName.VIRTUAL, covered - {"time.wait"})


# ------------------------------------------------------ parameters and expectations

def context() -> ScenarioContext:
    return ScenarioContext.for_diagnostic(self_echo_spec(), (
        ParameterSpec("speech.stale_ttl_ms", ParameterType.INT, 60000, minimum=0, maximum=600000),))


def test_parameter_override_is_a_validated_prelude():
    checked = check_scenario(
        scenario(("parameter.override", {AT_MS: 0, "parameter": "turns", "value": 5}),
                 ("parameter.override", {AT_MS: 0, "parameter": "speech.stale_ttl_ms", "value": 1000}),
                 ("time.wait", {AT_MS: 10})), context=context())
    assert dict(checked.overrides) == {"speech.stale_ttl_ms": 1000, "turns": 5}


@pytest.mark.parametrize(("steps", "code"), [
    ((("time.wait", {AT_MS: 0}), ("parameter.override", {AT_MS: 0, "parameter": "turns", "value": 5})),
     SCENARIO_TIMELINE_INVALID),
    ((("parameter.override", {AT_MS: 5, "parameter": "turns", "value": 5}),), SCENARIO_TIMELINE_INVALID),
    ((("parameter.override", {AT_MS: 0, "parameter": "turns", "value": 5}),
      ("parameter.override", {AT_MS: 0, "parameter": "turns", "value": 6})), PRIMITIVE_ARGS_INVALID),
    ((("parameter.override", {AT_MS: 0, "parameter": "unknown.setting", "value": 5}),), PARAMETER_INVALID),
    ((("parameter.override", {AT_MS: 0, "parameter": "turns", "value": 99}),), PARAMETER_INVALID),
])
def test_parameter_override_refusals(steps, code):
    with pytest.raises(TestLabError) as caught:
        check_scenario(scenario(*steps), context=context())
    assert caught.value.code == code


def test_expectations_must_name_declared_metrics_and_assertions():
    check_scenario(step("expect.metric", metric="speech.ready_to_play_ms", comparator="le", threshold=800),
                   context=context())
    check_scenario(step("expect.assertion", assertion_id="no_false_barge_in", outcome="failed"), context=context())
    for args, primitive in ((dict(metric="speech.invented_ms", comparator="le", threshold=1), "expect.metric"),
                            (dict(assertion_id="invented", outcome="passed"), "expect.assertion")):
        with pytest.raises(TestLabError) as caught:
            check_scenario(step(primitive, **args), context=context())
        assert caught.value.code == REFERENCE_INVALID


def test_expectation_thresholds_obey_the_assertion_rules():
    with pytest.raises(TestLabError) as caught:
        check_scenario(step("expect.metric", metric="speech.ready_to_play_ms", comparator="eq", threshold=800),
                       context=context())
    assert caught.value.code == REFERENCE_INVALID


def test_declared_names_are_only_checked_with_a_context():
    check_scenario(step("expect.metric", metric="speech.invented_ms", comparator="le", threshold=1))


# --------------------------------------------------------- code is refused

@pytest.mark.parametrize("args", [
    {AT_MS: 0, "checkpoint_id": "c", "command": "rm -rf /"},
    {AT_MS: 0, "checkpoint_id": "c", "python_code": "print(1)"},
    {AT_MS: 0, "checkpoint_id": "__import__('os').system('x')"},
])
def test_code_carrying_arguments_never_reach_a_primitive(args):
    with pytest.raises(ForbiddenCodeError) as caught:
        ScenarioStep("control.checkpoint", args)
    assert caught.value.code == FORBIDDEN_CODE


def test_both_step_checks_name_an_argument_with_the_same_indexed_path():
    """The Slice 01 decode path and the primitive path must agree: `steps[0].args.text`."""
    document = step("user.speech", turn_id="t1", text="ok").to_dict()
    document["steps"][0]["args"]["text"] = "x" * 600
    with pytest.raises(TestLabError) as decoded:
        Scenario.from_dict(document, primitives=DEFAULT_PRIMITIVES)
    assert decoded.value.detail.startswith("steps[0].args.text ")

    with pytest.raises(TestLabError) as checked:
        check_scenario(step("user.speech", turn_id="t1", text="x" * 400))
    assert checked.value.detail.startswith("steps[0].args.text ")

    with pytest.raises(TestLabError) as standalone:
        ScenarioStep("user.speech", {AT_MS: 0, "text": "x" * 600})
    assert standalone.value.detail.startswith("step.args.text "), "no index exists outside a scenario"


def test_the_documented_table_matches_the_registry():
    """docs/testlab.md, Scenario primitives: the table is the contract, not a copy that drifts."""
    document = (Path(__file__).parents[2] / "docs" / "testlab.md").read_text(encoding="utf-8")
    section = document.split("## Scenario primitives", 1)[1].split("## Replay fixtures", 1)[0]
    documented = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if len(cells) == 5 and re.fullmatch(r"`[a-z_]+\.[a-z_]+`", cells[0]):
            documented[cells[0].strip("`")] = tuple(
                frozenset(re.findall(r"`([a-z_]+)`", cell)) for cell in cells[1:3])
    assert set(documented) == set(DEFAULT_PRIMITIVES)
    for name, (required, optional) in documented.items():
        spec = DEFAULT_PRIMITIVES.get(name)
        assert (required, optional) == (frozenset(spec.required), frozenset(spec.optional)), name


def test_a_scenario_cannot_name_an_executable_primitive():
    with pytest.raises(PrimitiveError) as caught:
        check_scenario(scenario(("os.system", {AT_MS: 0})))
    assert caught.value.code == PRIMITIVE_UNKNOWN
