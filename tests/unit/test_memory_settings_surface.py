"""Destinations des champs mémoire dans les Réglages à six catégories (jarvis-settings-ui-reorganization, Slice 05 ;
refonte-ui-settings, Slices 05/06 : onglets Mémoire / Connaissances / Memory Center, réglages d'opérateur dans Avancé).

Le serveur décrit, pour chaque champ du schéma mémoire, l'unique section qui l'édite (`surface`). Ce fichier échoue dès
qu'un champ n'a pas de destination, qu'une destination n'est pas enregistrée par la page, ou que la table de
`docs/settings/memory.md` ne dit plus la vérité.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from jarvis.runtime import memory_settings
from jarvis.runtime.memory_settings import ADVANCED_CATEGORY, SURFACE_CATEGORY, SURFACE_SECTIONS, describe_memory_settings

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
DOC = ROOT / "docs" / "settings" / "memory.md"


def served_fields() -> dict[str, dict]:
    return {field["path"]: field["surface"] for section in describe_memory_settings()["sections"] for field in section["fields"]}


def test_every_field_has_exactly_one_known_destination():
    fields = served_fields()
    assert len(fields) == len(memory_settings._FIELDS)
    for path, surface in fields.items():
        assert surface["section"] in SURFACE_SECTIONS, path
        assert surface == {"category": SURFACE_SECTIONS[surface["section"]], "section": surface["section"]}, path
    # Chaque section de champs reçoit au moins un champ.
    assert {s["section"] for s in fields.values()} == set(SURFACE_SECTIONS)
    # Onglet Mémoire : rappel, recherche sémantique, consolidation — sauf le délai brut, réglage d'opérateur.
    ordinary = {p for p in fields if p.split(".")[0] in ("recall", "semantic", "consolidation")} - {"recall.timeout_ms"}
    assert {p for p, s in fields.items() if s["section"] == "recall"} == ordinary
    # Le délai brut et le sidecar Tencent vivent dans Avancé & diagnostic, jamais sur la page ordinaire.
    assert {p for p, s in fields.items() if s["section"] == "memory_advanced"} == {
        "recall.timeout_ms", *(p for p in fields if p.startswith("tencent."))}
    assert {s["category"] for s in fields.values() if s["section"] == "memory_advanced"} == {ADVANCED_CATEGORY}
    assert describe_memory_settings()["loadouts"]["surface"] == {"category": SURFACE_CATEGORY, "section": "knowledge_sources"}


def test_option_labels_are_served_in_product_language():
    """Fournisseurs et modes : libellés servis (`none` / OpenAI seulement), l'interface n'en code aucun."""
    options = {f["path"]: f["options"] for s in describe_memory_settings()["sections"] for f in s["fields"] if f["type"] == "enum"}
    assert options["semantic.provider"] == [{"id": "none", "label": "Aucun"}, {"id": "openai", "label": "OpenAI"}]
    assert options["consolidation.mode"] == [{"id": "manual", "label": "Manuelle"}, {"id": "auto", "label": "Automatique"}]


def test_a_section_without_destination_fails_loudly(monkeypatch):
    monkeypatch.delitem(memory_settings._SURFACE, "consolidation")
    with pytest.raises(RuntimeError, match="without settings destination: consolidation"):
        describe_memory_settings()


def test_every_destination_is_registered_by_the_page():
    page = PAGE.read_text(encoding="utf-8")
    block = page[page.index("const MEMORY_SECTIONS=[") : page.index("function memorySettingsStore()")]
    registered = dict(re.findall(r"\{id:'([a-z_]+)',category:'([a-z_]+)'", block))
    assert {section: registered.get(section) for section in SURFACE_SECTIONS} == SURFACE_SECTIONS
    assert set(registered) == set(SURFACE_SECTIONS) | {"memory_center"}


def test_the_documented_table_matches_the_server():
    doc = DOC.read_text(encoding="utf-8")
    table = doc[doc.index("| Champ | Section |") :]
    table = table[: table.index("\n\n")]
    rows = dict(re.findall(r"^\| `([a-z_.]+)`(?: \(lecture seule\))? \| `([a-z_]+)` · ", table, re.M))
    expected = {path: surface["section"] for path, surface in served_fields().items()}
    expected["loadouts"] = describe_memory_settings()["loadouts"]["surface"]["section"]
    assert rows == expected
