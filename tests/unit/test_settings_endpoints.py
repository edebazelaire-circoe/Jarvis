"""Les points d'entrée HTTP que consomme la fenêtre de réglages.

La page ne code aucun champ en dur : elle affiche ce que ces réponses décrivent.
Ce qui compte donc ici, c'est que la description soit fidèle (les piles vocales
et leurs champs, les CLI et leurs modes), que l'enregistrement soit rangé au
bon endroit, et qu'une valeur secrète ne remonte jamais vers le navigateur.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time

from aiohttp import web
import pytest

from jarvis.domain.v2 import BRAIN_NOT_ADDRESSED_ANSWER
from jarvis.runtime import agent_routing, cli_catalog, routing_hook
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.model_catalog import CatalogError
from jarvis.runtime.voice_capabilities import default_voice_registry


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
    for name in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "PORCUPINE_ACCESS_KEY",
        "JARVIS_VOICE_ARCH",
    ):
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
    assert payload["cli"]["delegation_mode"] == "duplicate"
    assert payload["cli"]["behavior"]["values"] == {
        "response_verbosity": "inherit", "politeness_formality": "inherit",
    }


async def test_agent_settings_round_trip_without_duplicate_delegation_storage(control, tmp_path):
    await control.save_settings(JsonRequest({
        "routing": {"profiles": {"code": {
            "candidates": [{"agent": "claude", "model": "saved"}],
            "allow_general_fallback": False,
        }}},
    }))
    await control.save_settings(JsonRequest({"cli": {
        "delegation_mode": "auto",
        "behavior": {"response_verbosity": "balanced", "politeness_formality": "direct"},
    }}))

    payload = await settings_of(control)
    stored = stored_settings(tmp_path)
    assert payload["cli"]["delegation_mode"] == "auto"
    assert payload["cli"]["behavior"]["values"] == {
        "response_verbosity": "balanced", "politeness_formality": "direct",
    }
    assert stored["agent_routing"]["profiles"]["code"]["candidates"] == [
        {"agent": "claude", "model": "saved"},
    ]
    assert stored["agent_behavior"] == payload["cli"]["behavior"]["values"]
    assert "delegation_mode" not in stored
    updates = [item for item in read_jsonl_tail(tmp_path / "trace.jsonl") if item["kind"] == "settings.update"]
    assert updates[-1]["level"] == "info"
    assert updates[-1]["data"] == {"keys": ["cli"]}


@pytest.mark.parametrize(
    ("cli", "code"),
    [
        ({"delegation_mode": "fan-out"}, "agent_settings_invalid_delegation_mode"),
        ({"behavior": {"response_verbosity": "huge"}}, "agent_settings_invalid_verbosity"),
        ({"behavior": {"politeness_formality": "casual"}}, "agent_settings_invalid_politeness_formality"),
    ],
)
async def test_invalid_agent_settings_are_atomic_and_emit_stable_secret_free_warning(
    control, tmp_path, cli, code,
):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({"cli": cli, "openai_api_key": "must-not-leak"}))

    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == code
    assert not (tmp_path / "control-center-settings.json").exists()
    events = read_jsonl_tail(tmp_path / "trace.jsonl")
    [event] = [item for item in events if item["kind"] == "settings.agent.rejected"]
    assert event["level"] == "warning"
    assert event["data"] == {"code": code}
    assert "must-not-leak" not in json.dumps(event)


async def test_conflicting_delegation_aliases_are_rejected_before_write(control, tmp_path):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({
            "cli": {"delegation_mode": "auto"},
            "routing": {"enabled": False},
        }))

    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "agent_settings_conflicting_delegation_mode"
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_behavior_prompt_overflow_is_rejected_before_disk_or_agent_memory_changes(control, tmp_path):
    from copy import deepcopy
    from jarvis.domain.prompt_registry import MAX_OVERRIDE_TEXT
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    descriptor = default_prompt_registry().require("backend.turn.addition")
    baseline = {
        "sentinel": {"keep": True},
        "agent_behavior": {"response_verbosity": "inherit", "politeness_formality": "inherit"},
        "prompt_overrides": {"schema_version": 1, "overrides": {
            descriptor.prompt_id: {
                "base_revision": descriptor.default_revision,
                "text": "x" * MAX_OVERRIDE_TEXT,
            },
        }},
    }
    control._write_settings(baseline)
    control._apply_agent_settings(baseline)
    disk_before = control.settings_path.read_bytes()
    memory_before = deepcopy(control.agent._prompt_overrides)

    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({"cli": {"behavior": {
            "response_verbosity": "concise", "politeness_formality": "inherit",
        }}}))

    code = "agent_settings_behavior_prompt_too_large"
    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == code
    assert control.settings_path.read_bytes() == disk_before
    assert control.agent._prompt_overrides == memory_before
    events = read_jsonl_tail(tmp_path / "trace.jsonl")
    assert [item["data"] for item in events if item["kind"] == "settings.agent.rejected"][-1] == {"code": code}


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


# ===========================================================================
# Architecture vocale
# ===========================================================================


def stored_settings(tmp_path) -> dict:
    return json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))


async def test_the_voice_architecture_is_described_with_its_choices(control):
    voice = (await settings_of(control))["voice"]

    # Rien d'enregistré : Voice suivra le défaut calculé, et la page le dit.
    assert voice["arch"] == ""
    assert voice["arch_effective"] == "legacy"
    assert voice["arch_source"] == "default"
    assert voice["arch_problem"] is None
    archs = {item["id"]: item for item in voice["archs"]}
    assert list(archs) == ["", "legacy", "continuous_brain"]
    assert archs["legacy"]["label"] == "Un tour par appui"
    assert archs["continuous_brain"]["label"] == "Conversation continue (jusqu'à F9)"
    assert archs[""]["label"] == "Par défaut — Un tour par appui"
    assert all(item["hint"] for item in voice["archs"])


async def test_the_voice_architecture_round_trips_and_can_be_reset(control, tmp_path):
    await control.save_settings(JsonRequest({"voice": {"arch": " Continuous_Brain "}}))

    assert stored_settings(tmp_path)["voice_arch"] == "continuous_brain"
    voice = (await settings_of(control))["voice"]
    assert (voice["arch"], voice["arch_effective"], voice["arch_source"]) == (
        "continuous_brain", "continuous_brain", "settings"
    )

    # Champ plat, pendant de `voice_turn_mode` ; vide rend la main au défaut.
    await control.save_settings(JsonRequest({"voice_arch": ""}))

    assert stored_settings(tmp_path)["voice_arch"] == ""
    voice = (await settings_of(control))["voice"]
    assert (voice["arch"], voice["arch_effective"], voice["arch_source"]) == ("", "legacy", "default")


@pytest.mark.parametrize("payload", [{"voice": {"arch": "continuous"}}, {"voice_arch": "duplex"}])
async def test_an_unknown_voice_architecture_is_refused_and_nothing_is_written(control, tmp_path, payload):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest(payload))

    assert "Architecture vocale inconnue" in refused.value.text
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_continuous_mode_is_refused_on_gemini_live(control, tmp_path):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({"voice": {"stack": "gemini_live", "arch": "continuous_brain"}}))

    assert "OpenAI Realtime" in refused.value.text
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_continuous_mode_is_refused_with_a_manual_turn(control, tmp_path):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({
            "voice": {"arch": "continuous_brain", "settings": {"openai_realtime": {"turn_mode": "manual"}}}
        }))

    assert "fin de tour automatique" in refused.value.text
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_the_environment_answers_while_nothing_is_chosen_but_is_never_copied(control, tmp_path, monkeypatch):
    """JARVIS_VOICE_ARCH reste le repli, et le retirer doit encore ramener à legacy.

    Si le premier enregistrement recopiait la variable dans le fichier, c'est
    cette copie figée qui gagnerait ensuite, et le retour arrière par le .env
    cesserait silencieusement de fonctionner.
    """
    monkeypatch.setenv("JARVIS_VOICE_ARCH", "continuous_brain")

    voice = (await settings_of(control))["voice"]
    assert (voice["arch"], voice["arch_effective"], voice["arch_source"]) == ("", "continuous_brain", "env")
    assert voice["archs"][0]["label"] == "Selon JARVIS_VOICE_ARCH — Conversation continue (jusqu'à F9)"

    await control.save_settings(JsonRequest({"voice": {"settings": {"openai_realtime": {"voice": "ash"}}}}))
    assert stored_settings(tmp_path)["voice_arch"] == ""


async def test_the_interface_choice_overrides_an_incompatible_environment(control, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_VOICE_ARCH", "continuous_brain")
    manual = {"settings": {"openai_realtime": {"turn_mode": "manual"}}}

    # La variable impose le continu : une fin de tour manuelle est refusée…
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest({"voice": manual}))
    assert "JARVIS_VOICE_ARCH" in refused.value.text

    # … sauf si l'interface choisit explicitement « Un tour par appui ».
    await control.save_settings(JsonRequest({"voice": {**manual, "arch": "legacy"}}))
    stored = stored_settings(tmp_path)
    assert stored["voice_arch"] == "legacy"
    assert stored["voice_turn_mode"] == "manual"


async def test_an_incompatible_file_written_by_hand_is_flagged(control, tmp_path):
    (tmp_path / "control-center-settings.json").write_text(
        json.dumps({"voice_stack": "gemini_live", "voice_arch": "continuous_brain"}), encoding="utf-8"
    )

    voice = (await settings_of(control))["voice"]
    assert "OpenAI Realtime" in voice["arch_problem"]


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


async def test_an_inactivity_timeout_of_zero_is_stored_as_never(control):
    await control.save_settings(JsonRequest({"audio": {"active_timeout_s": "0"}}))
    assert (await settings_of(control))["audio"]["active_timeout_s"] == "0"

    await control.save_settings(JsonRequest({"active_timeout_s": 45}))
    assert (await settings_of(control))["active_timeout_s"] == "45"

    # Un champ vidé reste vide : Voice retombe alors sur l'environnement.
    await control.save_settings(JsonRequest({"audio": {"active_timeout_s": " "}}))
    assert (await settings_of(control))["active_timeout_s"] == ""


@pytest.mark.parametrize("bad", ["3", "-1", "abc", "nan", True])
@pytest.mark.parametrize("shape", ["flat", "audio"])
async def test_an_invalid_inactivity_timeout_is_refused_and_nothing_is_written(control, tmp_path, shape, bad):
    payload = {"active_timeout_s": bad} if shape == "flat" else {"audio": {"active_timeout_s": bad}}
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_settings(JsonRequest(payload))
    assert "Délai d'inactivité invalide" in refused.value.text
    assert "indiquez 0" in refused.value.text
    assert not (tmp_path / "control-center-settings.json").exists()


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


async def test_canonical_subagent_catalog_is_sourced_read_only_and_refreshable(control, monkeypatch):
    async def detected(_commands):  # noqa: ANN001
        return [
            cli_catalog.describe(spec, command=spec.default_command, detection={"available": True})
            for spec in cli_catalog.AGENT_CLIS
        ]

    monkeypatch.setattr(cli_catalog, "detect_all", detected)
    control.catalog = FakeCatalog(result={
        "models": [{"id": "model-current", "roles": ["text"]}],
        "source": "live",
        "fetched_at": time.time(),
    })

    response = await control.catalog_view(QueryRequest(surface="subagents", role="text", refresh="true"))
    payload = json.loads(response.text)

    assert response.status == 200 and payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["surface"] == "subagents" and payload["role"] == "text"
    current = [item for item in payload["items"] if item["identity"]["model_id"] == "model-current"]
    defaults = [item for item in payload["items"] if item["identity"]["model_id"] == ""]
    assert {item["availability"]["state"] for item in current} == {"usable"}
    assert {item["availability"]["state"] for item in defaults} == {"configured_unverified"}
    assert all(item["actions"] == [] and item["key"].startswith("catalog_v1_") for item in payload["items"])
    assert {call[0] for call in control.catalog.calls} == {"anthropic", "openai"}
    assert all(call[2] is True for call in control.catalog.calls)


async def test_canonical_voice_catalog_uses_same_sourced_contract(control):
    registry = default_voice_registry()
    descriptor = registry.descriptors()[0]
    control._voice_registry = registry
    control.catalog = FakeCatalog(result={
        "models": [{"id": descriptor.ref.model_id, "roles": ["realtime"]}],
        "source": "live",
        "fetched_at": time.time(),
    })

    response = await control.catalog_view(QueryRequest(surface="voice", role="realtime"))
    payload = json.loads(response.text)

    assert response.status == 200 and payload["surface"] == "voice"
    assert payload["role"] == "realtime"
    assert any(item["availability"]["state"] == "usable" for item in payload["items"])
    assert all(item["pricing"] is None and item["actions"] == [] for item in payload["items"])


@pytest.mark.parametrize(
    ("surface_name", "role_name"),
    [("voice", "subagent"), ("subagents", "realtime"), ("voice", "spech")],
)
async def test_canonical_catalog_rejects_cross_surface_and_unknown_roles(control, surface_name, role_name):
    response = await control.catalog_view(QueryRequest(surface=surface_name, role=role_name))

    assert response.status == 400
    assert json.loads(response.text)["code"] == "catalog_role_invalid"


async def test_canonical_catalog_rejects_invalid_surface_and_malformed_role(control):
    surface = await control.catalog_view(QueryRequest(surface="agents"))
    role = await control.catalog_view(QueryRequest(surface="voice", role="bad role"))

    assert surface.status == 400 and json.loads(surface.text)["code"] == "catalog_surface_invalid"
    assert role.status == 400 and json.loads(role.text)["code"] == "catalog_role_invalid"


async def test_stale_saved_model_is_noneligible_across_catalog_legacy_and_hook(
    control, tmp_path, monkeypatch,
):
    observed = datetime.now(timezone.utc)
    stale = {
        "models": [{"id": "saved-stale", "roles": ["text"]}],
        "fetched_at": (observed - timedelta(days=1)).timestamp(),
    }

    async def detected(_commands):  # noqa: ANN001
        return [
            cli_catalog.describe(spec, command=spec.default_command, detection={"available": True})
            for spec in cli_catalog.AGENT_CLIS
        ]

    monkeypatch.setattr(cli_catalog, "detect_all", detected)
    agents = await detected({})
    monkeypatch.setattr(routing_hook, "local_agents", lambda: agents)
    control.catalog = FakeCatalog(
        error=CatalogError("catalog_unreachable", "Fournisseur injoignable."),
        stale=stale,
    )
    await control.save_settings(JsonRequest({"routing": {
        "enabled": True,
        "profiles": {"code": {"candidates": [{"agent": "claude", "model": "saved-stale"}]}},
    }}))

    canonical = json.loads((await control.catalog_view(QueryRequest(
        surface="subagents", role="text",
    ))).text)
    legacy = json.loads((await control.routing_candidates(None)).text)
    policy = agent_routing.load_policy(control._settings())
    (tmp_path / "model-catalog.json").write_text(
        json.dumps({provider: {**stale, "provider": provider} for provider in ("anthropic", "openai")}),
        encoding="utf-8",
    )
    hook = routing_hook.offline_candidates(tmp_path, policy, now=observed)

    catalog_item = next(
        item for item in canonical["items"]
        if item["identity"] == {"agent_id": "claude", "provider_id": "anthropic", "model_id": "saved-stale"}
    )
    legacy_item = next(
        item for item in legacy["candidates"]
        if item["agent"] == "claude" and item["model"] == "saved-stale"
    )
    hook_item = next(item for item in hook if item.agent == "claude" and item.model == "saved-stale")

    assert catalog_item["availability"]["state"] == "configured_unverified"
    assert catalog_item["availability"]["selectable"] is False
    assert legacy_item["available"] is False and "non vérifiée" in legacy_item["unavailable_reason"]
    assert hook_item.available is False and "non vérifiée" in (hook_item.unavailable_reason or "")


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


def sent_by(control: ControlCenter) -> list[str]:
    messages: list[str] = []

    async def fake_send(text: str) -> dict:
        messages.append(text)
        return {"ok": True}

    control.agent.send = fake_send  # type: ignore[assignment]
    return messages


async def test_an_ask_without_context_reaches_the_agent_unchanged(control):
    """Le chemin du panneau navigateur et de la passerelle legacy, inchangé."""

    questions = asked_by(control)

    await control.agent_ask(JsonRequest({"text": "salut", "timeout_s": 30}))

    assert questions == ["salut"]


async def test_a_context_that_is_not_an_object_is_ignored_rather_than_rendered(control):
    questions = asked_by(control)

    await control.agent_ask(JsonRequest({"text": "salut", "context": "n'importe quoi"}))

    assert questions == ["salut"]


async def test_non_inherited_behavior_is_applied_to_a_context_free_agent_turn(control):
    await control.save_settings(JsonRequest({"cli": {"behavior": {
        "response_verbosity": "concise", "politeness_formality": "formal",
    }}}))
    questions = asked_by(control)

    await control.agent_ask(JsonRequest({"text": "salut"}))

    assert "Réponds de façon concise" in questions[0]
    assert "Adopte un ton formel" in questions[0]
    assert questions[0].endswith("[Demande]\nsalut")


async def test_generated_behavior_does_not_masquerade_as_a_saved_prompt_override(control):
    await control.save_settings(JsonRequest({"cli": {"behavior": {
        "response_verbosity": "detailed", "politeness_formality": "inherit",
    }}}))

    prompts = json.loads((await control.get_prompts(None)).text)
    layer = next(item for item in prompts["layers"] if item["prompt_id"] == "backend.turn.addition")

    assert layer["current_text"] == ""
    assert layer["override"] is None


async def test_agent_send_preserves_inherit_and_applies_explicit_behavior(control):
    messages = sent_by(control)
    evidence = []
    control.agent.set_next_prompt_evidence = lambda value: evidence.append(value)  # type: ignore[method-assign]
    await control.agent_send(JsonRequest({"text": "message brut"}))
    assert messages == ["message brut"]
    assert evidence == []

    await control.save_settings(JsonRequest({"cli": {"behavior": {
        "response_verbosity": "concise", "politeness_formality": "direct",
    }}}))
    await control.agent_send(JsonRequest({"text": "message configuré"}))

    assert "Réponds de façon concise" in messages[1]
    assert "Adopte un ton direct" in messages[1]
    assert messages[1].endswith("[Demande]\nmessage configuré")
    assert len(evidence) == 1
    assert evidence[0]["program_id"] == "backend.claude.turn"
    assert evidence[0]["channel"] == "stdin.user_message"
    assert evidence[0]["application"] == "sent"
    assert "message configuré" not in json.dumps(evidence[0])


async def test_agent_send_rejects_blank_text_before_behavior_can_make_it_nonempty(control):
    await control.save_settings(JsonRequest({"cli": {"behavior": {
        "response_verbosity": "concise", "politeness_formality": "inherit",
    }}}))
    messages = sent_by(control)

    with pytest.raises(web.HTTPBadRequest):
        await control.agent_send(JsonRequest({"text": "   "}))

    assert messages == []


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
