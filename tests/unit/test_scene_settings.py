"""Interrupteur `scene.enabled` (handoff jarvis-constellation-scene-runtime, Slice 06).

Éteint par défaut ; persisté dans `control-center-settings.json` ;
`JARVIS_SCENE_ENABLED` l'emporte ; allumé, l'agent Claude reçoit la cible du
serveur MCP d'affichage (effective à son prochain démarrage), éteint il ne
reçoit rien.
"""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web
import pytest

from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.scene_settings import SceneSettingsError, apply_gate, load_gate


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv("JARVIS_SCENE_ENABLED", raising=False)


def target(tmp_path: Path) -> DisplayMcpTarget:
    return DisplayMcpTarget("127.0.0.1", 17999, tmp_path / "core.token", tmp_path)


def test_the_gate_is_off_by_default_and_reads_tolerantly():
    assert load_gate({}) == {"enabled": False, "source": "settings"}
    for stored in ({"scene": "yes"}, {"scene": {"enabled": "true"}}, {"scene": {"enabled": 1}}, {"scene": None}):
        assert load_gate(stored)["enabled"] is False
    assert load_gate({"scene": {"enabled": True}}) == {"enabled": True, "source": "settings"}


@pytest.mark.parametrize(("raw", "expected"), [("1", True), ("on", True), ("FALSE", False), ("0", False), ("peut-être", None)])
def test_the_environment_overrides_the_file(raw, expected):
    gate = load_gate({"scene": {"enabled": True}}, {"JARVIS_SCENE_ENABLED": raw})
    if expected is None:
        assert gate == {"enabled": True, "source": "settings"}
    else:
        assert gate == {"enabled": expected, "source": "env"}


def test_applying_is_strict_and_keeps_other_settings():
    settings = {"other": 1}
    assert apply_gate(settings, {"enabled": True}) == {"enabled": True}
    assert settings == {"other": 1, "scene": {"enabled": True}}
    assert apply_gate(settings, {}) == {"enabled": True}
    for payload, code in (([], "scene_bad_payload"), ({"enabled": "yes"}, "scene_bad_value"), ({"renderer": True}, "scene_unknown_field")):
        with pytest.raises(SceneSettingsError) as refused:
            apply_gate(settings, payload)
        assert refused.value.code == code
    assert settings["scene"] == {"enabled": True}


def test_applying_is_refused_while_the_environment_imposes_the_gate():
    settings = {"scene": {"enabled": False}}
    with pytest.raises(SceneSettingsError) as refused:
        apply_gate(settings, {"enabled": True}, {"JARVIS_SCENE_ENABLED": "1"})
    assert refused.value.code == "scene_env_override" and "JARVIS_SCENE_ENABLED impose la scène activée" in str(refused.value)
    assert settings == {"scene": {"enabled": False}}
    # Une valeur d'environnement non reconnue n'impose rien : l'écriture passe.
    assert apply_gate(settings, {"enabled": True}, {"JARVIS_SCENE_ENABLED": "peut-être"}) == {"enabled": True}


async def test_settings_endpoints_describe_persist_and_refuse_the_gate(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path))
    described = json.loads((await control.get_settings(None)).text)
    # Slice 11 : le bloc des réglages dit aussi la valeur enregistrée et la variable qui l'emporte.
    assert described["scene"] == {"enabled": False, "source": "settings", "stored": False, "env": None}
    assert control.agent.display_mcp is None

    saved = json.loads((await control.save_settings(JsonRequest({"scene": {"enabled": True}}))).text)
    assert saved["scene"] == {"enabled": True, "source": "settings", "stored": True, "env": None}
    assert json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))["scene"] == {"enabled": True}
    assert control.agent.display_mcp == target(tmp_path)

    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({"scene": {"enabled": "oui"}}))
    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "scene_bad_value"
    assert json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))["scene"] == {"enabled": True}

    await control.save_settings(JsonRequest({"scene": {"enabled": False}}))
    assert control.agent.display_mcp is None


async def test_a_persisted_gate_is_applied_at_construction_and_the_env_can_turn_it_off(tmp_path, monkeypatch):
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": True}}), encoding="utf-8")
    assert ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path)).agent.display_mcp == target(tmp_path)
    monkeypatch.setenv("JARVIS_SCENE_ENABLED", "0")
    assert ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path)).agent.display_mcp is None


async def test_an_enabled_gate_without_core_coordinates_is_said_once(tmp_path):
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": True}}), encoding="utf-8")
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    await control.save_settings(JsonRequest({"scene": {"enabled": True}}))
    assert control.agent.display_mcp is None
    warnings = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if e["kind"] == "scene.display_mcp_unconfigured"]
    assert len(warnings) == 1 and warnings[0]["level"] == "warning"
