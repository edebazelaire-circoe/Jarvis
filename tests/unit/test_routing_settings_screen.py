"""L'écran d'aiguillage : décrit par le serveur, enregistré par le serveur.

Ce que ces tests défendent : la page ne connaît aucun modèle, un enregistrement
refusé ne touche à rien, et régler l'aiguillage ne déplace pas un seul réglage
vocal ou CLI au passage.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time

import pytest
from aiohttp import web

from jarvis.domain import routing
from jarvis.runtime import agent_routing, cli_catalog
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter

PAGE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"


class QueryRequest:
    def __init__(self, **query: str) -> None:
        self.query = query


class PostRequest:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def settings_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_settings(None)).text)


async def save(control: ControlCenter, payload: dict) -> dict:
    return json.loads((await control.save_settings(PostRequest(payload))).text)


# ------------------------------------------------------------------ serveur


async def test_the_routing_screen_is_described_by_the_server(control):
    payload = (await settings_of(control))["routing"]

    assert payload["enabled"] is False
    assert [entry["id"] for entry in payload["profiles"]] == list(routing.TASK_PROFILE_IDS)
    assert all(entry["label"] and entry["description"] for entry in payload["profiles"])
    assert set(payload["policy"]) == set(routing.TASK_PROFILE_IDS)
    # Les candidats ne sont pas dans ce GET : les lister demande de sonder les
    # CLI et d'appeler les fournisseurs.
    assert payload["candidates"] == []


async def test_a_routing_policy_is_saved_and_read_back_without_touching_the_rest(control):
    before = await settings_of(control)

    after = await save(
        control,
        {"routing": {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "m1"}]}}}},
    )

    assert after["routing"]["enabled"] is True
    assert after["routing"]["policy"]["code"]["candidates"] == [{"agent": "claude", "model": "m1"}]
    # Rien d'autre n'a bougé : ni la voix, ni l'audio. Le CLI expose la
    # projection canonique du même switch routing, sans second stockage.
    for section in ("voice", "audio"):
        assert after[section] == before[section]
    assert after["cli"] == {**before["cli"], "delegation_mode": "auto"}
    # Et c'est bien écrit sur le disque, pas seulement en mémoire.
    stored = json.loads((control.runtime_root / "control-center-settings.json").read_text(encoding="utf-8"))
    assert agent_routing.load_policy(stored).enabled is True


async def test_a_refused_policy_leaves_the_previous_one_intact(control):
    await save(control, {"routing": {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude"}]}}}})

    with pytest.raises(web.HTTPBadRequest) as error:
        await save(control, {"routing": {"profiles": {"code": {"candidates": [{"agent": "astra"}]}}}})

    assert error.value.headers[SETTINGS_ERROR_CODE_HEADER] == "routing_unknown_agent"
    payload = await settings_of(control)
    assert payload["routing"]["policy"]["code"]["candidates"] == [{"agent": "claude", "model": ""}]
    assert payload["routing"]["enabled"] is True


async def test_the_candidates_endpoint_measures_instead_of_assuming(control, monkeypatch):
    async def fake_detect(commands):
        assert set(commands) == set(cli_catalog.AGENT_CLI_IDS)
        return [
            {"id": "claude", "label": "Claude Code", "model_provider": "anthropic", "available": True, "error": "", "path": "/bin/claude"},
            {"id": "codex", "label": "Codex CLI", "model_provider": "openai", "available": False, "error": "introuvable", "path": ""},
        ]

    async def fake_models(provider, api_key, **kwargs):
        if provider != "anthropic":
            raise __import__("jarvis.runtime.model_catalog", fromlist=["x"]).CatalogError("catalog_no_key", "pas de clé")
        return {
            "provider": provider,
            "models": [{"id": "m1", "label": "M1", "roles": ("text",)}],
            "source": "live",
            "fetched_at": time.time(),
        }

    monkeypatch.setattr(cli_catalog, "detect_all", fake_detect)
    monkeypatch.setattr(control.catalog, "models", fake_models)
    monkeypatch.setattr(control.catalog, "cached", lambda provider: None)

    payload = json.loads((await control.routing_candidates(None)).text)

    keys = [(item["agent"], item["model"]) for item in payload["candidates"]]
    assert ("claude", "m1") in keys
    claude = next(item for item in payload["candidates"] if item == payload["candidates"][0])
    assert claude["available"] is True
    # Le CLI absent est décrit, pas caché : l'utilisateur doit savoir pourquoi.
    codex = [item for item in payload["candidates"] if item["agent"] == "codex"]
    assert codex and all(not item["available"] and item["unavailable_reason"] for item in codex)
    assert payload["sources"]["openai"] == "catalog_no_key"
    # Les capacités viennent de la fiche du CLI, pas du modèle.
    assert routing.CODE in claude["capabilities"]


async def test_a_saved_candidate_that_vanished_is_still_shown(control, monkeypatch):
    await save(control, {"routing": {"profiles": {"code": {"candidates": [{"agent": "claude", "model": "disparu"}]}}}})

    async def fake_detect(commands):
        return [{"id": "claude", "label": "Claude", "model_provider": "anthropic", "available": True, "error": ""}]

    async def fake_models(provider, api_key, **kwargs):
        return {
            "provider": provider,
            "models": [{"id": "m1", "label": "M1", "roles": ("text",)}],
            "source": "live",
            "fetched_at": time.time(),
        }

    monkeypatch.setattr(cli_catalog, "detect_all", fake_detect)
    monkeypatch.setattr(control.catalog, "models", fake_models)

    payload = json.loads((await control.routing_candidates(None)).text)

    ghost = next(item for item in payload["candidates"] if item["model"] == "disparu")
    assert ghost["available"] is False and ghost["unavailable_reason"]


async def test_no_secret_ever_reaches_the_routing_payload(control, monkeypatch):
    async def fake_detect(commands):
        return [{"id": "claude", "label": "Claude", "model_provider": "anthropic", "available": True, "error": ""}]

    async def fake_models(provider, api_key, **kwargs):
        return {
            "provider": provider,
            "models": [{"id": "m1", "roles": ("text",)}],
            "source": "live",
            "fetched_at": time.time(),
            "key_hint": "…9ab",
        }

    monkeypatch.setattr(cli_catalog, "detect_all", fake_detect)
    monkeypatch.setattr(control.catalog, "models", fake_models)

    body = (await control.routing_candidates(None)).text

    assert "key_hint" not in body and "9ab" not in body


# ------------------------------------------------------------------- page


def test_the_advanced_agent_section_never_writes_a_model_or_profile_of_its_own():
    """Un nom de modèle codé dans le HTML périmerait sans que personne le voie."""

    page = PAGE.read_text(encoding="utf-8")
    start = page.index("function routingAdvancedBody()")
    body = page[start : page.index("/* --- onglet Config", start)]

    for invented in ("opus", "sonnet", "haiku", "gpt-", "astra", "luna", "claude-"):
        assert invented not in body.lower(), invented
    # Les profils viennent du serveur : la page itère, elle ne les nomme pas.
    assert "state.profiles" in body
    assert "profile.label" in body and "profile.description" in body


def test_the_page_shows_why_a_candidate_cannot_be_used():
    page = PAGE.read_text(encoding="utf-8")
    body = page[page.index("function routingRow(") : page.index("function routingAdvancedBody()")]

    assert "unavailable_reason" in body
    assert "indisponible" in body
    # Un candidat indisponible reste coché s'il était enregistré.
    assert "checked" in body and "rank>=0" in body


def test_policy_ui_is_advanced_inside_agent_cli_and_saved_canonically():
    page = PAGE.read_text(encoding="utf-8")

    assert re.search(r"\{id:'cli',label:'Agent / CLI',save:true\}", page)
    assert "id:'routing'" not in page
    assert "Configuration avancée des sous-agents" in page
    # Awaited panels publish only after the render revision guard; an older
    # catalog response cannot overwrite a newly selected voice architecture.
    assert "else if(SET.tab==='cli')content=tabCli()" in page
    assert "if(revision!==SET.renderRevision||SET.open===false)return" in page
    # Le brouillon envoie le mode via cli, jamais le switch historique en double.
    assert "delegation_mode:data.cli.delegation_mode" in page
    assert "routing:{profiles:JSON.parse(JSON.stringify(data.routing.policy))}" in page
    assert "routing:{enabled:data.routing.enabled" not in page
