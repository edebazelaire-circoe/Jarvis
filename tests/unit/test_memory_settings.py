"""Memory settings persistence (Slice 10a): tolerant read, strict whole-request write.

Pure, no I/O: `settings` is the dict that `control-center-settings.json` holds.
Every refusal is asserted twice: the stable code, and that nothing was written.
"""

from __future__ import annotations

import copy
import json

import pytest

from jarvis.domain.memory_settings import ConsolidationMode, EmbeddingProviderId, MemorySettings
from jarvis.runtime import credentials
from jarvis.runtime.memory_settings import (
    SETTING_KEY,
    MemorySettingsError,
    apply_memory_settings,
    describe_memory_settings,
    effective_memory_settings,
    memory_state,
    read_memory_settings,
    stored_memory_settings,
    validate_memory_settings_write,
)

SENTINEL = "sk-SECRET-sentinel-9f3a"


def refused(payload, stored=None) -> str:
    with pytest.raises(MemorySettingsError) as caught:
        validate_memory_settings_write(payload, stored)
    return caught.value.code


# ------------------------------------------------------------------- defaults


@pytest.mark.parametrize("raw", [None, {}, [], "x", 3, {"recall": None}])
def test_defaults_when_block_missing_or_garbage(raw):
    assert read_memory_settings(raw, {}) == MemorySettings()


def test_default_values_match_architecture():
    settings = read_memory_settings({}, {})
    assert (settings.recall.enabled, settings.recall.max_items, settings.recall.timeout_ms) == (True, 6, 400)
    assert settings.semantic.enabled is False and settings.semantic.provider is EmbeddingProviderId.NONE
    assert settings.consolidation.mode is ConsolidationMode.MANUAL
    assert settings.tencent.enabled is False
    assert settings.knowledge.wiki_enabled and settings.knowledge.codegraph_enabled and settings.knowledge.skills_enabled


# ----------------------------------------------------------------- round trip


def test_round_trip_through_json_file():
    settings: dict = {"other": 1}
    payload = {
        "recall": {"max_items": 3, "timeout_ms": 900},
        "semantic": {"enabled": True, "provider": "openai", "allow_private": True},
        "consolidation": {"mode": "auto", "auto_min_confidence": 0.9, "max_candidates_per_run": 5},
        "tencent": {"enabled": True, "url": "https://tencent.example:8443/v1"},
        "knowledge": {"skills_enabled": False},
    }
    written = apply_memory_settings(settings, payload)
    on_disk = json.loads(json.dumps(settings))
    assert on_disk["other"] == 1
    assert read_memory_settings(on_disk[SETTING_KEY], {}) == written
    assert written.recall.max_items == 3 and written.consolidation.mode is ConsolidationMode.AUTO
    assert written.knowledge.skills_enabled is False and written.knowledge.wiki_enabled is True
    assert isinstance(on_disk[SETTING_KEY]["semantic"]["provider"], str)


def test_write_is_a_patch_over_stored_values():
    settings: dict = {}
    apply_memory_settings(settings, {"recall": {"max_items": 4}})
    apply_memory_settings(settings, {"recall": {"timeout_ms": 200}})
    result = read_memory_settings(settings[SETTING_KEY], {})
    assert (result.recall.max_items, result.recall.timeout_ms) == (4, 200)


# ----------------------------------------------------------- env precedence


def test_env_beats_file_beats_default():
    block = {"recall": {"max_items": 3, "timeout_ms": 800}}
    env = {"JARVIS_MEMORY_RECALL_MAX_ITEMS": "9"}
    settings = read_memory_settings(block, env)
    assert settings.recall.max_items == 9  # env
    assert settings.recall.timeout_ms == 800  # file
    assert settings.recall.enabled is True  # default
    sources = {path: item["source"] for path, item in effective_memory_settings(block, env).items()}
    assert sources["recall.max_items"] == "env"
    assert sources["recall.timeout_ms"] == "file"
    assert sources["recall.enabled"] == "default"


def test_env_parses_each_kind_and_empty_means_unset():
    env = {
        "JARVIS_MEMORY_RECALL_ENABLED": "off",
        "JARVIS_MEMORY_SEMANTIC_ENABLED": "TRUE",
        "JARVIS_MEMORY_SEMANTIC_PROVIDER": "openai",
        "JARVIS_MEMORY_CONSOLIDATION_AUTO_MIN_CONFIDENCE": "0.5",
        "JARVIS_MEMORY_TENCENT_URL": "http://localhost:9000",
        "JARVIS_MEMORY_RECALL_MAX_ITEMS": "  ",
    }
    result = read_memory_settings({"recall": {"max_items": 2}}, env)
    assert result.recall.enabled is False and result.semantic.enabled is True
    assert result.semantic.provider is EmbeddingProviderId.OPENAI
    assert result.consolidation.auto_min_confidence == 0.5
    assert result.tencent.url == "http://localhost:9000"
    assert result.recall.max_items == 2


@pytest.mark.parametrize(
    "name,value",
    [
        ("JARVIS_MEMORY_RECALL_MAX_ITEMS", "11"),
        ("JARVIS_MEMORY_RECALL_MAX_ITEMS", "six"),
        ("JARVIS_MEMORY_RECALL_ENABLED", "maybe"),
        ("JARVIS_MEMORY_SEMANTIC_PROVIDER", "nope"),
        ("JARVIS_MEMORY_CONSOLIDATION_AUTO_MIN_CONFIDENCE", "nan"),
    ],
)
def test_bad_env_is_ignored_and_file_value_survives(name, value):
    block = {"recall": {"max_items": 3}, "consolidation": {"auto_min_confidence": 0.7}}
    result = read_memory_settings(block, {name: value})
    assert result.recall.max_items == 3
    assert result.consolidation.auto_min_confidence == 0.7
    assert result.recall.enabled is True


def test_env_never_leaks_into_the_stored_view_or_a_write():
    env = {"JARVIS_MEMORY_RECALL_MAX_ITEMS": "9"}
    block = {"recall": {"max_items": 3}}
    assert stored_memory_settings(block).recall.max_items == 3
    settings = {SETTING_KEY: block}
    apply_memory_settings(settings, {"recall": {"timeout_ms": 500}})
    assert settings[SETTING_KEY]["recall"]["max_items"] == 3
    assert read_memory_settings(settings[SETTING_KEY], env).recall.max_items == 9


def test_env_default_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_RECALL_TIMEOUT_MS", "1500")
    assert read_memory_settings({}).recall.timeout_ms == 1500


def test_env_incoherent_combination_is_downgraded_not_raised():
    env = {"JARVIS_MEMORY_CONSOLIDATION_MODE": "auto"}
    result = read_memory_settings({}, env)
    assert result.consolidation.mode is ConsolidationMode.MANUAL
    entry = effective_memory_settings({}, env)["consolidation.mode"]
    assert entry["downgraded"] == "memory_settings_auto_needs_semantic"


# --------------------------------------------------------- tolerant read


def test_corrupt_values_fall_back_field_by_field():
    block = {
        "recall": {"enabled": "yes", "max_items": 99, "timeout_ms": 400.5},
        "semantic": {"provider": "zzz", "allow_private": 1},
        "consolidation": {"mode": ["auto"], "auto_min_confidence": float("nan")},
        "tencent": {"url": 12},
        "knowledge": "broken",
        "future_section": {"x": 1},
    }
    assert read_memory_settings(block, {}) == MemorySettings()


def test_valid_neighbours_of_a_corrupt_field_are_kept():
    block = {"recall": {"max_items": "many", "timeout_ms": 700}}
    assert read_memory_settings(block, {}).recall.timeout_ms == 700


@pytest.mark.parametrize(
    "block,check",
    [
        ({"semantic": {"enabled": True, "provider": "none"}}, lambda s: s.semantic.enabled is False),
        (
            {"semantic": {"enabled": True, "provider": "openai"}, "consolidation": {"mode": "auto"}},
            lambda s: s.consolidation.mode is ConsolidationMode.AUTO,
        ),
        ({"consolidation": {"mode": "auto"}}, lambda s: s.consolidation.mode is ConsolidationMode.MANUAL),
        ({"tencent": {"enabled": True, "url": ""}}, lambda s: s.tencent.enabled is False),
        ({"tencent": {"enabled": True, "url": "ftp://x"}}, lambda s: s.tencent.enabled is False),
    ],
)
def test_incoherent_file_is_degraded_never_raised(block, check):
    assert check(read_memory_settings(block, {}))


def test_degrading_semantic_also_degrades_auto_consolidation():
    block = {"semantic": {"enabled": True, "provider": "none"}, "consolidation": {"mode": "auto"}}
    result = read_memory_settings(block, {})
    assert result.semantic.enabled is False
    assert result.consolidation.mode is ConsolidationMode.MANUAL


# ------------------------------------------------------- strict write refusals


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"semantic": {"enabled": True}}, "memory_settings_semantic_needs_provider"),
        ({"semantic": {"enabled": True, "provider": "none"}}, "memory_settings_semantic_needs_provider"),
        ({"consolidation": {"mode": "auto"}}, "memory_settings_auto_needs_semantic"),
        ({"tencent": {"enabled": True}}, "memory_settings_tencent_needs_url"),
        ({"tencent": {"enabled": True, "url": "   "}}, "memory_settings_tencent_needs_url"),
        ("nope", "memory_settings_bad_payload"),
        (["recall"], "memory_settings_bad_payload"),
        (None, "memory_settings_bad_payload"),
        ({"recall": 3}, "memory_settings_bad_section"),
        ({"recall": None}, "memory_settings_bad_section"),
        ({"recall": {"enabled": "true"}}, "memory_settings_bad_type"),
        ({"recall": {"enabled": 1}}, "memory_settings_bad_type"),
        ({"recall": {"max_items": True}}, "memory_settings_bad_type"),
        ({"recall": {"max_items": 3.0}}, "memory_settings_bad_type"),
        ({"recall": {"max_items": "3"}}, "memory_settings_bad_type"),
        ({"recall": {"max_items": None}}, "memory_settings_bad_type"),
        ({"consolidation": {"auto_min_confidence": True}}, "memory_settings_bad_type"),
        ({"consolidation": {"auto_min_confidence": "0.5"}}, "memory_settings_bad_type"),
        ({"semantic": {"provider": 3}}, "memory_settings_bad_type"),
        ({"semantic": {"provider": "cohere"}}, "memory_settings_bad_enum"),
        ({"consolidation": {"mode": "AUTO"}}, "memory_settings_bad_enum"),
        ({"tencent": {"url": "localhost:9"}}, "memory_settings_bad_url"),
        ({"tencent": {"url": "ftp://host/x"}}, "memory_settings_bad_url"),
        ({"tencent": {"url": "http://host:notaport"}}, "memory_settings_bad_url"),
        ({"tencent": {"url": "https://user:pw@host/x"}}, "memory_settings_secret_refused"),
        ({"tencent": {"url": "https://user@host/x"}}, "memory_settings_secret_refused"),
        ({"tencent": {"url": "https://h/" + "a" * 600}}, "memory_settings_out_of_range"),
    ],
)
def test_invalid_write_is_refused_with_stable_code_and_no_partial_write(payload, code):
    settings = {SETTING_KEY: {"recall": {"max_items": 2}}, "keep": True}
    before = copy.deepcopy(settings)
    with pytest.raises(MemorySettingsError) as caught:
        apply_memory_settings(settings, payload)
    assert caught.value.code == code
    assert settings == before


def test_one_bad_field_refuses_the_whole_request_even_after_good_ones():
    settings: dict = {}
    payload = {"recall": {"max_items": 3}, "knowledge": {"wiki_enabled": False}, "semantic": {"enabled": True}}
    with pytest.raises(MemorySettingsError):
        apply_memory_settings(settings, payload)
    assert settings == {}


def test_combination_is_judged_on_the_merged_result():
    stored = {"semantic": {"enabled": True, "provider": "openai"}}
    assert validate_memory_settings_write({"consolidation": {"mode": "auto"}}, stored).consolidation.mode is ConsolidationMode.AUTO
    assert refused({"semantic": {"provider": "none"}}, stored) == "memory_settings_semantic_needs_provider"
    both = {"semantic": {"enabled": False, "provider": "none"}}
    assert refused({"consolidation": {"mode": "auto"}}, both) == "memory_settings_auto_needs_semantic"


def test_stored_incoherence_does_not_block_an_unrelated_write():
    stored = {"tencent": {"enabled": True, "url": ""}}
    assert validate_memory_settings_write({"recall": {"max_items": 2}}, stored).tencent.enabled is False


def test_error_message_never_echoes_the_offending_value():
    with pytest.raises(MemorySettingsError) as caught:
        validate_memory_settings_write({"tencent": {"url": f"https://u:{SENTINEL}@h/"}})
    assert SENTINEL not in str(caught.value)
    with pytest.raises(MemorySettingsError) as caught:
        validate_memory_settings_write({"semantic": {"provider": SENTINEL}})
    assert SENTINEL not in str(caught.value)


# ------------------------------------------------------------------- ranges


@pytest.mark.parametrize(
    "section,name,low,high",
    [
        ("recall", "max_items", 1, 10),
        ("recall", "timeout_ms", 100, 1500),
        ("consolidation", "max_candidates_per_run", 1, 100),
        ("consolidation", "auto_min_confidence", 0, 1),
    ],
)
def test_range_boundaries(section, name, low, high):
    assert getattr(validate_memory_settings_write({section: {name: low}}), section)
    assert getattr(validate_memory_settings_write({section: {name: high}}), section)
    step = 1 if name != "auto_min_confidence" else 0.001
    assert refused({section: {name: low - step}}) == "memory_settings_out_of_range"
    assert refused({section: {name: high + step}}) == "memory_settings_out_of_range"


def test_float_rejects_non_finite_and_int_is_accepted_as_float():
    assert refused({"consolidation": {"auto_min_confidence": float("nan")}}) == "memory_settings_out_of_range"
    assert refused({"consolidation": {"auto_min_confidence": float("inf")}}) == "memory_settings_out_of_range"
    assert validate_memory_settings_write({"consolidation": {"auto_min_confidence": 1}}).consolidation.auto_min_confidence == 1.0


def test_url_is_stripped_and_empty_is_valid_while_disabled():
    ok = validate_memory_settings_write({"tencent": {"enabled": True, "url": "  http://h:1/x  "}})
    assert ok.tencent.url == "http://h:1/x"
    assert validate_memory_settings_write({"tencent": {"url": ""}}).tencent.url == ""


# ------------------------------------------------------------- unknown keys


def test_unknown_keys_are_preserved_on_write():
    settings = {
        SETTING_KEY: {
            "future": {"deep": [1, 2]},
            "recall": {"max_items": 2, "future_field": "kept"},
        }
    }
    apply_memory_settings(settings, {"recall": {"timeout_ms": 300}, "newer_top": 1, "knowledge": {"x_new": True}})
    block = settings[SETTING_KEY]
    assert block["future"] == {"deep": [1, 2]}
    assert block["recall"]["future_field"] == "kept"
    assert block["recall"]["max_items"] == 2 and block["recall"]["timeout_ms"] == 300
    assert block["newer_top"] == 1
    assert block["knowledge"]["x_new"] is True


def test_unknown_keys_survive_a_corrupt_known_field_rewrite():
    settings = {SETTING_KEY: {"recall": {"max_items": "bad", "future_field": 1}}}
    apply_memory_settings(settings, {"knowledge": {"wiki_enabled": False}})
    assert settings[SETTING_KEY]["recall"]["future_field"] == 1
    assert settings[SETTING_KEY]["recall"]["max_items"] == 6


def test_unrelated_settings_keys_are_never_touched():
    settings = {"agent_routing": {"enabled": True}, "x": [1]}
    snapshot = copy.deepcopy(settings)
    apply_memory_settings(settings, {"recall": {"max_items": 2}})
    assert {k: v for k, v in settings.items() if k != SETTING_KEY} == snapshot


# ------------------------------------------------------------------ secrets


@pytest.mark.parametrize(
    "payload",
    [
        {"tencent": {"token": SENTINEL}},
        {"tencent": {"api_key": SENTINEL}},
        {"semantic": {"apiKey": SENTINEL}},
        {"semantic": {"openai_api_key": SENTINEL}},
        {"password": SENTINEL},
        {"future": {"nested": {"Secret": SENTINEL}}},
        {"tencent": {"Authorization_Bearer": SENTINEL}},
    ],
)
def test_secret_looking_keys_are_refused_and_never_stored(payload):
    settings: dict = {}
    with pytest.raises(MemorySettingsError) as caught:
        apply_memory_settings(settings, payload)
    assert caught.value.code == "memory_settings_secret_refused"
    assert SENTINEL not in str(caught.value) and SENTINEL not in json.dumps(settings)


def test_has_secret_is_accepted_from_a_round_trip_but_never_written():
    settings: dict = {}
    apply_memory_settings(settings, {"has_secret": True, "tencent": {"has_secret": True, "url": "http://h"}})
    assert "has_secret" not in json.dumps(settings)


def test_secret_never_appears_in_any_payload_and_has_secret_reports_presence():
    settings: dict = {}
    credentials.upsert_credential(settings, provider="openai", name="main", value=SENTINEL)
    credentials.upsert_credential(settings, provider="tencent", name="side", value=SENTINEL + "-t")
    apply_memory_settings(
        settings,
        {"semantic": {"enabled": True, "provider": "openai"}, "tencent": {"enabled": True, "url": "https://t.example"}},
    )
    state = memory_state(settings, {})
    assert state["secrets"] == {"semantic": {"has_secret": True}, "tencent": {"has_secret": True}}
    memory_block = json.dumps(settings[SETTING_KEY])
    everything = json.dumps([state, describe_memory_settings(), memory_block])
    assert SENTINEL not in everything


def test_has_secret_false_without_credential_and_true_from_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_TENCENT_TOKEN", raising=False)
    assert memory_state({}, {})["secrets"] == {"semantic": {"has_secret": False}, "tencent": {"has_secret": False}}
    monkeypatch.setenv("JARVIS_TENCENT_TOKEN", SENTINEL)
    state = memory_state({}, {})
    assert state["secrets"]["tencent"] == {"has_secret": True}
    assert SENTINEL not in json.dumps(state)


# ---------------------------------------------------------------- description


def test_description_is_server_driven_and_matches_the_validators():
    schema = describe_memory_settings()
    by_path = {f["path"]: f for s in schema["sections"] for f in s["fields"]}
    assert by_path["recall.max_items"]["min"] == 1 and by_path["recall.max_items"]["max"] == 10
    assert by_path["recall.timeout_ms"]["min"] == 100 and by_path["recall.timeout_ms"]["max"] == 1500
    assert by_path["recall.max_items"]["default"] == 6 and by_path["recall.timeout_ms"]["default"] == 400
    assert [o["id"] for o in by_path["semantic.provider"]["options"]] == ["none", "openai"]
    assert [o["id"] for o in by_path["consolidation.mode"]["options"]] == ["manual", "auto"]
    assert by_path["semantic.provider"]["default"] == "none"
    assert by_path["tencent.url"]["env"] == "JARVIS_MEMORY_TENCENT_URL"
    assert [c["code"] for c in schema["compatibility"]] == [
        "memory_settings_semantic_needs_provider",
        "memory_settings_auto_needs_semantic",
        "memory_settings_tencent_needs_url",
    ]
    assert schema["precedence"] == ["env", "file", "default"]
    json.dumps(schema)


def test_every_described_default_and_option_is_accepted_by_the_validator():
    schema = describe_memory_settings()
    for section in schema["sections"]:
        for field in section["fields"]:
            validate_memory_settings_write({section["id"]: {field["id"]: field["default"]}})
            for option in field.get("options", ()):
                if option["id"] in ("openai", "auto"):  # alone, these need the semantic leg: see the matrix tests
                    continue
                validate_memory_settings_write({section["id"]: {field["id"]: option["id"]}})


def test_describe_covers_every_dataclass_field():
    from dataclasses import fields

    schema = describe_memory_settings()
    described = {(s["id"], f["id"]) for s in schema["sections"] for f in s["fields"]}
    settings = MemorySettings()
    expected = {(f.name, g.name) for f in fields(settings) for g in fields(getattr(settings, f.name))}
    assert described == expected


def test_memory_state_effective_reports_sources():
    settings = {SETTING_KEY: {"recall": {"max_items": 3}}}
    state = memory_state(settings, {"JARVIS_MEMORY_RECALL_TIMEOUT_MS": "700"})
    assert state["values"]["recall.max_items"] == 3 and state["values"]["recall.timeout_ms"] == 400
    assert state["effective"]["recall.timeout_ms"] == {"value": 700, "source": "env"}
    assert state["effective"]["recall.max_items"] == {"value": 3, "source": "file"}
    assert state["effective"]["recall.enabled"] == {"value": True, "source": "default"}
