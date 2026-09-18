"""Réglages d'affichage de la constellation (handoff
jarvis-constellation-scene-runtime, Slice 12).

Le petit bouton « Affichage des étoiles » en bas à droite de la scène ouvre une
fenêtre qui règle la taille des étoiles, leur halo, la gravitation et les fils.
Ce sont des préférences de ce navigateur : rien ne part vers Core.

Prouvé sur le fichier même que la page reçoit :

- la logique pure (`control_center_scene_view.js`) exécutée avec node :
  normalisation de ce qui a été enregistré (valeurs hors plage, champs inconnus,
  stockage illisible), variables CSS, classes, options de la dérive orbitale ;
- son insertion dans la page servie, avant le rendu qui la lit ;
- les garanties statiques du branchement navigateur dans
  `control_center_scene_page.js` : le bouton vit dans le conteneur de scène (il
  disparaît donc avec elle), le stockage est protégé, la fenêtre est un dialogue
  nommé, et aucun texte n'entre par `innerHTML`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import pytest

from jarvis.runtime.control_center import (
    SCENE_PAGE_SCRIPT_MARKER,
    SCENE_VIEW_SCRIPT_MARKER,
    ControlCenter,
)

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
VIEW_JS = RUNTIME / "control_center_scene_view.js"
LAYOUT_JS = RUNTIME / "control_center_scene_layout.js"
PAGE_JS = RUNTIME / "control_center_scene_page.js"
PAGE_HTML = RUNTIME / "control_center.html"
_NODE = shutil.which("node")

#: Les réglages livrés : tout est à 1, tout est allumé.
DEFAULTS = {
    "size": 1,
    "halo": 1,
    "breathe": True,
    "orbit": True,
    "spread": 1,
    "speed": 1,
    "links": True,
}


def _node(expression: str) -> Any:
    if _NODE is None:
        pytest.skip("node absent")
    script = f"const V=require({json.dumps(str(VIEW_JS))});console.log(JSON.stringify({expression}))"
    result = subprocess.run([_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def normalize(value: Any) -> dict[str, Any]:
    return _node(f"V.normalize({json.dumps(value)})")


# --------------------------------------------------------------- logique pure


def test_the_defaults_are_the_reference_look_and_survive_anything_stored():
    assert normalize(None) == DEFAULTS
    assert _node("V.DEFAULTS") == DEFAULTS
    assert _node("V.isDefault(null)") is True

    # Champ inconnu ignoré, champ manquant repris au défaut.
    assert normalize({"size": 1.5, "inconnu": 12}) == {**DEFAULTS, "size": 1.5}
    # Valeurs hors plage ou illisibles : bornées, jamais une scène invisible.
    assert normalize({"size": 99})["size"] == 2.4
    assert normalize({"size": -4})["size"] == 0.6
    assert normalize({"size": "grand"})["size"] == 1
    assert normalize({"halo": -1})["halo"] == 0
    # Curseur arrondi à son pas : la fenêtre n'affiche jamais 1,37 ×.
    assert normalize({"size": 1.37})["size"] == 1.4
    assert normalize({"speed": 1.1})["speed"] == 1.0
    assert normalize({"orbit": "false"})["orbit"] is False
    assert normalize({"orbit": 0})["orbit"] is False
    assert normalize({"breathe": "oui"})["breathe"] is True


def test_what_was_stored_is_read_back_and_a_broken_store_falls_back():
    stored = _node('V.encode({size:1.5,orbit:false,inconnu:1})')
    assert json.loads(stored) == {"version": 1, "view": {**DEFAULTS, "size": 1.5, "orbit": False}}
    assert _node(f"V.decode({json.dumps(stored)})") == {**DEFAULTS, "size": 1.5, "orbit": False}
    # Stockage vide, illisible, ou d'une autre forme : les défauts, sans erreur.
    for text in ("", "{pas du json", "[]", "null", '{"view":"grand"}'):
        assert _node(f"V.decode({json.dumps(text)})") == DEFAULTS, text
    # Ancienne forme (les réglages à plat) : relue telle quelle.
    assert _node('V.decode(JSON.stringify({size:2}))') == {**DEFAULTS, "size": 2}


def test_the_look_is_only_css_variables_and_classes_on_the_scene():
    assert _node("V.cssVars(null)") == {"--sc-star-scale": "1", "--sc-halo-scale": "1"}
    assert _node("V.cssVars({size:1.5,halo:.4})") == {"--sc-star-scale": "1.5", "--sc-halo-scale": "0.4"}
    # Toutes les classes possibles sont annoncées : la page les retire avant de poser les bonnes.
    assert set(_node("V.CLASSES")) == {"sc-no-halo", "sc-still-halo", "sc-no-orbit", "sc-no-links"}
    assert _node("V.classes(null)") == []
    assert _node("V.classes({halo:0})") == ["sc-no-halo"]
    assert _node("V.classes({breathe:false})") == ["sc-still-halo"]
    assert _node("V.classes({links:false})") == ["sc-no-links"]
    assert set(_node("V.classes({halo:0,breathe:false,orbit:false,links:false})")) == {
        "sc-no-halo",
        "sc-still-halo",
        "sc-no-orbit",
        "sc-no-links",
    }


def test_gravity_off_means_no_drift_is_computed_at_all():
    # `null` : la page ne calcule aucune dérive (aucune animation ne tourne).
    assert _node("V.orbitOptions({orbit:false})") is None
    assert _node("V.orbitOptions(null)") == {"gain": 1, "rate": 1}
    assert _node("V.orbitOptions({spread:2,speed:.5})") == {"gain": 2, "rate": 0.5}


def test_a_setting_without_effect_is_greyed_but_never_forgotten():
    model = _node("V.describe({orbit:false,spread:2,halo:0,breathe:true})")
    rows = {row["field"]["id"]: row for row in model["rows"]}
    assert [row["field"]["id"] for row in model["rows"]] == list(DEFAULTS)
    # Gravitation éteinte : l'ampleur et la vitesse sont grisées, leur valeur gardée.
    assert rows["spread"]["enabled"] is False and rows["spread"]["value"] == 2
    assert rows["speed"]["enabled"] is False
    # Halo à zéro : sa respiration n'a plus de sens.
    assert rows["breathe"]["enabled"] is False
    assert rows["size"]["enabled"] is True
    # Ce que la fenêtre écrit à côté de chaque réglage.
    assert rows["halo"]["label"] == "éteint"
    assert rows["orbit"]["label"] == "éteint"
    assert rows["size"]["label"] == "1 ×"
    assert _node("V.describe({size:1.5}).rows[0].label") == "1,5 ×"
    # « Réinitialiser » ne s'allume que si quelque chose a été changé.
    assert model["custom"] is True and _node("V.describe(null).custom") is False


def test_every_setting_is_named_for_the_screen_reader():
    fields = _node("V.FIELDS")
    assert [f["id"] for f in fields] == list(DEFAULTS)
    for field in fields:
        assert field["label"] and field["hint"], field["id"]
        assert field["type"] in {"range", "toggle"}
        if field["type"] == "range":
            assert field["min"] < field["value"] <= field["max"] and field["step"] > 0
    assert _node("V.changeSentence(V.FIELDS[3],false)") == "Gravitation : éteint."


# ----------------------------------------------------- insertion dans la page


async def test_the_module_is_served_inside_the_page_before_the_rendering(tmp_path):
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert SCENE_VIEW_SCRIPT_MARKER in html
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    served = (await control.index(None)).text
    assert SCENE_VIEW_SCRIPT_MARKER not in served and SCENE_PAGE_SCRIPT_MARKER not in served
    source = VIEW_JS.read_text(encoding="utf-8")
    assert source in served
    # Le rendu lit `window.JarvisSceneView` : il est donc inséré avant lui.
    assert served.index(source) < served.index(PAGE_JS.read_text(encoding="utf-8"))
    # Aucune ressource externe : tout est dans la page.
    assert "control_center_scene_view.js" not in served


def test_the_pure_part_touches_neither_the_dom_nor_the_storage():
    code = re.sub(r"/\*.*?\*/", "", VIEW_JS.read_text(encoding="utf-8"), flags=re.S)
    for forbidden in ("document.", "window.", "fetch(", "localStorage", "addEventListener", "innerHTML"):
        assert forbidden not in code, forbidden


def test_the_button_lives_in_the_scene_and_the_storage_can_always_fail():
    page = PAGE_JS.read_text(encoding="utf-8")
    # Bouton et fenêtre sont posés dans le conteneur de scène : l'interrupteur
    # de la scène les emporte avec elle (`teardown`).
    assert "root.append(viewBtn,viewEl);" in page
    assert "viewBtn=null;viewEl=null;viewRows=[];" in page
    # Stockage refusé (navigation privée) : les défauts, sans erreur à l'écran.
    assert "try{text=window.localStorage.getItem(V.KEY)}catch(_error)" in page
    assert "catch(error){consoleLog('warn','scene.view_not_saved'" in page
    # Un autre onglet règle l'affichage : le même écran partout.
    assert "window.addEventListener('storage',onViewStorage);" in page
    assert "window.removeEventListener('storage',onViewStorage);" in page
    # Dialogue nommé, replié par défaut, fermé par Échap et par un clic ailleurs.
    assert "viewEl.setAttribute('role','dialog');" in page
    assert "viewBtn.setAttribute('aria-expanded','false');" in page
    assert "if(viewEl&&!viewEl.hidden&&(!target||!target.closest('.sc-view,.sc-view-btn')))toggleViewPanel(false);" in page
    # La scène absente de la page (module non inséré) ne casse rien.
    assert "const V=window.JarvisSceneView||null;" in page
    assert "if(V){viewPrefs=loadViewPrefs();buildViewControls();applyViewPrefs()}" in page
    # Le réglage n'est jamais envoyé à Core : aucune requête dans ce branchement.
    block = page.split("affichage réglé par l'utilisateur")[1].split("function ensureRoot(")[0]
    for forbidden in ("fetch(", "requestJson", "/api/"):
        assert forbidden not in block, forbidden
