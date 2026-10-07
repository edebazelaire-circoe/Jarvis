"""Bloc de réglages `wake_word` : défauts sûrs, lecture tolérante, écriture stricte.

Le bloc est lu, pas encore consommé (Slices 04-05) : ces tests tiennent le
contrat du module seul, sans Core, sans micro, sans base.
"""

from __future__ import annotations

import copy
import json

import pytest

from jarvis.adapters import wakeword_model_catalog as catalog
from jarvis.runtime import wake_word_settings as ww
from jarvis.runtime.wake_word_settings import WakeWordSettingsError


def refused(settings, payload) -> str:
    with pytest.raises(WakeWordSettingsError) as caught:
        ww.apply(settings, payload)
    return caught.value.code


# --------------------------------------------------------------- défauts


def test_absent_block_means_disabled_with_safe_defaults():
    loaded = ww.load({})

    assert loaded.enabled is False
    assert loaded.provider == "porcupine"
    assert loaded.keyword == "jarvis"
    assert loaded.sensitivity == 0.5
    assert loaded.cooldown_ms == 2000
    seen = ww.inspect({})
    assert seen["present"] is False and seen["unreadable"] is False and seen["problems"] == []
    described = ww.describe({})
    assert described["enabled"] is False
    assert "inactif" in described["state"].lower()


def test_the_default_keyword_follows_the_provider():
    assert ww.default_keyword("porcupine") == "jarvis"
    assert ww.default_keyword("openwakeword") == "hey_jarvis"
    assert ww.load({"wake_word": {"schema_version": 1, "provider": "openwakeword"}}).keyword == "hey_jarvis"


def test_the_openwakeword_keywords_are_the_detectors_of_the_model_catalog():
    detectors = tuple(m.key for m in catalog.MODELS if m.key not in {"melspectrogram", "embedding"})
    assert ww.OPENWAKEWORD_KEYWORDS == detectors


def test_the_block_never_renames_existing_keys():
    assert ww.SETTING_KEY == "wake_word"
    assert ww.SCHEMA_VERSION == 1
    assert "manual_wake_key" not in ww.FIELDS and "wake_toggle" not in ww.FIELDS
    assert ww.FIELDS == ("enabled", "provider", "keyword", "sensitivity", "cooldown_ms")


# ------------------------------------------------------ lecture tolérante


@pytest.mark.parametrize("stored", ["oui", 3, ["enabled"], None, True])
def test_malformed_block_falls_back_without_raising(stored):
    settings = {"wake_word": stored}

    loaded = ww.load(settings)

    assert loaded == ww.defaults()
    assert loaded.enabled is False
    ww.describe(settings)  # ne lève pas non plus


@pytest.mark.parametrize("version", [0, 2, 99, "x", [1], True])
def test_unknown_schema_version_falls_back_and_says_so(version):
    settings = {"wake_word": {"schema_version": version, "enabled": True, "sensitivity": 0.9}}

    assert ww.load(settings) == ww.defaults()
    seen = ww.inspect(settings)
    assert seen["unreadable"] is True
    assert {p["code"] for p in seen["problems"]} == {"wake_word_stored_version_unreadable"}
    assert ww.describe(settings)["unreadable"] is True


@pytest.mark.parametrize(
    "field, value",
    [
        ("enabled", "yes"), ("enabled", 1), ("provider", "alexa"), ("provider", 3),
        ("keyword", 5), ("keyword", "Not A Token!"), ("keyword", "jarvis"),  # jarvis n'existe pas pour openwakeword
        ("sensitivity", 1.5), ("sensitivity", -0.1), ("sensitivity", "high"), ("sensitivity", True),
        ("cooldown_ms", 10), ("cooldown_ms", 10**9), ("cooldown_ms", 2000.5), ("cooldown_ms", "2s"),
    ],
)
def test_an_invalid_stored_field_makes_the_whole_block_fall_back_and_names_the_field(field, value):
    block = {"schema_version": 1, "enabled": True, "provider": "openwakeword", "keyword": "hey_jarvis"}
    block[field] = value
    settings = {"wake_word": block}

    loaded = ww.load(settings)

    assert loaded == ww.defaults(), "un bloc qu'on ne sait pas lire n'active jamais le micro"
    problems = ww.inspect(settings)["problems"]
    assert [p["field"] for p in problems] == [field]
    assert ww.describe(settings)["problems"] == problems


def test_unknown_stored_keys_are_ignored_but_reported():
    settings = {"wake_word": {"schema_version": 1, "enabled": True, "mystery": 1}}

    loaded = ww.load(settings)

    assert loaded.enabled is True
    assert ww.inspect(settings)["ignored_fields"] == ["mystery"]


def test_a_missing_version_is_read_as_ours():
    assert ww.load({"wake_word": {"enabled": True}}).enabled is True


def test_a_valid_stored_block_is_read_back():
    stored = {"schema_version": 1, "enabled": True, "provider": "openwakeword", "keyword": "hey_jarvis",
              "sensitivity": 0.8, "cooldown_ms": 3000}

    loaded = ww.load({"wake_word": stored})

    assert (loaded.enabled, loaded.provider, loaded.keyword, loaded.sensitivity, loaded.cooldown_ms) == (
        True, "openwakeword", "hey_jarvis", 0.8, 3000)


# ------------------------------------------------------- écriture stricte


def test_apply_writes_the_full_block_into_the_mapping_only():
    settings = {"manual_wake_key": "f9"}

    result = ww.apply(settings, {"enabled": True, "provider": "openwakeword", "sensitivity": 0.7})

    assert settings["wake_word"] == {
        "schema_version": 1, "enabled": True, "provider": "openwakeword", "keyword": "hey_jarvis",
        "sensitivity": 0.7, "cooldown_ms": 2000,
    }
    assert result == ww.load(settings)


def test_apply_merges_over_the_current_block():
    settings = {}
    ww.apply(settings, {"enabled": True, "provider": "openwakeword", "cooldown_ms": 4000})

    ww.apply(settings, {"sensitivity": 0.9})

    assert settings["wake_word"]["enabled"] is True and settings["wake_word"]["cooldown_ms"] == 4000
    assert settings["wake_word"]["sensitivity"] == 0.9
    assert settings["wake_word"]["keyword"] == "hey_jarvis"


def test_changing_the_provider_without_a_keyword_resets_the_keyword_to_the_provider_default():
    settings = {}
    ww.apply(settings, {"provider": "openwakeword"})

    ww.apply(settings, {"provider": "porcupine"})

    assert settings["wake_word"]["keyword"] == "jarvis"


def test_apply_refuses_unknown_field():
    assert refused({}, {"enabled": True, "modelPath": "x"}) == "wake_word_unknown_field"


def test_apply_refuses_a_payload_that_is_not_an_object():
    assert refused({}, ["enabled"]) == "wake_word_bad_payload"
    assert refused({}, None) == "wake_word_bad_payload"


def test_apply_refuses_a_foreign_schema_version():
    assert refused({}, {"schema_version": 2, "enabled": True}) == "wake_word_schema_version_unsupported"
    assert refused({}, {"schema_version": "1"}) == "wake_word_schema_version_unsupported"


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"enabled": "true"}, "wake_word_enabled_invalid"),
        ({"enabled": 1}, "wake_word_enabled_invalid"),
        ({"provider": 7}, "wake_word_provider_invalid"),
        ({"keyword": 7}, "wake_word_keyword_invalid"),
        ({"sensitivity": "0.5"}, "wake_word_sensitivity_invalid"),
        ({"sensitivity": True}, "wake_word_sensitivity_invalid"),
        ({"sensitivity": float("nan")}, "wake_word_sensitivity_invalid"),
        ({"cooldown_ms": "2000"}, "wake_word_cooldown_invalid"),
        ({"cooldown_ms": 2000.5}, "wake_word_cooldown_invalid"),
        ({"cooldown_ms": True}, "wake_word_cooldown_invalid"),
    ],
)
def test_apply_refuses_wrong_types(payload, code):
    assert refused({}, payload) == code


@pytest.mark.parametrize("value", [-0.01, 1.01, 2, -1])
def test_apply_refuses_out_of_range_sensitivity(value):
    assert refused({}, {"sensitivity": value}) == "wake_word_sensitivity_out_of_range"


def test_the_sensitivity_bounds_are_inclusive():
    for value in (0, 1, 0.0, 1.0):
        ww.apply({}, {"sensitivity": value})


@pytest.mark.parametrize("value", [ww.COOLDOWN_MS_MIN - 1, ww.COOLDOWN_MS_MAX + 1, 0, -5])
def test_apply_refuses_out_of_range_cooldown(value):
    assert refused({}, {"cooldown_ms": value}) == "wake_word_cooldown_out_of_range"


def test_the_cooldown_bounds_are_documented_and_inclusive():
    assert (ww.COOLDOWN_MS_MIN, ww.COOLDOWN_MS_MAX) == (80, 30000)
    for value in (ww.COOLDOWN_MS_MIN, ww.COOLDOWN_MS_MAX):
        ww.apply({}, {"cooldown_ms": value})


def test_apply_refuses_unknown_provider():
    assert refused({}, {"provider": "alexa"}) == "wake_word_provider_unknown"
    assert refused({}, {"provider": "OpenWakeWord"}) == "wake_word_provider_unknown"


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "openwakeword", "keyword": "jarvis"},          # mot Porcupine, pas un modèle openWakeWord
        {"provider": "openwakeword", "keyword": "melspectrogram"},  # pré-traitement, pas un mot
        {"provider": "porcupine", "keyword": "hey_jarvis"},         # pas un jeton Porcupine valide
        {"keyword": "../etc/passwd"}, {"keyword": ""}, {"keyword": "Jarvis"}, {"keyword": "a" * 80},
    ],
)
def test_apply_refuses_an_unknown_keyword_by_token(payload):
    assert refused({}, payload) == "wake_word_keyword_unknown"


def test_a_refusal_leaves_the_mapping_untouched():
    settings = {"wake_word": {"schema_version": 1, "enabled": True}, "x": 1}
    before = copy.deepcopy(settings)

    for payload in ({"sensitivity": 5}, {"zzz": 1}, {"enabled": "no"}, {"provider": "x"}):
        refused(settings, payload)

    assert settings == before


def test_apply_replaces_an_unreadable_stored_block_by_a_clean_one():
    settings = {"wake_word": {"schema_version": 9, "enabled": True, "weird": 1}}

    ww.apply(settings, {"enabled": False})

    assert settings["wake_word"]["schema_version"] == 1 and "weird" not in settings["wake_word"]
    assert settings["wake_word"]["enabled"] is False


def test_apply_preserves_other_keys():
    settings = {"manual_wake_key": "f9", "shortcuts": {"wake_toggle": "f8"}, "interaction_mode": {"mode": "assistant"},
                "secrets": {"openai": "sk-keep"}}
    others = copy.deepcopy(settings)

    ww.apply(settings, {"enabled": True})

    assert {k: v for k, v in settings.items() if k != "wake_word"} == others


# ---------------------------------------------------------------- describe


def test_describe_says_the_effective_state_and_that_voice_must_restart():
    settings = {}
    ww.apply(settings, {"enabled": True, "provider": "openwakeword"})

    described = ww.describe(settings)

    assert described["restart_required"] is True
    assert "redémarrage de Voice" in described["restart_message"]
    assert "actif" in described["state"].lower() and "openwakeword" in described["state"]
    assert described["schema_version"] == 1
    assert described["bounds"]["sensitivity"] == {"min": 0, "max": 1}
    assert described["bounds"]["cooldown_ms"] == {"min": 80, "max": 30000}
    assert described["providers"]["porcupine"]["default_keyword"] == "jarvis"
    assert described["providers"]["openwakeword"]["keywords"] == ["hey_jarvis"]
    json.dumps(described)  # sérialisable tel quel


def test_describe_of_a_disabled_block_says_the_current_behaviour_is_unchanged():
    described = ww.describe({"wake_word": {"schema_version": 1, "enabled": False}})

    assert described["enabled"] is False
    assert "inchangé" in described["state"]
