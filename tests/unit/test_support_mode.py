"""Mode support des Réglages (V1.2 Slice 06, `docs/settings/support-mode.md`).

Un interrupteur de navigation : persisté, réversible, relu par le battement ; il ne donne aucune capacité au
cerveau (le manifeste `agent_capabilities` reste maître) et le serveur MCP des réglages ne le voit pas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from aiohttp import web

from jarvis.domain.agent_capabilities import PRESENTATION_CAPABILITIES, agent_capability_policy
from jarvis.runtime import support_mode as S
from jarvis.runtime.agent_settings import edition_capabilities
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.journal import read_jsonl_tail

ROOT = Path(__file__).resolve().parents[2]


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


@pytest.fixture
def control(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.environment.load_project_environment", lambda: None)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


@pytest.mark.parametrize(("stored", "expected"), [
    (None, {"enabled": False, "problem": None}),
    ({"schema_version": 1, "enabled": True}, {"enabled": True, "problem": None}),
    ({"enabled": False}, {"enabled": False, "problem": None}),
    ("on", {"enabled": False, "problem": "support_mode_block_malformed"}),
    ({"schema_version": 2, "enabled": True}, {"enabled": False, "problem": "support_mode_stored_version_unreadable"}),
    ({"schema_version": True, "enabled": True}, {"enabled": False, "problem": "support_mode_stored_version_unreadable"}),
    ({"schema_version": 1, "enabled": "yes"}, {"enabled": False, "problem": "support_mode_value_invalid"}),
])
def test_inspect_never_raises_and_an_unreadable_block_reads_off(stored, expected):
    settings = {} if stored is None else {S.SETTING_KEY: stored}
    assert S.inspect(settings) == expected


@pytest.mark.parametrize("payload", [None, {}, {"enabled": 1}, {"enabled": "true"}, {"enabled": True, "x": 1}, [True]])
def test_apply_is_strict_and_touches_nothing_on_refusal(payload):
    settings = {"keep": 1}
    with pytest.raises(S.SupportModeError) as refused:
        S.apply(settings, payload)
    assert refused.value.code == "support_mode_bad_payload" and settings == {"keep": 1}


def test_routes_are_registered(control):
    routes = {(r.method, r.resource.canonical) for r in control._app.router.routes()}
    assert ("GET", "/api/support-mode") in routes and ("POST", "/api/support-mode") in routes


async def test_switch_on_is_persisted_projected_journaled_and_reversible(control, tmp_path):
    assert json.loads((await control.get_support_mode(None)).text) == {"enabled": False, "problem": None}
    assert not control.settings_path.exists(), "lire n'écrit rien"
    control.settings_path.write_text(json.dumps({"keep": {"a": 1}}), encoding="utf-8")
    on = json.loads((await control.save_support_mode(JsonRequest({"enabled": True}))).text)
    assert on == {"enabled": True, "problem": None}
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["support_mode"] == {"schema_version": 1, "enabled": True} and stored["keep"] == {"a": 1}
    status = json.loads((await control.status(None)).text)
    assert status["support_mode"] == {"enabled": True, "problem": None}
    off = json.loads((await control.save_support_mode(JsonRequest({"enabled": False}))).text)
    assert off["enabled"] is False
    rows = [row["data"] for row in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if row["kind"] == "support_mode.saved"]
    assert rows == [{"before": False, "after": True}, {"before": True, "after": False}]


async def test_a_bad_payload_is_a_coded_400_and_writes_nothing(control):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_support_mode(JsonRequest({"enabled": "oui"}))
    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "support_mode_bad_payload"
    assert not control.settings_path.exists()


async def test_support_mode_is_not_in_the_settings_projection_the_console_mcp_reads(control):
    """`jarvis-console` décrit et écrit ce que projette `GET /api/settings` : le mode support n'y est pas."""

    control.settings_path.write_text(json.dumps({"support_mode": {"schema_version": 1, "enabled": True}}),
                                     encoding="utf-8")
    projection = json.loads((await control.get_settings(None)).text)

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert not [key for key in keys(projection) if "support_mode" in str(key).lower()]


def test_support_mode_widens_no_agent_capability(tmp_path, monkeypatch):
    """Le manifeste ne dépend que de l'édition du processus ; aucun lancement d'agent ne lit le bloc.

    Lecteurs cherchés par le mot entier `support_mode` (module ou clé) : `support_model_unavailable` (code de la Slice 07,
    modèle du rapport IA) n'est pas une lecture du mode support (faux positif constaté à la fusion de la Slice 07)."""

    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    (tmp_path / "control-center-settings.json").write_text(
        json.dumps({"support_mode": {"schema_version": 1, "enabled": True}}), encoding="utf-8")
    assert edition_capabilities() is PRESENTATION_CAPABILITIES
    assert agent_capability_policy("presentation").cli_args(["jarvis-workspace"]) == \
        PRESENTATION_CAPABILITIES.cli_args(["jarvis-workspace"])
    readers = sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in (ROOT / "jarvis").rglob("*.py")
                     if re.search(r"\bsupport_mode\b", path.read_text(encoding="utf-8")) and path.name != "support_mode.py")
    assert readers == ["jarvis/runtime/control_center.py"], readers
