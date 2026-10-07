"""Décideurs du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S5) : modèle remplaçable, jamais de code."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.ports.context_enrichment import (
    MODEL_FAILED, MODEL_TIMEOUT, MODEL_UNAVAILABLE, EnrichmentModelError, EnrichmentReply,
)
from jarvis.ports.tool_brain import (
    DECIDER_FAILED, DECIDER_INVALID_OUTPUT, DECIDER_TIMEOUT, DECIDER_UNAVAILABLE, DeciderError, ToolBrainRequest,
)
from jarvis.runtime.tool_brain_decider import (
    DEFAULT_TOOL_BRAIN_MODEL, MAX_PROMPT_BYTES, ModelToolBrainDecider, RuleToolBrainDecider, build_prompt,
    parse_plan, tool_brain_decider_provider, tool_brain_model_name,
)

PLAN = {"actions": [{"server": "jarvis-display", "tool": "scene_get", "arguments": {"object_ids": ["n1"]},
                     "reason": "show it"}], "rationale": "ok"}


def _request(**overrides) -> ToolBrainRequest:
    base = dict(decision_id="tbd-000001", trigger={"classes": {"user_turn": 1}}, perception={"schema": "p"},
                manifest={"schema": "m", "tools": []}, intents=(), inspections=(), round=0, inspections_left=3)
    return ToolBrainRequest(**{**base, **overrides})


class FakeText:
    model = "fake-model"
    supports_images = False

    def __init__(self, text="", error=None):
        self.text, self.error, self.prompts = text, error, []

    async def complete(self, prompt, *, timeout_s, images=()):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return EnrichmentReply(text=self.text, model="fake-model", cost_usd=0.01, duration_ms=12)


@pytest.mark.parametrize("text", [json.dumps(PLAN), "```json\n" + json.dumps(PLAN) + "\n```",
                                  "Here you go: " + json.dumps(PLAN) + " done"])
async def test_the_model_decider_turns_json_text_into_a_structured_plan(text):
    decider = ModelToolBrainDecider(FakeText(text))
    reply = await decider.decide(_request(), timeout_s=5)
    assert decider.name == "model:fake-model" and reply.model == "fake-model" and reply.cost_usd == 0.01
    assert reply.actions[0].tool == "scene_get" and reply.actions[0].arguments == {"object_ids": ["n1"]}


@pytest.mark.parametrize("text", ["no json here", "{broken", "[1, 2]", '{"actions": [{"tool": "x"}]}',
                                  '{"code": "import os"}'])
async def test_anything_that_is_not_a_plan_is_an_invalid_output_never_code(text):
    with pytest.raises(DeciderError) as caught:
        await ModelToolBrainDecider(FakeText(text)).decide(_request(), timeout_s=5)
    assert caught.value.code == DECIDER_INVALID_OUTPUT


@pytest.mark.parametrize("model_code,expected", [(MODEL_UNAVAILABLE, DECIDER_UNAVAILABLE), (MODEL_TIMEOUT, DECIDER_TIMEOUT),
                                                 (MODEL_FAILED, DECIDER_FAILED)])
async def test_provider_errors_keep_their_real_cause(model_code, expected):
    decider = ModelToolBrainDecider(FakeText(error=EnrichmentModelError(model_code, "credit balance too low")))
    with pytest.raises(DeciderError) as caught:
        await decider.decide(_request(), timeout_s=5)
    assert caught.value.code == expected and "credit balance too low" in caught.value.detail


def test_the_prompt_carries_the_input_the_rules_and_the_allowed_reads_and_is_bounded():
    text = build_prompt(_request(inspections=({"ok": True, "kind": "object"},), round=1, inspections_left=2))
    assert "get_information_on" in text and "never invent an id" in text and '"inspections_left":2' in text
    assert '"manifest":{"schema":"m","tools":[]}' in text
    with pytest.raises(DeciderError) as caught:
        build_prompt(_request(manifest={"blob": "x" * MAX_PROMPT_BYTES}))
    assert caught.value.code == DECIDER_FAILED


def test_parse_plan_takes_the_first_json_object():
    assert parse_plan('x {"a": 1} {"b": 2}') == {"a": 1}


async def test_the_rule_decider_is_deterministic_and_does_nothing_without_a_valid_intent():
    rule = RuleToolBrainDecider()
    assert (await rule.decide(_request(), timeout_s=1)).actions == ()
    refused = {"kind": "reveal", "refs": [{"kind": "object", "id": "x"}], "ref_refusals": ["unknown_object"]}
    assert (await rule.decide(_request(intents=(refused,)), timeout_s=1)).actions == ()
    good = {"kind": "attention", "refs": [{"kind": "object", "id": "n1"}], "ref_refusals": [], "intent_id": "ui1"}
    one = await rule.decide(_request(intents=(good,), inspections=({"ok": True},)), timeout_s=1)
    two = await rule.decide(_request(intents=(good,), inspections=({"ok": True},)), timeout_s=1)
    assert one == two and one.actions[0].tool == "scene_get"


def test_the_model_is_swappable_by_environment_with_a_cheap_default():
    assert tool_brain_model_name({}) == DEFAULT_TOOL_BRAIN_MODEL
    assert tool_brain_model_name({"JARVIS_TOOL_BRAIN_MODEL": " opus "}) == "opus"


def test_the_provider_gives_the_rule_decider_on_request_and_nothing_without_a_native_claude_cli(tmp_path: Path):
    settings = lambda: {"agent_cli": "codex"}  # noqa: E731
    rule = tool_brain_decider_provider(settings, cwd=tmp_path, runtime_root=tmp_path,
                                       environ={"JARVIS_TOOL_BRAIN_DECIDER": "rule"})
    assert isinstance(rule(), RuleToolBrainDecider)
    model = tool_brain_decider_provider(settings, cwd=tmp_path, runtime_root=tmp_path, environ={})
    assert model() is None  # not Claude: unavailable, the runtime backs off and the UI stays as it is
