"""L'explorateur de variantes sur un faux DOM, par node (studio de présentation, Slice 18).

Le module testé est le VRAI `control_center_presentation_studio_explorer.js` (et son noyau pur) ; seuls le DOM, l'horloge, le réseau (un Core
minuscule : `tests/fakes/explorer_world.cjs`), le module plein écran et le runtime des prefabs sont des doubles. La preuve dans un vrai Chrome,
contre un vrai Core, est `test_presentation_studio_explorer_browser.py`.

Épinglé : ce que l'écran montre (arbre, aperçu, métadonnées, actions) et où le texte d'auteur peut aller (`textContent` seulement) ; la
navigation clavier de l'arbre ARIA ; l'aperçu qui LIT sans jamais écrire ; chaque action par le relais, relue ensuite ; le plan d'archivage et son
jeton (périmé, expiré, ensemble changé) ; chaque refus dit en français ; le plein écran armé ; l'ouverture refusée pendant une lecture ; Échap imbriqué.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui


def test_opening_draws_the_tree_the_preview_and_the_metadata_from_the_graph_of_core(tmp_path):
    out = run_ui(tmp_path, """
seed(8);
const {ex,result}=await opened();
const rows=rowsOf();
const mounted=prefabFake.mounts.slice(-1)[0];
return {result,numbers:numbers(),labels:rows.slice(0,3).map(r=>r.getAttribute('aria-label')),levels:rows.map(r=>r.getAttribute('aria-level')),
  selected:rows.map(r=>r.getAttribute('aria-selected')),active:rows.filter(r=>r.dataset.active==='true').map(r=>r.dataset.id.slice(-2)),
  num:rows[0].querySelector('.jvx-num').textContent,flag:rows[0].querySelector('.jvx-flag').textContent,
  header:q('.jvx-subtitle').textContent,mode:q('.jvx-top .jvx-chip').textContent,
  meta:q('.jvx-meta-title').textContent,facts:q('.jvx-facts').textContent,
  mounted:mounted&&{id:mounted.prefab.id,object:mounted.object_id,title:mounted.title},hostMode:prefabFake.hosts[0].mode,
  scenes:qa('.jvx-scene').length,sceneTitle:q('.jvx-scene-title').textContent,sceneCount:q('.jvx-stage-note > span').textContent,
  actions:qa('.jvx-actions .jvx-btn').map(b=>[b.dataset.act,b.getAttribute('aria-disabled')]),
  violations:doc.violations,errors:env.errors,state:ex.state(),role:host().getAttribute('role'),modal:host().getAttribute('aria-modal'),
  object:host().dataset.objectId,inertBody:doc.body.children.filter(n=>n.inert).length};
""")
    assert out["result"]["state"] == "opened" and out["result"]["mode"] == "fullscreen"
    assert out["numbers"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert out["labels"][0] == "Variante 1, Variante 1, active, 7 sous-branches"
    assert out["levels"] == ["1", "2", "3", "2", "3", "2", "3", "3"]
    assert out["selected"][0] == "true" and out["selected"][1:] == ["false"] * 7
    assert out["active"] == ["01"] and out["num"] == "#1" and out["flag"] == "Actif"
    assert "8 variantes" in out["header"] and "Atelier du cadran" in out["header"]
    assert out["mode"] == "Plein écran"
    assert "#1" in out["meta"] and "Racine de l'arbre" in out["facts"] and "3 scènes" in out["facts"]
    assert out["hostMode"] == "preview", "the preview frame is a host in preview mode: it posts nothing"
    assert out["mounted"] == {"id": "lab.dial", "object": "studio-explorer-preview", "title": "Scène 1 de 1"}
    assert out["scenes"] == 3 and out["sceneTitle"] == "Scène 1 de 1" and out["sceneCount"] == "Scène 1 sur 3"
    assert [a[0] for a in out["actions"]] == ["activate", "branch", "rename", "archive"] and out["actions"][0][1] == "true", "the active variant is already active"
    assert out["violations"] == [] and out["errors"] == []
    assert out["role"] == "dialog" and out["modal"] == "true" and out["object"] == "studio-explorer"
    assert out["state"]["selected"].endswith("1") and out["state"]["live"] == 8
