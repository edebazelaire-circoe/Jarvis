"""Solo Owner et qualité audio dans le Control Center (handoff Solo Owner, tâche 08).

L'écran projette un état, il ne décide rien : ce qui est prouvé ici, c'est que
chaque réglage enregistrable passe par le validateur même de Voice (refus en
HTTP 400 avec un code stable, rien d'écrit), que l'écran dit si Solo Owner est
réellement appliqué ou non, d'où vient ce verdict (sonde des réglages ou
constat de Voice), que l'annulation d'écho indisponible se voit, et qu'aucune
empreinte vocale n'atteint l'API ni la page.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from aiohttp import web
import pytest

from jarvis.adapters import file_replace
from jarvis.adapters import sherpa_speaker_embedder as engine
from jarvis.adapters.owner_voice_profile import OwnerVoiceProfile, save_profile
from jarvis.domain.speaker import ConversationAuthorization, ConversationMode, SpeakerVerificationMode, VerifierAvailability
from jarvis.domain.voice_architecture import VoiceArchitectureId
import jarvis.runtime.control_center as control_module
from jarvis.runtime import voice_stack
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import (
    DEFAULT_OWNER_EVIDENCE_MS,
    DEFAULT_OWNER_SHORT_EVIDENCE_MS,
    DEFAULT_OWNER_SHORT_MARGIN,
    MAX_OWNER_EVIDENCE_MS,
    MAX_OWNER_SHORT_MARGIN,
    MIN_OWNER_EVIDENCE_MS,
    VoiceArchitecture,
    parse_speaker_verifier_settings,
)

CONTROL_CENTER_HTML = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"
BIOMETRIC_KEYS = {"embedding", "embeddings", "voiceprint", "empreinte"}


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


class Probe:
    """Sonde du vérificateur réduite à ce que le Control Center lit."""

    def __init__(self, availability: VerifierAvailability = VerifierAvailability.READY, code: str = "ready") -> None:
        self.availability = availability
        self.code = code

    def payload(self) -> dict[str, object]:
        return {"availability": self.availability.value, "code": self.code}


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


def ready_probe(monkeypatch, availability: VerifierAvailability = VerifierAvailability.READY) -> None:
    monkeypatch.setattr(control_module, "probe_owner_verifier", lambda *args, **kwargs: Probe(availability))


async def voice_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_settings(None)).text)["voice"]


async def authorization_of(control: ControlCenter) -> dict:
    return (await voice_of(control))["authorization"]


async def save(control: ControlCenter, **voice) -> None:
    await control.save_settings(JsonRequest({"voice": voice}))


async def save_authorization(control: ControlCenter, **values) -> None:
    await save(control, authorization=values)


def stored_settings(tmp_path) -> dict:
    return json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))


def write_settings(tmp_path, settings: dict) -> None:
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")


def keys_and_lists(value, found=None):  # noqa: ANN001, ANN201
    found = found if found is not None else {"keys": set(), "numeric_lists": []}
    if isinstance(value, dict):
        for key, item in value.items():
            found["keys"].add(key)
            keys_and_lists(item, found)
    elif isinstance(value, list):
        if value and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            found["numeric_lists"].append(value)
        for item in value:
            keys_and_lists(item, found)
    return found


# ===========================================================================
# Description : champs, choix cohérents, bornes
# ===========================================================================


async def test_the_screen_describes_the_solo_owner_controls_from_the_server(control):
    authorization = await authorization_of(control)

    assert [field["key"] for field in authorization["fields"]] == [
        "conversation_mode", "speaker_verification", "owner_buffer_ms",
    ]
    assert [field["key"] for field in authorization["advanced_fields"]] == [
        "owner_threshold", "owner_evidence_ms", "owner_short_evidence_ms", "owner_short_margin",
    ]
    # Le chemin du profil n'est pas un champ : lecture seule.
    assert "owner_profile_path" not in {field["key"] for field in authorization["advanced_fields"]}
    assert authorization["verifier_settings"]["read_only"] == ["owner_profile_path"]
    # Seules les combinaisons que l'enregistrement accepterait sont proposées.
    assert authorization["verification_modes_by_mode"] == {"open_room": ["off", "shadow"], "solo_owner": ["enforce"]}
    for mode, allowed in authorization["verification_modes_by_mode"].items():
        for verification in allowed:
            ConversationAuthorization(ConversationMode(mode), SpeakerVerificationMode(verification))


def test_the_advanced_fields_take_their_bounds_from_the_validator():
    fields = {field.key: field for field in voice_stack.OWNER_TUNING_FIELDS}

    assert (fields["owner_evidence_ms"].minimum, fields["owner_evidence_ms"].maximum) == (
        MIN_OWNER_EVIDENCE_MS, MAX_OWNER_EVIDENCE_MS,
    )
    assert fields["owner_evidence_ms"].default == DEFAULT_OWNER_EVIDENCE_MS
    assert fields["owner_short_evidence_ms"].default == DEFAULT_OWNER_SHORT_EVIDENCE_MS
    assert fields["owner_short_margin"].maximum == MAX_OWNER_SHORT_MARGIN
    assert fields["owner_short_margin"].default == DEFAULT_OWNER_SHORT_MARGIN
    assert (fields["owner_threshold"].minimum, fields["owner_threshold"].maximum) == (0.0, 1.0)
    # Chaque champ décrit est un champ que Voice lit.
    for key in fields:
        parse_speaker_verifier_settings({key: fields[key].default}, runtime_root=Path("."))


async def test_by_default_every_value_is_reported_as_a_default(control, tmp_path):
    authorization = await authorization_of(control)

    assert set(authorization["origin"].values()) == {"default"}
    verifier = authorization["verifier_settings"]
    assert set(verifier["origin"].values()) == {"default"}
    assert verifier["status"] == "valid"
    assert verifier["effective"] == {
        "owner_threshold": engine.DEFAULT_THRESHOLD,
        "owner_evidence_ms": DEFAULT_OWNER_EVIDENCE_MS,
        "owner_short_evidence_ms": DEFAULT_OWNER_SHORT_EVIDENCE_MS,
        "owner_short_margin": DEFAULT_OWNER_SHORT_MARGIN,
        "owner_profile_path": str(tmp_path / "speaker-verification" / "owner-voice-profile.json"),
    }
    assert authorization["restart_required"] is False


# ===========================================================================
# Enregistrement des réglages fins : aller-retour, refus, cohérence
# ===========================================================================


@pytest.mark.parametrize(
    "key, raw, stored",
    [
        ("owner_threshold", "0.62", 0.62),
        ("owner_threshold", 1, 1.0),
        ("owner_evidence_ms", "2000", 2000),
        ("owner_evidence_ms", 500.0, 500),
        ("owner_short_evidence_ms", "0", 0),
        ("owner_short_evidence_ms", 300, 300),
        ("owner_short_margin", 0.2, 0.2),
        ("owner_short_margin", "0", 0.0),
    ],
)
async def test_a_tuning_value_round_trips_through_the_file(control, tmp_path, key, raw, stored):
    await save_authorization(control, **{key: raw})

    assert stored_settings(tmp_path)[key] == stored
    authorization = await authorization_of(control)
    verifier = authorization["verifier_settings"]
    assert verifier["stored"][key] == stored
    assert verifier["origin"][key] == "stored"
    assert verifier["effective"][key] == stored
    # Même lecture que Voice : le fichier relu donne la même valeur.
    parsed = parse_speaker_verifier_settings(stored_settings(tmp_path), runtime_root=tmp_path)
    assert {
        "owner_threshold": parsed.threshold,
        "owner_evidence_ms": parsed.evidence_ms,
        "owner_short_evidence_ms": parsed.short_evidence_ms or 0,
        "owner_short_margin": parsed.short_margin,
    }[key] == stored


async def test_an_emptied_tuning_value_goes_back_to_its_default(control, tmp_path):
    await save_authorization(control, owner_threshold="0.7", owner_evidence_ms=2000)
    await save_authorization(control, owner_threshold="", owner_evidence_ms=" ")

    assert "owner_threshold" not in stored_settings(tmp_path)
    assert "owner_evidence_ms" not in stored_settings(tmp_path)
    verifier = (await authorization_of(control))["verifier_settings"]
    assert verifier["effective"]["owner_threshold"] == engine.DEFAULT_THRESHOLD
    assert verifier["origin"]["owner_threshold"] == "default"


@pytest.mark.parametrize(
    "values, code, fragment",
    [
        ({"owner_threshold": 0}, "owner_threshold_invalid", "]0, 1]"),
        ({"owner_threshold": "1.5"}, "owner_threshold_invalid", "« 1.5 »"),
        ({"owner_threshold": "abc"}, "owner_threshold_invalid", "owner_threshold"),
        ({"owner_threshold": True}, "owner_threshold_invalid", "owner_threshold"),
        ({"owner_evidence_ms": 400}, "owner_evidence_invalid", "entre 500 et 4000"),
        ({"owner_evidence_ms": "4001"}, "owner_evidence_invalid", "entre 500 et 4000"),
        ({"owner_evidence_ms": 1500.5}, "owner_evidence_invalid", "nombre entier"),
        ({"owner_short_evidence_ms": 200}, "owner_short_evidence_invalid", "au moins 300"),
        ({"owner_short_evidence_ms": DEFAULT_OWNER_EVIDENCE_MS}, "owner_short_evidence_invalid", "inférieur"),
        ({"owner_short_margin": -0.1}, "owner_short_margin_invalid", "entre 0 et 0.3"),
        ({"owner_short_margin": "0.31"}, "owner_short_margin_invalid", "entre 0 et 0.3"),
        # Incohérence croisée : la réponse brève doit rester plus courte que la fenêtre.
        ({"owner_evidence_ms": 1000, "owner_short_evidence_ms": 1200}, "owner_short_evidence_invalid", "(1000 ms)"),
        # Autorisation : mêmes codes que la tâche 01, désormais aussi en en-tête.
        ({"conversation_mode": "solo_owner", "speaker_verification": "shadow"}, "solo_owner_requires_enforce", "« enforce »"),
        ({"speaker_verification": "enforce"}, "enforce_requires_solo_owner", "solo_owner"),
        ({"owner_buffer_ms": 100}, "owner_buffer_out_of_range", "entre 500 et 5000 ms"),
        ({"conversation_mode": "salle"}, "conversation_mode_unknown", "« salle »"),
    ],
)
async def test_an_invalid_value_is_refused_with_its_stable_code_and_nothing_is_written(
    control, tmp_path, values, code, fragment
):
    with pytest.raises(web.HTTPBadRequest) as refusal:
        await save_authorization(control, **values)

    assert refusal.value.headers[SETTINGS_ERROR_CODE_HEADER] == code
    assert fragment in refusal.value.text
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_a_tuning_change_is_checked_against_what_is_already_stored(control, tmp_path):
    await save_authorization(control, owner_short_evidence_ms=600)

    with pytest.raises(web.HTTPBadRequest) as refusal:
        await save_authorization(control, owner_evidence_ms=600)

    assert refusal.value.headers[SETTINGS_ERROR_CODE_HEADER] == "owner_short_evidence_invalid"
    assert "owner_evidence_ms" not in stored_settings(tmp_path)


async def test_an_invalid_tuning_value_blocks_the_whole_save(control, tmp_path):
    """Un seul POST : rien ne part si une valeur est refusée, pas même la voix choisie."""

    with pytest.raises(web.HTTPBadRequest):
        await save(control, settings={"openai_realtime": {"voice": "ash"}}, authorization={"owner_threshold": 3})

    assert not (tmp_path / "control-center-settings.json").exists()


async def test_the_profile_path_is_never_written_from_the_page(control, tmp_path):
    await save_authorization(control, owner_profile_path=str(tmp_path / "ailleurs.json"), owner_threshold=0.6)

    stored = stored_settings(tmp_path)
    assert "owner_profile_path" not in stored and stored["owner_threshold"] == 0.6
    assert (await authorization_of(control))["verifier_settings"]["origin"]["owner_profile_path"] == "default"


async def test_a_client_that_sends_the_description_back_touches_nothing(control, tmp_path):
    await save_authorization(control, conversation_mode="solo_owner", owner_threshold=0.6)
    before = stored_settings(tmp_path)

    await save_authorization(control, **await authorization_of(control))

    assert stored_settings(tmp_path) == before


async def test_a_hand_written_invalid_tuning_value_is_flagged_without_blocking_other_settings(control, tmp_path):
    write_settings(tmp_path, {"owner_threshold": "beaucoup"})

    verifier = (await authorization_of(control))["verifier_settings"]
    assert (verifier["status"], verifier["code"], verifier["effective"]) == ("invalid", "owner_threshold_invalid", None)

    await save(control, settings={"openai_realtime": {"voice": "ash"}})
    assert stored_settings(tmp_path)["realtime_voice"] == "ash"
    # L'autorisation, elle, s'enregistre encore : seuls les réglages fins touchés sont revalidés.
    await save_authorization(control, speaker_verification="shadow")
    assert stored_settings(tmp_path)["speaker_verification"] == "shadow"


async def test_saving_settings_survives_a_file_briefly_held_by_windows(control, tmp_path, monkeypatch):
    """Tâche 14 : un antivirus qui tient le fichier ne doit pas rendre une erreur 500."""

    real = os.replace
    calls = {"count": 0}

    def flaky(source, target):  # noqa: ANN001, ANN202
        calls["count"] += 1
        if calls["count"] <= 2:
            raise PermissionError(13, "Access is denied", str(target), 5)
        return real(source, target)

    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_S", 0.0)
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_MAX_S", 0.0)
    monkeypatch.setattr(os, "replace", flaky)

    await save_authorization(control, conversation_mode="solo_owner")

    assert calls["count"] == 3
    assert stored_settings(tmp_path)["conversation_mode"] == "solo_owner"
    assert not list(tmp_path.glob("*.tmp"))


async def test_settings_that_cannot_be_written_leave_no_secret_behind(control, tmp_path, monkeypatch):
    """Toutes les tentatives épuisées : refus codé, et pas un secret sur le disque.

    Le fichier temporaire porte la même clé API que le fichier final ; il ne
    doit pas survivre à l'échec, et les réglages précédents restent intacts.
    """

    def refused(source, target):  # noqa: ANN001, ANN202
        raise PermissionError(13, "Access is denied", str(target), 5)

    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_S", 0.0)
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_MAX_S", 0.0)
    await save_authorization(control, speaker_verification="shadow")
    before = (tmp_path / "control-center-settings.json").read_text(encoding="utf-8")
    monkeypatch.setattr(os, "replace", refused)

    with pytest.raises(web.HTTPServiceUnavailable) as refusal:
        await control.save_settings(JsonRequest({"openai_api_key": "sk-secret-de-test"}))

    assert refusal.value.headers[SETTINGS_ERROR_CODE_HEADER] == "settings_write_failed"
    assert "sk-secret-de-test" not in refusal.value.text
    assert not list(tmp_path.glob("**/*.tmp"))
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "sk-secret-de-test" not in path.read_text(encoding="utf-8", errors="replace"), path
    # Les réglages précédents sont intacts : rien n'est à moitié écrit.
    assert (tmp_path / "control-center-settings.json").read_text(encoding="utf-8") == before


async def test_existing_vad_aec_noise_and_ack_fields_still_save_next_to_solo_owner(control, tmp_path):
    await save(
        control,
        settings={
            "openai_realtime": {
                "vad_type": "semantic_vad",
                "vad_eagerness": "low",
                "noise_reduction": "near_field",
                "echo_cancellation": False,
                "ack_delay_ms": 800,
            }
        },
        authorization={"conversation_mode": "solo_owner", "owner_evidence_ms": 2000},
    )

    values = (await voice_of(control))["settings"]["openai_realtime"]
    assert (values["vad_type"], values["vad_eagerness"], values["noise_reduction"]) == ("semantic_vad", "low", "near_field")
    assert (values["echo_cancellation"], values["ack_delay_ms"]) == (False, 800)
    stored = stored_settings(tmp_path)
    assert (stored["conversation_mode"], stored["owner_evidence_ms"]) == ("solo_owner", 2000)


# ===========================================================================
# Shadow / enforce : ce que l'écran affiche
# ===========================================================================


async def test_shadow_observation_is_displayed_as_measuring_only(control, monkeypatch):
    ready_probe(monkeypatch)
    await save_authorization(control, speaker_verification="shadow")

    authorization = await authorization_of(control)

    assert authorization["effective"]["conversation_mode"] == "open_room"
    assert authorization["effective"]["speaker_verification"] == "shadow"
    assert authorization["origin"] == {
        "conversation_mode": "default", "speaker_verification": "stored", "owner_buffer_ms": "default",
    }
    assert (authorization["status"], authorization["status_source"]) == ("ready", "settings")


async def test_enforce_follows_solo_owner_and_is_ready_only_with_a_usable_verifier(control, monkeypatch):
    ready_probe(monkeypatch)
    await save(control, arch="continuous_brain", authorization={"conversation_mode": "solo_owner"})

    authorization = await authorization_of(control)

    assert authorization["effective"]["speaker_verification"] == "enforce"
    assert authorization["origin"]["speaker_verification"] == "default"
    assert (authorization["status"], authorization["verifier"]) == ("ready", "ready")


@pytest.mark.parametrize(
    "hand_written, expected",
    [
        ({"voice_stack": "gemini_live"}, "Gemini Live"),
        ({"voice_stack_settings": {"openai_realtime": {"turn_mode": "manual"}}}, "fin de tour automatique"),
    ],
)
async def test_a_hand_written_pair_that_voice_would_refuse_is_never_shown_as_applied(
    control, tmp_path, monkeypatch, hand_written, expected
):
    """Solo Owner n'est « appliqué » que si Voice démarre vraiment en conversation continue.

    L'écran refuse ces paires à l'enregistrement ; le fichier, écrit à la main,
    peut les porter. L'architecture demandée est bien `continuous_brain`, mais
    Voice ne démarrera pas : rien n'est appliqué, et rien n'est vert.
    """
    ready_probe(monkeypatch)
    write_settings(tmp_path, {"voice_arch": "continuous_brain", "conversation_mode": "solo_owner", **hand_written})

    voice = await voice_of(control)
    authorization = voice["authorization"]

    assert voice["arch_problem"] and expected in voice["arch_problem"]
    assert authorization["status"] == "refused"
    assert authorization["code"] == "solo_owner_requires_continuous_brain"
    # Le motif dit la vraie cause, pas « un tour par appui » : l'architecture
    # demandée est bien la conversation continue.
    assert expected in authorization["problem"] and "legacy" not in authorization["problem"]
    # L'annulation d'écho non plus ne se dit pas active pour un runtime mort-né.
    assert voice["echo_cancellation"]["status"] == "not_applicable"


async def test_a_mode_change_only_resets_a_verification_the_new_mode_would_refuse(control, page_logic):
    """Tâche 08 : l'aller-retour entre modes ne perd pas une observation enregistrée.

    La règle est celle du serveur (`verification_modes_by_mode`) ; la page ne
    redécide rien. `null` = la clé sort du brouillon, donc n'est pas envoyée et
    la valeur enregistrée continue de s'appliquer.
    """
    described = await authorization_of(control)
    by_mode = described["verification_modes_by_mode"]

    decided = page_logic(f"""
      const byMode={json.dumps(by_mode)};
      const stored={{conversation_mode:'open_room',speaker_verification:'shadow'}};
      const change=(draft,mode)=>W.authDraftAfterChange(draft,'conversation_mode',mode,stored,byMode);
      const solo=change({{}},'solo_owner');
      const back=change(solo,'open_room');
      return {{
        solo,back,
        keptShadow:!('speaker_verification' in back),
        enforceToOpenRoom:W.authDraftAfterChange({{}},'conversation_mode','open_room',
          {{conversation_mode:'solo_owner',speaker_verification:'enforce'}},byMode),
        otherFieldUntouched:W.authDraftAfterChange({{speaker_verification:'shadow'}},'owner_threshold','0.7',stored,byMode),
        unknownMode:change({{}},'autre_chose'),
      }};
    """)

    # open_room + shadow → solo_owner : la paire serait refusée, retour au défaut du mode.
    assert decided["solo"] == {"conversation_mode": "solo_owner", "speaker_verification": ""}
    # … puis retour à open_room : la clé quitte le brouillon, le « shadow » enregistré revient.
    assert decided["back"] == {"conversation_mode": "open_room"} and decided["keptShadow"] is True
    # Dans l'autre sens, « enforce » enregistré serait refusé en salle ouverte.
    assert decided["enforceToOpenRoom"] == {"conversation_mode": "open_room", "speaker_verification": ""}
    # Un autre champ ne touche jamais à la vérification.
    assert decided["otherFieldUntouched"] == {"speaker_verification": "shadow", "owner_threshold": "0.7"}
    # Mode que le serveur ne décrit pas : ne rien casser.
    assert decided["unknownMode"] == {"conversation_mode": "autre_chose"}
    # La règle du serveur est bien celle-là.
    assert "shadow" not in by_mode["solo_owner"] and "enforce" not in by_mode["open_room"]


# ===========================================================================
# Vérificateur et profil : état, commande de reprise, jamais d'empreinte
# ===========================================================================


def make_profile(**overrides) -> OwnerVoiceProfile:  # noqa: ANN003
    values = dict(
        profile_id="owner-abcd1234",
        engine="sherpa-onnx/1.13.8",
        model_id=engine.MODEL_ID,
        model_sha256=engine.MODEL_SHA256,
        embedding_dim=engine.MODEL_DIM,
        sample_rate=engine.MODEL_SAMPLE_RATE,
        enrollment_ms=21_000,
        segments=7,
        created_at="2026-09-11T14:00:00+00:00",
        embedding=tuple(float(i + 1) / 1000.0 for i in range(engine.MODEL_DIM)),
        consistency=0.8,
    )
    values.update(overrides)
    return OwnerVoiceProfile(**values)


@pytest.fixture
def model_ready(tmp_path, monkeypatch):
    """Moteur « installé » et fichier modèle de la bonne taille (zéros, jamais chargé).

    La sonde vérifie aussi l'empreinte du fichier : le SHA-256 épinglé est celui
    de ces zéros, faute du vrai modèle de 27 Mio dans les tests.
    """

    monkeypatch.setattr(engine, "engine_installed", lambda: True)
    monkeypatch.setattr(engine, "engine_version", lambda: "1.13.8")
    settings = parse_speaker_verifier_settings({}, runtime_root=tmp_path)
    settings.model_dir.mkdir(parents=True)
    model = engine.model_path(settings.model_dir)
    with model.open("wb") as handle:
        handle.truncate(engine.MODEL_SIZE)
    monkeypatch.setattr(engine, "MODEL_SHA256", engine.cached_file_sha256(model))
    return settings


async def solo_owner(control: ControlCenter) -> dict:
    await save(control, arch="continuous_brain", authorization={"conversation_mode": "solo_owner"})
    return await authorization_of(control)


async def test_a_missing_profile_is_a_refusal_with_the_enrollment_command(control, model_ready):
    authorization = await solo_owner(control)

    assert (authorization["status"], authorization["code"]) == ("refused", "solo_owner_unavailable")
    assert authorization["verifier_detail"]["code"] == "owner_profile_missing"
    assert authorization["verifier_remedy"].endswith("-m jarvis owner-voice enroll --mic")


@pytest.mark.parametrize(
    "content, code",
    [
        ("{", "owner_profile_corrupt"),
        (None, "owner_profile_incompatible"),
    ],
)
async def test_a_corrupt_or_incompatible_profile_is_flagged_with_a_replace_command(control, model_ready, content, code):
    if content is None:
        save_profile(model_ready.profile_path, make_profile(model_sha256="f" * 64))
    else:
        model_ready.profile_path.write_text(content, encoding="utf-8")

    authorization = await solo_owner(control)

    assert authorization["status"] == "refused"
    assert (authorization["verifier"], authorization["verifier_detail"]["code"]) == ("no_owner_profile", code)
    assert authorization["verifier_remedy"].endswith("enroll --mic --replace")


async def test_without_the_engine_the_remedy_is_the_install_command(control, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "engine_installed", lambda: False)

    authorization = await solo_owner(control)

    assert authorization["verifier_detail"]["code"] == "speaker_engine_not_installed"
    assert '".[speaker]"' in authorization["verifier_remedy"]


async def test_a_ready_profile_shows_its_metadata_and_never_the_voiceprint(control, model_ready):
    save_profile(model_ready.profile_path, make_profile())

    response = await control.get_settings(None)
    authorization = json.loads(response.text)["voice"]["authorization"]

    assert (authorization["status"], authorization["verifier_remedy"]) == ("ready", None)
    profile = authorization["verifier_detail"]["profile"]
    assert (profile["profile_id"], profile["created_at"], profile["enrollment_ms"]) == (
        "owner-abcd1234", "2026-09-11T14:00:00+00:00", 21_000,
    )
    assert authorization["verifier_detail"]["engine"] == "sherpa-onnx/1.13.8"
    assert authorization["verifier_detail"]["model_id"] == engine.MODEL_ID
    found = keys_and_lists(json.loads(response.text))
    # `embedding_dim` est une métadonnée ; l'empreinte elle-même n'a aucune clé.
    assert not found["keys"] & BIOMETRIC_KEYS
    assert not any(len(values) == engine.MODEL_DIM for values in found["numeric_lists"])


# ===========================================================================
# Constat de Voice : refus d'exécution, fil du vérificateur, redémarrage
# ===========================================================================


def voice_publishes(tmp_path, *, authorization: dict | None = None, capture: dict | None = None) -> VisualSignalBus:
    signals = VisualSignalBus(tmp_path)
    signals.heartbeat()
    if authorization is not None:
        signals.authorization(authorization)
    if capture is not None:
        signals.capture(capture)
    return signals


RUNTIME_REFUSAL = {
    "status": "refused",
    "code": "solo_owner_unavailable",
    "problem": "Mode Solo Owner refusé : le vérificateur de locuteur est en panne.",
    "conversation_mode": "solo_owner",
    "arch": "continuous_brain",
    "phase": "activation",
}


async def test_a_refusal_seen_by_voice_is_shown_with_its_runtime_details(control, tmp_path, monkeypatch):
    ready_probe(monkeypatch)
    await solo_owner(control)
    signals = voice_publishes(tmp_path, authorization=RUNTIME_REFUSAL)

    authorization = await authorization_of(control)

    assert (authorization["status"], authorization["code"], authorization["status_source"]) == (
        "refused", "solo_owner_unavailable", "voice",
    )
    runtime = authorization["runtime"]
    assert {key: runtime[key] for key in ("status", "code", "problem", "phase", "arch")} == {
        key: RUNTIME_REFUSAL[key] for key in ("status", "code", "problem", "phase", "arch")
    }
    assert isinstance(runtime["ts"], float)
    assert authorization["restart_required"] is False

    signals.offline()
    authorization = await authorization_of(control)
    assert (authorization["status"], authorization["status_source"]) == ("ready", "settings")
    assert "runtime" not in authorization and "worker" not in authorization


async def test_a_mode_change_not_yet_applied_by_voice_asks_for_a_restart(control, tmp_path, monkeypatch):
    ready_probe(monkeypatch)
    await solo_owner(control)
    voice_publishes(tmp_path, authorization={**RUNTIME_REFUSAL, "conversation_mode": "open_room", "status": "ready"})

    assert (await authorization_of(control))["restart_required"] is True


def capture_report(**overrides) -> dict:
    report = {
        "echo_cancellation": {"requested": True, "active": True, "code": "aec_active"},
        "verifier": {"availability": "ready", "dropped_ms": 0},
        "speaker_verification": "shadow",
        "arch": "continuous_brain",
        "phase": "activation",
    }
    report.update(overrides)
    return report


async def test_the_verifier_worker_state_published_by_voice_is_shown(control, tmp_path, monkeypatch):
    ready_probe(monkeypatch)
    await save(control, arch="continuous_brain", authorization={"speaker_verification": "shadow"})
    voice_publishes(tmp_path, capture=capture_report(verifier={"availability": "ready", "dropped_ms": 300}))

    authorization = await authorization_of(control)

    assert authorization["worker"]["availability"] == "ready"
    assert authorization["worker"]["dropped_ms"] == 300
    assert authorization["worker"]["phase"] == "activation"
    assert (authorization["status"], authorization["status_source"]) == ("ready", "settings")


@pytest.mark.parametrize("verifier", [None, {"availability": "failed", "dropped_ms": 0}])
async def test_shadow_measuring_nothing_in_voice_is_degraded_from_the_voice_report(control, tmp_path, monkeypatch, verifier):
    ready_probe(monkeypatch)
    await save(control, arch="continuous_brain", authorization={"speaker_verification": "shadow"})
    voice_publishes(tmp_path, capture=capture_report(verifier=verifier))

    authorization = await authorization_of(control)

    assert (authorization["status"], authorization["code"], authorization["status_source"]) == (
        "degraded", "speaker_verification_unavailable", "voice",
    )
    assert "rien n'est mesuré" in authorization["problem"]


async def test_a_voice_report_for_other_settings_is_not_taken_for_the_current_state(control, tmp_path, monkeypatch):
    ready_probe(monkeypatch)
    await save(control, arch="continuous_brain", authorization={"speaker_verification": "shadow"})
    voice_publishes(tmp_path, capture=capture_report(verifier=None, speaker_verification="off"))

    authorization = await authorization_of(control)

    assert (authorization["status"], authorization["status_source"]) == ("ready", "settings")
    assert authorization["restart_required"] is True


async def test_a_malformed_voice_report_is_sanitized(control, tmp_path, monkeypatch):
    ready_probe(monkeypatch)
    await save(control, arch="continuous_brain")
    signals = voice_publishes(tmp_path)
    (tmp_path / VisualSignalBus.CAPTURE_FILE).write_text(
        json.dumps({
            "echo_cancellation": {"requested": "oui", "active": 1, "code": "x" * 500},
            "verifier": {"availability": "géniale", "dropped_ms": -5, "embedding": [0.1] * 192},
            "arch": ["continuous_brain"],
        }),
        encoding="utf-8",
    )
    del signals

    voice = await voice_of(control)

    assert voice["authorization"]["worker"] == {"availability": None, "dropped_ms": None, "phase": None, "ts": None}
    runtime = voice["echo_cancellation"]["runtime"]
    assert (runtime["requested"], runtime["active"], len(runtime["code"])) == (None, False, 64)
    assert not keys_and_lists(voice)["keys"] & BIOMETRIC_KEYS


# ===========================================================================
# Annulation d'écho : demandée, installée, appliquée
# ===========================================================================


def aec_installed(monkeypatch, installed: bool = True) -> None:
    monkeypatch.setattr(control_module, "echo_cancellation_installed", lambda: installed)


async def test_echo_cancellation_is_not_applicable_outside_the_continuous_conversation(control, monkeypatch):
    aec_installed(monkeypatch)

    aec = (await voice_of(control))["echo_cancellation"]

    assert (aec["status"], aec["code"], aec["applicable"], aec["configured"]) == (
        "not_applicable", "aec_not_applicable", False, True,
    )


async def test_echo_cancellation_ready_when_requested_and_installed(control, monkeypatch):
    aec_installed(monkeypatch)
    await save(control, arch="continuous_brain")

    aec = (await voice_of(control))["echo_cancellation"]

    assert (aec["status"], aec["code"], aec["problem"], aec["status_source"]) == ("ready", None, None, "settings")


async def test_echo_cancellation_requested_but_not_installed_is_degraded(control, monkeypatch):
    aec_installed(monkeypatch, False)
    await save(control, arch="continuous_brain")

    aec = (await voice_of(control))["echo_cancellation"]

    assert (aec["status"], aec["code"], aec["installed"]) == ("degraded", "aec_not_installed", False)
    assert "garde d'écho seule" in aec["problem"] and ".[voice]" in aec["problem"]


async def test_echo_cancellation_switched_off_is_said(control, monkeypatch):
    aec_installed(monkeypatch)
    await save(control, arch="continuous_brain", settings={"openai_realtime": {"echo_cancellation": False}})

    aec = (await voice_of(control))["echo_cancellation"]

    assert (aec["status"], aec["code"], aec["configured"]) == ("off", "aec_disabled", False)


@pytest.mark.parametrize(
    "runtime, status, code",
    [
        ({"requested": True, "active": True, "code": "aec_active"}, "ready", None),
        ({"requested": True, "active": False, "code": "aec_unavailable"}, "degraded", "aec_unavailable"),
        ({"requested": True, "active": False, "code": "aec_failed"}, "degraded", "aec_failed"),
        ({"requested": True, "active": False, "code": "duplex_capture_unavailable"}, "degraded", "duplex_capture_unavailable"),
    ],
)
async def test_what_voice_applied_wins_over_the_installation_probe(control, tmp_path, monkeypatch, runtime, status, code):
    aec_installed(monkeypatch)
    await save(control, arch="continuous_brain")
    voice_publishes(tmp_path, capture=capture_report(echo_cancellation=runtime, speaker_verification="off"))

    aec = (await voice_of(control))["echo_cancellation"]

    assert (aec["status"], aec["code"], aec["status_source"]) == (status, code, "voice")
    assert aec["runtime"]["code"] == runtime["code"] and aec["restart_required"] is False
    if status == "degraded":
        assert "dégradé" in aec["problem"]


async def test_a_voice_aec_report_for_another_request_waits_for_a_restart(control, tmp_path, monkeypatch):
    aec_installed(monkeypatch)
    await save(control, arch="continuous_brain")
    voice_publishes(
        tmp_path,
        capture=capture_report(echo_cancellation={"requested": False, "active": False, "code": "aec_disabled"}),
    )

    aec = (await voice_of(control))["echo_cancellation"]

    assert (aec["status"], aec["status_source"], aec["restart_required"]) == ("ready", "settings", True)


async def test_a_stale_voice_report_is_ignored(control, tmp_path, monkeypatch):
    aec_installed(monkeypatch)
    await save(control, arch="continuous_brain")
    signals = voice_publishes(tmp_path, capture=capture_report(echo_cancellation={"requested": True, "active": False, "code": "aec_failed"}))
    (tmp_path / ".voice_heartbeat").write_text("0\n", encoding="utf-8")
    del signals

    aec = (await voice_of(control))["echo_cancellation"]

    assert (aec["status"], aec["status_source"]) == ("ready", "settings") and "runtime" not in aec


def test_the_install_probe_never_loads_the_native_library():
    code = (
        "import sys; from jarvis.adapters.webrtc_echo import echo_cancellation_installed as f; "
        "r = f(); print(type(r).__name__, 'livekit.rtc' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60)

    assert result.stdout.split() == ["bool", "False"]


# ===========================================================================
# Côté Voice : ce qui est publié pour le Control Center
# ===========================================================================


class Journal:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})


class Observer:
    availability = VerifierAvailability.READY
    dropped_ms = 0


class Capture:
    def __init__(self, *, canceller: object | None = object(), observer: object | None = None) -> None:
        self.canceller = canceller
        self.canceller_failed = False
        self.observer = observer
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1


def voice_runtime(
    tmp_path,
    factory,
    *,
    echo_cancellation: bool | None = True,
    journal: Journal | None = None,
    voice_arch: VoiceArchitecture = VoiceArchitecture.CONTINUOUS_BRAIN,
    conversation_architecture: VoiceArchitectureId | None = None,
    configuration_id: str | None = None,
):
    return PersistentVoiceRuntime(
        wakeword=object(),
        core=object(),
        realtime_factory=lambda context: None,
        signals=VisualSignalBus(tmp_path),
        journal=journal,
        auto_turn=True,
        voice_arch=voice_arch,
        conversation_architecture=conversation_architecture,
        configuration_id=configuration_id,
        capture_factory=factory,
        authorization=ConversationAuthorization(ConversationMode.OPEN_ROOM, SpeakerVerificationMode.SHADOW),
        echo_cancellation=echo_cancellation,
    )


def published(tmp_path) -> dict:
    return json.loads((tmp_path / VisualSignalBus.CAPTURE_FILE).read_text(encoding="utf-8"))


def test_voice_publishes_the_capture_it_applies_at_each_activation(tmp_path):
    observer = Observer()
    runtime = voice_runtime(tmp_path, lambda: Capture(observer=observer))

    capture = runtime._duplex_capture()

    report = published(tmp_path)
    assert report["echo_cancellation"] == {"requested": True, "active": True, "code": "aec_active"}
    assert report["verifier"] == {"availability": "ready", "dropped_ms": 0}
    assert (report["speaker_verification"], report["arch"], report["phase"]) == ("shadow", "continuous_brain", "activation")
    assert capture.resets == 1


def test_explicit_voice_capture_publishes_its_configuration_identity_despite_legacy_operational_arch(tmp_path):
    runtime = voice_runtime(
        tmp_path,
        lambda: Capture(),
        voice_arch=VoiceArchitecture.LEGACY,
        conversation_architecture=VoiceArchitectureId.DUPLEX,
        configuration_id="c" * 64,
    )

    runtime._duplex_capture()

    report = published(tmp_path)
    assert report["arch"] == "legacy"
    assert report["architecture"] == "duplex"
    assert report["configuration_id"] == "c" * 64


def test_an_aec_failure_during_the_session_is_published_before_the_reset_and_traced_once(tmp_path):
    journal = Journal()
    observer = Observer()
    runtime = voice_runtime(tmp_path, lambda: Capture(observer=observer), journal=journal)
    capture = runtime._duplex_capture()
    capture.canceller_failed = True
    observer.availability = VerifierAvailability.FAILED
    observer.dropped_ms = 400

    runtime._end_capture_session()
    report = published(tmp_path)
    runtime._duplex_capture()
    runtime._end_capture_session()

    assert report["echo_cancellation"] == {"requested": True, "active": False, "code": "aec_failed"}
    assert report["verifier"] == {"availability": "failed", "dropped_ms": 400}
    assert report["phase"] == "session_end"
    failures = [item for item in journal.events if item["data"].get("code") == "duplex_aec_failed"]
    assert len(failures) == 1 and failures[0]["level"] == "warning"


@pytest.mark.parametrize("requested, code", [(True, "aec_unavailable"), (False, "aec_disabled")])
def test_a_capture_without_canceller_says_whether_it_was_requested(tmp_path, requested, code):
    runtime = voice_runtime(tmp_path, lambda: Capture(canceller=None), echo_cancellation=requested)

    runtime._duplex_capture()

    assert published(tmp_path)["echo_cancellation"] == {"requested": requested, "active": False, "code": code}
    assert published(tmp_path)["verifier"] is None


def test_a_failing_capture_factory_is_published_as_unavailable(tmp_path):
    def broken():
        raise RuntimeError("PortAudio")

    runtime = voice_runtime(tmp_path, broken)

    assert runtime._duplex_capture() is None
    assert published(tmp_path)["echo_cancellation"]["code"] == "duplex_capture_unavailable"


def test_voice_going_offline_clears_its_capture_report(tmp_path):
    signals = VisualSignalBus(tmp_path)
    signals.capture(capture_report())

    signals.offline()

    assert not (tmp_path / VisualSignalBus.CAPTURE_FILE).exists()


# ===========================================================================
# Page : structure et syntaxe
# ===========================================================================


def test_the_page_renders_the_solo_owner_and_aec_status_from_the_api():
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")

    for needle in (
        "async function authSectionHtml()",
        "function aecHtml()",
        "function authFieldChanged(el,revision)",
        "function voiceDiagnosticHtml(records)",
        "'owner_profile_path':((a.verifier_settings||{}).effective||{}).owner_profile_path",
        "verification_modes_by_mode",
        "a.status_source==='voice'",
        "Solo Owner configuré mais NON appliqué",
        "Solo Owner appliqué",
        "vérification en ombre",
        "Redémarrez Voice pour appliquer",
        "Réglages avancés — R&amp;D",
        "a.verifier_remedy",
        "lecture seule",
        "Mode dégradé",
        "authorization:{}",
    ):
        assert needle in html, needle
    diagnostic = html[html.index("function voiceDiagnosticHtml(records)") : html.index("function voiceCatalogHtml()")]
    assert "authVerdictHtml" not in diagnostic and "verifierHtml" not in diagnostic
    assert "authEffectiveHtml" not in diagnostic and "aecHtml" not in diagnostic
    # Aucune empreinte n'est lue ni affichée par la page.
    assert not re.search(r"embedding|voiceprint", html, re.I)


async def test_the_page_script_parses(control, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    # La page servie, logique pure insérée comprise : c'est elle que le
    # navigateur reçoit, et donc elle qui doit se lire.
    html = (await control.index(None)).text
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts
    script = tmp_path / "control_center.js"
    script.write_text("\n".join(scripts), encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stderr
