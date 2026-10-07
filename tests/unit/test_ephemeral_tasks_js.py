"""Tâches éphémères, côté page : règle d'affichage, réglage local, scène, panneau Agents.

Le serveur dit `ephemeral` (voir `test_ephemeral_tasks.py`) ; la page décide de
ce qu'elle montre. Prouvé ici :

- la règle pure (`JarvisSceneView.ephemeralVisibility`), exécutée avec node :
  une éphémère en cours ou réussie s'efface après `EPHEMERAL_LINGER_MS` ;
  réglage éteint, elle ne s'affiche pas du tout ; un échec, un arrêt, une
  interruption ou un blocage ne sont JAMAIS masqués, quel que soit le réglage ;
- le réglage `showEphemeral` : défaut vrai, libellé français, stocké localement ;
- le modèle de vue de la scène : une étoile masquée n'est ni dessinée ni
  supprimée (la scène enregistrée ne bouge pas), le drapeau arrive au nœud ;
- le panneau Agents, dans un vrai Chrome (voir plus bas).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import pytest

from tests.unit.test_scene_renderer_logic import run_node
from tests.unit.test_scene_view_prefs import PAGE_HTML, PAGE_JS, VIEW_JS

NODE = shutil.which("node")


def _node(expression: str) -> Any:
    if NODE is None:
        pytest.skip("node absent")
    script = f"const V=require({json.dumps(str(VIEW_JS))});console.log(JSON.stringify({expression}))"
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def visibility(settings: Any, work: Any, now: int) -> dict[str, Any]:
    return _node(f"V.ephemeralVisibility({json.dumps(settings)},{json.dumps(work)},{now})")


NOW = 1_000_000


@pytest.fixture
def LINGER():
    return _node("V.EPHEMERAL_LINGER_MS")


def work(status: str, *, ephemeral: bool = True, ended_ago: int | None = None) -> dict[str, Any]:
    ended = None if ended_ago is None else NOW - ended_ago
    return {"ephemeral": ephemeral, "status": status, "ended_ms": ended}


# --------------------------------------------------------------- le réglage


def test_the_setting_is_on_by_default_in_french_and_stored_locally():
    field = next(f for f in _node("V.FIELDS") if f["id"] == "showEphemeral")
    assert field["type"] == "toggle" and field["value"] is True
    assert field["label"] == "Afficher les tâches éphémères"
    assert "navigateur" in field["hint"] and "échec" in field["hint"]
    assert _node("V.DEFAULTS.showEphemeral") is True
    assert _node("V.normalize({showEphemeral:false}).showEphemeral") is False
    assert _node("V.normalize({showEphemeral:'false'}).showEphemeral") is False
    assert _node("V.normalize({}).showEphemeral") is True
    assert _node("V.KEY") == "jarvis.scene.view"  # même stockage local que les autres réglages d'affichage
    stored = _node("V.encode({showEphemeral:false})")
    assert _node(f"V.decode({json.dumps(stored)}).showEphemeral") is False
    assert _node("V.describe({showEphemeral:false}).custom") is True
    assert _node("V.changeSentence(V.FIELD_BY_ID.get('showEphemeral'),false)") == "Afficher les tâches éphémères : éteint."


def test_the_setting_never_touches_the_scene_classes_or_css_variables():
    # Un réglage qui ne dessine rien : il filtre, il ne peint pas.
    assert _node("V.classes({showEphemeral:false})") == []
    assert _node("V.cssVars({showEphemeral:false})") == _node("V.cssVars(null)")


# ------------------------------------------------------------ règle d'affichage


def test_the_linger_is_short_and_bounded(LINGER):
    assert 1000 <= LINGER <= 15000


def test_a_running_ephemeral_is_shown_and_a_normal_task_is_never_touched(LINGER):
    assert visibility(None, work("running"), NOW) == {"ephemeral": True, "hidden": False, "remainingMs": None}
    assert visibility(None, work("running", ephemeral=False), NOW)["ephemeral"] is False
    for status in ("running", "completed", "failed"):
        shown = visibility({"showEphemeral": False}, work(status, ephemeral=False, ended_ago=10 * LINGER), NOW)
        assert shown["hidden"] is False and shown["ephemeral"] is False
    assert visibility(None, None, NOW) == {"ephemeral": False, "hidden": False, "remainingMs": None}


def test_a_finished_ephemeral_lingers_then_leaves(LINGER):
    just_done = visibility(None, work("completed", ended_ago=0), NOW)
    assert just_done["hidden"] is False and just_done["remainingMs"] == LINGER
    half = visibility(None, work("completed", ended_ago=LINGER // 2), NOW)
    assert half["hidden"] is False and half["remainingMs"] == LINGER - LINGER // 2
    assert visibility(None, work("completed", ended_ago=LINGER), NOW)["hidden"] is True
    assert visibility(None, work("completed", ended_ago=LINGER + 5000), NOW)["hidden"] is True


def test_a_clock_skew_never_stretches_the_linger_and_a_missing_end_date_never_hides(LINGER):
    future = visibility(None, work("completed", ended_ago=-60_000), NOW)
    assert future["hidden"] is False and future["remainingMs"] == LINGER
    undated = visibility(None, {"ephemeral": True, "status": "completed", "ended_ms": None}, NOW)
    assert undated["hidden"] is False and undated["remainingMs"] is None


def test_with_the_setting_off_ephemerals_are_not_shown_at_all_even_while_running():
    off = {"showEphemeral": False}
    for status in ("pending", "running"):
        assert visibility(off, work(status), NOW)["hidden"] is True
    assert visibility(off, work("completed", ended_ago=0), NOW)["hidden"] is True


@pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted", "blocked"])
@pytest.mark.parametrize("setting", [True, False])
def test_a_task_that_did_not_end_well_is_never_hidden_whatever_the_flag_or_the_setting(status, setting, LINGER):
    # Même si un producteur laissait `ephemeral` vrai : la page ne masque jamais un échec.
    for ended_ago in (0, LINGER * 10):
        seen = visibility({"showEphemeral": setting}, work(status, ended_ago=ended_ago), NOW)
        assert seen == {"ephemeral": False, "hidden": False, "remainingMs": None}


def test_the_work_index_joins_core_items_by_source_and_id_on_the_local_clock():
    items = [
        {"source": "claude", "external_id": "a", "status": "completed", "ephemeral": True, "ended_at": "2026-10-07T10:00:10.000Z"},
        {"source": "claude", "external_id": "b", "status": "failed", "ephemeral": False, "ended_at": "2026-10-07T10:00:10.000Z"},
        {"source": "job", "external_id": "a", "status": "running"},
        {"source": "", "external_id": "x"},
        None,
    ]
    ended = _node("Date.parse('2026-10-07T10:00:10.000Z')")
    index = _node(f"[...V.indexWork({json.dumps(items)},2000).entries()]")
    assert dict(index) == {
        "claude|a": {"ephemeral": True, "status": "completed", "ended_ms": ended - 2000},
        "claude|b": {"ephemeral": False, "status": "failed", "ended_ms": ended - 2000},
        "job|a": {"ephemeral": False, "status": "running", "ended_ms": None},
    }


def test_the_pure_part_stays_free_of_dom_and_storage_with_the_new_rules():
    code = re.sub(r"/\*.*?\*/", "", VIEW_JS.read_text(encoding="utf-8"), flags=re.S)
    for forbidden in ("document.", "window.", "fetch(", "localStorage", "Date.now", "setTimeout"):
        assert forbidden not in code, forbidden


# ------------------------------------------------------------------- la scène


def test_the_scene_hides_a_vanished_ephemeral_star_without_removing_it(tmp_path):
    result = run_node(tmp_path, r"""
      const gone=obj('claude:e1','agent',{exec_state:'completed',work_ref:{source:'claude',external_id:'e1',work_id:null}});
      const live=obj('claude:e2','agent',{exec_state:'running',work_ref:{source:'claude',external_id:'e2',work_id:null}});
      const normal=obj('claude:n1','agent',{exec_state:'completed',work_ref:{source:'claude',external_id:'n1',work_id:null}});
      const s=state([gone,live,normal],[rel('r1','groups','claude:e1','claude:e2')]);
      const view=item=>item.object_id==='claude:e1'?{ephemeral:true,hidden:true}
        :item.object_id==='claude:e2'?{ephemeral:true,hidden:false}:{ephemeral:false,hidden:false};
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080),{workView:view});
      const plain=L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080),{});
      return {ids:vm.nodes.map(n=>n.id),eph:Object.fromEntries(vm.nodes.map(n=>[n.id,n.ephemeral])),
        hidden:vm.hidden,quiet:vm.ephemeralHidden,edges:vm.edges.length,
        plainIds:plain.nodes.map(n=>n.id),plainEph:plain.nodes.map(n=>n.ephemeral),plainQuiet:plain.ephemeralHidden,
        stillInState:s.objects.has('claude:e1'),visibility:s.objects.get('claude:e1').visibility};
    """)
    assert result["ids"] == ["claude:e2", "claude:n1"]
    assert result["eph"] == {"claude:e2": True, "claude:n1": False}
    # Masquée côté vue seulement : ni « masqué par l'utilisateur », ni retirée de l'état.
    assert result["hidden"] == 0 and result["quiet"] == 1
    assert result["stillInState"] is True and result["visibility"] == "visible"
    assert result["edges"] == 0  # le fil d'une étoile qui n'est plus dessinée n'est pas dessiné
    # Sans résolveur, la scène est inchangée.
    assert result["plainIds"] == ["claude:e1", "claude:e2", "claude:n1"]
    assert result["plainEph"] == [False, False, False] and result["plainQuiet"] == 0


def test_the_scene_page_wires_the_work_feed_the_setting_the_timer_and_the_tone():
    page = PAGE_JS.read_text(encoding="utf-8")
    assert "workView:" in page and "V.ephemeralVisibility" in page
    assert "setWork" in page  # couture appelée par le Control Center avec les travaux Core
    assert "node.ephemeral" in page and "sc-ephemeral" in page
    # Le dessin change quand le drapeau change.
    assert re.search(r"node\.alerted,\s*node\.ephemeral\]", page)
    # La couleur propre et le halo sombre existent, et le mouvement réduit les arrête.
    assert ".scene .sc-ephemeral" in page
    reduced = page[page.index("@media(prefers-reduced-motion:reduce)"):]
    assert "sc-ephemeral" in reduced


# ---------------------------------------------------------- le panneau Agents


def test_the_agents_panel_and_the_core_bridge_use_the_same_rule():
    html = PAGE_HTML.read_text(encoding="utf-8")
    work_js = (PAGE_JS.parent / "control_center_work.js").read_text(encoding="utf-8")
    # La carte porte le drapeau de Core, qui prime sur le diagnostic du tracker.
    assert "ephemeral:!!item.ephemeral" in work_js
    assert "ephemeralVisibility" in html and "JarvisScene.setWork" in html


# ------------------------------------------- vrai Chrome : le panneau Agents
#
# La page est composée comme `ControlCenter.index` la sert et chargée dans
# Chrome sans tête (harnais CDP des autres tests navigateur). On y pose un état
# Core et on relève ce que `listHtml` dessine et les styles CALCULÉS — pas le
# texte de la feuille de style.

PANEL_PROBE = r"""(()=>{
  const now=Date.now(),iso=ms=>new Date(ms).toISOString();
  const item=(id,status,extra)=>Object.assign({source:'claude',external_id:id,status,kind:'agent',label:id,
    started_at:iso(now-60000),ended_at:status==='running'?null:iso(now-(extra&&extra.agoMs||0)),ephemeral:false,
    activity:'',summary:'',model:'',parent_external_id:null,revision:1,background:true},extra||{});
  AG.skew=0;AG.data={tasks:[],now_ms:now};AG.missing=false;AG.error='';
  AG.core={ok:true,store_id:'s',revision:1,updated_at:iso(now),error:'',subtasks_supported:true,items:[
    item('e_run','running',{ephemeral:true}),
    item('e_fresh','completed',{ephemeral:true,agoMs:1000}),
    item('e_old','completed',{ephemeral:true,agoMs:20000}),
    item('e_failed','failed',{ephemeral:false,agoMs:20000,error_class:'x'}),
    item('n_done','completed',{agoMs:20000}),
    item('n_run','running'),
  ]};
  const read=()=>{
    AG.projected=null;
    const doc=new DOMParser().parseFromString('<div>'+listHtml(now)+'</div>','text/html');
    const ids=sel=>[...doc.querySelectorAll(sel)].map(el=>el.dataset.id);
    const done=doc.querySelector('details[data-sect=done]');
    return {live:ids('.acard:not(.brain)').filter(id=>!done||![...done.querySelectorAll('.acard')].some(c=>c.dataset.id===id)),
      done:done?[...done.querySelectorAll('.acard')].map(c=>c.dataset.id):[],
      badge:activeAgents().map(t=>t.id)};
  };
  const out={};
  try{localStorage.removeItem(JarvisSceneView.KEY)}catch(_e){}
  out.on=read();
  try{localStorage.setItem(JarvisSceneView.KEY,JarvisSceneView.encode({showEphemeral:false}))}catch(_e){out.storage='refused'}
  out.off=read();
  try{localStorage.removeItem(JarvisSceneView.KEY)}catch(_e){}
  return out;
})()"""

CARD_PROBE = r"""(()=>{
  const now=Date.now();
  const make=(id,ephemeral)=>coreTask({source:'claude',external_id:id,status:'running',kind:'agent',label:id,
    started_at:new Date(now-5000).toISOString(),ended_at:null,ephemeral,background:true},null);
  const host=document.createElement('div');host.id='probe';
  host.innerHTML=cardsHtml([make('eph',true),make('plain',false)]);
  document.body.appendChild(host);
  const pick=id=>{const card=host.querySelector('.acard[data-id='+id+']'),dot=card.querySelector('.adot');
    const style=getComputedStyle(card);
    return {cls:card.className,shadow:style.boxShadow,border:style.borderTopColor,dotAnimation:getComputedStyle(dot).animationName,
      chips:[...card.querySelectorAll('.chip')].map(c=>c.textContent)};};
  return {eph:pick('eph'),plain:pick('plain')};
})()"""


def _panel_run(tmp_path, expression: str, *, reduced: bool = False) -> Any:
    from tests.unit.test_interaction_mode_hud_browser import _drive

    step = {"width": 1440, "height": 900, "reducedMotion": reduced,
            "actions": [{"a": "eval", "expr": expression}]}
    return _drive(tmp_path, [step])[0]["actions"][0]["value"]


def test_the_agents_panel_hides_vanished_ephemerals_and_keeps_failures_in_a_real_browser(tmp_path):
    seen = _panel_run(tmp_path, PANEL_PROBE)
    assert seen.get("storage") != "refused", "le stockage local doit marcher pour prouver le réglage"
    # Réglage allumé (défaut) : l'éphémère en cours et celle qui vient de finir sont là ; l'ancienne n'est NULLE PART
    # (ni dans la liste, ni dans « Terminés ») ; l'échec et la tâche normale terminée sont dans « Terminés ».
    assert sorted(seen["on"]["live"]) == ["e_fresh", "e_run", "n_run"]
    assert sorted(seen["on"]["done"]) == ["e_failed", "n_done"]
    assert sorted(seen["on"]["badge"]) == ["e_run", "n_run"]
    # Réglage éteint : plus aucune éphémère, en cours ou non ; l'échec reste visible.
    assert seen["off"]["live"] == ["n_run"]
    assert sorted(seen["off"]["done"]) == ["e_failed", "n_done"]
    assert seen["off"]["badge"] == ["n_run"]


def test_a_running_ephemeral_card_has_its_own_colour_a_dark_halo_and_a_word(tmp_path):
    seen = _panel_run(tmp_path, CARD_PROBE)
    eph, plain = seen["eph"], seen["plain"]
    assert "eph" in eph["cls"].split() and "eph" not in plain["cls"].split()
    assert eph["border"] != plain["border"]
    assert "rgba(2, 6, 10" in eph["shadow"] and "rgba(2, 6, 10" not in plain["shadow"]
    assert "éphémère" in eph["chips"] and "éphémère" not in plain["chips"]
    assert eph["dotAnimation"] != "none"  # la pastille de vie respire, comme pour toute tâche en cours


def test_reduced_motion_stops_the_ephemeral_dot(tmp_path):
    seen = _panel_run(tmp_path, CARD_PROBE, reduced=True)
    assert seen["eph"]["dotAnimation"] == "none" and seen["plain"]["dotAnimation"] == "none"
