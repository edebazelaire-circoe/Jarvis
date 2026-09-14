from __future__ import annotations

from copy import deepcopy

import pytest

from jarvis.domain.prompt_registry import MAX_OVERRIDE_TEXT, PromptTarget
from jarvis.runtime import agent_behavior, agent_routing
from jarvis.runtime.agent_settings import resolve_agent_execution
from jarvis.runtime.prompt_catalog import default_prompt_registry
from jarvis.runtime.prompt_overrides import prompt_override_document, stored_prompt_override_document
from jarvis.runtime.prompt_runtime import prompt_channel


def test_missing_and_damaged_behavior_inherit_without_mutating_settings():
    for settings in ({}, {"agent_behavior": "damaged"}, {"agent_behavior": {"response_verbosity": "future"}}):
        before = deepcopy(settings)
        assert agent_behavior.load(settings) == agent_behavior.AgentBehaviorSettings()
        assert agent_behavior.prompt_instruction(settings) == ""
        assert settings == before


def test_behavior_patch_is_strict_atomic_and_preserves_its_other_value():
    settings = {"kept": {"future": True}}
    agent_behavior.apply(settings, {"response_verbosity": "detailed"})
    agent_behavior.apply(settings, {"politeness_formality": "formal"})

    assert settings == {
        "kept": {"future": True},
        "agent_behavior": {"response_verbosity": "detailed", "politeness_formality": "formal"},
    }
    before = deepcopy(settings)
    with pytest.raises(agent_behavior.AgentBehaviorError) as invalid:
        agent_behavior.apply(settings, {"response_verbosity": "verbose", "politeness_formality": "direct"})
    assert invalid.value.code == "agent_settings_invalid_verbosity"
    assert settings == before


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"politeness_formality": "friendly"}, "agent_settings_invalid_politeness_formality"),
        ({"future": "x"}, "agent_settings_invalid_behavior"),
    ],
)
def test_behavior_rejects_unknown_values_and_fields(payload, code):
    with pytest.raises(agent_behavior.AgentBehaviorError) as invalid:
        agent_behavior.apply({}, payload)
    assert invalid.value.code == code


def test_behavior_metadata_matches_the_live_consumer():
    payload = agent_behavior.describe({})
    fields = {field["id"]: field for field in payload["fields"]}

    assert payload["values"] == {"response_verbosity": "inherit", "politeness_formality": "inherit"}
    assert [option["id"] for option in fields["response_verbosity"]["options"]] == [
        "inherit", "concise", "balanced", "detailed",
    ]
    assert [option["id"] for option in fields["politeness_formality"]["options"]] == [
        "inherit", "direct", "courteous", "formal",
    ]


def test_inherit_preserves_the_original_prompt_override_document_exactly():
    original = {
        "schema_version": 1,
        "overrides": {
            "backend.turn.addition": {
                "base_revision": default_prompt_registry().require("backend.turn.addition").default_revision,
                "text": "Consigne existante.",
            }
        },
    }
    settings = {"prompt_overrides": deepcopy(original), "agent_behavior": {
        "response_verbosity": "inherit", "politeness_formality": "inherit",
    }}

    assert prompt_override_document(settings) == original
    assert settings["prompt_overrides"] == original


def test_non_inherited_behavior_is_composed_once_for_both_agent_clis():
    settings = {"agent_behavior": {"response_verbosity": "concise", "politeness_formality": "courteous"}}
    overrides = prompt_override_document(settings)
    assert overrides is not None
    assert stored_prompt_override_document(settings) is None
    registry = default_prompt_registry()

    for agent_id in ("claude", "codex"):
        resolution = registry.resolve(
            PromptTarget("backend", None, agent_id, None, None, "turn"),
            overrides=overrides,
            variables={"context": {}, "request_text": "Question brute"},
        )
        text = prompt_channel(resolution, "stdin.user_message")
        assert text.count("[Préférences de réponse JARVIS]") == 1
        assert "Réponds de façon concise" in text
        assert "Adopte un ton courtois" in text
        assert text.endswith("[Demande]\nQuestion brute")


def test_agent_execution_carries_only_an_explicit_behavior_consumer_flag(tmp_path):
    inherited = resolve_agent_execution({}, cwd=tmp_path, runtime_root=tmp_path, environ={})
    explicit = resolve_agent_execution(
        {"agent_behavior": {"response_verbosity": "concise", "politeness_formality": "inherit"}},
        cwd=tmp_path, runtime_root=tmp_path, environ={},
    )

    assert inherited.behavior_active is False
    assert inherited.prompt_overrides is None
    assert explicit.behavior_active is True
    assert explicit.prompt_overrides is not None


def test_stale_custom_turn_override_is_not_resurrected_by_behavior_composition():
    settings = {
        "prompt_overrides": {"schema_version": 1, "overrides": {
            "backend.turn.addition": {"base_revision": "0" * 64, "text": "NE PAS RÉANIMER"},
        }},
        "agent_behavior": {"response_verbosity": "detailed", "politeness_formality": "inherit"},
    }

    document = prompt_override_document(settings)

    assert document is not None
    text = document["overrides"]["backend.turn.addition"]["text"]
    assert "NE PAS RÉANIMER" not in text
    assert "Réponds de façon détaillée" in text


def test_behavior_and_saved_turn_addition_share_one_explicit_bound():
    descriptor = default_prompt_registry().require("backend.turn.addition")
    behavior_settings = {
        "agent_behavior": {"response_verbosity": "concise", "politeness_formality": "inherit"},
    }
    behavior = agent_behavior.prompt_instruction(behavior_settings)
    exact = "x" * (MAX_OVERRIDE_TEXT - len(behavior) - 1)
    settings = {**behavior_settings, "prompt_overrides": {"schema_version": 1, "overrides": {
        descriptor.prompt_id: {"base_revision": descriptor.default_revision, "text": exact},
    }}}

    document = prompt_override_document(settings)
    assert len(document["overrides"][descriptor.prompt_id]["text"]) == MAX_OVERRIDE_TEXT

    settings["prompt_overrides"]["overrides"][descriptor.prompt_id]["text"] = exact + "x"
    with pytest.raises(agent_behavior.AgentBehaviorError) as overflow:
        prompt_override_document(settings)
    assert overflow.value.code == "agent_settings_behavior_prompt_too_large"


def test_delegation_projection_and_write_use_only_existing_routing_storage():
    assert agent_routing.delegation_mode({}) == "duplicate"
    assert agent_routing.delegation_mode({"agent_routing": {"enabled": False}}) == "duplicate"
    assert agent_routing.delegation_mode({"agent_routing": {"enabled": True}}) == "auto"

    settings = {"agent_routing": {"enabled": False, "profiles": {
        "code": {"enabled": True, "allow_general_fallback": False,
                 "candidates": [{"agent": "claude", "model": "saved"}]},
    }}}
    agent_routing.apply_delegation_mode(settings, "auto")
    assert settings["agent_routing"]["enabled"] is True
    assert settings["agent_routing"]["profiles"]["code"]["candidates"] == [
        {"agent": "claude", "model": "saved"},
    ]
    assert "delegation_mode" not in settings

    metadata = agent_routing.describe_delegation_modes()
    assert metadata["persistence"] == "agent_routing.enabled"
    assert metadata["default"] == "duplicate"
    assert [option["id"] for option in metadata["options"]] == ["auto", "duplicate"]


def test_invalid_delegation_mode_does_not_mutate_settings():
    settings = {"agent_routing": {"enabled": False, "profiles": {}}}
    before = deepcopy(settings)
    with pytest.raises(Exception) as invalid:
        agent_routing.apply_delegation_mode(settings, "fan-out")
    assert invalid.value.code == "agent_settings_invalid_delegation_mode"
    assert settings == before
