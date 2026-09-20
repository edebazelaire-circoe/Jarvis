"""Task14 acceptance probes for the architecture-first Voice settings UI.

The server owns labels, fields and capability-derived model choices.  These
tests deliberately avoid browser styling details: they pin the data contract
and the few source invariants that keep the generic renderer honest.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from jarvis.domain.voice_architecture import ModelAvailability, VoiceArchitectureId
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.voice_capabilities import VoiceCapabilityRegistry, default_voice_registry


PAGE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


def _registry_with_unavailable_duplex() -> VoiceCapabilityRegistry:
    source = default_voice_registry()
    descriptors = {}
    for architecture in VoiceArchitectureId:
        for role in ("conversation", "analysis"):
            if role == "analysis" and architecture is not VoiceArchitectureId.FRONT_BRAIN:
                continue
            for descriptor in source.query(architecture, role=role):
                descriptors[descriptor.ref] = descriptor
    live = next(item for item in descriptors.values() if item.ref.model_id == "gpt-live-1")
    descriptors[live.ref] = replace(live, availability=ModelAvailability.UNAVAILABLE)
    return VoiceCapabilityRegistry(descriptors.values())


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK", "OPENAI_REALTIME_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def _payload(control: ControlCenter) -> dict:
    return json.loads((await control.get_settings(None)).text)


async def test_server_describes_three_understandable_architectures_and_exact_panels(control):
    architecture = (await _payload(control))["voice"]["architecture"]
    profiles = {item["id"]: item for item in architecture["architectures"]}

    assert list(profiles) == ["simple", "front_brain", "duplex"]
    assert [profiles[key]["label"] for key in profiles] == ["Simple", "Front Brain", "Duplex"]
    assert all(profile["description"].strip() for profile in profiles.values())

    fields = {
        key: {field["key"]: field for field in profile["fields"]}
        for key, profile in profiles.items()
    }
    assert set(fields["simple"]) == {"conversation_model"}
    assert set(fields["front_brain"]) == {
        "reflex_model", "analysis_model", "speculative_deltas", "reasoning_effort",
    }
    assert set(fields["duplex"]) == {"conversation_model", "client_delegation", "idle_timeout_s", "brain_orchestration"}
    assert fields["duplex"]["brain_orchestration"]["default"] is True

    delegation = fields["duplex"]["client_delegation"]
    assert delegation["default"] is True
    assert delegation["readonly"] is True
    assert "délégation" in delegation["label"].casefold()
    idle = fields["duplex"]["idle_timeout_s"]
    assert (idle["min"], idle["max"]) == (5, 3600)
    assert 5 <= idle["default"] <= 3600


async def test_model_options_are_exactly_registry_driven_and_never_hardcoded_in_page(control):
    architecture = (await _payload(control))["voice"]["architecture"]
    profiles = {item["id"]: item for item in architecture["architectures"]}
    registry = default_voice_registry()

    def refs(options):
        return {(item["provider_id"], item["model_id"]) for item in options}

    for mode in VoiceArchitectureId:
        profile = profiles[mode.value]
        expected = {(item.ref.provider_id, item.ref.model_id) for item in registry.query(mode)}
        model_fields = [field for field in profile["fields"] if field["kind"] == "model"]
        conversation = next(field for field in model_fields if field["key"] != "analysis_model")
        assert refs(conversation["options"]) == expected
        if mode is VoiceArchitectureId.FRONT_BRAIN:
            analysis = next(field for field in model_fields if field["key"] == "analysis_model")
            expected_analysis = {
                (item.ref.provider_id, item.ref.model_id)
                for item in registry.query(mode, role="analysis")
            }
            assert refs(analysis["options"]) == expected_analysis

    html = PAGE.read_text(encoding="utf-8")
    for descriptor in {
        item
        for mode in VoiceArchitectureId
        for role in (("conversation", "analysis") if mode is VoiceArchitectureId.FRONT_BRAIN else ("conversation",))
        for item in registry.query(mode, role=role)
    }:
        assert descriptor.ref.model_id not in html


async def test_unavailable_registry_choice_carries_a_visible_reason(tmp_path):
    control = ControlCenter(
        runtime_root=tmp_path,
        project_root=tmp_path,
        voice_registry=_registry_with_unavailable_duplex(),
    )
    architecture = (await _payload(control))["voice"]["architecture"]
    duplex = next(item for item in architecture["architectures"] if item["id"] == "duplex")
    model = next(
        option
        for field in duplex["fields"] if field["key"] == "conversation_model"
        for option in field["options"] if option["model_id"] == "gpt-live-1"
    )

    assert model["availability"] == "unavailable"
    assert model["selectable"] is False
    assert model["reason"].strip()

    html = PAGE.read_text(encoding="utf-8")
    assert re.search(r"\bselectable\b", html)
    assert re.search(r"\breason\b", html)


async def test_unchanged_legacy_projection_is_not_migrated_by_an_ordinary_save(control, tmp_path):
    before = (await _payload(control))["voice"]["architecture"]
    assert before["compatibility_runtime"] is True
    assert before["selection"]["compatibility"] is not None

    # This is the payload emitted when another Settings field is saved without
    # an explicit architecture interaction.
    await control.save_settings(JsonRequest({"audio": {"input_device": "3"}}))

    stored = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert "voice_architecture" not in stored
    after = (await _payload(control))["voice"]["architecture"]
    assert after["compatibility_runtime"] is True
    assert after["selection"]["compatibility"] == before["selection"]["compatibility"]


def test_page_is_a_generic_architecture_renderer_with_an_explicit_change_latch():
    html = PAGE.read_text(encoding="utf-8")

    assert "voice.architecture" in html
    assert re.search(r"\.architectures\b", html)
    assert re.search(r"\.fields\b", html)
    assert "data-voice-architecture" in html
    # Merely keeping a dirty flag is insufficient: the POST payload must add
    # the discriminated config only under that explicit-interaction guard.
    assert re.search(
        r"if\s*\([^)]*arch(?:itecture)?(?:Changed|Dirty)[^)]*\)"
        r"[^;]{0,500}voice\.architecture",
        html,
        re.I | re.S,
    )

    # Architecture IDs are data from the endpoint. Branching on them in the
    # browser would duplicate the registry and make future models/modes require
    # JavaScript edits.
    for architecture_id in ("simple", "front_brain", "duplex"):
        assert not re.search(rf"['\"]{architecture_id}['\"]", html)


def test_page_announces_deferred_architecture_apply_and_uses_task16_live_control():
    html = PAGE.read_text(encoding="utf-8")

    assert re.search(r"prochaine activation", html, re.I)
    assert "/api/live/stop" in html
    assert 'id="liveStop"' in html
    assert "session.close" not in html
