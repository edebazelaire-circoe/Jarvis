"""Conformance tests for safe Test Lab scenarios (docs/testlab.md, Scenarios)."""

from __future__ import annotations

import json

import pytest

from jarvis.testlab.scenarios import (
    MAX_STEP_ARGS_BYTES,
    MAX_STEPS,
    SHAPE_ONLY,
    Scenario,
    ScenarioStep,
    check_scenario_primitives,
)
from jarvis.testlab.validation import (
    FIELDS_MISMATCH,
    FORBIDDEN_CODE,
    FORBIDDEN_PRIVATE_DATA,
    LIMIT_EXCEEDED,
    REFERENCE_INVALID,
    SCHEMA_UNSUPPORTED,
    ForbiddenCodeError,
    TestLabError,
    TestLabRedactionError,
)

PRIMITIVES = frozenset({"user.turn", "provider.output_started", "control.checkpoint"})


def decode(document: object) -> Scenario:
    return Scenario.from_dict(document, primitives=PRIMITIVES)


def payload(**changes) -> dict:
    document = {
        "schema": "jarvis.testlab.scenario",
        "schema_version": 1,
        "scenario_id": "echo.interrupt_basic",
        "title": "User interrupts Jarvis",
        "description": "Jarvis speaks, the user says stop.",
        "provenance": None,
        "steps": [
            {"primitive": "provider.output_started", "args": {"output_id": "out-1", "at_ms": 0}},
            {"primitive": "user.turn", "args": {"turn_id": "t1", "content_tag": "stop",
                                                "timing": {"at_ms": 250, "jitter": [0, 5, 10.5]},
                                                "addressing": None, "flags": {"barge_in": True}}},
            {"primitive": "control.checkpoint", "args": {}},
        ],
    }
    document.update(changes)
    return document


def with_args(args: object) -> dict:
    return payload(steps=[{"primitive": "user.turn", "args": args}])


def test_round_trip_is_stable_and_read_only():
    scenario = Scenario.from_dict(payload(), primitives=PRIMITIVES)
    encoded = json.loads(json.dumps(scenario.to_dict()))
    assert encoded == payload()
    assert decode(encoded) == scenario
    assert decode(encoded).fingerprint() == scenario.fingerprint()
    assert hash(decode(encoded)) == hash(scenario)
    args = scenario.steps[1].args
    assert args["timing"]["jitter"] == (0, 5, 10.5)
    with pytest.raises(TypeError):
        args["timing"]["at_ms"] = 1


def test_fingerprint_depends_on_step_order():
    steps = payload()["steps"]
    assert (decode(payload()).fingerprint()
            != decode(payload(steps=list(reversed(steps)))).fingerprint())


@pytest.mark.parametrize("args", [
    {"code": "print(1)"},
    {"shell": "dir"},
    {"on_start": {"exec": "x"}},
    {"timing": {"deep": [{"module": "os"}]}},
    {"hook": {"a": {"b": {"c": [{"python_callable": "x"}]}}}},
    {"__class__": 1},
    {"text": "__import__('os').system('dir')"},
    {"list": ["ok", {"nested": "import subprocess"}]},
    {"a": {"b": {"c": {"d": "os.system('dir')"}}}},
    {"cmdline": "dir"},
    {"hook": {"on_exit_command": "x"}},
    {"text": "().__class__.__bases__"},
    {"x": "from subprocess import run"},
    {"x": "getattr(__builtins__, 'open')"},
])
def test_forbidden_code_is_rejected_at_any_depth(args):
    with pytest.raises(ForbiddenCodeError) as caught:
        decode(with_args(args))
    assert caught.value.code == FORBIDDEN_CODE
    with pytest.raises(ForbiddenCodeError):
        ScenarioStep("user.turn", args)


def test_code_rejection_names_the_path_never_the_value():
    with pytest.raises(ForbiddenCodeError) as caught:
        decode(with_args({"a": [{"b": "eval(secret_payload)"}]}))
    assert "scenario.steps[0].args.a[0].b" in str(caught.value)
    assert "secret_payload" not in str(caught.value)


@pytest.mark.parametrize("value", [{1, 2}, object(), len, lambda: None, complex(1, 2)])
def test_non_json_values_are_rejected(value):
    with pytest.raises(ForbiddenCodeError):
        ScenarioStep("user.turn", {"value": value})


def test_raw_bytes_and_private_keys_are_redaction_errors():
    with pytest.raises(TestLabRedactionError) as caught:
        ScenarioStep("user.turn", {"clip": b"RIFF"})
    assert caught.value.code == FORBIDDEN_PRIVATE_DATA
    with pytest.raises(TestLabRedactionError):
        decode(with_args({"deep": {"system_prompt": "x"}}))
    with pytest.raises(TestLabRedactionError):
        decode(payload(chain_of_thought="x"))


@pytest.mark.parametrize("utterance", [
    "Jarvis, import the calendar and run the command later",
    "import photos", "Import contacts", "Je suis un utilisateur lambda : peux-tu m'aider ?",
    "Un citoyen lambda, il est 10:30", "Le subprocess a planté", "Compile (vite) le rapport",
    "exec (le directeur) arrive", "__Important__ : rappelle-moi", "Lance python -c dans le terminal",
    "Ça coûte $(10)", "from Paris import wine", "#! bonjour", "Évalue (eval) la situation",
])
def test_natural_utterances_are_allowed(utterance):
    assert ScenarioStep("user.turn", {"utterance": utterance}).args["utterance"] == utterance
    assert decode(with_args({"utterance": utterance})).steps[0].args["utterance"] == utterance


@pytest.mark.parametrize("key", ["reason_code", "status_code", "module_id", "prompt_id", "reasoning_tokens",
                                 "token_budget", "thinking_pause_ms", "command_timeout_ms", "function_name"])
def test_metadata_arg_keys_are_allowed(key):
    assert key in ScenarioStep("user.turn", {key: 1}).args


def test_primitives_is_a_required_explicit_choice():
    with pytest.raises(TypeError):
        Scenario.from_dict(payload())
    for bad in ("user.turn", None, 3):
        with pytest.raises(TestLabError):
            Scenario.from_dict(payload(), primitives=bad)
    assert Scenario.from_dict(payload(), primitives=SHAPE_ONLY) == decode(payload())


@pytest.mark.parametrize("args", [
    {"TurnId": "t1"},
    {"turn.id": "t1"},
    {"": 1},
    {"a": float("nan")},
    {"a": 2**60},
    {"a": "x" * 513},
    {"a": list(range(65))},
])
def test_arg_shape_is_bounded(args):
    with pytest.raises(TestLabError):
        ScenarioStep("user.turn", args)


def test_depth_and_size_limits():
    deep: dict = {"leaf": 1}
    for _ in range(7):
        deep = {"n": deep}
    with pytest.raises(TestLabError) as caught:
        ScenarioStep("user.turn", deep)
    assert caught.value.code == LIMIT_EXCEEDED
    big = {f"k{index}": "x" * 100 for index in range(50)}
    assert len(json.dumps(big)) > MAX_STEP_ARGS_BYTES
    with pytest.raises(TestLabError) as caught:
        ScenarioStep("user.turn", big)
    assert caught.value.code == LIMIT_EXCEEDED
    step = {"primitive": "control.checkpoint", "args": {}}
    with pytest.raises(TestLabError):
        decode(payload(steps=[step] * (MAX_STEPS + 1)))
    with pytest.raises(TestLabError):
        decode(payload(steps=[]))


def test_primitive_names_and_registry_hook():
    for name in ("User.turn", "user turn", "user/turn", "", None, "os.system("):
        with pytest.raises(TestLabError):
            ScenarioStep(name, {})
    unregistered = payload(steps=[{"primitive": "device.consume", "args": {}}])
    Scenario.from_dict(unregistered, primitives=SHAPE_ONLY)  # explicit opt-out: shape and safety only
    with pytest.raises(TestLabError) as caught:
        Scenario.from_dict(unregistered, primitives=PRIMITIVES)
    assert caught.value.code == REFERENCE_INVALID
    check_scenario_primitives(decode(payload()), PRIMITIVES)


def test_strict_document_fields():
    with pytest.raises(TestLabError) as caught:
        decode(payload(extra=1))
    assert caught.value.code == FIELDS_MISMATCH
    document = payload()
    document["steps"][0]["when"] = 5
    with pytest.raises(TestLabError) as caught:
        decode(document)
    assert caught.value.code == FIELDS_MISMATCH
    document = payload()
    del document["title"]
    with pytest.raises(TestLabError):
        decode(document)
    for key, value in (("schema_version", 2), ("schema", "jarvis.voice_replay")):
        with pytest.raises(TestLabError) as caught:
            decode(payload(**{key: value}))
        assert caught.value.code == SCHEMA_UNSUPPORTED
    with pytest.raises(TestLabError):
        decode(payload(steps={"0": {}}))
    with pytest.raises(TestLabError):
        decode(payload(steps=[{"primitive": "user.turn", "args": ["not", "an", "object"]}]))


def test_title_and_description_cannot_carry_code():
    with pytest.raises(ForbiddenCodeError):
        Scenario("echo.basic", (ScenarioStep("user.turn", {}),), description="exec(open('x').read())")
