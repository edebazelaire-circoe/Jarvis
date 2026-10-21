"""Destinations des options Voix dans les Réglages à six catégories (jarvis-settings-ui-reorganization, Slice 03).

Le serveur décrit, pour chaque option de `voice.option_metadata`, l'unique section qui l'héberge (`surface`). Ce
fichier échoue dès qu'une option n'a pas de destination, qu'une destination n'est pas servie par la page, ou que la
table de correspondance de `docs/settings/voice-audio.md` ne dit plus la vérité.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from jarvis.runtime import voice_settings_schema
from jarvis.runtime.control_center import ControlCenter

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
WAKE = ROOT / "jarvis" / "runtime" / "control_center_wake_word.js"
DOC = ROOT / "docs" / "settings" / "voice-audio.md"
CATEGORIES = {"voice_audio", "agents_models", "memory_knowledge", "interface_interactions", "connections", "advanced_diagnostics"}


@pytest.fixture
def metadata(tmp_path, monkeypatch) -> list[dict]:
    for name in ("JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK"):
        monkeypatch.delenv(name, raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    return control._settings_payload(control._settings())["voice"]["option_metadata"]


def test_every_server_option_has_exactly_one_known_destination(metadata):
    assert len(metadata) == len(voice_settings_schema.PERSISTABLE_OPTION_IDS) + len(voice_settings_schema.DIAGNOSTIC_OPTION_IDS)
    for record in metadata:
        surface = record.get("surface")
        assert surface, f"option sans destination : {record['id']}"
        assert surface["section"] in voice_settings_schema.SURFACE_SECTIONS, record["id"]
        assert surface["category"] == voice_settings_schema.SURFACE_SECTIONS[surface["section"]] in CATEGORIES
    by_section: dict[str, list[str]] = {}
    for record in metadata:
        by_section.setdefault(record["surface"]["section"], []).append(record["id"])
    # Les quatre sections ordinaires de Voix & audio reçoivent toutes des options (le Mot d'éveil a sa propre route).
    for section in ("conversation", "voice_output", "microphone_sound", "turns_interruptions"):
        assert by_section.get(section), section


def test_architecture_compatibility_and_diagnostics_leave_the_ordinary_view(metadata):
    section = {record["id"]: record["surface"]["section"] for record in metadata}
    for option in ("architecture", "voice_stack", "voice_arch", "client_delegation", "brain_orchestration",
                   "speculative_deltas", "reasoning_effort", "owner_buffer_ms", "owner_threshold",
                   "owner_evidence_ms", "owner_short_evidence_ms", "owner_short_margin",
                   "openai.vad_eagerness", "openai.vad_threshold", "gemini.vad_start_sensitivity"):
        assert section[option] == "architecture_compat", option
    for option in (*voice_settings_schema.DIAGNOSTIC_OPTION_IDS, "owner_profile_path"):
        assert section[option] == "diagnostics", option
    for record in metadata:
        if record["readonly"] and record["persistence"] is None:
            assert record["surface"]["category"] == "advanced_diagnostics", record["id"]


def test_wake_shortcut_is_edited_in_shortcuts_and_only_shown_in_voice(metadata):
    wake = next(record for record in metadata if record["id"] == "wake_toggle")
    assert wake["surface"] == {"category": "interface_interactions", "section": "shortcuts", "context": ["turns_interruptions"]}
    assert [record["id"] for record in metadata if "context" in record["surface"]] == ["wake_toggle"]


def test_a_live_option_without_destination_fails_loudly(monkeypatch):
    monkeypatch.delitem(voice_settings_schema._SURFACE, "openai.voice")
    with pytest.raises(RuntimeError, match="without settings destination: openai.voice"):
        voice_settings_schema._surface("openai.voice")


def test_every_destination_is_served_by_the_page(metadata):
    """Une section décrite par le serveur est enregistrée par la page, ou servie par l'onglet hérité qui l'héberge
    encore (Raccourcis, jusqu'à la Slice 06)."""

    page = PAGE.read_text(encoding="utf-8")
    registered = set(re.findall(r"\{id:'([a-z_]+)',category:'[a-z_]+'", page[page.index("const VOICE_SECTIONS=[") : page.index("function voiceSectionSpec")]))
    registered |= set(re.findall(r"registerSettingsSection\(\{id:'([a-z_]+)'", page))
    registered |= set(re.findall(r"const DIAGNOSTICS_SECTION=\{id:'([a-z_]+)'", page))
    assert "registerSettingsSection(DIAGNOSTICS_SECTION);" in page
    registered |= set(re.findall(r"registerSettingsSection\(\{id:'([a-z_]+)'", WAKE.read_text(encoding="utf-8")))
    tabs = set(re.findall(r"\{id:'(\w+)'", page[page.index("\nconst TABS=[") : page.index("\nconst SET=")]))
    for record in metadata:
        section = record["surface"]["section"]
        assert section in registered or section in tabs, (record["id"], section)
        for shown in record["surface"].get("context", []):
            assert shown in registered, (record["id"], shown)
    assert {"conversation", "voice_output", "microphone_sound", "turns_interruptions", "wake_word",
            "architecture_compat", "diagnostics"} <= registered


def test_the_documented_mapping_is_the_server_mapping(metadata):
    rows = re.findall(r"^\| `([a-z_.]+)` \| `([a-z_]+)` › `([a-z_]+)` \|", DOC.read_text(encoding="utf-8"), re.M)
    documented = {option: (category, section) for option, category, section in rows}
    served = {record["id"]: (record["surface"]["category"], record["surface"]["section"]) for record in metadata}
    assert documented == served
