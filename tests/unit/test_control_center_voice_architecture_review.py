"""Independent Task14 server/config review; no provider or running frontend."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import AsyncMock

from aiohttp import web
import pytest

from jarvis.runtime.control_center import ControlCenter, SETTINGS_ERROR_CODE_HEADER
from jarvis.domain.voice_architecture import (
    ModelAvailability, VoiceAdapterStatus, VoiceArchitectureId, VoiceModelRef,
)
from jarvis.runtime.voice_capabilities import VoiceCapabilityRegistry, default_voice_registry
from jarvis.runtime.voice_architecture_config import load_voice_architecture
from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL, DEFAULT_REALTIME_MODEL
from tests.unit.test_settings_endpoints import JsonRequest, settings_of


def ref(model=DEFAULT_REALTIME_MODEL, provider="openai"):
    return {"provider_id": provider, "model_id": model}


def simple():
    return {"architecture": "simple", "conversation_model": ref()}


def duplex():
    return {"architecture": "duplex", "conversation_model": ref("gpt-live-1"),
            "client_delegation": True, "idle_timeout_s": 60.0}


def front_brain():
    return {"architecture": "front_brain", "reflex_model": ref(),
            "analysis_model": ref("gpt-5.6-luna"), "speculative_deltas": True,
            "reasoning_effort": "low"}


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                 "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK",
                 "OPENAI_REALTIME_MODEL", "JARVIS_AGENT_CLI"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


def seed(control, *, old_mode="legacy"):
    values = {
        "voice_arch": old_mode, "voice_stack": "openai_realtime",
        "voice_stack_settings": {
            "openai_realtime": {"model": DEFAULT_REALTIME_MODEL, "voice": "cedar", "turn_mode": "auto"},
            "gemini_live": {"model": "previous-exact-model", "voice": "Kore"},
        },
        "prompt_profiles": {"inactive": {"prompt": "keep this exact inactive prompt"}},
        "unrelated_extension": {"nested": [1, {"enabled": False}]},
    }
    control._write_settings(values)
    return values


def stored(control):
    return json.loads(control.settings_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("old_mode", ["legacy", "continuous_brain"])
async def test_unchanged_projection_save_preserves_compatibility_execution(control, old_mode):
    seed(control, old_mode=old_mode)
    before = load_voice_architecture(control._settings())
    description = (await settings_of(control))["voice"]["architecture"]
    assert description["compatibility_runtime"] is True
    assert description["selection"]["compatibility"]["execution_mode"] == old_mode
    # The unchanged UI omits architecture; a separate unrelated setting saves.
    await control.save_settings(JsonRequest({"active_timeout_s": "120"}))
    after = load_voice_architecture(stored(control))
    assert after == before
    assert "voice_architecture" not in stored(control)


async def test_ordinary_save_keeps_environment_selection_dynamic(control, monkeypatch):
    control._write_settings({"voice_stack": "openai_realtime"})
    monkeypatch.setenv("JARVIS_VOICE_ARCH", "legacy")
    monkeypatch.setenv("OPENAI_REALTIME_MODEL", DEFAULT_REALTIME_MODEL)
    await control.save_settings(JsonRequest({"active_timeout_s": "120"}))
    assert "voice_architecture" not in stored(control)
    monkeypatch.setenv("JARVIS_VOICE_ARCH", "continuous_brain")
    monkeypatch.setenv("OPENAI_REALTIME_MODEL", DEFAULT_CONTINUOUS_SURFACE_MODEL)
    selection = load_voice_architecture(control._settings())
    assert selection.compatibility.execution_mode == "continuous_brain"
    assert selection.compatibility.architecture_source == "env"
    assert selection.compatibility.model_source == "env"
    assert selection.to_dict()["config"]["conversation_model"] == ref(DEFAULT_CONTINUOUS_SURFACE_MODEL)


@pytest.mark.parametrize("config", [simple(), front_brain(), duplex()])
async def test_explicit_selection_roundtrip_preserves_inactive_and_unrelated_settings(control, monkeypatch, config):
    original = seed(control, old_mode="continuous_brain")
    switch = AsyncMock()
    monkeypatch.setattr(control, "_switch_agent", switch)
    response = await control.save_settings(JsonRequest({"voice": {"architecture": config}}))
    assert response.status == 200
    data = stored(control)
    selected = load_voice_architecture(data)
    assert selected.compatibility is None
    assert selected.to_dict()["config"] == config
    for key in ("voice_arch", "voice_stack_settings", "prompt_profiles", "unrelated_extension"):
        assert data[key] == original[key]
    switch.assert_not_awaited()
    projected = json.loads(response.text)["voice"]["architecture"]
    assert projected["selection"] == selected.to_dict()
    assert projected["new_runtime_ready"] is True


INVALID_CONFIGS = [
    None, [], "simple", True,
    {**simple(), "unknown": 1},
    {**simple(), "architecture": "future"},
    {**simple(), "conversation_model": {**ref(), "extra": "forged"}},
    {**simple(), "conversation_model": ref("unknown-exact-model")},
    {**simple(), "conversation_model": ref("gpt-live-1")},
    {**duplex(), "conversation_model": ref()},
    {**front_brain(), "analysis_model": ref()},
    {**front_brain(), "speculative_deltas": 1},
    {**front_brain(), "reasoning_effort": "unsupported"},
    {**duplex(), "client_delegation": 1},
    {**duplex(), "client_delegation": False},
    *[{**duplex(), "idle_timeout_s": raw} for raw in (True, "60", 0, 4.99, 3601, float("nan"), float("inf"), 10**400)],
    {"schema_version": True, "config": simple(), "compatibility": None},
]


@pytest.mark.parametrize("config", INVALID_CONFIGS)
async def test_invalid_explicit_selection_rejects_atomically(control, config):
    seed(control)
    before = control.settings_path.read_bytes()
    with pytest.raises(web.HTTPBadRequest) as rejected:
        await control.save_settings(JsonRequest({
            "voice": {"architecture": deepcopy(config), "settings": {"openai_realtime": {"voice": "ash"}}},
            "active_timeout_s": "180",
        }))
    assert rejected.value.headers[SETTINGS_ERROR_CODE_HEADER] in {
        "voice_schema_invalid", "voice_schema_unknown_field", "voice_architecture_unknown",
        "voice_model_unsupported", "voice_model_incompatible", "voice_model_invalid",
        "voice_speculation_invalid", "voice_reasoning_unsupported",
        "voice_client_delegation_required", "voice_idle_timeout_invalid",
    }
    assert control.settings_path.read_bytes() == before


async def test_unrelated_invalid_field_rolls_back_otherwise_valid_architecture(control):
    seed(control)
    before = control.settings_path.read_bytes()
    with pytest.raises(web.HTTPBadRequest):
        await control.save_settings(JsonRequest({"voice": {"architecture": duplex()}, "active_timeout_s": "1"}))
    assert control.settings_path.read_bytes() == before


async def test_failed_atomic_replace_preserves_previous_selection(control, monkeypatch):
    seed(control)
    before = control.settings_path.read_bytes()

    def fail_replace(*_args, **_kwargs):
        raise PermissionError("controlled file lock")

    monkeypatch.setattr("jarvis.runtime.control_center.replace_with_retry", fail_replace)
    with pytest.raises(web.HTTPServiceUnavailable):
        await control.save_settings(JsonRequest({"voice": {"architecture": duplex()}}))
    assert control.settings_path.read_bytes() == before
    assert not control.settings_path.with_suffix(".json.tmp").exists()


async def test_unknown_legacy_model_is_visible_without_becoming_valid_explicit_selection(control):
    values = seed(control)
    values["voice_stack_settings"]["openai_realtime"]["model"] = "previous-private-model"
    control._write_settings(values)
    description = (await settings_of(control))["voice"]["architecture"]
    assert description["selection"]["config"]["conversation_model"] == ref("previous-private-model")
    assert description["problem"] is not None
    assert not description["new_runtime_ready"]
    with pytest.raises(web.HTTPBadRequest):
        await control.save_settings(JsonRequest({"voice": {"architecture": description["selection"]["config"]}}))
    assert stored(control) == values


@pytest.mark.parametrize("raw", [
    {"schema_version": True, "config": simple()},
    {"schema_version": 999, "config": simple()},
    {"schema_version": 1, "config": {**simple(), "conversation_model": ref("removed-model")}},
])
async def test_corrupt_or_removed_saved_selection_remains_inspectable(control, raw):
    values = seed(control)
    values["voice_architecture"] = raw
    control._write_settings(values)
    before = control.settings_path.read_bytes()
    description = (await settings_of(control))["voice"]["architecture"]
    assert description["problem"] is not None
    assert description["new_runtime_ready"] is False
    assert control.settings_path.read_bytes() == before


def registry_with_extra(*, status=VoiceAdapterStatus.READY, availability=ModelAvailability.UNKNOWN):
    original = default_voice_registry()
    descriptors = {}
    for architecture in VoiceArchitectureId:
        roles = ("conversation", "analysis") if architecture is VoiceArchitectureId.FRONT_BRAIN else ("conversation",)
        for role in roles:
            for item in original.query(architecture, role=role):
                descriptors[item.ref] = item
    extra = replace(original.require(VoiceModelRef("openai", DEFAULT_REALTIME_MODEL)),
                    ref=VoiceModelRef("future-provider", "exact-future-model"),
                    adapter_status=status, availability=availability)
    return VoiceCapabilityRegistry([*descriptors.values(), extra]), extra


@pytest.mark.parametrize("status,availability,selectable", [
    (VoiceAdapterStatus.READY, ModelAvailability.UNKNOWN, True),
    (VoiceAdapterStatus.READY, ModelAvailability.AVAILABLE, True),
    (VoiceAdapterStatus.READY, ModelAvailability.UNAVAILABLE, False),
    (VoiceAdapterStatus.PLANNED, ModelAvailability.UNKNOWN, False),
    (VoiceAdapterStatus.LEGACY_ONLY, ModelAvailability.AVAILABLE, False),
])
async def test_registry_projection_and_explicit_validation_share_readiness_contract(
    control, monkeypatch, status, availability, selectable,
):
    registry, extra = registry_with_extra(status=status, availability=availability)
    monkeypatch.setattr(control, "_voice_architecture_registry", lambda _settings: registry)
    description = (await settings_of(control))["voice"]["architecture"]
    for entry in description["architectures"]:
        expected = {(item.ref.provider_id, item.ref.model_id) for item in registry.query(entry["id"])}
        assert {(item["provider_id"], item["model_id"]) for item in entry["conversation_models"]} == expected
        assert len(entry["conversation_models"]) == len(expected)
    simple_entry = next(item for item in description["architectures"] if item["id"] == "simple")
    model_field = next(item for item in simple_entry["fields"] if item["key"] == "conversation_model")
    assert {(item["provider_id"], item["model_id"]) for item in model_field["options"]} == {
        (item.ref.provider_id, item.ref.model_id) for item in registry.query("simple")
    }
    option = next(item for item in model_field["options"] if item["model_id"] == extra.ref.model_id)
    conversation_option = next(item for item in simple_entry["conversation_models"] if item["model_id"] == extra.ref.model_id)
    assert conversation_option == option, "Legacy and UI model lists share one enriched projection"
    assert option["selectable"] is selectable
    assert option["adapter_status"] == status.value
    assert option["availability"] == availability.value
    candidate = {"architecture": "simple", "conversation_model": ref(extra.ref.model_id, extra.ref.provider_id)}
    if selectable:
        await control.save_settings(JsonRequest({"voice": {"architecture": candidate}}))
        assert stored(control)["voice_architecture"]["config"] == candidate
    else:
        assert option["reason"]
        with pytest.raises(web.HTTPBadRequest) as rejected:
            await control.save_settings(JsonRequest({"voice": {"architecture": candidate}}))
        expected_code = "voice_adapter_not_ready" if status is not VoiceAdapterStatus.READY else "voice_model_unavailable"
        assert rejected.value.headers[SETTINGS_ERROR_CODE_HEADER] == expected_code
        assert not control.settings_path.exists()


@pytest.mark.parametrize("models", [None, [None], [{"id": "", "methods": ["bidiGenerateContent"]}]])
async def test_corrupt_optional_catalog_cannot_break_all_settings(control, monkeypatch, models):
    seed(control)
    before = control.settings_path.read_bytes()
    secret = "review-cache-private-value"
    monkeypatch.setattr(control.catalog, "cached", lambda _provider: {"models": models, "private": secret})
    payload = await settings_of(control)
    architecture = payload["voice"]["architecture"]
    assert {item["id"] for item in architecture["architectures"]} == {"simple", "front_brain", "duplex"}
    assert secret not in json.dumps(payload)
    if control.journal.trace_path.exists():
        trace = control.journal.trace_path.read_text(encoding="utf-8")
        assert secret not in trace
        records = [json.loads(line) for line in trace.splitlines()]
        assert any(item["kind"] == "voice.settings.catalog_rejected"
                   and item["data"].get("code") == "voice_catalog_invalid" for item in records)
    assert control.settings_path.read_bytes() == before


async def test_explicit_registry_is_not_replaced_by_optional_catalog_fallback(control, monkeypatch):
    registry, extra = registry_with_extra()
    control._voice_registry = registry

    def must_not_read_cache(_provider):
        pytest.fail("An explicit injected registry owns its own discovery")

    monkeypatch.setattr(control.catalog, "cached", must_not_read_cache)
    description = (await settings_of(control))["voice"]["architecture"]
    simple_entry = next(item for item in description["architectures"] if item["id"] == "simple")
    assert any(item["model_id"] == extra.ref.model_id for item in simple_entry["conversation_models"])


@pytest.mark.parametrize("entry", ["review-cache-private-entry", ["review-cache-private-entry"]])
async def test_corrupt_catalog_envelope_from_disk_keeps_settings_available(control, entry):
    # ModelCatalog loads arbitrary JSON mappings from disk. Exercise its real
    # cached() boundary, not a replacement that already assumes a valid entry.
    control.catalog.cache_path.write_text(json.dumps({"google": entry}), encoding="utf-8")
    control.catalog._cache = control.catalog._load()
    payload = await settings_of(control)
    assert len(payload["voice"]["architecture"]["architectures"]) == 3
    assert "review-cache-private-entry" not in json.dumps(payload)


@pytest.mark.parametrize("config", [simple(), front_brain()])
async def test_explicit_manual_mode_is_rejected_until_same_save_prepares_auto(control, config):
    original = seed(control)
    original["voice_stack_settings"]["openai_realtime"]["turn_mode"] = "manual"
    control._write_settings(original)
    before = control.settings_path.read_bytes()
    with pytest.raises(web.HTTPBadRequest) as rejected:
        await control.save_settings(JsonRequest({"voice": {"architecture": config}}))
    assert rejected.value.headers[SETTINGS_ERROR_CODE_HEADER] == "voice_auto_turn_required"
    assert control.settings_path.read_bytes() == before
    response = await control.save_settings(JsonRequest({"voice": {
        "architecture": config,
        "settings": {"openai_realtime": {"turn_mode": "auto"}},
    }}))
    assert response.status == 200
    assert json.loads(response.text)["voice"]["architecture"]["new_runtime_ready"] is True
    assert stored(control)["voice_stack_settings"]["openai_realtime"]["turn_mode"] == "auto"
    assert stored(control)["voice_stack_settings"]["gemini_live"] == original["voice_stack_settings"]["gemini_live"]
