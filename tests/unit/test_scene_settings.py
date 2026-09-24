"""Interrupteur `scene.enabled` (handoff jarvis-constellation-scene-runtime, Slice 06).

Allumé par défaut (décision humaine B1) ; persisté dans
`control-center-settings.json`, où un `false` enregistré l'emporte sur le
défaut ; `JARVIS_SCENE_ENABLED` l'emporte sur les deux ; allumé, l'agent Claude
reçoit la cible du serveur MCP d'affichage (effective à son prochain
démarrage), éteint il ne reçoit rien.
"""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web
import pytest

from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.scene_settings import DEFAULT_ENABLED, SceneSettingsError, apply_gate, describe_gate, load_gate


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


def test_the_gate_is_on_by_default_and_reads_tolerantly():
    # Installation neuve : ni réglage enregistré, ni variable d'environnement.
    assert DEFAULT_ENABLED is True
    assert load_gate({}) == {"enabled": True, "source": "settings"}
    # Illisible n'est pas « éteint » : on retombe sur le défaut plutôt que d'éteindre sur un fichier abîmé.
    for stored in ({"scene": "yes"}, {"scene": {"enabled": "true"}}, {"scene": {"enabled": 1}}, {"scene": None},
                   {"scene": {}}, {"scene": {"enabled": None}}, {"scene": {"enabled": 0}}, {"scene": []}):
        assert load_gate(stored)["enabled"] is True, stored
    assert load_gate({"scene": {"enabled": True}}) == {"enabled": True, "source": "settings"}


def test_a_stored_false_beats_the_default():
    assert load_gate({"scene": {"enabled": False}}) == {"enabled": False, "source": "settings"}
    assert describe_gate({"scene": {"enabled": False}}) == {"enabled": False, "source": "settings", "stored": False, "env": None}
    # Et le défaut ne le ressuscite pas quand on réécrit sans dire `enabled`.
    settings = {"scene": {"enabled": False}}
    assert apply_gate(settings, {}) == {"enabled": False} and settings["scene"] == {"enabled": False}


@pytest.mark.parametrize("stored", [None, True, False])
@pytest.mark.parametrize(("raw", "expected"), [("1", True), ("on", True), ("FALSE", False), ("0", False), ("peut-être", None)])
def test_the_environment_overrides_the_file_and_the_default(raw, expected, stored):
    settings = {} if stored is None else {"scene": {"enabled": stored}}
    gate = load_gate(settings, {"JARVIS_SCENE_ENABLED": raw})
    if expected is None:  # valeur non reconnue : ni le fichier ni le défaut ne bougent
        assert gate == {"enabled": True if stored is None else stored, "source": "settings"}
    else:
        assert gate == {"enabled": expected, "source": "env"}
        # L'écran continue de montrer ce que le fichier (ou le défaut) dirait sans la variable.
        described = describe_gate(settings, {"JARVIS_SCENE_ENABLED": raw})
        assert described == {"enabled": expected, "source": "env",
                             "stored": True if stored is None else stored, "env": "JARVIS_SCENE_ENABLED"}


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
    # Intégration finale : rien d'enregistré, donc le défaut — allumé.
    assert described["scene"] == {"enabled": True, "source": "settings", "stored": True, "env": None}
    assert control.agent.display_mcp == target(tmp_path)

    saved = json.loads((await control.save_settings(JsonRequest({"scene": {"enabled": False}}))).text)
    assert saved["scene"] == {"enabled": False, "source": "settings", "stored": False, "env": None}
    assert json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))["scene"] == {"enabled": False}
    assert control.agent.display_mcp is None

    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({"scene": {"enabled": "oui"}}))
    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "scene_bad_value"
    assert json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))["scene"] == {"enabled": False}

    await control.save_settings(JsonRequest({"scene": {"enabled": True}}))
    assert control.agent.display_mcp == target(tmp_path)


async def test_a_control_center_started_without_any_settings_file_renders_and_arms_the_brain(tmp_path):
    """Installation neuve : pas de fichier de réglages du tout, pas de variable."""

    assert not (tmp_path / "control-center-settings.json").exists()
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path))
    # Le rendu suit `/api/status`, les outils du cerveau suivent `agent.display_mcp`.
    assert json.loads((await control.status(None)).text)["scene"] == {"enabled": True, "source": "settings"}
    assert control.agent.display_mcp == target(tmp_path)
    # Rien n'a été écrit pour autant : le défaut n'est pas un réglage enregistré.
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_a_persisted_gate_is_applied_at_construction_and_the_env_can_turn_it_off(tmp_path, monkeypatch):
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": True}}), encoding="utf-8")
    assert ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path)).agent.display_mcp == target(tmp_path)
    # Un `false` enregistré l'emporte sur le nouveau défaut, sans variable d'environnement.
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": False}}), encoding="utf-8")
    assert ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path)).agent.display_mcp is None
    # Et la variable l'emporte sur ce `false` comme sur le défaut.
    monkeypatch.setenv("JARVIS_SCENE_ENABLED", "1")
    assert ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path)).agent.display_mcp == target(tmp_path)
    monkeypatch.setenv("JARVIS_SCENE_ENABLED", "0")
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": True}}), encoding="utf-8")
    assert ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path)).agent.display_mcp is None


@pytest.mark.parametrize(("stored", "env", "display", "prompt_grows"), [
    (None, None, True, True),      # installation neuve : le défaut allume tout
    (False, None, False, False),   # un `false` enregistré l'emporte sur le défaut
    (True, None, True, True),
    (None, "0", False, False),     # la variable l'emporte sur le défaut…
    (False, "1", True, True),      # … et sur le fichier
])
async def test_the_gate_decides_the_brain_launch_arguments_and_its_system_prompt(
    tmp_path, monkeypatch, stored, env, display, prompt_grows,
):
    """Conséquence du défaut : `--mcp-config` et la consigne d'affichage au prochain démarrage.

    Éteint, la consigne système reste celle de main, octet pour octet.
    """

    from jarvis.runtime import claude_local
    from jarvis.runtime.claude_local import BRAIN_ARTIFACT_PROMPT, BRAIN_DISPLAY_PROMPT, BRAIN_SYSTEM_PROMPT
    from tests.unit.test_display_mcp import _launch, _prompt

    if stored is not None:
        (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": stored}}), encoding="utf-8")
    if env is not None:
        monkeypatch.setenv("JARVIS_SCENE_ENABLED", env)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=target(tmp_path))
    assert (control.agent.display_mcp is not None) is display

    agent = claude_local.ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, display_mcp=control.agent.display_mcp)
    argv = await _launch(monkeypatch, agent)
    system = _prompt(argv, "--append-system-prompt")
    assert ("--mcp-config" in argv) is display
    if prompt_grows:
        assert BRAIN_DISPLAY_PROMPT in system and BRAIN_ARTIFACT_PROMPT in system
    else:
        # Octet pour octet, comme sans la scène. Réalignement baseline (main) : la
        # conversation porte toujours la consigne des réglages (`jarvis-console`).
        assert system == BRAIN_SYSTEM_PROMPT + "\n" + claude_local.BRAIN_SETTINGS_PROMPT


async def test_an_enabled_gate_without_core_coordinates_is_said_once(tmp_path):
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": True}}), encoding="utf-8")
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    await control.save_settings(JsonRequest({"scene": {"enabled": True}}))
    assert control.agent.display_mcp is None
    warnings = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if e["kind"] == "scene.display_mcp_unconfigured"]
    assert len(warnings) == 1 and warnings[0]["level"] == "warning"
