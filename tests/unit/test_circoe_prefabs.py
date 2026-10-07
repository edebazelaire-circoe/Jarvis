"""Modèles soignés circoe.* (langage CX) : sources valides, compatibles, hygiéniques.

Les sources vivent dans `jarvis/prefabs/circoe/<id>/` ; elles sont publiées
dans la bibliothèque du poste par `prefab_save` (jamais sous `jarvis.*`). Le
rendu réel est prouvé par `scripts/prefab_preview.py` (captures dans
`docs/results/prefab-cx/`), ceci prouve le contrat : manifeste strict, exemple
valide, bornes, LF, comportement assemblé à jour, syntaxe JS, aucune
écriture HTML dynamique, la coquille CX présente.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.prefab import parse_bundle, validate_value
from scripts.circoe_assemble import BASE, assembled

SHELL = (BASE.parent / "runtime" / "shell.css").read_text(encoding="utf-8")
FOLDERS = sorted(path.parent for path in BASE.glob("*/manifest.json"))
IDS = [folder.name for folder in FOLDERS]


def load(folder: Path):
    files = {name: (folder / name).read_text(encoding="utf-8")
             for name in ("manifest.json", "template.html", "style.css", "behavior.js")}
    return files, parse_bundle(json.loads(files["manifest.json"]), files["template.html"],
                               files["style.css"], files["behavior.js"])


def test_the_four_models_exist():
    assert {"circoe.dashboard", "circoe.hero", "circoe.timeline", "circoe.metrics"} <= set(IDS)


@pytest.mark.parametrize("folder", FOLDERS, ids=IDS)
def test_each_model_is_a_valid_custom_prefab_with_a_valid_rich_sample(folder):
    files, bundle = load(folder)
    manifest = bundle.manifest
    assert manifest.prefab_id == folder.name and manifest.prefab_id.startswith("circoe.")
    assert not manifest.prefab_id.startswith("jarvis.")
    assert manifest.aliases and manifest.tags and manifest.description
    _, problems = validate_value(manifest.props, manifest.sample_props, "props")
    _, more = validate_value(manifest.data, manifest.sample_data, "data")
    assert problems + more == ()
    # L'instance vide (props par défaut) reste acceptée quand rien n'est requis.
    assert validate_value(manifest.props, {}, "props")[1] == ()
    assert len(json.dumps(manifest.sample_data).encode()) <= 16 * 1024


@pytest.mark.parametrize("folder", FOLDERS, ids=IDS)
def test_sources_are_lf_assembled_and_within_bounds(folder):
    for name in ("manifest.json", "template.html", "style.css", "behavior.js", "behavior.body.js"):
        assert b"\r" not in (folder / name).read_bytes(), f"{folder.name}/{name} must be LF"
    assert (folder / "behavior.js").read_text(encoding="utf-8") == assembled(folder), \
        "run: python scripts/circoe_assemble.py"
    files, _ = load(folder)
    assert len(files["template.html"].encode()) <= 32 * 1024
    assert len(files["style.css"].encode()) <= 32 * 1024
    assert len(files["behavior.js"].encode()) <= 64 * 1024


@pytest.mark.parametrize("folder", FOLDERS, ids=IDS)
def test_a_model_writes_no_html_and_composes_the_shared_cx_shell(folder):
    files, _ = load(folder)
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "fetch(", "XMLHttpRequest"):
        assert forbidden not in files["behavior.js"], forbidden
    assert 'class="cx ' in files["template.html"] and "cx-ambient" in files["template.html"]
    assert "prefers-reduced-motion" in SHELL and "CX_REDUCED" in files["behavior.js"]
    assert "http://" not in files["style.css"] and "https://" not in files["style.css"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node requis")
@pytest.mark.parametrize("folder", FOLDERS, ids=IDS)
def test_the_assembled_behavior_is_valid_javascript(folder, tmp_path):
    wrapped = tmp_path / "behavior.cjs"
    wrapped.write_text("(function(jarvis){\n" + (folder / "behavior.js").read_text(encoding="utf-8") + "\n});",
                       encoding="utf-8")
    result = subprocess.run(["node", "--check", str(wrapped)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_shell_ships_the_cx_language_and_respects_reduced_motion():
    for name in (".cx-page", ".cx-glass", ".cx-display", ".cx-pill", ".cx-btn", ".cx-rise", ".cx-ambient"):
        assert name in SHELL
    assert "backdrop-filter" in SHELL and "prefers-reduced-motion:reduce" in SHELL
    assert SHELL.rstrip().endswith("}")
    # La coupure du mouvement réduit reste la dernière règle : elle l'emporte sur toute animation CX.
    assert SHELL.rindex("prefers-reduced-motion:reduce") > SHELL.rindex(".cx-rise")


def test_dashboard_v2_keeps_the_v1_data_schema_and_events():
    manifest = json.loads((BASE / "circoe.dashboard" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["events"]) == {"item_done", "section_done", "section_toggled", "item_remind", "item_postpone",
                                       "item_open", "section_remind", "section_postpone"}
    assert {name: event["class"] for name, event in manifest["events"].items()} == {
        "item_done": "state", "section_done": "state", "section_toggled": "state", "item_remind": "notify",
        "item_postpone": "notify", "item_open": "notify", "section_remind": "notify", "section_postpone": "notify"}
    data = manifest["inputs"]["data"]
    assert data["required"] == ["sections", "items"]
    assert set(data["properties"]["items"]["items"]["properties"]) == {
        "id", "section", "title", "detail", "due", "accent", "done"}
    assert set(data["properties"]["sections"]["items"]["properties"]) == {"id", "title", "accent", "collapsed"}
    assert {"accent", "show_done"} <= set(manifest["inputs"]["props"]["properties"])
