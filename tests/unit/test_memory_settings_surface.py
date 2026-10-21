"""Destinations des champs mémoire dans les Réglages à six catégories (jarvis-settings-ui-reorganization, Slice 05).

Le serveur décrit, pour chaque champ du schéma mémoire, l'unique section qui l'édite (`surface`). Ce fichier échoue dès
qu'un champ n'a pas de destination, qu'une destination n'est pas enregistrée par la page, ou que la table de
`docs/settings/memory.md` ne dit plus la vérité.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from jarvis.runtime import memory_settings
from jarvis.runtime.memory_settings import SURFACE_CATEGORY, SURFACE_SECTIONS, describe_memory_settings

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
DOC = ROOT / "docs" / "settings" / "memory.md"


def served_fields() -> dict[str, dict]:
    return {field["path"]: field["surface"] for section in describe_memory_settings()["sections"] for field in section["fields"]}


def test_every_field_has_exactly_one_known_destination():
    fields = served_fields()
    assert len(fields) == len(memory_settings._FIELDS)
    for path, surface in fields.items():
        assert surface == {"category": SURFACE_CATEGORY, "section": surface["section"]}, path
        assert surface["section"] in SURFACE_SECTIONS, path
    # Chaque section de champs reçoit au moins un champ ; le sidecar Tencent vit avec les sources de connaissances.
    assert {s["section"] for s in fields.values()} == set(SURFACE_SECTIONS)
    assert {p for p, s in fields.items() if p.startswith("tencent.")} == {
        p for p, s in fields.items() if p.startswith("tencent.") and s["section"] == "knowledge_sources"}
    assert describe_memory_settings()["loadouts"]["surface"] == {"category": SURFACE_CATEGORY, "section": "knowledge_sources"}


def test_a_section_without_destination_fails_loudly(monkeypatch):
    monkeypatch.delitem(memory_settings._SURFACE, "consolidation")
    with pytest.raises(RuntimeError, match="without settings destination: consolidation"):
        describe_memory_settings()


def test_every_destination_is_registered_by_the_page():
    page = PAGE.read_text(encoding="utf-8")
    block = page[page.index("const MEMORY_SECTIONS=[") : page.index("function memorySettingsStore()")]
    registered = set(re.findall(r"\{id:'([a-z_]+)',category:'memory_knowledge'", block))
    assert set(SURFACE_SECTIONS) | {"memory_center"} == registered


def test_the_documented_table_matches_the_server():
    doc = DOC.read_text(encoding="utf-8")
    table = doc[doc.index("| Champ | Section |") :]
    table = table[: table.index("\n\n")]
    rows = dict(re.findall(r"^\| `([a-z_.]+)`(?: \(lecture seule\))? \| `([a-z_]+)` · ", table, re.M))
    expected = {path: surface["section"] for path, surface in served_fields().items()}
    expected["loadouts"] = describe_memory_settings()["loadouts"]["surface"]["section"]
    assert rows == expected
