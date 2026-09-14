"""Task15A registry, provenance, resolution, and override-store contract."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from jarvis.adapters.openai_realtime import (
    CONTINUOUS_BRAIN_OPERATING_RULES,
    JARVIS_PERSONA,
    OPERATING_RULES,
    VERBATIM_SPEECH_INSTRUCTION,
    build_reflex_instruction,
    build_session_instructions,
)
from jarvis.domain.conversation_prompt import CONVERSATION_OPERATING_RULES
from jarvis.domain.front_brain_prompt import FRONT_BRAIN_INSTRUCTIONS, front_brain_schema
from jarvis.domain.live_prompt import LIVE_OPERATING_RULES
from jarvis.domain.prompt_registry import PromptError, PromptTarget
from jarvis.runtime.back_brain_delegation import conversation_tools
from jarvis.runtime.claude_local import (
    BRAIN_SYSTEM_PROMPT,
    JOB_RESULT_SYSTEM_PROMPT,
    SPECULATIVE_SYSTEM_PROMPT,
)
from jarvis.runtime.control_center import build_agent_brief
from jarvis.runtime.prompt_catalog import default_prompt_registry
from jarvis.runtime.prompt_overrides import PromptOverrideStore, prompt_override_document
from jarvis.runtime.agent_behavior import AgentBehaviorError
from jarvis.runtime.realtime_tools import tools_for


def channel(resolution, name):
    return next(item for item in resolution.channels if item["channel"] == name)


@pytest.mark.parametrize("architecture", ["simple", "front_brain"])
def test_explicit_realtime_session_resolves_exact_current_material(architecture):
    registry = default_prompt_registry()
    context = {"voice_ledger": {}, "recent_turns": [
        {"kind": "user", "content": "question"},
        {"kind": "assistant", "content": "heard answer"},
    ]}
    result = registry.resolve(
        PromptTarget("conversation", architecture, "openai", "registered-model", "explicit", "session"),
        variables={"context": context},
    )
    assert channel(result, "session.instructions")["text"] == JARVIS_PERSONA + " " + CONVERSATION_OPERATING_RULES
    assert json.loads(channel(result, "session.initial_context")["text"]) == [
        {"role": "user", "text": "question"},
        {"role": "assistant", "text": "heard answer"},
    ]
    assert json.loads(channel(result, "session.tools")["text"]) == conversation_tools()


@pytest.mark.parametrize(("provider", "compatibility", "rules", "expected_tools"), [
    ("openai", "legacy", OPERATING_RULES, tools_for(continuous_brain=False)),
    ("google", "legacy", OPERATING_RULES, tools_for(continuous_brain=False)),
    ("openai", "continuous_brain", CONTINUOUS_BRAIN_OPERATING_RULES, tools_for(continuous_brain=True)),
])
def test_compatibility_sessions_match_actual_instruction_builder(provider, compatibility, rules, expected_tools):
    registry = default_prompt_registry()
    context = {"recent_turns": [{"kind": "user", "content": str(index)} for index in range(14)]}
    result = registry.resolve(
        PromptTarget("conversation", "simple", provider, "exact-model", compatibility, "session"),
        variables={"context": context},
    )
    assert channel(result, "session.instructions")["text"] == build_session_instructions(
        context, continuous_brain=compatibility == "continuous_brain"
    )
    assert channel(result, "session.instructions")["text"].startswith(JARVIS_PERSONA + " " + rules)
    assert json.loads(channel(result, "session.tools")["text"]) == expected_tools


def test_continuous_gemini_is_not_a_registered_prompt_program():
    with pytest.raises(PromptError) as failure:
        default_prompt_registry().resolve(
            PromptTarget("conversation", "simple", "google", "model", "continuous_brain", "session"),
            variables={"context": {}},
        )
    assert failure.value.code == "prompt_target_unsupported"


def test_duplex_has_live_rules_and_structured_initial_context_without_realtime_persona():
    context = {"recent_turns": [{"kind": "user", "content": "hello"}]}
    result = default_prompt_registry().resolve(
        PromptTarget("conversation", "duplex", "openai", "gpt-live-1", "explicit", "session"),
        variables={"context": context},
    )
    assert channel(result, "session.instructions")["text"] == LIVE_OPERATING_RULES
    assert JARVIS_PERSONA not in channel(result, "session.instructions")["text"]
    assert json.loads(channel(result, "session.initial_context")["text"]) == [{"role": "user", "text": "hello"}]


def test_response_replacements_and_analysis_channels_remain_separate():
    registry = default_prompt_registry()
    reflex = registry.resolve(
        PromptTarget("reflex", provider="openai", model="m", compatibility="explicit", invocation="reflex"),
        variables={"transcript": "Une demande", "avoid": ["Un instant."]},
    )
    assert reflex.channels == ({"channel": "response.instructions", "operation": "replace",
                                "text": build_reflex_instruction("Une demande", ["Un instant."])},)
    verbatim = registry.resolve(
        PromptTarget("speech", provider="openai", model="m", compatibility="legacy", invocation="verbatim"),
        variables={"text": "Résultat exact"},
    )
    assert channel(verbatim, "response.instructions")["text"] == VERBATIM_SPEECH_INSTRUCTION.format(text="Résultat exact")

    analysis = registry.resolve(
        PromptTarget("analysis", "front_brain", "openai", "gpt-5.6-luna", "explicit", "hint"),
        variables={"observation": {"input": "untrusted"}},
    )
    assert channel(analysis, "request.instructions")["text"] == FRONT_BRAIN_INSTRUCTIONS
    assert json.loads(channel(analysis, "request.user_message")["text"]) == {"input": "untrusted"}
    assert json.loads(channel(analysis, "request.response_schema")["text"]) == front_brain_schema()


@pytest.mark.parametrize(("invocation", "expected_channel", "expected"), [
    ("conversation_session", "cli.append_system_prompt", BRAIN_SYSTEM_PROMPT),
    ("job_result_session", "cli.append_system_prompt", JOB_RESULT_SYSTEM_PROMPT),
    ("speculative_session", "cli.system_prompt", SPECULATIVE_SYSTEM_PROMPT),
])
def test_claude_profiles_keep_append_and_replace_semantics(invocation, expected_channel, expected):
    result = default_prompt_registry().resolve(
        PromptTarget("backend", provider="claude", model="configured", compatibility="legacy", invocation=invocation)
    )
    assert channel(result, expected_channel)["text"] == expected
    assert channel(result, expected_channel)["operation"] == ("replace" if invocation == "speculative_session" else "append")


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_backend_turn_uses_the_actual_brief_without_claiming_claude_system_for_codex(provider):
    context = {"addressing": "addressed", "state": {"conversation_goal": "test"}}
    result = default_prompt_registry().resolve(
        PromptTarget("backend", provider=provider, model="configured", compatibility="explicit", invocation="turn"),
        variables={"context": context, "request_text": "Continue"},
    )
    assert channel(result, "stdin.user_message")["text"] == build_agent_brief(context, "Continue")
    if provider == "codex":
        assert BRAIN_SYSTEM_PROMPT not in json.dumps(result.to_payload(), ensure_ascii=False)


def test_valid_override_changes_effective_revision_and_fingerprint_while_stale_falls_back():
    registry = default_prompt_registry()
    descriptor = registry.require("voice.persona")
    target = PromptTarget("conversation", "simple", "openai", "m", "explicit", "session")
    base = registry.resolve(target, variables={"context": {}})
    document = {"schema_version": 1, "overrides": {
        descriptor.prompt_id: {"base_revision": descriptor.default_revision, "text": "A different concise persona."}
    }}
    changed = registry.resolve(target, overrides=document, variables={"context": {}})
    assert changed.static_fingerprint != base.static_fingerprint
    layer = next(item for item in changed.layers if item["prompt_id"] == descriptor.prompt_id)
    assert layer["source"] == "override"
    assert layer["effective_revision"] != layer["base_revision"]

    stale = deepcopy(document)
    stale["overrides"][descriptor.prompt_id]["base_revision"] = "0" * 64
    fallback = registry.resolve(target, overrides=stale, variables={"context": {}})
    stale_layer = next(item for item in fallback.layers if item["prompt_id"] == descriptor.prompt_id)
    assert stale_layer["source"] == "default" and stale_layer["conflict"] == "prompt_override_stale"
    assert channel(fallback, "session.instructions")["text"].startswith(JARVIS_PERSONA)


class Journal:
    def __init__(self):
        self.events = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append({"kind": kind, "message": message, "level": level, "data": data})


def test_override_store_preserves_unrelated_unknown_entries_and_rolls_back_rejections():
    registry = default_prompt_registry()
    known = registry.require("voice.persona")
    future = {"base_revision": "a" * 64, "text": "future value"}
    state = {"other": {"nested": [1]}, "prompt_overrides": {"schema_version": 1, "overrides": {"future.layer": future}}}
    writes = []
    journal = Journal()

    def write(value):
        writes.append(deepcopy(value))
        state.clear(); state.update(deepcopy(value))

    store = PromptOverrideStore(registry, read_settings=lambda: state, write_settings=write, diagnostics=journal)
    inspected = store.inspect()
    revision = next(item for item in inspected["layers"] if item["prompt_id"] == known.prompt_id)["effective_revision"]
    result = store.edit(known.prompt_id, text="Edited persona", base_revision=known.default_revision,
                        expected_effective_revision=revision)
    assert result["changed"] and state["other"] == {"nested": [1]}
    assert state["prompt_overrides"]["overrides"]["future.layer"] == future
    before = deepcopy(state)
    with pytest.raises(PromptError) as failure:
        store.edit("voice.rules.legacy", text="unsafe", base_revision=registry.require("voice.rules.legacy").default_revision)
    assert failure.value.code == "prompt_read_only" and state == before
    assert all("Edited persona" not in json.dumps(event) for event in journal.events)

    store.reset(known.prompt_id)
    assert state["prompt_overrides"]["overrides"] == {"future.layer": future}
    assert prompt_override_document(state)["overrides"] == {"future.layer": future}


def test_override_store_detects_concurrent_editor_and_writer_failure_without_false_success():
    registry = default_prompt_registry()
    descriptor = registry.require("voice.persona")
    state = {}
    journal = Journal()
    fail = False

    def writer(value):
        if fail:
            raise PermissionError("controlled lock")
        state.clear(); state.update(deepcopy(value))

    store = PromptOverrideStore(registry, read_settings=lambda: state, write_settings=writer, diagnostics=journal)
    old = next(item for item in store.inspect()["layers"] if item["prompt_id"] == descriptor.prompt_id)["effective_revision"]
    store.edit(descriptor.prompt_id, text="first", base_revision=descriptor.default_revision,
               expected_effective_revision=old)
    snapshot = deepcopy(state)
    with pytest.raises(PromptError) as failure:
        store.edit(descriptor.prompt_id, text="second", base_revision=descriptor.default_revision,
                   expected_effective_revision=old)
    assert failure.value.code == "prompt_override_concurrent" and state == snapshot

    fail = True
    with pytest.raises(PermissionError):
        store.edit(descriptor.prompt_id, text="third", base_revision=descriptor.default_revision)
    assert state == snapshot
    assert journal.events[-1]["kind"] == "prompt.override.write_failed"
    assert not any(event["kind"] == "prompt.override.saved" and event["data"]["fingerprint"] is None
                   for event in journal.events)


def test_override_store_rejects_behavior_combination_overflow_before_writer():
    registry = default_prompt_registry()
    descriptor = registry.require("backend.turn.addition")
    state = {"sentinel": "kept", "agent_behavior": {
        "response_verbosity": "concise", "politeness_formality": "inherit",
    }}
    before = deepcopy(state)
    writes = []
    journal = Journal()
    store = PromptOverrideStore(
        registry, read_settings=lambda: state, write_settings=lambda value: writes.append(value), diagnostics=journal,
    )

    with pytest.raises(AgentBehaviorError) as overflow:
        store.edit(descriptor.prompt_id, text="x" * 8192, base_revision=descriptor.default_revision)

    assert overflow.value.code == "agent_settings_behavior_prompt_too_large"
    assert state == before
    assert writes == []
    assert journal.events[-1]["kind"] == "prompt.override.rejected"
    assert journal.events[-1]["data"]["code"] == overflow.value.code
