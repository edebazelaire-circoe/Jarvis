# -*- coding: utf-8 -*-
"""Les deux tests qui epinglaient le bouton flottant epinglent desormais la
section de l'onglet Apparence."""
from pathlib import Path

BASE = Path(r"D:\Projects\CIRCOE\Jarvis")

# ---------------------------------------------------------------- view prefs
p = BASE / "tests/unit/test_scene_view_prefs.py"
s = p.read_text(encoding="utf-8")

OLD = '''def test_the_button_lives_in_the_scene_and_the_storage_can_always_fail():
    page = PAGE_JS.read_text(encoding="utf-8")
    # Bouton et fen\u00eatre sont pos\u00e9s dans le conteneur de sc\u00e8ne : l'interrupteur
    # de la sc\u00e8ne les emporte avec elle (`teardown`).
    assert "root.append(viewBtn,viewEl);" in page
    assert "viewBtn=null;viewEl=null;viewRows=[];" in page
    # Stockage refus\u00e9 (navigation priv\u00e9e) : les d\u00e9fauts, sans erreur \u00e0 l'\u00e9cran.
    assert "try{text=window.localStorage.getItem(V.KEY)}catch(_error)" in page
    assert "catch(error){consoleLog('warn','scene.view_not_saved'" in page
    # Un autre onglet r\u00e8gle l'affichage : le m\u00eame \u00e9cran partout.
    assert "window.addEventListener('storage',onViewStorage);" in page
    assert "window.removeEventListener('storage',onViewStorage);" in page
    # Dialogue nomm\u00e9, repli\u00e9 par d\u00e9faut, ferm\u00e9 par \u00c9chap et par un clic ailleurs.
    assert "viewEl.setAttribute('role','dialog');" in page
    assert "viewBtn.setAttribute('aria-expanded','false');" in page
    assert "if(viewEl&&!viewEl.hidden&&(!target||!target.closest('.sc-view,.sc-view-btn')))toggleViewPanel(false);" in page
    # La sc\u00e8ne absente de la page (module non ins\u00e9r\u00e9) ne casse rien.
    assert "const V=window.JarvisSceneView||null;" in page
    assert "if(V){viewPrefs=loadViewPrefs();buildViewControls();applyViewPrefs()}" in page
    # Le r\u00e9glage n'est jamais envoy\u00e9 \u00e0 Core : aucune requ\u00eate dans ce branchement.
    block = page.split("affichage r\u00e9gl\u00e9 par l'utilisateur")[1].split("function ensureRoot(")[0]
    for forbidden in ("fetch(", "requestJson", "/api/"):
        assert forbidden not in block, forbidden'''

NEW = '''def test_the_settings_live_in_the_appearance_tab_and_the_storage_can_always_fail():
    """Demande du 20/09/2026 : \u00ab toute cette partie-l\u00e0, d\u00e9plac\u00e9e dans les
    settings \u203a Apparence \u00bb.

    Le bouton flottant en bas \u00e0 droite de la sc\u00e8ne et sa fen\u00eatre n'existent
    plus : les r\u00e9glages sont une section de l'onglet Apparence, sous la version
    Cosmos. Ce test \u00e9pingle ce d\u00e9m\u00e9nagement \u2014 y compris ce qu'il a fallu
    d\u00e9crocher de la sc\u00e8ne pour que la section tienne debout sans elle."""

    page = PAGE_JS.read_text(encoding="utf-8")
    # Plus rien du bouton ni de la fen\u00eatre flottante.
    for gone in ("viewBtn", "viewEl", "toggleViewPanel", "buildViewControls",
                 "sc-view-btn", "VIEW_STAR_PATH"):
        assert gone not in page, gone
    # La section est ajout\u00e9e au rendu de l'onglet Apparence, jamais ailleurs.
    assert "if(typeof SET!=='undefined'&&SET.open&&SET.tab==='appearance'){" in page
    assert "const baseRenderTab=renderTab;" in page
    assert "if(section)content.append(section);" in page
    assert "section.id='sceneViewSettings';" in page
    # Elle doit tenir sans la sc\u00e8ne : son style lui est propre, et la sc\u00e8ne
    # \u00e9teinte ne retire plus l'\u00e9coute qui la tient \u00e0 jour.
    assert "style.id='jarvisSceneViewStyle';" in page
    assert "window.addEventListener('storage',onViewStorage);" in page
    assert "window.removeEventListener('storage',onViewStorage);" not in page
    assert "if(!V||(event.key!==null&&event.key!==V.KEY))return;" in page
    # Et sans la r\u00e9gion vivante de la sc\u00e8ne, qui peut ne pas exister.
    assert "function announceView(text){" in page
    # On ne parle jamais \u00e0 une section jet\u00e9e avec le modal.
    assert "if(!viewSection||!viewSection.isConnected||!V)return;" in page
    # Stockage refus\u00e9 (navigation priv\u00e9e) : les d\u00e9fauts, sans erreur \u00e0 l'\u00e9cran.
    assert "try{text=window.localStorage.getItem(V.KEY)}catch(_error)" in page
    assert "catch(error){consoleLog('warn','scene.view_not_saved'" in page
    # La sc\u00e8ne absente de la page (module non ins\u00e9r\u00e9) ne casse rien.
    assert "const V=window.JarvisSceneView||null;" in page
    assert "if(V){viewPrefs=loadViewPrefs();applyViewPrefs()}" in page
    # Le r\u00e9glage n'est jamais envoy\u00e9 \u00e0 Core : aucune requ\u00eate dans ce branchement.
    block = page.split("affichage r\u00e9gl\u00e9 par l'utilisateur")[1].split("function ensureRoot(")[0]
    for forbidden in ("fetch(", "requestJson", "/api/"):
        assert forbidden not in block, forbidden
    # Les sept r\u00e9glages que la fen\u00eatre portait sont tous dans la section.
    view = VIEW_JS.read_text(encoding="utf-8")
    for field in ("'size'", "'halo'", "'breathe'", "'orbit'", "'spread'", "'speed'", "'links'"):
        assert f"id:{field}" in view, field
    assert "input.id=`scView_${field.id}`;" in page
    assert "element('button','sc-view-reset'" in page'''

assert s.count(OLD) == 1
s = s.replace(OLD, NEW)
p.write_text(s, encoding="utf-8")
print("test_scene_view_prefs.py mis a jour")

# ------------------------------------------------------------ renderer logic
q = BASE / "tests/unit/test_scene_renderer_logic.py"
t = q.read_text(encoding="utf-8")
OLD2 = '    assert "#sceneLayer .sc-node,.sc-view,.sc-view-btn,.sc-status,#ctxMenu,#confirmBack" in candidate'
NEW2 = '    assert "#sceneLayer .sc-node,.sc-status,#ctxMenu,#confirmBack" in candidate'
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)
q.write_text(t, encoding="utf-8")
print("test_scene_renderer_logic.py mis a jour")
