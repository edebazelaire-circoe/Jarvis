"""Profils de la page Personnalisation : module pur et route `/api/personalization/profiles`."""

from __future__ import annotations

from copy import deepcopy
import json

from aiohttp import web
import pytest

from jarvis.runtime import agent_behavior, personalization_profiles as profiles
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER
from tests.unit.test_settings_endpoints import JsonRequest, control  # noqa: F401


def test_reading_without_a_block_gives_one_implicit_profile_and_writes_nothing():
    settings = {"agent_behavior": {"response_verbosity": "concise", "politeness_formality": "inherit"}}
    before = deepcopy(settings)
    state = profiles.describe(settings)
    assert settings == before
    assert state["stored"] is False and state["active"] == profiles.DEFAULT_ID
    [only] = state["profiles"]
    assert only["name"] == profiles.DEFAULT_NAME and only["active"] is True
    assert only["values"]["behavior"]["response_verbosity"] == "concise"
    assert only["values"]["voices"]["openai_realtime"] == "cedar"


def test_switching_profiles_saves_the_one_left_and_restores_the_one_chosen():
    settings: dict = {}
    agent_behavior.apply(settings, {"response_verbosity": "detailed", "custom_instructions": "Avec des exemples."})
    new_id = profiles.create(settings, "  Efficace  ")
    assert new_id == "efficace" and profiles.describe(settings)["active"] == "efficace"
    agent_behavior.apply(settings, {"response_verbosity": "concise", "politeness_formality": "direct",
                                    "custom_instructions": ""})
    settings["voice_stack_settings"] = {"openai_realtime": {"voice": "alloy"}}

    assert profiles.select(settings, "classic") is True  # la voix change : redémarrage de Voice
    assert settings["agent_behavior"] == {"response_verbosity": "detailed", "politeness_formality": "inherit",
                                          "custom_instructions": "Avec des exemples."}
    assert settings["voice_stack_settings"]["openai_realtime"]["voice"] == "cedar"

    assert profiles.select(settings, "efficace") is True
    assert settings["agent_behavior"] == {"response_verbosity": "concise", "politeness_formality": "direct"}
    assert settings["voice_stack_settings"]["openai_realtime"]["voice"] == "alloy"
    assert profiles.select(settings, "efficace") is False


@pytest.mark.parametrize(("call", "code"), [
    (lambda s: profiles.create(s, ""), "personalization_profile_invalid_name"),
    (lambda s: profiles.create(s, "x" * (profiles.MAX_NAME_CHARS + 1)), "personalization_profile_invalid_name"),
    (lambda s: profiles.create(s, "jarvis classique"), "personalization_profile_duplicate"),
    (lambda s: profiles.create(s, "Autre", "pink"), "personalization_profile_invalid_accent"),
    (lambda s: profiles.select(s, "nope"), "personalization_profile_unknown"),
    (lambda s: profiles.delete(s, "classic"), "personalization_profile_active"),
    (lambda s: profiles.delete(s, "nope"), "personalization_profile_unknown"),
])
def test_refusals_carry_a_stable_code_and_change_nothing(call, code):
    settings = {"kept": True}
    with pytest.raises(profiles.ProfileError) as refused:
        call(settings)
    assert refused.value.code == code
    assert settings == {"kept": True}


def test_a_damaged_block_reads_tolerantly():
    settings = {profiles.SETTING_KEY: {"schema_version": 1, "active": "ghost", "profiles": [
        "junk", {"id": "BAD ID", "name": "x"}, {"id": "ok", "name": " Ok ", "accent": "neon",
                                                  "values": {"voices": {"openai_realtime": "not-a-voice"}}},
    ]}}
    state = profiles.describe(settings)
    assert [p["id"] for p in state["profiles"]] == ["ok"] and state["active"] == "ok"
    assert state["profiles"][0]["name"] == "Ok" and state["profiles"][0]["accent"] == "blue"
    assert state["profiles"][0]["values"]["voices"]["openai_realtime"] == "cedar"
    assert profiles.describe({profiles.SETTING_KEY: {"schema_version": 99}})["stored"] is False


def test_the_profile_limit_is_enforced():
    settings: dict = {}
    for n in range(profiles.MAX_PROFILES - 1):
        profiles.create(settings, f"Profil {n}")
    with pytest.raises(profiles.ProfileError) as refused:
        profiles.create(settings, "Un de trop")
    assert refused.value.code == "personalization_profile_limit"


async def test_route_creates_selects_and_refuses_with_its_code(control, tmp_path):  # noqa: F811
    response = await control.get_personalization_profiles(JsonRequest(None))
    assert json.loads(response.text)["stored"] is False
    assert not control.settings_path.exists()

    created = json.loads((await control.save_personalization_profiles(JsonRequest(
        {"action": "create", "name": "Décontracté"}))).text)
    assert created["profiles"]["active"] == "decontracte" and created["voice_restart"] is False
    assert created["settings"]["cli"]["behavior"]["values"]["response_verbosity"] == "inherit"
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert [p["id"] for p in stored["personalization_profiles"]["profiles"]] == ["classic", "decontracte"]

    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_personalization_profiles(JsonRequest({"action": "delete", "id": "decontracte"}))
    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "personalization_profile_active"
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_personalization_profiles(JsonRequest({"action": "rename"}))
    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "personalization_profile_invalid_action"

    selected = json.loads((await control.save_personalization_profiles(JsonRequest(
        {"action": "select", "id": "classic"}))).text)
    assert selected["profiles"]["active"] == "classic"
