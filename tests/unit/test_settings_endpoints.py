"""Les points d'entrée HTTP que consomme la fenêtre de réglages.

La page ne code aucun champ en dur : elle affiche ce que ces réponses décrivent.
Ce qui compte donc ici, c'est que la description soit fidèle (les piles vocales
et leurs champs, les CLI et leurs modes), que l'enregistrement soit rangé au
bon endroit, et qu'une valeur secrète ne remonte jamais vers le navigateur.
"""

from __future__ import annotations

import json

from aiohttp import web
import pytest

from jarvis.domain.v2 import BRAIN_NOT_ADDRESSED_ANSWER
from jarvis.runtime import cli_catalog
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.model_catalog import CatalogError


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


class QueryRequest:
    def __init__(self, **query: str) -> None:
        self.query = query


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "PORCUPINE_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def settings_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_settings(None)).text)


# ===========================================================================
# Description
# ===========================================================================


async def test_the_screen_is_described_by_the_server_not_by_the_page(control):
    payload = await settings_of(control)

    stacks = {stack["id"]: stack for stack in payload["voice"]["stacks"]}
    assert set(stacks) == {"openai_realtime", "gemini_live"}
    assert stacks["gemini_live"]["credential_provider"] == "google"
    assert stacks["gemini_live"]["input_sample_rate"] == 16000

    fields = {field["key"]: field for field in stacks["openai_realtime"]["fields"]}
    assert fields["model"]["source"] == "openai:realtime"
    assert fields["vad_silence_duration_ms"]["depends_on"] == "turn_mode"

    agents = {agent["id"]: agent for agent in payload["cli"]["agents"]}
    assert set(agents) == {"claude", "codex"}
    assert "bypassPermissions" in agents["claude"]["permission_modes"]
    assert "danger-full-access" in agents["codex"]["permission_modes"]

    assert [item["id"] for item in payload["shortcuts"]["shortcuts"]][0] == "wake_toggle"
    assert any(provider["id"] == "porcupine" for provider in payload["credentials"]["providers"])


async def test_the_defaults_are_the_current_behaviour_not_a_reset(control):
    payload = await settings_of(control)

    assert payload["voice"]["stack"] == "openai_realtime"
    assert payload["cli"]["agent"] == "claude"
    values = payload["voice"]["settings"]["openai_realtime"]
    assert values["voice"] == "cedar"
    assert values["turn_mode"] == "auto"
    assert values["vad_silence_duration_ms"] == 1500


# ===========================================================================
# Enregistrement
# ===========================================================================


async def test_voice_settings_are_stored_per_stack(control, tmp_path):
    await control.save_settings(JsonRequest({
        "voice": {
            "stack": "gemini_live",
            "settings": {
                "gemini_live": {"voice": "Kore", "model": "gemini-live-2.5-flash", "vad_silence_duration_ms": 1200},
                "openai_realtime": {"voice": "ash"},
            },
        }
    }))

    stored = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert stored["voice_stack"] == "gemini_live"
    assert stored["voice_stack_settings"]["gemini_live"]["voice"] == "Kore"
    assert stored["voice_stack_settings"]["openai_realtime"]["voice"] == "ash"
    # Le champ plat historique reste le reflet de la pile OpenAI : le processus
    # Voice d'une version antérieure le lit encore.
    assert stored["realtime_voice"] == "ash"


async def test_a_setting_outside_its_range_is_refused_and_nothing_is_written(control, tmp_path):
    with pytest.raises(web.HTTPBadRequest):
        await control.save_settings(JsonRequest({
            "voice": {"settings": {"openai_realtime": {"vad_threshold": 12}}}
        }))
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_the_turn_mode_of_the_active_stack_drives_the_key_hint(control):
    await control.save_settings(JsonRequest({
        "voice": {"stack": "gemini_live", "settings": {"gemini_live": {"turn_mode": "manual"}}}
    }))

    status = json.loads((await control.status(None)).text)
    assert status["voice_turn_mode"] == "manual"
    assert status["voice_stack"] == "gemini_live"


async def test_cli_settings_are_stored_per_agent_and_reach_the_running_one(control, tmp_path):
    await control.save_settings(JsonRequest({
        "cli": {
            "settings": {
                "claude": {"model": "claude-opus-5", "permission_mode": "acceptEdits"},
                "codex": {"model": "gpt-5-codex", "permission_mode": "read-only"},
            }
        }
    }))

    assert control.agent.model == "claude-opus-5"
    assert control.agent.permission_mode == "acceptEdits"
    stored = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert stored["agent_cli_settings"]["codex"]["permission_mode"] == "read-only"
    # Le modèle de Codex ne doit pas contaminer celui de Claude.
    payload = await settings_of(control)
    assert payload["cli"]["settings"]["codex"]["model"] == "gpt-5-codex"


async def test_a_sandbox_mode_is_refused_on_the_cli_that_does_not_know_it(control):
    with pytest.raises(web.HTTPBadRequest):
        await control.save_settings(JsonRequest({"cli": {"settings": {"claude": {"permission_mode": "read-only"}}}}))
    with pytest.raises(web.HTTPBadRequest):
        await control.save_settings(JsonRequest({"cli": {"settings": {"codex": {"permission_mode": "bypassPermissions"}}}}))


async def test_choosing_codex_actually_swaps_the_agent(control, monkeypatch):
    async def available(command):  # noqa: ANN001
        return {"available": True, "path": "C:/fake/codex.exe", "version": "codex-cli 1.0", "error": ""}

    monkeypatch.setattr(cli_catalog, "probe", available)
    claude = control.agent
    stopped: list[bool] = []

    async def record_stop():
        stopped.append(True)
        return claude.snapshot()

    monkeypatch.setattr(claude, "stop", record_stop)

    await control.save_settings(JsonRequest({"cli": {"agent": "codex"}}))

    assert control.agent is not claude
    assert control.agent.snapshot()["name"] == "Codex"
    # Deux agents vivants écriraient dans le même dépôt sans se voir.
    assert stopped == [True]
    status = json.loads((await control.status(None)).text)
    assert status["agent_cli"] == "codex"


async def test_the_audio_section_and_the_flat_fields_lead_to_the_same_place(control, tmp_path):
    await control.save_settings(JsonRequest({"audio": {"input_device": "3", "output_device": "7", "active_timeout_s": "120"}}))

    payload = await settings_of(control)
    assert payload["audio"] == {"input_device": "3", "output_device": "7", "active_timeout_s": "120"}
    assert payload["audio_input_device"] == "3"


# ===========================================================================
# Clés API
# ===========================================================================


async def test_a_key_added_through_the_api_is_selectable_and_never_echoed(control):
    response = await control.save_credential(JsonRequest({"provider": "google", "name": "Perso", "value": "AIza-secret-9876"}))
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["credential"]["hint"] == "…9876"
    assert "AIza-secret-9876" not in response.text
    assert payload["bindings"]["google"] == payload["credential"]["id"]

    settings = await settings_of(control)
    assert "AIza-secret-9876" not in json.dumps(settings)


async def test_a_nameless_key_is_refused_with_a_code(control):
    response = await control.save_credential(JsonRequest({"provider": "openai", "name": "", "value": "sk-x"}))
    assert response.status == 400
    assert json.loads(response.text)["code"] == "credential_name_required"


async def test_binding_another_key_changes_which_one_the_services_use(control):
    first = json.loads((await control.save_credential(JsonRequest({"provider": "openai", "name": "Perso", "value": "sk-a"}))).text)
    second = json.loads((await control.save_credential(JsonRequest({"provider": "openai", "name": "Travail", "value": "sk-b"}))).text)
    second_id = second["credential"]["id"]

    await control.bind_credential(JsonRequest({"provider": "openai", "id": second_id}))

    state = json.loads((await control.get_credentials(None)).text)
    assert state["bindings"]["openai"] == second_id
    assert {c["id"]: c["bound"] for c in state["credentials"]}[first["credential"]["id"]] is False


async def test_deleting_a_key_that_is_already_gone_says_so(control):
    response = await control.remove_credential(JsonRequest({"id": "cred_inexistant"}))
    assert response.status == 404
    assert json.loads(response.text)["code"] == "credential_not_found"


async def test_a_key_from_the_env_is_used_but_never_copied_to_disk(tmp_path, monkeypatch):
    """Le .env doit rester la source de sa propre clé.

    La recopier dans le fichier de réglages au premier enregistrement crée un
    second exemplaire du secret, qui ne bougera plus quand la clé sera changée
    dans le .env — et c'est celui-là qui gagnerait.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-du-dotenv")
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    assert (await settings_of(control))["openai_api_key_set"] is True

    await control.save_settings(JsonRequest({"voice": {"settings": {"openai_realtime": {"voice": "ash"}}}}))

    written = (tmp_path / "control-center-settings.json").read_text(encoding="utf-8")
    assert "sk-du-dotenv" not in written
    state = json.loads((await control.get_credentials(None)).text)
    assert state["credentials"] == []
    assert state["environment"]["openai"] == ["OPENAI_API_KEY"]


async def test_an_old_flat_key_appears_in_the_store_without_being_erased(control, tmp_path):
    (tmp_path / "control-center-settings.json").write_text(
        json.dumps({"openai_api_key": "sk-historique"}), encoding="utf-8"
    )

    state = json.loads((await control.get_credentials(None)).text)

    assert [c["provider"] for c in state["credentials"]] == ["openai"]
    stored = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert stored["openai_api_key"] == "sk-historique"


# ===========================================================================
# Catalogue de modèles
# ===========================================================================


class FakeCatalog:
    def __init__(self, result=None, error=None, stale=None) -> None:  # noqa: ANN001
        self.result, self.error, self.stale = result, error, stale
        self.invalidated: list[str] = []
        self.calls: list[tuple[str, str, bool]] = []

    async def models(self, provider, api_key, *, refresh=False):  # noqa: ANN001
        self.calls.append((provider, api_key, refresh))
        if self.error is not None:
            raise self.error
        return self.result

    def cached(self, provider):  # noqa: ANN001
        return self.stale

    def invalidate(self, provider=None):  # noqa: ANN001
        self.invalidated.append(provider)


async def test_the_models_endpoint_filters_by_usage(control):
    control.catalog = FakeCatalog(result={
        "models": [
            {"id": "gpt-realtime-2.1", "label": "gpt-realtime-2.1", "roles": ["realtime"]},
            {"id": "gpt-5-codex", "label": "gpt-5-codex", "roles": ["text"]},
        ],
        "source": "live",
        "fetched_at": 1.0,
    })
    await control.save_credential(JsonRequest({"provider": "openai", "name": "Perso", "value": "sk-a"}))

    payload = json.loads((await control.models(QueryRequest(provider="openai", role="realtime"))).text)

    assert [m["id"] for m in payload["models"]] == ["gpt-realtime-2.1"]
    assert control.catalog.calls[-1][1] == "sk-a", "la clé sélectionnée doit être celle utilisée"


async def test_a_missing_key_gives_an_actionable_code_rather_than_an_empty_list(control):
    control.catalog = FakeCatalog(error=CatalogError("catalog_no_key", "Ajoutez une clé."))

    response = await control.models(QueryRequest(provider="anthropic", role="text"))
    payload = json.loads(response.text)

    assert response.status == 424
    assert payload["code"] == "catalog_no_key"
    assert "models" not in payload


async def test_a_provider_outage_falls_back_on_the_last_known_list_and_says_so(control):
    control.catalog = FakeCatalog(
        error=CatalogError("catalog_unreachable", "Fournisseur injoignable."),
        stale={"models": [{"id": "gpt-realtime-2.1", "roles": ["realtime"]}], "fetched_at": 12.0},
    )

    response = await control.models(QueryRequest(provider="openai", role="realtime"))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ok"] is False
    assert payload["source"] == "stale"
    assert [m["id"] for m in payload["models"]] == ["gpt-realtime-2.1"]


async def test_changing_the_active_key_drops_the_cached_catalogue(control):
    control.catalog = FakeCatalog(result={"models": [], "source": "live"})
    created = json.loads((await control.save_credential(JsonRequest({"provider": "openai", "name": "Perso", "value": "sk-a"}))).text)

    await control.bind_credential(JsonRequest({"provider": "openai", "id": created["credential"]["id"]}))

    # Les modèles visibles dépendent du compte, pas seulement du fournisseur.
    assert control.catalog.invalidated == ["openai"]


# ===========================================================================
# CLI et raccourcis
# ===========================================================================


async def test_the_cli_list_reports_what_is_really_installed(control, monkeypatch):
    async def probe(command):  # noqa: ANN001
        return {"available": command == "claude", "path": "C:/fake/claude.exe" if command == "claude" else "",
                "version": "2.0.0" if command == "claude" else "", "error": "" if command == "claude" else "introuvable"}

    monkeypatch.setattr(cli_catalog, "probe", probe)

    payload = json.loads((await control.cli_agents(None)).text)
    agents = {agent["id"]: agent for agent in payload["agents"]}

    assert agents["claude"]["available"] is True
    assert agents["claude"]["version"] == "2.0.0"
    assert agents["codex"]["available"] is False
    assert agents["codex"]["error"] == "introuvable"
    assert payload["active"] == "claude"


async def test_the_cli_list_probes_the_command_the_user_configured(control, monkeypatch):
    probed: list[str] = []

    async def probe(command):  # noqa: ANN001
        probed.append(command)
        return {"available": True, "path": command, "version": "1.0", "error": ""}

    monkeypatch.setattr(cli_catalog, "probe", probe)
    await control.save_settings(JsonRequest({"cli": {"settings": {"claude": {"command": "C:/outils/claude.cmd"}}}}))

    await control.cli_agents(None)

    assert "C:/outils/claude.cmd" in probed


async def test_a_shortcut_is_saved_and_reflected_in_the_status_hint(control):
    response = await control.save_shortcuts(JsonRequest({"shortcuts": {"wake_toggle": "F8"}}))
    payload = json.loads(response.text)

    assert payload["values"]["wake_toggle"] == "f8"
    status = json.loads((await control.status(None)).text)
    assert status["manual_wake_key"] == "f8"


async def test_a_shortcut_the_wake_detector_cannot_capture_is_refused(control):
    response = await control.save_shortcuts(JsonRequest({"shortcuts": {"wake_toggle": "ctrl+j"}}))

    assert response.status == 400
    assert json.loads(response.text)["code"] == "shortcut_global_no_modifier"


async def test_a_conflicting_shortcut_names_the_action_that_holds_the_key(control):
    response = await control.save_shortcuts(JsonRequest({"shortcuts": {"ui_panel_trace": "e"}}))

    assert response.status == 400
    assert json.loads(response.text)["code"] == "shortcut_conflict"


# ===========================================================================
# Le contexte joint à un tour du cerveau (`POST /api/agent/ask`)
#
# La route est partagée : la passerelle legacy et le panneau navigateur
# appellent sans contexte, Core appelle avec. Ce qui est prouvé ici, c'est que
# les deux chemins restent distincts et que le second n'ajoute rien de plus que
# ce que Core a envoyé.
# ===========================================================================


def asked_by(control: ControlCenter) -> list[str]:
    """Brancher un agent qui note la question qu'on lui pose."""

    questions: list[str] = []

    async def fake_ask(text: str, *, timeout_s: float) -> dict:
        del timeout_s
        questions.append(text)
        return {"ok": True, "text": "fait"}

    control.agent.ask = fake_ask  # type: ignore[assignment]
    return questions


async def test_an_ask_without_context_reaches_the_agent_unchanged(control):
    """Le chemin du panneau navigateur et de la passerelle legacy, inchangé."""

    questions = asked_by(control)

    await control.agent_ask(JsonRequest({"text": "salut", "timeout_s": 30}))

    assert questions == ["salut"]


async def test_a_context_that_is_not_an_object_is_ignored_rather_than_rendered(control):
    questions = asked_by(control)

    await control.agent_ask(JsonRequest({"text": "salut", "context": "n'importe quoi"}))

    assert questions == ["salut"]


async def test_an_uncertain_turn_tells_the_agent_it_may_conclude_it_was_not_for_it(control):
    """Décision 44 : la marque ne sert à rien si rien n'en explique le sens au modèle."""

    questions = asked_by(control)

    await control.agent_ask(
        JsonRequest(
            {
                "text": "tu as vu le match hier soir",
                "context": {"addressing": "uncertain", "state": {"current_user_intent": "Faire les comptes."}},
            }
        )
    )

    brief = questions[0]
    assert "INCERTAIN" in brief
    assert BRAIN_NOT_ADDRESSED_ANSWER in brief
    assert "Intention courante : Faire les comptes." in brief
    # La demande reste lisible telle quelle, à la fin, jamais reformulée.
    assert brief.endswith("[Demande]\ntu as vu le match hier soir")


async def test_an_addressed_turn_gets_the_context_without_the_escape_hatch(control):
    questions = asked_by(control)

    await control.agent_ask(
        JsonRequest(
            {
                "text": "donne moi le total",
                "context": {
                    "addressing": "addressed",
                    "state": {
                        "current_user_intent": "Faire les comptes.",
                        "active_work_ids": ["brain-turn:corr-1"],
                        "known_public_facts": ["Le fichier est dans le Drive."],
                    },
                },
            }
        )
    )

    brief = questions[0]
    assert "Adressage : direct" in brief
    assert BRAIN_NOT_ADDRESSED_ANSWER not in brief
    assert "Travaux en cours : brain-turn:corr-1" in brief
    assert "Déjà dit à l'utilisateur : Le fichier est dans le Drive." in brief


async def test_only_the_known_public_fields_are_rendered_to_the_agent(control):
    """Liste blanche : un champ que Core n'a pas prévu n'atteint pas le modèle."""

    questions = asked_by(control)

    await control.agent_ask(
        JsonRequest(
            {
                "text": "vas-y",
                "context": {
                    "addressing": "addressed",
                    "state": {
                        "current_user_intent": "",
                        "conversation_id": "conv-1",
                        "revision": 7,
                        "updated_at": "2026-09-09T10:00:00+00:00",
                        "reasoning": "surtout ne pas dire ça",
                    },
                },
            }
        )
    )

    brief = questions[0]
    assert "surtout ne pas dire ça" not in brief
    assert "conv-1" not in brief
    assert "2026-09-09" not in brief
    # Un champ public vide ne produit pas de ligne vide.
    assert "Intention courante" not in brief
