from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig,
    FrontBrainVoiceConfig,
    SimpleVoiceConfig,
    VoiceModelRef,
)
from jarvis.runtime import voice_settings_schema, voice_stack
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings
from jarvis.runtime.voice_capabilities import default_voice_registry
from jarvis.runtime.voice_composition import resolve_voice_composition
from jarvis.runtime.visual_signals import VisualSignalBus


CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "tasks"
    / "jarvis-settings-model-catalog-ux"
    / "docs"
    / "settings-ia-contract.json"
)


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK", "OPENAI_REALTIME_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


def _voice(control: ControlCenter, settings: dict | None = None) -> dict:
    return control._settings_payload(settings if settings is not None else control._settings())["voice"]


def _contract_voice() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["voice"]


def test_projection_matches_the_canonical_inventory_categories_and_rendering_contract(control):
    voice = _voice(control)
    contract = _contract_voice()
    records = voice["option_metadata"]
    persistable = records[: len(voice_settings_schema.PERSISTABLE_OPTION_IDS)]
    diagnostics = records[len(persistable):]

    assert voice["categories"] == contract["categories"]
    assert [record["id"] for record in persistable] == list(voice_settings_schema.PERSISTABLE_OPTION_IDS)
    assert {record["id"] for record in persistable} == {item["id"] for item in contract["settings"]}
    assert [record["id"] for record in diagnostics] == contract["diagnostic_projections"]
    assert len({record["id"] for record in records}) == len(records)

    expected = {item["id"]: item for item in contract["settings"]}
    required = {
        "id", "persistence", "source", "kind", "type", "label", "help", "options",
        "category", "destination", "advanced", "runtime_status", "readonly",
    }
    for record in records:
        assert required <= set(record)
        assert all(set(option) >= {"id", "label"} for option in record["options"])
        assert record["destination"] == f"voice.{record['category']}"
        assert record["category"] in {item["id"] for item in voice["categories"]}
        assert "settings_fields" not in json.dumps(record)
    for record in persistable:
        canonical = expected[record["id"]]
        assert record["persistence"] == canonical["persistence"]
        assert record["destination"] == canonical["destination"]
        assert record["advanced"] is canonical["advanced"]
        assert record["runtime_status"] == canonical["runtime_status"]
    assert all(item["persistence"] is None and item["readonly"] for item in diagnostics)


def test_every_live_stack_and_architecture_field_is_projected_once_including_ack_delay(control):
    metadata = _voice(control)["option_metadata"]
    persisted = [item["persistence"] for item in metadata if item["persistence"]]

    for stack in voice_stack.VOICE_STACKS:
        expected = {f"voice_stack_settings.{stack.id}.{field.key}" for field in stack.fields}
        actual = {value for value in persisted if value.startswith(f"voice_stack_settings.{stack.id}.")}
        assert actual == expected
    assert "voice_stack_settings.openai_realtime.ack_delay_ms" in persisted

    expected_architecture = {
        f"voice_architecture.config.{field['key']}"
        for profile in default_voice_registry().settings_architectures()
        for field in profile["fields"]
    } | {"voice_architecture.config.architecture"}
    actual_architecture = {value for value in persisted if value.startswith("voice_architecture.config.")}
    assert actual_architecture == expected_architecture
    assert len(actual_architecture) == sum(value in actual_architecture for value in persisted)


def test_metadata_has_valid_defaults_bounds_and_detached_model_options(control):
    first = _voice(control)
    records = {item["id"]: item for item in first["option_metadata"]}

    for record in records.values():
        if record["type"] == "enum" and record["default"] is not None:
            assert record["default"] in {option["id"] for option in record["options"]}
        if record["type"].startswith("number"):
            assert "minimum" in record and "maximum" in record
    assert records["architecture"]["default"] is None
    assert records["architecture"]["placeholder"]
    assert records["speaker_verification"]["default"] == ""
    assert records["speaker_verification"]["options"][0]["id"] == ""
    assert records["owner_threshold"]["exclusive_minimum"] == 0.0
    assert records["active_timeout_s"]["maximum"] is None
    assert all(
        {"adapter_status", "availability"} <= set(option)
        for option in records["conversation_model"]["options"]
    )

    first["categories"][0]["label"] = "mutated"
    first["option_metadata"][0]["options"][0]["label"] = "mutated"
    second = _voice(control)
    assert second["categories"][0]["label"] == "Architecture"
    assert second["option_metadata"][0]["options"][0]["label"] != "mutated"


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, "openai_realtime"),
        ({"voice_stack": "gemini_live"}, "gemini_live"),
        ({
            "voice_stack": "gemini_live",
            "voice_architecture": VoiceArchitectureSettings(
                SimpleVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1"))
            ).to_dict(),
        }, "openai_realtime"),
        ({
            "voice_stack": "gemini_live",
            "voice_architecture": VoiceArchitectureSettings(FrontBrainVoiceConfig(
                VoiceModelRef("openai", "gpt-realtime-2.1-mini"),
                VoiceModelRef("openai", "gpt-5.6-luna"),
            )).to_dict(),
        }, "openai_realtime"),
        ({
            "voice_stack": "gemini_live",
            "voice_architecture": VoiceArchitectureSettings(
                DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))
            ).to_dict(),
        }, "openai_realtime"),
    ],
)
def test_effective_stack_follows_runtime_composition_not_legacy_storage(control, settings, expected):
    before = deepcopy(settings)

    assert _voice(control, settings)["effective_stack"] == expected
    assert settings == before


def test_echo_cancellation_uses_the_explicit_architecture_derived_stack(control, monkeypatch):
    settings = {
        "voice_stack": "gemini_live",
        "voice_architecture": VoiceArchitectureSettings(
            DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))
        ).to_dict(),
        "voice_stack_settings": {"openai_realtime": {"echo_cancellation": True}},
    }
    monkeypatch.setattr("jarvis.runtime.control_center.echo_cancellation_installed", lambda: True)

    voice = _voice(control, settings)

    assert voice["stack"] == "gemini_live"
    assert voice["effective_stack"] == "openai_realtime"
    assert voice["echo_cancellation"]["applicable"] is True
    assert voice["echo_cancellation"]["status"] == "ready"


def test_explicit_architecture_accepts_only_its_correlated_legacy_arch_aec_report(
    control, tmp_path, monkeypatch,
):
    settings = {
        "voice_stack": "gemini_live",
        "voice_architecture": VoiceArchitectureSettings(
            DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))
        ).to_dict(),
        "voice_stack_settings": {"openai_realtime": {"echo_cancellation": True}},
    }
    composition = resolve_voice_composition(settings)
    signals = VisualSignalBus(tmp_path)
    signals.heartbeat()
    monkeypatch.setattr("jarvis.runtime.control_center.echo_cancellation_installed", lambda: True)

    report = {
        "configuration_id": composition.configuration_id,
        "architecture": "duplex",
        # PersistentVoiceRuntime conserve ce champ opérationnel historique.
        "arch": "legacy",
        "phase": "session_end",
        "speaker_verification": "off",
        "echo_cancellation": {"requested": True, "active": False, "code": "aec_failed"},
        "verifier": None,
    }
    signals.capture(report)

    aec = _voice(control, settings)["echo_cancellation"]

    assert (aec["status"], aec["code"], aec["status_source"], aec["restart_required"]) == (
        "degraded", "aec_failed", "voice", False,
    )
    assert (aec["runtime"]["arch"], aec["runtime"]["architecture"]) == ("legacy", "duplex")
    assert aec["runtime"]["configuration_id"] == composition.configuration_id

    signals.capture({**report, "configuration_id": "0" * 64})
    mismatched = _voice(control, settings)["echo_cancellation"]
    assert (mismatched["status"], mismatched["status_source"], mismatched["restart_required"]) == (
        "ready", "settings", True,
    )


async def test_settings_endpoint_projection_is_additive_and_never_persisted(control, tmp_path):
    response = await control.get_settings(None)
    original = json.loads(response.text)

    await control.save_settings(JsonRequest({
        "voice": {
            "stack": "gemini_live",
            "categories": [{"id": "invented"}],
            "option_metadata": [{"id": "invented"}],
            "effective_stack": "invented",
        }
    }))

    stored = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert stored["voice_stack"] == "gemini_live"
    assert not ({"categories", "option_metadata", "effective_stack"} & set(stored))
    projected = json.loads((await control.get_settings(None)).text)["voice"]
    assert projected["categories"] == original["voice"]["categories"]
    assert projected["effective_stack"] == "gemini_live"
    assert [item["id"] for item in projected["option_metadata"]] == [
        *voice_settings_schema.PERSISTABLE_OPTION_IDS,
        *voice_settings_schema.DIAGNOSTIC_OPTION_IDS,
    ]
