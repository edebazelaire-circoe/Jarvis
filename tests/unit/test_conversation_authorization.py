"""Autorisation de conversation : qui peut parler à JARVIS (Solo Owner, tâche 01).

Ce qui est prouvé ici, c'est le contrat, pas un comportement vocal : un fichier
de réglages antérieur rend exactement le comportement d'avant, chaque valeur
invalide ou combinaison incohérente est refusée avec un code et un message en
clair, et un Solo Owner inapplicable est dit tel quel plutôt que simulé.
"""

from __future__ import annotations

import json

from aiohttp import web
import pytest

from jarvis.domain.speaker import (
    DEFAULT_OWNER_BUFFER_MS,
    MAX_OWNER_BUFFER_MS,
    MIN_OWNER_BUFFER_MS,
    AuthorizationStatus,
    ConversationAuthorization,
    ConversationAuthorizationError,
    ConversationMode,
    SpeakerVerificationMode,
    VerifierAvailability,
    assess_authorization,
)
from jarvis.runtime.control_center import ControlCenter
from jarvis.v2_config import (
    VoiceArchitecture,
    conversation_authorization_settings,
    parse_conversation_authorization,
)

OPEN_ROOM = ConversationMode.OPEN_ROOM
SOLO_OWNER = ConversationMode.SOLO_OWNER
OFF = SpeakerVerificationMode.OFF
SHADOW = SpeakerVerificationMode.SHADOW
ENFORCE = SpeakerVerificationMode.ENFORCE

VALID = (
    ConversationAuthorization(),
    ConversationAuthorization(OPEN_ROOM, SHADOW, MIN_OWNER_BUFFER_MS),
    ConversationAuthorization(SOLO_OWNER, ENFORCE, MAX_OWNER_BUFFER_MS),
)

# Un fichier de réglages tel que l'écrit la version précédente, sans secret.
PREVIOUS_SETTINGS_FILE = {
    "active_timeout_s": "90",
    "agent_cli": "claude",
    "manual_wake_key": "f9",
    "realtime_voice": "cedar",
    "voice_arch": "continuous_brain",
    "voice_stack": "openai_realtime",
    "voice_stack_settings": {"openai_realtime": {"echo_cancellation": True, "vad_type": "semantic_vad"}},
    "voice_turn_mode": "auto",
}


def refused(settings: dict) -> ConversationAuthorizationError:
    with pytest.raises(ConversationAuthorizationError) as caught:
        parse_conversation_authorization(settings)
    return caught.value


# ===========================================================================
# Lecture des réglages
# ===========================================================================


@pytest.mark.parametrize(
    "settings",
    [
        {},
        PREVIOUS_SETTINGS_FILE,
        {"conversation_mode": "", "speaker_verification": "", "owner_buffer_ms": ""},
        {"conversation_mode": None, "speaker_verification": None, "owner_buffer_ms": None},
    ],
)
def test_absent_settings_give_the_current_behaviour(settings):
    authorization = parse_conversation_authorization(settings)

    assert authorization == ConversationAuthorization()
    assert (authorization.mode, authorization.verification, authorization.owner_buffer_ms) == (
        OPEN_ROOM, OFF, DEFAULT_OWNER_BUFFER_MS
    )
    assert authorization.owner_enforced is False


@pytest.mark.parametrize("authorization", VALID)
def test_the_settings_form_round_trips_through_the_file(authorization):
    written = json.loads(json.dumps(conversation_authorization_settings(authorization)))

    assert parse_conversation_authorization(written) == authorization


def test_values_are_normalised_and_the_buffer_accepts_integral_numbers():
    authorization = parse_conversation_authorization(
        {"conversation_mode": " Solo_Owner ", "speaker_verification": "ENFORCE", "owner_buffer_ms": "3000"}
    )
    assert authorization == ConversationAuthorization(SOLO_OWNER, ENFORCE, 3000)
    assert parse_conversation_authorization({"owner_buffer_ms": 1500.0}).owner_buffer_ms == 1500


def test_verification_follows_the_mode_when_it_is_not_chosen():
    assert parse_conversation_authorization({"conversation_mode": "solo_owner"}).verification is ENFORCE
    assert parse_conversation_authorization({"conversation_mode": "open_room"}).verification is OFF


def test_conversation_mode_does_not_overload_the_voice_architecture():
    assert not {item.value for item in ConversationMode} & {item.value for item in VoiceArchitecture}
    # `voice_arch` n'est pas lu : l'autorisation ne dépend pas de l'architecture.
    assert parse_conversation_authorization({"voice_arch": "solo_owner"}) == ConversationAuthorization()


@pytest.mark.parametrize(
    "settings, code, fragment",
    [
        ({"conversation_mode": "solo"}, "conversation_mode_unknown", "« solo »"),
        ({"speaker_verification": "strict"}, "speaker_verification_unknown", "off, shadow, enforce"),
        ({"owner_buffer_ms": "abc"}, "owner_buffer_not_an_integer", "« abc »"),
        ({"owner_buffer_ms": True}, "owner_buffer_not_an_integer", "nombre entier"),
        ({"owner_buffer_ms": 2500.5}, "owner_buffer_not_an_integer", "nombre entier"),
        ({"owner_buffer_ms": "nan"}, "owner_buffer_not_an_integer", "nombre entier"),
        ({"owner_buffer_ms": "inf"}, "owner_buffer_not_an_integer", "nombre entier"),
        ({"owner_buffer_ms": [2500]}, "owner_buffer_not_an_integer", "nombre entier"),
        ({"owner_buffer_ms": 499}, "owner_buffer_out_of_range", "entre 500 et 5000 ms"),
        ({"owner_buffer_ms": "5001"}, "owner_buffer_out_of_range", "reçu 5001"),
        ({"owner_buffer_ms": 0}, "owner_buffer_out_of_range", "entre 500 et 5000 ms"),
    ],
)
def test_invalid_values_are_refused_with_a_code_and_a_readable_message(settings, code, fragment):
    error = refused(settings)

    assert error.code == code
    assert fragment in str(error)


@pytest.mark.parametrize("verification", ["off", "shadow"])
def test_solo_owner_without_enforced_verification_is_refused(verification):
    error = refused({"conversation_mode": "solo_owner", "speaker_verification": verification})

    assert error.code == "solo_owner_requires_enforce"
    assert f"« {verification} »" in str(error)
    assert "shadow" in str(error), "le message doit indiquer le chemin de mesure"


def test_enforced_verification_in_an_open_room_is_refused():
    error = refused({"speaker_verification": "enforce"})

    assert error.code == "enforce_requires_solo_owner"
    assert "solo_owner" in str(error)


def test_an_incoherent_authorization_cannot_be_built_in_code_either():
    with pytest.raises(ConversationAuthorizationError):
        ConversationAuthorization(SOLO_OWNER, OFF)
    with pytest.raises(ConversationAuthorizationError):
        ConversationAuthorization(OPEN_ROOM, ENFORCE)
    with pytest.raises(ConversationAuthorizationError):
        ConversationAuthorization(owner_buffer_ms=MAX_OWNER_BUFFER_MS + 1)
    with pytest.raises(TypeError):
        ConversationAuthorization(mode="solo_owner")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ConversationAuthorization(owner_buffer_ms=True)


# ===========================================================================
# Ce qui s'applique réellement
# ===========================================================================


@pytest.mark.parametrize("verifier", list(VerifierAvailability))
def test_the_open_room_without_verifier_is_always_ready(verifier):
    assessment = assess_authorization(ConversationAuthorization(), verifier)

    assert assessment.status is AuthorizationStatus.READY
    assert (assessment.code, assessment.message) == ("", "")


@pytest.mark.parametrize("authorization", VALID[1:])
def test_a_ready_verifier_applies_the_authorization_as_configured(authorization):
    assessment = assess_authorization(authorization, VerifierAvailability.READY)

    assert assessment.status is AuthorizationStatus.READY
    assert assessment.authorization is authorization


@pytest.mark.parametrize(
    "verifier, reason",
    [
        (VerifierAvailability.NOT_INSTALLED, "aucun vérificateur"),
        (VerifierAvailability.NO_OWNER_PROFILE, "aucune voix de propriétaire"),
        (VerifierAvailability.FAILED, "en panne"),
    ],
)
def test_solo_owner_is_refused_rather_than_pretended_when_the_verifier_is_missing(verifier, reason):
    assessment = assess_authorization(ConversationAuthorization(SOLO_OWNER, ENFORCE), verifier)

    assert assessment.status is AuthorizationStatus.REFUSED
    assert assessment.code == "solo_owner_unavailable"
    assert reason in assessment.message
    assert "ne fera pas semblant" in assessment.message


def test_shadow_observation_without_verifier_degrades_but_keeps_the_open_room():
    assessment = assess_authorization(
        ConversationAuthorization(OPEN_ROOM, SHADOW), VerifierAvailability.NOT_INSTALLED
    )

    assert assessment.status is AuthorizationStatus.DEGRADED
    assert assessment.code == "speaker_verification_unavailable"
    assert "comme avant" in assessment.message


# ===========================================================================
# Control Center : description, enregistrement, refus
# ===========================================================================


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def authorization_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_settings(None)).text)["voice"]["authorization"]


def stored_settings(tmp_path) -> dict:
    return json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))


async def save_authorization(control: ControlCenter, **values) -> None:
    await control.save_settings(JsonRequest({"voice": {"authorization": values}}))


async def test_the_screen_describes_the_current_behaviour_by_default(control):
    authorization = await authorization_of(control)

    assert authorization["stored"] == {"conversation_mode": "", "speaker_verification": "", "owner_buffer_ms": ""}
    assert authorization["effective"] == {
        "conversation_mode": "open_room", "speaker_verification": "off", "owner_buffer_ms": 2500,
    }
    assert (authorization["status"], authorization["problem"]) == ("ready", None)
    assert authorization["conversation_modes"] == ["open_room", "solo_owner"]
    assert authorization["verification_modes"] == ["off", "shadow", "enforce"]
    assert authorization["owner_buffer_ms_bounds"] == {"default": 2500, "min": 500, "max": 5000}


async def test_a_previous_settings_file_stays_valid_and_is_not_rewritten(control, tmp_path):
    path = tmp_path / "control-center-settings.json"
    path.write_text(json.dumps(PREVIOUS_SETTINGS_FILE), encoding="utf-8")

    authorization = await authorization_of(control)

    assert authorization["effective"]["conversation_mode"] == "open_room"
    assert authorization["status"] == "ready"
    assert json.loads(path.read_text(encoding="utf-8")) == PREVIOUS_SETTINGS_FILE


async def test_solo_owner_is_persisted_and_reported_as_not_applicable(control, tmp_path):
    # Tâche 07 : sous `legacy` (défaut ici), la première raison dite serait l'architecture.
    await control.save_settings(JsonRequest({"voice": {"arch": "continuous_brain"}}))
    await save_authorization(control, conversation_mode="solo_owner", owner_buffer_ms="3000")

    stored = stored_settings(tmp_path)
    assert (stored["conversation_mode"], stored["owner_buffer_ms"]) == ("solo_owner", 3000)
    # La vérification n'a pas été choisie : elle suit le mode, rien n'est figé.
    assert "speaker_verification" not in stored
    authorization = await authorization_of(control)
    assert authorization["effective"]["speaker_verification"] == "enforce"
    # Aucun vérificateur n'existe encore : le dire, ne pas faire semblant.
    assert (authorization["status"], authorization["code"]) == ("refused", "solo_owner_unavailable")
    assert "aucun vérificateur" in authorization["problem"]


async def test_an_emptied_value_goes_back_to_its_default(control, tmp_path):
    await save_authorization(control, conversation_mode="solo_owner", owner_buffer_ms=4000)
    await save_authorization(control, conversation_mode="", owner_buffer_ms="")

    stored = stored_settings(tmp_path)
    assert "conversation_mode" not in stored and "owner_buffer_ms" not in stored
    assert (await authorization_of(control))["effective"]["conversation_mode"] == "open_room"


async def test_leaving_solo_owner_does_not_leave_an_incoherent_verification_behind(control):
    await save_authorization(control, conversation_mode="solo_owner")
    await save_authorization(control, conversation_mode="open_room")

    authorization = await authorization_of(control)
    assert authorization["effective"]["speaker_verification"] == "off"
    assert authorization["status"] == "ready"


async def test_shadow_observation_is_stored_and_flagged_as_degraded(control, tmp_path):
    await save_authorization(control, speaker_verification=" Shadow ")

    assert stored_settings(tmp_path)["speaker_verification"] == "shadow"
    authorization = await authorization_of(control)
    assert (authorization["status"], authorization["code"]) == ("degraded", "speaker_verification_unavailable")


@pytest.mark.parametrize(
    "values, fragment",
    [
        ({"conversation_mode": "salle"}, "Mode de conversation inconnu"),
        ({"speaker_verification": "always"}, "Mode de vérification du locuteur inconnu"),
        ({"owner_buffer_ms": 100}, "entre 500 et 5000 ms"),
        ({"owner_buffer_ms": "deux"}, "nombre entier"),
        ({"conversation_mode": "solo_owner", "speaker_verification": "off"}, "« enforce »"),
        ({"conversation_mode": "solo_owner", "speaker_verification": "shadow"}, "« enforce »"),
        ({"speaker_verification": "enforce"}, "n'a de sens qu'en mode solo_owner"),
    ],
)
async def test_an_invalid_authorization_is_refused_and_nothing_is_written(control, tmp_path, values, fragment):
    with pytest.raises(web.HTTPBadRequest) as refusal:
        await save_authorization(control, **values)

    assert fragment in refusal.value.text
    assert not (tmp_path / "control-center-settings.json").exists()


async def test_a_combination_is_checked_against_what_is_already_stored(control, tmp_path):
    await save_authorization(control, speaker_verification="shadow")

    with pytest.raises(web.HTTPBadRequest):
        await save_authorization(control, conversation_mode="solo_owner")

    assert "conversation_mode" not in stored_settings(tmp_path)


async def test_a_hand_written_invalid_value_is_flagged_without_blocking_other_settings(control, tmp_path):
    (tmp_path / "control-center-settings.json").write_text(
        json.dumps({"conversation_mode": "solo_owner", "speaker_verification": "off"}), encoding="utf-8"
    )

    authorization = await authorization_of(control)
    assert (authorization["status"], authorization["code"]) == ("invalid", "solo_owner_requires_enforce")
    assert authorization["effective"] is None

    await control.save_settings(JsonRequest({"voice": {"settings": {"openai_realtime": {"voice": "ash"}}}}))
    assert stored_settings(tmp_path)["realtime_voice"] == "ash"
    # Un client qui renvoie la description reçue ne touche à aucune clé.
    await control.save_settings(JsonRequest({"voice": {"authorization": authorization}}))
    assert stored_settings(tmp_path)["speaker_verification"] == "off"


async def test_authorization_and_voice_architecture_are_stored_independently(control, tmp_path):
    await save_authorization(control, conversation_mode="solo_owner")
    await control.save_settings(JsonRequest({"voice": {"arch": "continuous_brain"}}))

    stored = stored_settings(tmp_path)
    assert (stored["voice_arch"], stored["conversation_mode"]) == ("continuous_brain", "solo_owner")
    voice = json.loads((await control.get_settings(None)).text)["voice"]
    assert voice["arch_effective"] == "continuous_brain"
    assert voice["authorization"]["effective"]["conversation_mode"] == "solo_owner"
