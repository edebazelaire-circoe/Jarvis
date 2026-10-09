"""Bloc de réglages `wake_word` : défauts sûrs, lecture tolérante, écriture stricte.

Le bloc est consommé par Voice en PRESENTATION (Slice 04) et en SIMPLE
(Slice 05) : ces tests tiennent le contrat du module seul, sans Core, sans micro, sans base.
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


def test_apply_refuses_to_overwrite_a_block_written_by_a_foreign_schema_version():
    block = {"schema_version": 9, "enabled": True, "weird": 1}
    settings = {"wake_word": copy.deepcopy(block)}

    assert refused(settings, {"enabled": False}) == "wake_word_foreign_version"

    assert settings["wake_word"] == block


@pytest.mark.parametrize("version", [2, 9, "x", None, True, 1.5])
def test_apply_refuses_any_stored_block_whose_version_is_not_ours(version):
    settings = {"wake_word": {"schema_version": version, "enabled": True}}

    assert refused(settings, {"enabled": False}) == "wake_word_foreign_version"


def test_apply_still_replaces_a_malformed_block_that_is_not_a_foreign_version():
    settings = {"wake_word": "garbage"}

    ww.apply(settings, {"enabled": False})

    assert settings["wake_word"]["schema_version"] == 1


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


# ----------------------------------------- B1 : entiers démesurés, jamais d'exception

HUGE = 10**400


@pytest.mark.parametrize("field", ["sensitivity", "cooldown_ms"])
@pytest.mark.parametrize("value", [pytest.param(HUGE, id="huge"), pytest.param(-HUGE, id="neg-huge")])
def test_reading_a_giant_integer_falls_back_to_defaults_and_says_so(field, value):
    settings = {"wake_word": {"schema_version": 1, "enabled": True, field: value}}

    loaded = ww.load(settings)
    described = ww.describe(settings)
    seen = ww.inspect(settings)

    assert loaded == ww.defaults() and loaded.enabled is False
    assert described["enabled"] is False
    assert [p["code"] for p in seen["problems"]] == [f"wake_word_{field.split('_')[0]}_out_of_range"]
    json.dumps(described)
    assert all(len(p["message"]) < 300 for p in seen["problems"])


@pytest.mark.parametrize("field", ["sensitivity", "cooldown_ms"])
@pytest.mark.parametrize("value", [pytest.param(HUGE, id="huge"), pytest.param(-HUGE, id="neg-huge")])
def test_apply_refuses_a_giant_integer_with_the_out_of_range_code(field, value):
    settings = {"wake_word": {"schema_version": 1, "enabled": True}}
    before = copy.deepcopy(settings)

    assert refused(settings, {field: value}) == f"wake_word_{field.split('_')[0]}_out_of_range"

    assert settings == before


@pytest.mark.parametrize("field, code", [
    ("sensitivity", "wake_word_sensitivity_invalid"), ("cooldown_ms", "wake_word_cooldown_invalid")])
@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), "5", "1e400", [1], {"a": 1}, True])
def test_apply_refuses_non_finite_and_non_numeric_values_with_the_invalid_code(field, code, value):
    assert refused({}, {field: value}) == code


def test_json_1e400_parses_to_inf_and_is_refused_as_invalid_not_raised():
    payload = json.loads('{"sensitivity": 1e400}')

    assert refused({}, payload) == "wake_word_sensitivity_invalid"


# ------------------------------------------------------ P1 : fullmatch


@pytest.mark.parametrize("keyword", ["jarvis\n", "jarvis\n\n", "hey google\n", "\njarvis"])
def test_a_porcupine_keyword_with_a_newline_is_refused(keyword):
    assert refused({}, {"provider": "porcupine", "keyword": keyword}) == "wake_word_keyword_unknown"


def test_a_clean_porcupine_keyword_is_still_accepted():
    settings = {}
    ww.apply(settings, {"provider": "porcupine", "keyword": "hey google"})
    assert settings["wake_word"]["keyword"] == "hey google"


# ------------------------------------------------- honnêteté : quand le réglage s'applique


def test_describe_of_an_enabled_block_says_when_it_applies():
    """Slices 04-06 : le bloc est consommé en PRESENTATION et en SIMPLE.

    La formule « seulement là où le mot d'éveil configurable est câblé » est
    devenue fausse ; la phrase dit désormais la seule chose vraie et utile.
    """

    settings = {}
    ww.apply(settings, {"enabled": True})

    described = ww.describe(settings)

    for text in (described["state"], described["restart_message"]):
        assert "Réglage enregistré ; il ne s'applique qu'au prochain démarrage de Voice." in text
        assert "câblé" not in text
        assert "seulement là où" not in text
    assert "redémarrage de Voice" in described["restart_message"]
