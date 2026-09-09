"""Ce qui tient debout derrière la fenêtre de réglages.

Trois promesses sont faites à l'utilisateur dans cet écran, et chacune est
vérifiable :

* une clé API rangée une fois est sélectionnable partout, et sa valeur ne
  ressort jamais vers la page ;
* les modèles proposés viennent de l'API du fournisseur — jamais d'une liste
  écrite en dur — et un échec se dit au lieu de se déguiser en liste vide ;
* un raccourci proposé est un raccourci que le système sait réellement capter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.runtime import cli_catalog, credentials as creds, shortcuts, voice_stack
from jarvis.runtime.model_catalog import CatalogError, ModelCatalog


# ===========================================================================
# Magasin de clés API
# ===========================================================================


def test_a_stored_key_is_never_returned_in_clear(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings: dict = {}
    record = creds.upsert_credential(settings, provider="openai", name="Perso", value="sk-secret-value-1234")

    assert record["hint"] == "…1234"
    public = json.dumps(creds.credentials_state(settings))
    assert "sk-secret-value-1234" not in public
    # Les processus JARVIS, eux, y ont accès : c'est le seul chemin de sortie.
    assert creds.secret_for(settings, "openai") == "sk-secret-value-1234"


def test_two_keys_of_the_same_provider_coexist_and_the_bound_one_wins(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings: dict = {}
    perso = creds.upsert_credential(settings, provider="openai", name="Perso", value="sk-perso")
    travail = creds.upsert_credential(settings, provider="openai", name="Travail", value="sk-travail")

    # La première clé enregistrée devient active toute seule : sans cela le
    # service resterait muet alors qu'une clé est bien là.
    assert creds.secret_for(settings, "openai") == "sk-perso"

    creds.bind_credential(settings, "openai", travail["id"])
    assert creds.secret_for(settings, "openai") == "sk-travail"

    assert [c["bound"] for c in creds.list_credentials(settings) if c["id"] == perso["id"]] == [False]


def test_renaming_a_key_without_retyping_it_keeps_its_value(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings: dict = {}
    record = creds.upsert_credential(settings, provider="openai", name="Perso", value="sk-perso")

    creds.upsert_credential(settings, credential_id=record["id"], provider="openai", name="Maison", value="")

    assert creds.secret_for(settings, "openai") == "sk-perso"
    assert [c["name"] for c in creds.list_credentials(settings)] == ["Maison"]


def test_deleting_the_active_key_promotes_another_one_of_the_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings: dict = {}
    first = creds.upsert_credential(settings, provider="openai", name="Perso", value="sk-perso")
    creds.upsert_credential(settings, provider="openai", name="Travail", value="sk-travail")

    assert creds.delete_credential(settings, first["id"]) is True
    assert creds.secret_for(settings, "openai") == "sk-travail"


def test_a_key_cannot_be_bound_to_the_wrong_provider(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    settings: dict = {}
    record = creds.upsert_credential(settings, provider="openai", name="Perso", value="sk-perso")

    with pytest.raises(creds.CredentialError) as excinfo:
        creds.bind_credential(settings, "google", record["id"])
    assert excinfo.value.code == "credential_provider_mismatch"


def test_the_environment_still_answers_when_no_key_is_stored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert creds.secret_for({}, "openai") == "env-key"


def test_the_previous_flat_configuration_is_taken_over_not_dropped(monkeypatch):
    """Un .env et un ancien réglage plat doivent survivre à cet écran.

    L'ancien format n'est pas effacé : d'autres chemins de démarrage le lisent
    encore, et une clé perdue des deux côtés est une panne silencieuse.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = {"openai_api_key": "sk-historique", "porcupine_access_key": "pv-historique"}

    assert creds.migrate_legacy(settings) is True

    providers = {c["provider"] for c in creds.list_credentials(settings)}
    assert providers == {"openai", "porcupine"}
    assert settings["openai_api_key"] == "sk-historique"
    assert creds.secret_for(settings, "porcupine") == "pv-historique"
    # Rejouer la migration ne doit pas créer de doublon.
    assert creds.migrate_legacy(settings) is False


def test_a_key_needs_a_name_and_a_value():
    with pytest.raises(creds.CredentialError) as no_name:
        creds.upsert_credential({}, provider="openai", name="  ", value="sk-x")
    assert no_name.value.code == "credential_name_required"

    with pytest.raises(creds.CredentialError) as no_value:
        creds.upsert_credential({}, provider="openai", name="Perso", value="")
    assert no_value.value.code == "credential_value_required"


# ===========================================================================
# Catalogue de modèles
# ===========================================================================


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload

    async def text(self) -> str:
        return json.dumps(self._payload) if not isinstance(self._payload, str) else self._payload

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc) -> bool:  # noqa: ANN001
        return False


class FakeSession:
    """Double d'aiohttp.ClientSession réduit à ce que le catalogue utilise."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, *, params=None, headers=None):  # noqa: ANN001
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_anthropic_models_are_paginated_and_authenticated(tmp_path):
    session = FakeSession(
        FakeResponse(200, {"data": [{"id": "claude-opus-5", "display_name": "Opus 5"}], "has_more": True, "last_id": "claude-opus-5"}),
        FakeResponse(200, {"data": [{"id": "claude-sonnet-5", "display_name": "Sonnet 5"}], "has_more": False}),
    )
    catalog = ModelCatalog(tmp_path / "cache.json")

    result = await catalog.models("anthropic", "sk-ant-key", session=session)

    assert [m["id"] for m in result["models"]] == ["claude-opus-5", "claude-sonnet-5"]
    assert result["source"] == "live"
    url, params, headers = session.calls[0]
    assert headers["x-api-key"] == "sk-ant-key"
    assert headers["anthropic-version"]
    assert session.calls[1][1]["after_id"] == "claude-opus-5"


@pytest.mark.asyncio
async def test_openai_models_are_sorted_into_the_usages_the_interface_offers(tmp_path):
    session = FakeSession(
        FakeResponse(
            200,
            {
                "data": [
                    {"id": "gpt-realtime-2.1"},
                    {"id": "gpt-4o-mini-transcribe"},
                    {"id": "whisper-1"},
                    {"id": "gpt-5-codex"},
                    {"id": "tts-1"},
                    {"id": "text-embedding-3-small"},
                ]
            },
        )
    )
    catalog = ModelCatalog(tmp_path / "cache.json")

    models = (await catalog.models("openai", "sk-key", session=session))["models"]
    roles = {m["id"]: m["roles"] for m in models}

    assert roles["gpt-realtime-2.1"] == ("realtime",)
    assert roles["gpt-4o-mini-transcribe"] == ("transcription",)
    assert roles["whisper-1"] == ("transcription",)
    assert roles["gpt-5-codex"] == ("text",)
    assert roles["tts-1"] == ("speech",)
    # Un modèle d'embedding n'a sa place dans aucun menu de cet écran.
    assert "text-embedding-3-small" not in roles


@pytest.mark.asyncio
async def test_gemini_live_models_come_from_the_capability_google_declares(tmp_path):
    session = FakeSession(
        FakeResponse(
            200,
            {
                "models": [
                    {"name": "models/gemini-live-2.5-flash", "displayName": "Live Flash",
                     "supportedGenerationMethods": ["bidiGenerateContent"]},
                    {"name": "models/gemini-2.5-pro", "displayName": "Pro",
                     "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]
            },
        )
    )
    catalog = ModelCatalog(tmp_path / "cache.json")

    models = (await catalog.models("google", "AIza-key", session=session))["models"]
    live = [m["id"] for m in models if "realtime" in m["roles"]]

    assert live == ["gemini-live-2.5-flash"]
    assert "gemini-2.5-pro" in [m["id"] for m in models if "text" in m["roles"]]
    assert "embedding-001" not in [m["id"] for m in models]


@pytest.mark.asyncio
async def test_a_missing_key_says_so_instead_of_returning_an_empty_catalogue(tmp_path):
    catalog = ModelCatalog(tmp_path / "cache.json")
    with pytest.raises(CatalogError) as excinfo:
        await catalog.models("openai", "")
    assert excinfo.value.code == "catalog_no_key"
    assert "API Keys" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_refused_key_is_reported_as_such(tmp_path):
    session = FakeSession(FakeResponse(401, {"error": "nope"}))
    catalog = ModelCatalog(tmp_path / "cache.json")

    with pytest.raises(CatalogError) as excinfo:
        await catalog.models("openai", "sk-wrong", session=session)
    assert excinfo.value.code == "catalog_unauthorized"


@pytest.mark.asyncio
async def test_the_catalogue_is_cached_and_a_new_key_invalidates_it(tmp_path):
    session = FakeSession(
        FakeResponse(200, {"data": [{"id": "gpt-5"}]}),
        FakeResponse(200, {"data": [{"id": "gpt-5"}, {"id": "gpt-5-codex"}]}),
    )
    catalog = ModelCatalog(tmp_path / "cache.json")

    first = await catalog.models("openai", "sk-one", session=session)
    again = await catalog.models("openai", "sk-one", session=session)
    assert again["source"] == "cache"
    assert len(session.calls) == 1
    assert first["models"] == again["models"]

    # Une autre clé, c'est un autre compte : les modèles visibles changent.
    switched = await catalog.models("openai", "sk-two", session=session)
    assert switched["source"] == "live"
    assert len(switched["models"]) == 2


@pytest.mark.asyncio
async def test_the_cache_survives_a_restart(tmp_path):
    session = FakeSession(FakeResponse(200, {"data": [{"id": "gpt-5"}]}))
    path = tmp_path / "cache.json"

    await ModelCatalog(path).models("openai", "sk-one", session=session)

    assert ModelCatalog(path).cached("openai")["models"][0]["id"] == "gpt-5"


# ===========================================================================
# Détection des CLI
# ===========================================================================


@pytest.mark.asyncio
async def test_a_cli_absent_from_the_path_is_reported_absent():
    result = await cli_catalog.probe("jarvis-cli-qui-nexiste-pas")
    assert result["available"] is False
    assert "PATH" in result["error"]


@pytest.mark.asyncio
async def test_a_present_cli_reports_its_real_version():
    import sys

    result = await cli_catalog.probe(sys.executable)
    assert result["available"] is True
    assert result["version"].lower().startswith("python")
    assert result["path"]


def test_each_cli_declares_the_provider_that_lists_its_models():
    assert cli_catalog.spec_for("claude").model_provider == "anthropic"
    assert cli_catalog.spec_for("codex").model_provider == "openai"
    # Le vocabulaire n'est pas le même des deux côtés, et l'interface le reprend.
    assert cli_catalog.spec_for("claude").permission_label == "Autorisations"
    assert cli_catalog.spec_for("codex").permission_label == "Bac à sable"
    assert cli_catalog.normalize_agent_cli("n'importe quoi") == "claude"


# ===========================================================================
# Piles vocales
# ===========================================================================


def test_each_stack_declares_the_sample_rates_its_provider_imposes():
    assert voice_stack.OPENAI_REALTIME.input_sample_rate == 24000
    assert voice_stack.OPENAI_REALTIME.output_sample_rate == 24000
    # L'API Live de Google veut du 16 kHz en entrée et rend du 24 kHz.
    assert voice_stack.GEMINI_LIVE.input_sample_rate == 16000
    assert voice_stack.GEMINI_LIVE.output_sample_rate == 24000


def test_silence_settings_only_exist_when_the_provider_closes_the_turn():
    spec = voice_stack.OPENAI_REALTIME
    silence = next(f for f in spec.fields if f.key == "vad_silence_duration_ms")
    assert silence.depends_on == "turn_mode"
    assert silence.depends_values == ("auto",)


def test_model_fields_point_at_the_provider_catalogue_not_at_a_hardcoded_list():
    sources = {f.key: f.source for spec in voice_stack.VOICE_STACKS for f in spec.fields if f.source}
    assert sources["model"] in {"openai:realtime", "google:realtime"}
    assert sources["transcription_model"] == "openai:transcription"


def test_an_out_of_range_setting_is_refused_with_a_readable_message():
    with pytest.raises(voice_stack.VoiceStackError) as excinfo:
        voice_stack.coerce(voice_stack.OPENAI_REALTIME, {"vad_threshold": 4})
    assert excinfo.value.code == "voice_field_out_of_range"
    assert "Seuil" in str(excinfo.value)


def test_an_unknown_option_is_refused_rather_than_silently_defaulted():
    with pytest.raises(voice_stack.VoiceStackError) as excinfo:
        voice_stack.coerce(voice_stack.GEMINI_LIVE, {"voice": "Bruno"})
    assert excinfo.value.code == "voice_field_unknown_option"


def test_settings_read_the_previous_flat_format_before_the_new_one():
    legacy = {"voice_turn_mode": "manual", "realtime_voice": "ash"}
    values = voice_stack.settings_for(legacy, voice_stack.OPENAI_REALTIME.id)
    assert values["turn_mode"] == "manual"
    assert values["voice"] == "ash"

    voice_stack.store_for(legacy, voice_stack.OPENAI_REALTIME.id, {"voice": "verse"})
    assert voice_stack.settings_for(legacy, voice_stack.OPENAI_REALTIME.id)["voice"] == "verse"


def test_a_gemini_setting_does_not_leak_into_the_openai_stack():
    settings: dict = {}
    voice_stack.store_for(settings, voice_stack.GEMINI_LIVE.id, {"voice": "Kore"})
    assert voice_stack.settings_for(settings, voice_stack.OPENAI_REALTIME.id)["voice"] == "cedar"
    assert voice_stack.settings_for(settings, voice_stack.GEMINI_LIVE.id)["voice"] == "Kore"


# ===========================================================================
# Raccourcis
# ===========================================================================


def test_a_system_shortcut_refuses_a_combination_it_could_not_capture():
    """Le détecteur de réveil ne sait résoudre qu'une touche seule.

    Accepter « ctrl+j » ici donnerait un raccourci enregistré qui ne se
    déclenche jamais, et rien ne le dirait.
    """
    with pytest.raises(shortcuts.ShortcutError) as excinfo:
        shortcuts.normalize_global("ctrl+j")
    assert excinfo.value.code == "shortcut_global_no_modifier"

    with pytest.raises(shortcuts.ShortcutError) as unsupported:
        shortcuts.normalize_global("touche_inventee")
    assert unsupported.value.code == "shortcut_global_unsupported"

    assert shortcuts.normalize_global("F12") == "f12"
    assert shortcuts.normalize_global("Home") == "home"


def test_an_interface_shortcut_normalises_its_modifier_order():
    assert shortcuts.normalize_ui("shift+ctrl+ArrowRight") == "ctrl+shift+ArrowRight"
    assert shortcuts.normalize_ui("alt+K") == "alt+k"
    with pytest.raises(shortcuts.ShortcutError) as excinfo:
        shortcuts.normalize_ui("hyper+k")
    assert excinfo.value.code == "shortcut_unknown_modifier"


def test_two_actions_cannot_share_one_key_in_the_same_scope():
    settings: dict = {}
    with pytest.raises(shortcuts.ShortcutError) as excinfo:
        shortcuts.apply(settings, {"ui_panel_trace": "e"})  # « e » est déjà le panneau Erreurs
    assert excinfo.value.code == "shortcut_conflict"
    assert "Erreurs" in str(excinfo.value)
    assert "shortcuts" not in settings


def test_the_wake_key_keeps_its_historic_setting_name():
    settings = {"manual_wake_key": "f8"}
    assert shortcuts.current(settings)["wake_toggle"] == "f8"

    shortcuts.apply(settings, {"wake_toggle": "f7"})
    # Le processus Voice et la barre d'état lisent encore cette clé.
    assert settings["manual_wake_key"] == "f7"
    assert settings["shortcuts"]["wake_toggle"] == "f7"


def test_an_unreadable_stored_shortcut_falls_back_instead_of_breaking_the_screen():
    settings = {"shortcuts": {"wake_toggle": "ctrl+alt+inconnu"}}
    assert shortcuts.current(settings)["wake_toggle"] == "f9"


def test_every_listed_shortcut_is_wired_in_the_page():
    """Un raccourci listé mais inerte est pire qu'un raccourci absent."""
    html = (Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html").read_text(encoding="utf-8")
    for spec in shortcuts.SHORTCUTS:
        if spec.scope == "global":
            continue
        assert spec.id in html, f"{spec.id} est proposé mais la page ne le traite pas"
