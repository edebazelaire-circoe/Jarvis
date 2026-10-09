"""Slice 10b : la section `memory` de `/api/settings`, son enregistrement et le relais `/api/memory/*`.

Contrat : `jarvis/runtime/memory_relay.py`, `docs/settings/memory.md`. Ce qui doit tenir : la forme du payload,
un étage désactivé ou dégradé dit sa raison, `downgraded` est visible, `memory.tencent.service_id` et
`allow_private` (faux par défaut) font l'aller-retour, aucun secret dans aucune réponse, un changement valide
s'applique au tour suivant sans redémarrage, une combinaison invalide est un 400 au code stable sans écriture,
et les réglages existants ne bougent pas.
"""

from __future__ import annotations

import json

from aiohttp import web
import pytest

from jarvis.core.memory_context import CachedMemorySettings
from jarvis.protocol.client import FORWARDABLE_PREFIXES
from jarvis.protocol.memory_routes import MemoryProtocolRoutes
from jarvis.runtime.control_center import READ_GUARDED_ROUTES, SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.memory_relay import GUARDED_PREFIXES, MemoryRelayRoutes
from jarvis.runtime.memory_settings import read_memory_settings_file

SECRET = "sk-memory-secret-8675309"
TOKEN = "tencent-token-5551212"


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "JARVIS_TENCENT_TOKEN", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    for name in list(__import__("os").environ):
        if name.startswith("JARVIS_MEMORY_"):
            monkeypatch.delenv(name)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def memory_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_settings(None)).text)["memory"]


async def save(control: ControlCenter, memory: object) -> None:
    await control.save_settings(JsonRequest({"memory": memory}))


# ------------------------------------------------------------------- payload


async def test_the_payload_carries_schema_values_effective_and_status(control):
    memory = await memory_of(control)

    assert {"schema", "values", "effective", "downgraded", "secrets", "loadouts", "status"} <= set(memory)
    assert memory["schema"]["key"] == "memory"
    paths = {field["path"] for section in memory["schema"]["sections"] for field in section["fields"]}
    assert {"tencent.service_id", "tencent.allow_private"} <= paths
    assert memory["values"]["tencent.service_id"] == ""
    assert memory["values"]["tencent.allow_private"] is False
    assert memory["effective"]["tencent.allow_private"] == {"value": False, "source": "default"}
    assert memory["downgraded"] == {}
    assert memory["status"]["downgraded"] == {}
    assert memory["status"]["live"] == "/api/memory/status"


async def test_a_disabled_or_unkeyed_leg_says_why(control):
    legs = (await memory_of(control))["status"]["legs"]
    assert legs["semantic"]["status"] == "disabled" and legs["semantic"]["reason_code"] == "semantic_disabled"
    assert legs["tencent"]["status"] == "disabled" and legs["tencent"]["reason_code"] == "tencent_disabled"
    assert legs["lexical"]["status"] == "ok"

    await save(control, {"semantic": {"enabled": True, "provider": "openai"}})
    legs = (await memory_of(control))["status"]["legs"]
    assert legs["semantic"]["status"] == "unavailable" and legs["semantic"]["reason_code"] == "semantic_no_key"
    assert legs["semantic"]["how_to_fix"]


async def test_a_hand_edited_incoherent_file_is_downgraded_and_shown(control, tmp_path):
    (tmp_path / "control-center-settings.json").write_text(
        json.dumps({"memory": {"tencent": {"enabled": True, "url": ""}, "semantic": {"enabled": True}}}),
        encoding="utf-8")

    memory = await memory_of(control)

    assert memory["downgraded"] == {
        "semantic.enabled": "memory_settings_semantic_needs_provider",
        "tencent.enabled": "memory_settings_tencent_needs_url",
    }
    assert memory["status"]["downgraded"] == memory["downgraded"]
    assert memory["status"]["legs"]["tencent"]["reason_code"] == "memory_settings_tencent_needs_url"
    assert memory["effective"]["tencent.enabled"]["downgraded"] == "memory_settings_tencent_needs_url"


# ------------------------------------------------------------------ round trip


async def test_service_id_and_allow_private_round_trip(control, tmp_path):
    await save(control, {"tencent": {"enabled": True, "url": "http://127.0.0.1:8421",
                                     "service_id": "jarvis-main", "allow_private": True}})

    memory = await memory_of(control)
    assert memory["values"]["tencent.service_id"] == "jarvis-main"
    assert memory["values"]["tencent.allow_private"] is True
    assert memory["effective"]["tencent.service_id"]["source"] == "file"
    assert memory["status"]["legs"]["tencent"]["status"] == "ok"
    stored = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert stored["memory"]["tencent"]["service_id"] == "jarvis-main"


async def test_a_change_reaches_the_next_turn_without_restart(control, tmp_path):
    path = tmp_path / "control-center-settings.json"
    await save(control, {"recall": {"max_items": 3}})
    cached = CachedMemorySettings(path, read_memory_settings_file)
    assert cached.current().recall.max_items == 3

    await save(control, {"recall": {"max_items": 7}, "knowledge": {"wiki_enabled": False}})

    after = CachedMemorySettings(path, read_memory_settings_file).current()
    assert after.recall.max_items == 7 and after.knowledge.wiki_enabled is False


async def test_existing_settings_are_untouched_by_a_memory_save(control):
    before = json.loads((await control.get_settings(None)).text)
    await save(control, {"recall": {"enabled": False}})
    after = json.loads((await control.get_settings(None)).text)

    assert {key: after[key] for key in before if key != "memory"} == {key: before[key] for key in before if key != "memory"}
    assert after["memory"]["values"]["recall.enabled"] is False


# --------------------------------------------------------------------- refusals


@pytest.mark.parametrize("memory, code", [
    ({"semantic": {"enabled": True}}, "memory_settings_semantic_needs_provider"),
    ({"consolidation": {"mode": "auto"}}, "memory_settings_auto_needs_semantic"),
    ({"tencent": {"enabled": True}}, "memory_settings_tencent_needs_url"),
    ({"tencent": {"service_id": "bad id!"}}, "memory_settings_bad_identifier"),
    ({"tencent": {"allow_private": "yes"}}, "memory_settings_bad_type"),
    ({"recall": {"max_items": 99}}, "memory_settings_out_of_range"),
    ({"tencent": {"api_key": "x"}}, "memory_settings_secret_refused"),
])
async def test_an_invalid_write_is_a_400_with_a_stable_code_and_writes_nothing(control, tmp_path, memory, code):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await save(control, memory)

    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == code
    assert not (tmp_path / "control-center-settings.json").exists()


# ---------------------------------------------------------------------- secrets


async def test_no_secret_reaches_any_response(control, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TENCENT_TOKEN", TOKEN)
    await control.save_credential(JsonRequest({"provider": "openai", "name": "Perso", "value": SECRET}))

    response = await control.get_settings(None)
    memory = json.loads(response.text)["memory"]

    assert memory["secrets"] == {"semantic": {"has_secret": True}, "tencent": {"has_secret": True}}
    assert memory["status"]["legs"]["semantic"]["reason_code"] == "semantic_disabled"
    for text in (response.text, json.dumps(memory)):
        assert SECRET not in text and TOKEN not in text


# ------------------------------------------------------------------------ relay


def test_the_relay_is_guarded_forwardable_and_matches_core_routes():
    assert GUARDED_PREFIXES == ("/api/memory",)
    assert set(GUARDED_PREFIXES) <= set(READ_GUARDED_ROUTES)
    assert any("/v1/memory/status".startswith(prefix) for prefix in FORWARDABLE_PREFIXES)
    core = {(route.method, route.path) for route in MemoryProtocolRoutes(object()).routes()}
    relay = MemoryRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = {(route.method, "/v1" + route.path[len("/api"):]) for route in relay.routes()}
    # la décision (POST) n'est pas relayée ici : Slice 12
    assert mapped == {r for r in core if r[0] == 'GET'}
    assert {method for method, _ in mapped} == {"GET"}


def test_the_control_center_serves_the_two_hooks(control):
    paths = {route.resource.canonical for route in control._app.router.routes() if route.resource is not None}
    assert "/api/memory/status" in paths and "/api/memory/notes/{memory_id}" in paths


async def test_the_page_carries_both_hooks(control):
    html = (await control.index(None)).text
    assert "JarvisMemorySettings" in html and "JarvisMemoryCenter" in html
    assert 'id="memorySettingsMount"' in html and 'id="memoryCenterMount"' in html
    assert "__CONTROL_CENTER_MEMORY" not in html
