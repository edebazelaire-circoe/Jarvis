from copy import deepcopy
from dataclasses import replace
import json

import pytest

from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig, FrontBrainVoiceConfig, ModelAvailability, SimpleVoiceConfig,
    VoiceAdapterStatus, VoiceConfigError, VoiceModelCapabilities, VoiceModelDescriptor, VoiceModelRef,
)
from jarvis.runtime.model_catalog import _openai_roles, filter_by_role
from jarvis.runtime.voice_architecture_config import (
    VoiceArchitectureSettings, decode_voice_architecture, load_voice_architecture,
    store_voice_architecture, voice_architecture_query,
)
from jarvis.runtime.voice_capabilities import VoiceCapabilityRegistry, default_voice_registry


REALTIME = VoiceModelRef("openai", "gpt-realtime-2.1-mini")
LUNA = VoiceModelRef("openai", "gpt-5.6-luna")
LIVE = VoiceModelRef("openai", "gpt-live-1")


@pytest.mark.parametrize("config", [SimpleVoiceConfig(REALTIME), FrontBrainVoiceConfig(REALTIME, LUNA), DuplexVoiceConfig(LIVE)])
def test_versioned_config_json_roundtrip(config):
    original = VoiceArchitectureSettings(config)
    assert decode_voice_architecture(json.loads(json.dumps(original.to_dict()))) == original


@pytest.mark.parametrize("version", [True, False, "1", 1.0, 0, 2, None])
def test_schema_version_strict(version):
    payload = VoiceArchitectureSettings(SimpleVoiceConfig(REALTIME)).to_dict()
    payload["schema_version"] = version
    with pytest.raises(VoiceConfigError, match="schema_version"):
        decode_voice_architecture(payload)


@pytest.mark.parametrize("value", [True, False, "60", float("nan"), float("inf"), -1, 0, 4.99, 3601, None])
def test_live_timeout_never_inherits_unbounded_or_nonfinite(value):
    with pytest.raises(VoiceConfigError) as failure:
        DuplexVoiceConfig(LIVE, idle_timeout_s=value)
    assert failure.value.code == "voice_idle_timeout_invalid"


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_duplex_requires_boolean_client_delegation(value):
    with pytest.raises(VoiceConfigError):
        DuplexVoiceConfig(LIVE, client_delegation=value)


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_duplex_requires_boolean_brain_orchestration(value):
    with pytest.raises(VoiceConfigError) as failure:
        DuplexVoiceConfig(LIVE, brain_orchestration=value)
    assert failure.value.code == "voice_brain_orchestration_invalid"


def test_absent_brain_orchestration_decodes_to_the_orchestrated_default():
    payload = VoiceArchitectureSettings(DuplexVoiceConfig(LIVE)).to_dict()
    assert payload["config"]["brain_orchestration"] is True
    # Un réglage écrit avant ce champ reste lisible sans migration.
    del payload["config"]["brain_orchestration"]
    decoded = decode_voice_architecture(payload)
    assert decoded.config.brain_orchestration is True
    assert decoded.schema_version == 1
    legacy = VoiceArchitectureSettings(DuplexVoiceConfig(LIVE, brain_orchestration=False))
    assert decode_voice_architecture(json.loads(json.dumps(legacy.to_dict()))) == legacy


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_speculative_switch_requires_boolean(value):
    with pytest.raises(VoiceConfigError):
        FrontBrainVoiceConfig(REALTIME, LUNA, speculative_deltas=value)


@pytest.mark.parametrize("config", [SimpleVoiceConfig(LUNA), SimpleVoiceConfig(LIVE), DuplexVoiceConfig(REALTIME),
                                        FrontBrainVoiceConfig(REALTIME, REALTIME),
                                        FrontBrainVoiceConfig(REALTIME, LUNA, reasoning_effort="ultra")])
def test_incompatible_roles_and_reasoning_rejected(config):
    with pytest.raises(VoiceConfigError):
        default_voice_registry().validate(config)


def test_unknown_explicit_model_fails_actionably_but_legacy_is_preserved():
    settings = {"voice_arch": "continuous_brain", "voice_stack_settings": {"openai_realtime": {"model": "custom-old-model"}}}
    migrated = load_voice_architecture(settings, environ={})
    assert migrated.config.conversation_model.model_id == "custom-old-model"
    assert migrated.compatibility.execution_mode == "continuous_brain"
    assert decode_voice_architecture(migrated.to_dict()) == migrated
    assert voice_architecture_query(settings, environ={})["problem"]["code"] == "voice_model_unsupported"
    with pytest.raises(VoiceConfigError, match="Refresh the provider catalog"):
        store_voice_architecture(settings, migrated.config)


@pytest.mark.parametrize("old_mode,expected", [("legacy", "gpt-realtime-2.1"), ("continuous_brain", "gpt-realtime-2.1-mini")])
def test_migration_maps_simple_projection_without_reinterpreting_execution(old_mode, expected):
    settings = {"voice_arch": old_mode, "active_timeout_s": "0", "custom_prompt": "keep me"}
    original = deepcopy(settings)
    migrated = load_voice_architecture(settings, environ={})
    assert migrated.config.architecture.value == "simple"
    assert migrated.config.conversation_model.model_id == expected
    assert migrated.compatibility.execution_mode == old_mode
    assert migrated.uses_compatibility_runtime
    assert migrated.compatibility.architecture_source == "settings"
    assert settings == original
    assert DuplexVoiceConfig(LIVE).idle_timeout_s == 60.0


def test_saved_arch_and_model_precede_environment_and_preserve_sources():
    settings = {"voice_arch": "continuous_brain", "realtime_voice": "ash",
                "voice_stack_settings": {"openai_realtime": {"model": "gpt-realtime-2.1", "voice": "cedar"}}}
    migrated = load_voice_architecture(settings, environ={"JARVIS_VOICE_ARCH": "legacy", "OPENAI_REALTIME_MODEL": "other"})
    assert migrated.compatibility.execution_mode == "continuous_brain"
    assert migrated.compatibility.model_source == "settings"
    assert migrated.config.conversation_model.model_id == "gpt-realtime-2.1"
    assert migrated.compatibility.stack_settings["voice"] == "cedar"


def test_environment_and_current_safe_default_are_preserved():
    default = load_voice_architecture({}, environ={})
    assert default.compatibility.execution_mode == "legacy"
    assert default.compatibility.architecture_source == "default"
    loaded = load_voice_architecture({}, environ={"JARVIS_VOICE_ARCH": "continuous_brain", "OPENAI_REALTIME_MODEL": "explicit-env-model"})
    assert loaded.compatibility.architecture_source == "env"
    assert loaded.compatibility.model_source == "env"
    assert loaded.config.conversation_model.model_id == "explicit-env-model"


def test_empty_environment_model_is_preserved_as_invalid_not_silently_recommended():
    loaded = load_voice_architecture({}, environ={"OPENAI_REALTIME_MODEL": ""})
    assert loaded.config.conversation_model.model_id == ""
    assert loaded.compatibility.model_source == "env"
    assert voice_architecture_query({}, environ={"OPENAI_REALTIME_MODEL": ""})["problem"]["code"] == "voice_model_unsupported"


def test_missing_gemini_model_and_unsupported_legacy_combination_remain_explicit():
    settings = {"voice_stack": "gemini_live", "voice_arch": "continuous_brain"}
    loaded = load_voice_architecture(settings, environ={})
    assert loaded.config.conversation_model == VoiceModelRef("google", "")
    assert loaded.compatibility.execution_mode == "continuous_brain"
    assert loaded.compatibility.model_source == "missing"
    assert not voice_architecture_query(settings, environ={})["new_runtime_ready"]


def test_explicit_new_selection_preserves_inactive_settings_and_prompts():
    settings = {"voice_arch": "continuous_brain", "credentials": {"private": "secret"},
                "voice_stack_settings": {"gemini_live": {"model": "old", "voice": "Puck"}}, "prompts": {"custom": "words"}}
    original = deepcopy(settings)
    store_voice_architecture(settings, FrontBrainVoiceConfig(REALTIME, LUNA))
    assert {key: settings[key] for key in original} == original
    loaded = load_voice_architecture(settings, environ={"JARVIS_VOICE_ARCH": "bad"})
    assert loaded.config.analysis_model == LUNA
    assert not loaded.uses_compatibility_runtime
    assert "secret" not in json.dumps(voice_architecture_query(settings))


def test_query_distinguishes_documented_capability_from_ready_adapter():
    registry = default_voice_registry()
    assert {model.ref.model_id for model in registry.query("simple")} == {"gpt-realtime-2.1", "gpt-realtime-2.1-mini"}
    assert [model.ref for model in registry.query("front_brain", role="analysis")] == [LUNA]
    assert [model.ref for model in registry.query("duplex")] == [LIVE]
    assert [model.ref for model in registry.query("duplex", ready_only=True)] == [LIVE]
    assert {model.ref.model_id for model in registry.query("simple", ready_only=True)} == {"gpt-realtime-2.1", "gpt-realtime-2.1-mini"}
    assert [model.ref for model in registry.query("front_brain", role="analysis", ready_only=True)] == [LUNA]
    assert registry.require(LIVE).availability is ModelAvailability.UNKNOWN
    assert registry.require(REALTIME).adapter_status is VoiceAdapterStatus.READY
    assert registry.require(LUNA).adapter_status is VoiceAdapterStatus.READY
    assert registry.require(REALTIME).availability is registry.require(LUNA).availability is ModelAvailability.UNKNOWN
    registry.validate(FrontBrainVoiceConfig(REALTIME, LUNA), require_ready=True)
    assert not registry.require(REALTIME).capabilities.supports_quiet_context_injection
    assert not registry.require(REALTIME).capabilities.supports_usage_events
    assert registry.require(LIVE).adapter_status is VoiceAdapterStatus.READY
    registry.validate(DuplexVoiceConfig(LIVE), require_ready=True)


def test_gemini_discovery_requires_declared_method_not_name_or_realtime_role():
    registry = default_voice_registry(google_models=[
        {"id": "invented-live-name", "roles": ["realtime"]},
        {"id": "provider-returned-model", "methods": ["bidiGenerateContent"]},
        {"id": "provider-returned-model", "methods": ["bidiGenerateContent"]},
    ])
    assert registry.find(VoiceModelRef("google", "invented-live-name")) is None
    ref = VoiceModelRef("google", "provider-returned-model")
    assert registry.require(ref).availability is ModelAvailability.AVAILABLE
    registry.validate(SimpleVoiceConfig(ref))
    with pytest.raises(VoiceConfigError) as failure:
        registry.validate(FrontBrainVoiceConfig(ref, LUNA))
    assert failure.value.code == "voice_deltas_unsupported"
    registry.validate(FrontBrainVoiceConfig(ref, LUNA, speculative_deltas=False))


def test_registry_extension_needs_no_ui_change_and_unavailable_is_not_ready():
    source = default_voice_registry().require(LIVE)
    extended = replace(source, ref=VoiceModelRef("other-provider", "new-model"), adapter_status=VoiceAdapterStatus.READY,
                       availability=ModelAvailability.UNAVAILABLE)
    registry = VoiceCapabilityRegistry([extended])
    assert registry.query("duplex") == (extended,)
    assert registry.query("duplex", ready_only=True) == ()
    with pytest.raises(VoiceConfigError) as failure:
        registry.validate(DuplexVoiceConfig(extended.ref), require_ready=True)
    assert failure.value.code == "voice_model_unavailable"


def test_unknown_fields_and_tampered_compatibility_rejected():
    payload = load_voice_architecture({}, environ={}).to_dict()
    payload["compatibility"]["stack_settings"]["api_key"] = "secret"
    with pytest.raises(VoiceConfigError):
        decode_voice_architecture(payload)
    payload = VoiceArchitectureSettings(SimpleVoiceConfig(REALTIME)).to_dict()
    payload["config"]["idle_timeout_s"] = 10
    with pytest.raises(VoiceConfigError):
        decode_voice_architecture(payload)


def test_capabilities_reject_truthy_nonbools():
    with pytest.raises(VoiceConfigError):
        VoiceModelCapabilities(supports_audio_input=1)


def test_catalog_live_is_not_a_text_or_realtime_adapter_model():
    assert _openai_roles("gpt-live-1") == ("duplex",)
    assert _openai_roles("gpt-5.6-luna") == ("text",)
    models = [{"id": "gpt-live-1", "roles": ("duplex",)}, {"id": "gpt-realtime-2.1", "roles": ("realtime",)}]
    assert filter_by_role(models, "duplex") == models[:1]
    assert filter_by_role(models, "realtime") == models[1:]


def test_duplex_eligibility_is_not_a_billing_policy():
    source = default_voice_registry().require(LIVE)
    free_duplex = replace(source, ref=VoiceModelRef("example", "free-duplex"),
                          capabilities=replace(source.capabilities, billable_session_time=False))
    registry = VoiceCapabilityRegistry([free_duplex])
    registry.validate(DuplexVoiceConfig(free_duplex.ref))
    assert registry.query("duplex") == (free_duplex,)


def test_analysis_reasoning_effort_is_optional_provider_control():
    registry = default_voice_registry()
    ref = VoiceModelRef("example", "structured-text")
    registry.register(VoiceModelDescriptor(ref, VoiceModelCapabilities(supports_text_output=True, supports_structured_output=True), "test-only descriptor"))
    registry.validate(FrontBrainVoiceConfig(REALTIME, ref, reasoning_effort=None))
    assert registry.require(ref) in registry.query("front_brain", role="analysis")
    with pytest.raises(VoiceConfigError):
        registry.validate(FrontBrainVoiceConfig(REALTIME, ref, reasoning_effort="low"))


def test_initial_stack_environment_matches_control_center_default():
    loaded = load_voice_architecture({}, environ={"JARVIS_VOICE_STACK": "gemini_live"})
    assert loaded.compatibility.stack_id == "gemini_live"
    assert loaded.compatibility.stack_source == "env"
    saved = load_voice_architecture({"voice_stack": "openai_realtime"}, environ={"JARVIS_VOICE_STACK": "gemini_live"})
    assert saved.compatibility.stack_source == "settings"
    assert saved.config.conversation_model.provider_id == "openai"


@pytest.mark.parametrize("value", [{"secret": "private"}, ["private"], False, float("nan")])
def test_nested_or_wrong_type_legacy_field_never_leaks_into_query(value):
    settings = {"voice_stack_settings": {"openai_realtime": {"model": value}}}
    with pytest.raises(VoiceConfigError) as failure:
        voice_architecture_query(settings, environ={})
    assert failure.value.code == "voice_compatibility_setting_invalid"
    assert "private" not in str(failure.value)


def test_runtime_journal_contract_has_safe_normal_and_rejected_events(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    journal = RuntimeJournal(tmp_path)
    voice_architecture_query({"credentials": {"api_key": "private"}}, environ={}, diagnostics=journal)
    with pytest.raises(VoiceConfigError):
        voice_architecture_query({"voice_architecture": {"schema_version": True}}, diagnostics=journal)
    events = read_jsonl_tail(journal.trace_path)
    assert [event["kind"] for event in events] == ["voice.config.validated", "voice.config.rejected"]
    assert [event["level"] for event in events] == ["info", "warning"]
    assert events[0]["data"]["compatibility_runtime"] is True
    assert events[1]["data"]["code"] == "voice_schema_version_unsupported"
    assert not journal.error_path.exists()
    assert "private" not in json.dumps(events)
