"""Interactions de l'utilisateur sur la scène (handoff jarvis-constellation-scene-runtime, Slice 08).

Prouvé en exécutant avec node le fichier même que la page reçoit
(`control_center_scene_interact.js`) :

- géométrie bornée au cadre (glisser, redimensionner, clavier, changement de forme) ;
- modèle de menu selon nature, origine et état — « Arrêter » pour un job Core
  seulement, jamais pour un sous-agent du brain ;
- sélection de l'archivage groupé **identique** à `bulk_archivable` du domaine
  (parité sur une scène riche) et découpage borné ;
- affichage optimiste : aperçu, confirmation par révision, annulation, délai ;
- lecture des réponses de commande ;
- câblage de la page : marqueur inséré, aucune boîte de dialogue du navigateur.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import pytest

from jarvis.domain.scene import (
    MAX_ARCHIVE_MANY_IDS,
    MAX_SCENE_OBJECTS,
    SCENE_FRAME_HALF_HEIGHT,
    SCENE_FRAME_HALF_WIDTH,
    bulk_archivable,
    runtime_signals_of,
    signal_owners,
)
from jarvis.protocol.scene_wire import MAX_SCENE_COMMAND_BYTES
from jarvis.runtime.control_center import SCENE_INTERACT_SCRIPT_MARKER, ControlCenter
from tests.unit.test_scene_user_lifecycle import lifecycle_scene, with_orphan

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
CLIENT_JS = RUNTIME / "control_center_scene.js"
LAYOUT_JS = RUNTIME / "control_center_scene_layout.js"
INTERACT_JS = RUNTIME / "control_center_scene_interact.js"
PAGE_JS = RUNTIME / "control_center_scene_page.js"
PAGE_HTML = RUNTIME / "control_center.html"

PRELUDE = r"""
const S=require(PATHS.client),Lay=require(PATHS.layout),I=require(PATHS.interact);
function obj(id,kind,extra){
  const layer={agent:100,job:100,artifact:120,window:220,attention:300,group:50}[kind];
  return Object.assign({object_id:id,kind,category:kind,exec_state:'running',
    representation:kind==='window'?'window':kind==='artifact'?'capsule':'point',geometry:null,layer,order:0,
    visibility:'visible',disposition:'active',constraints:{placed_by:'runtime',pinned_by_user:false},origin:'runtime',
    work_ref:null,payload:{title:id,summary:'',items:[]}},extra||{});
}
function rel(id,kind,from,to){return {relation_id:id,kind,from_id:from,to_id:to,layer:50}}
function state(objects,relations,revision){
  return {scene_id:'scene',epoch:'e1',revision:revision||1,objects:new Map(objects.map(o=>[o.object_id,o])),
    relations:new Map((relations||[]).map(r=>[r.relation_id,r])),archived_ids:new Set()};
}
"""


def run_node(tmp_path: Path, body: str, data: Any = None) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    paths = {"client": str(CLIENT_JS), "layout": str(LAYOUT_JS), "interact": str(INTERACT_JS)}
    index = len(list(tmp_path.glob("scene-interact-*.cjs")))
    data_file = tmp_path / f"scene-interact-{index}.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / f"scene-interact-{index}.cjs"
    script.write_text(
        f"const PATHS={json.dumps(paths)};\n"
        f"const D=JSON.parse(require('fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        + PRELUDE
        + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),e=>{console.error(e&&e.stack||e);process.exit(1)});\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ---------------------------------------------------------------- géométrie


def test_the_frame_matches_the_domain(tmp_path):
    result = run_node(tmp_path, "return I.FRAME;")
    assert result == {"halfWidth": SCENE_FRAME_HALF_WIDTH, "halfHeight": SCENE_FRAME_HALF_HEIGHT}


def test_drag_and_resize_stay_inside_the_frame_with_minimum_sizes(tmp_path):
    result = run_node(tmp_path, r"""
      const vp=Lay.viewport(1920,1080);   // 6 px par unité
      const start={x:-20,y:-10,w:40,h:7};
      return {
        units:I.pxToUnits(vp,60,-30),
        moved:I.dragBox(start,10,-5,'capsule'),
        pastRight:I.dragBox(start,1000,0,'capsule'),
        pastTopLeft:I.dragBox(start,-1000,-1000,'capsule'),
        grow:I.resizeBox({x:-40,y:-20,w:64,h:40},20,10,'window'),
        growPastEdge:I.resizeBox({x:100,y:40,w:40,h:30},500,500,'window'),
        shrinkBelowMin:I.resizeBox({x:0,y:0,w:64,h:40},-500,-500,'window'),
        capsuleMin:I.resizeBox({x:0,y:0,w:40,h:7},-500,-500,'capsule'),
        huge:I.clampBox({x:-500,y:-500,w:5000,h:5000},'window'),
        noisy:I.dragBox({x:0.1,y:0.2,w:6,h:6},0.123456,0.987654,'point'),
      };
    """)
    assert result["units"] == {"dx": 10, "dy": -5}
    assert result["moved"] == {"x": -10, "y": -15, "w": 40, "h": 7}
    assert result["pastRight"] == {"x": 120, "y": -10, "w": 40, "h": 7}  # 120 + 40 = 160
    assert result["pastTopLeft"] == {"x": -160, "y": -90, "w": 40, "h": 7}
    assert result["grow"] == {"x": -40, "y": -20, "w": 84, "h": 50}
    assert result["growPastEdge"] == {"x": 100, "y": 40, "w": 60, "h": 50}  # bord du cadre : 160, 90
    assert result["shrinkBelowMin"] == {"x": 0, "y": 0, "w": 40, "h": 24}
    assert result["capsuleMin"] == {"x": 0, "y": 0, "w": 16, "h": 5}
    assert result["huge"] == {"x": -160, "y": -90, "w": 320, "h": 180}
    assert result["noisy"] == {"x": 0.2, "y": 1.2, "w": 6, "h": 6}


def test_keyboard_intents_move_resize_open_the_menu_or_navigate(tmp_path):
    result = run_node(tmp_path, r"""
      const k=(key,mods)=>I.keyIntent({key,...(mods||{})});
      const box={x:0,y:0,w:40,h:7};
      return {
        nav:k('ArrowRight'),home:k('Home'),shiftHome:k('Home',{shiftKey:true}),
        move:k('ArrowLeft',{shiftKey:true}),moveLarge:k('ArrowDown',{shiftKey:true,ctrlKey:true}),
        resize:k('ArrowRight',{ctrlKey:true}),alt:k('ArrowLeft',{altKey:true}),meta:k('ArrowUp',{metaKey:true,shiftKey:true}),
        menu:k('ContextMenu'),shiftF10:k('F10',{shiftKey:true}),f10:k('F10'),letter:k('a'),
        applied:I.applyKey(box,k('ArrowUp',{shiftKey:true}),'capsule'),
        grown:I.applyKey(box,k('ArrowRight',{ctrlKey:true}),'capsule'),
        pointNoResize:I.applyKey({x:0,y:0,w:6,h:6},k('ArrowRight',{ctrlKey:true}),'point'),
        edge:I.applyKey({x:150,y:0,w:10,h:6},k('ArrowRight',{shiftKey:true,ctrlKey:true}),'point'),
      };
    """)
    assert result["nav"] == {"type": "nav"} and result["home"] == {"type": "nav"} and result["shiftHome"] is None
    assert result["move"] == {"type": "move", "dx": -2, "dy": 0}
    assert result["moveLarge"] == {"type": "move", "dx": 0, "dy": 10}
    assert result["resize"] == {"type": "resize", "dx": 2, "dy": 0}
    # Alt+flèche (retour du navigateur) et Méta ne sont jamais interceptés.
    assert result["alt"] is None and result["meta"] is None
    assert result["menu"] == {"type": "menu"} and result["shiftF10"] == {"type": "menu"}
    assert result["f10"] is None and result["letter"] is None
    assert result["applied"] == {"x": 0, "y": -2, "w": 40, "h": 7}
    assert result["grown"] == {"x": 0, "y": 0, "w": 42, "h": 7}
    assert result["pointNoResize"] == {"x": 0, "y": 0, "w": 6, "h": 6}
    assert result["edge"] == {"x": 150, "y": 0, "w": 10, "h": 6}


def test_a_representation_change_keeps_the_centre_and_takes_the_default_size(tmp_path):
    result = run_node(tmp_path, r"""
      const layoutSizes=Lay.DEFAULT_SIZE;
      return {
        sizes:I.DEFAULT_SIZE,layoutSizes,
        toWindow:I.representationBox({x:-3,y:-3,w:6,h:6},'window','agent'),
        toPoint:I.representationBox({x:-32,y:-20,w:64,h:40},'point','agent'),
        signal:I.representationBox({x:-32,y:-20,w:64,h:40},'point','attention'),
        edge:I.representationBox({x:154,y:84,w:6,h:6},'window','agent'),
      };
    """)
    assert result["sizes"] == result["layoutSizes"]  # même taille que le résolveur
    assert result["toWindow"] == {"x": -32, "y": -20, "w": 64, "h": 40}
    assert result["toPoint"] == {"x": -3, "y": -3, "w": 6, "h": 6}
    assert result["signal"] == {"x": -2, "y": -2, "w": 4, "h": 4}
    assert result["edge"] == {"x": 96, "y": 50, "w": 64, "h": 40}


# ---------------------------------------------------------------- menu


def test_menu_entries_depend_on_kind_origin_and_state(tmp_path):
    result = run_node(tmp_path, r"""
      const st=state([
        obj('job:run','job',{exec_state:'running',work_ref:{source:'job',external_id:'run'}}),
        obj('job:done','job',{exec_state:'completed',work_ref:{source:'job',external_id:'done'}}),
        obj('claude:run','agent',{exec_state:'running',work_ref:{source:'claude',external_id:'run'}}),
        obj('claude:bad','agent',{exec_state:'failed',work_ref:{source:'claude',external_id:'bad'},geometry:{x:0,y:0,w:6,h:6},
          constraints:{placed_by:'user',pinned_by_user:true}}),
        obj('attention!claude:bad','attention',{exec_state:'failed',work_ref:{source:'claude',external_id:'bad'}}),
        obj('note','window',{origin:'brain',exec_state:'unknown'}),
        obj('odd:job','job',{exec_state:'blocked',work_ref:{source:'claude',external_id:'odd'}}),
      ],[rel('attention!claude:bad','explains','attention!claude:bad','claude:bad')]);
      const acts=id=>{const m=I.menuModel(st,id,{finished:3});return m.items.map(it=>it==='-'?'-':`${it.act}${it.disabled?'(off)':''}${it.danger?'!':''}`)};
      return {jobRun:acts('job:run'),jobDone:acts('job:done'),claudeRun:acts('claude:run'),claudeBad:acts('claude:bad'),
        signal:acts('attention!claude:bad'),note:acts('note'),oddJob:acts('odd:job'),
        noFinished:I.menuModel(st,'job:done',{finished:0}).items.filter(it=>it!=='-').map(it=>it.act),
        title:I.menuModel(st,'note',{title:'Résumé'}).title,missing:I.menuModel(st,'absent',{}),
        badLabel:I.menuModel(st,'claude:bad',{}).items.find(it=>it.act==='archive').label,
        claudeRunLabel:I.menuModel(st,'claude:run',{}).items.find(it=>it.act==='stop-unavailable').label};
    """)
    assert result["jobRun"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "stop!", "archive!", "archive-finished!"]
    assert result["jobDone"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "archive!", "archive-finished!"]
    # Sous-agent du brain en cours : jamais d'arrêt, une entrée désactivée le dit.
    assert result["claudeRun"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "stop-unavailable(off)", "archive!", "archive-finished!"]
    assert "stop" not in result["claudeRun"]
    assert result["claudeBad"] == ["rep:capsule", "rep:window", "-", "unpin", "hide", "-", "archive!", "archive-finished!"]
    assert result["badLabel"] == "Archiver avec son signal…"
    assert result["signal"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "archive!", "archive-finished!"]
    # Fenêtre du brain : pas d'arrêt ni d'archivage groupé depuis son menu.
    assert result["note"] == ["rep:point", "rep:capsule", "-", "pin", "hide", "-", "archive!"]
    # Un job dont le travail n'est pas un job Core (source claude) n'a pas d'arrêt.
    assert "stop-unavailable(off)" in result["oddJob"] and "stop!" not in result["oddJob"]
    assert "archive-finished" not in result["noFinished"]
    assert result["title"] == "Résumé" and result["missing"] is None
    assert result["claudeRunLabel"] == "Arrêt impossible : sous-agent du brain"


# ---------------------------------------------------------------- archivage groupé


def test_bulk_selection_is_the_domain_rule_on_the_same_scene(tmp_path):
    scene = with_orphan(lifecycle_scene())
    expected_stars = sorted(item.object_id for item in scene.objects if item.kind.value in ("agent", "job") and bulk_archivable(scene, item.object_id))
    owners = signal_owners(scene)
    orphans = sorted(signal for signal, owner in owners.items() if owner is None)
    cascaded = sorted(signal for star in expected_stars for signal in runtime_signals_of(scene, star, owners))
    # Tout ce que la sélection enverra passe la règle du domaine, cascade comprise.
    selected = frozenset(expected_stars + orphans)
    assert all(bulk_archivable(scene, object_id, selected) for object_id in [*selected, *cascaded])

    result = run_node(tmp_path, r"""
      const loaded=S.fromSnapshot({scene_id:D.snapshot.scene_id,epoch:'e',revision:D.snapshot.revision,snapshot:D.snapshot});
      const st=loaded.state;
      const sel=I.bulkSelection(st);
      const owners=Object.fromEntries(I.signalOwners(st));
      const cascade=Object.fromEntries([...st.objects.keys()].map(id=>[id,I.cascadeOf(st,id)]));
      return {sel,owners,cascade};
    """, {"snapshot": scene.to_payload()})

    sel = result["sel"]
    assert sorted(sel["ids"]) == sorted(expected_stars + orphans)
    assert sel["stars"] == len(expected_stars) and sel["orphans"] == len(orphans) and sel["cascaded"] == len(cascaded)
    assert sel["objects"] == len(expected_stars) + len(orphans) + len(cascaded)
    assert sel["byState"] == {"completed": 1, "failed": 1, "cancelled": 1, "interrupted": 1}
    assert result["owners"] == owners
    for object_id in (item.object_id for item in scene.objects):
        assert result["cascade"][object_id] == list(runtime_signals_of(scene, object_id, owners)), object_id


def test_bulk_ids_are_chunked_inside_the_domain_and_transport_bounds(tmp_path):
    result = run_node(tmp_path, r"""
      const short=Array.from({length:1200},(_,i)=>`claude:toolu_${i}`);
      const long=Array.from({length:512},(_,i)=>'é'.repeat(120)+`:${i}`);
      const size=chunk=>Buffer.byteLength(JSON.stringify(I.commands.archiveMany(chunk)),'utf8');
      const a=I.chunkIds(short),b=I.chunkIds(long);
      return {short:a.map(c=>c.length),long:b.map(c=>c.length),maxBytes:Math.max(...a.map(size),...b.map(size)),
        flat:[].concat(...a).length===short.length&&[].concat(...b).join()===long.join(),empty:I.chunkIds([]),
        command:I.commands.archiveMany(['a','b'])};
    """)
    assert result["short"] == [512, 512, 176]
    assert all(length <= MAX_ARCHIVE_MANY_IDS for length in result["long"]) and len(result["long"]) > 1
    assert result["maxBytes"] < MAX_SCENE_COMMAND_BYTES and result["flat"] is True and result["empty"] == []
    assert result["command"] == {"schema_version": 1, "op": "archive_many", "object_ids": ["a", "b"]}
    assert MAX_ARCHIVE_MANY_IDS == MAX_SCENE_OBJECTS


# ---------------------------------------------------------------- optimiste


def test_optimistic_changes_draw_at_once_then_yield_to_the_state_or_roll_back(tmp_path):
    result = run_node(tmp_path, r"""
      const base=state([obj('a','artifact',{geometry:{x:0,y:0,w:40,h:7}}),obj('b','agent'),obj('c','window')],[],10);
      const P=I.createPending(30000);
      const out={same:P.overlay(base)===base};
      const t1=P.begin('a',{geometry:{x:50,y:5,w:40,h:7},pinned:true},1000);
      const t2=P.begin('b',{visibility:'hidden'},1000);
      const t3=P.begin('c',{archived:true},1000);
      const drawn=P.overlay(base);
      out.drawn={a:drawn.objects.get('a').geometry,aPinned:drawn.objects.get('a').constraints.pinned_by_user,
        b:drawn.objects.get('b').visibility,c:drawn.objects.has('c'),baseUntouched:base.objects.get('a').geometry.x===0&&base.objects.get('b').visibility==='visible'};
      // Placement refusé : l'objet revient à sa place.
      out.rollback=P.rollback('b',t2);
      out.afterRollback=P.overlay(base).objects.get('b').visibility;
      // Déplacement accepté à la révision 11, épinglage refusé : seul l'épinglage s'efface.
      P.confirm('a',t1,11);
      out.drop=P.drop('a',t1,'pinned');
      out.aAfterDrop=P.overlay(base).objects.get('a').constraints.pinned_by_user;
      // Un geste plus récent remplace le jeton : l'ancien ne peut plus rien annuler.
      const t4=P.begin('a',{geometry:{x:60,y:5,w:40,h:7}},1100);
      out.staleRollback=P.rollback('a',t1);out.staleConfirm=P.confirm('a',t1,11);
      P.confirm('a',t4,12);P.confirm('c',t3,12);
      out.pruneEarly=P.prune({...base,revision:11},2000);
      out.pruneReached=P.prune({...base,revision:12},2000);
      const t5=P.begin('b',{visibility:'hidden'},2000);
      out.pruneExpired=P.prune({...base,revision:12},2000+30001);
      out.size=P.size();
      const v=P.version();P.begin('zz',{visibility:'hidden'},0);
      out.missingIgnored=P.overlay(base)===base;out.versionMoves=P.version()>v;
      return out;
    """)
    assert result["same"] is True
    assert result["drawn"] == {"a": {"x": 50, "y": 5, "w": 40, "h": 7}, "aPinned": True, "b": "hidden", "c": False, "baseUntouched": True}
    assert result["rollback"] is True and result["afterRollback"] == "visible"
    assert result["drop"] is True and result["aAfterDrop"] is False
    assert result["staleRollback"] is False and result["staleConfirm"] is False
    assert result["pruneEarly"] == []
    assert sorted(entry["id"] for entry in result["pruneReached"]) == ["a", "c"]
    assert result["pruneExpired"] == [{"id": "b", "reason": "expired"}]
    assert result["size"] == 0 and result["missingIgnored"] is True and result["versionMoves"] is True


def test_command_responses_are_read_in_user_words(tmp_path):
    result = run_node(tmp_path, r"""
      const c=I.classifyResponse;
      return {
        applied:c(200,{outcome:'applied',reason:null,revision:7}),duplicate:c(200,{outcome:'duplicate',revision:7}),
        refused:c(200,{outcome:'rejected_authority',reason:'pinned_by_user',revision:7}),
        bulk:c(200,{outcome:'invalid',reason:'not_bulk_archivable',revision:7}),
        unknownReason:c(200,{outcome:'invalid',reason:'something_new',revision:7}),
        timeout:c(504,{error:{code:'core_timeout',message:'Core n’a pas répondu'}}),
        down:c(503,{error:{code:'core_unreachable',message:'Core injoignable'}}),
        garbage:c(502,null),network:c(0,null),
      };
    """)
    assert result["applied"]["ok"] is True and result["applied"]["revision"] == 7 and result["applied"]["message"] == ""
    assert result["duplicate"]["ok"] is True
    assert result["refused"] == {"ok": False, "outcome": "rejected_authority", "reason": "pinned_by_user", "code": "",
                                 "revision": 7, "unknown": False, "message": "refusé : l'objet est épinglé"}
    assert "n’est plus un travail terminé" in result["bulk"]["message"]
    assert result["unknownReason"]["message"] == "refusé : something_new"
    assert result["timeout"]["unknown"] is True and result["timeout"]["code"] == "core_timeout"
    assert result["down"] == {"ok": False, "outcome": "failed", "reason": "", "code": "core_unreachable", "message": "Core injoignable",
                              "revision": None, "unknown": False}
    assert result["garbage"]["code"] == "http_502" and result["network"]["code"] == "network_error"


def test_hidden_objects_are_listed_in_core_order(tmp_path):
    result = run_node(tmp_path, r"""
      const st=state([obj('a','artifact',{visibility:'hidden',payload:{title:'Note A',summary:'',items:[]}}),obj('b','agent'),
        obj('c','window',{visibility:'hidden'})]);
      return I.hiddenObjects(st);
    """)
    assert result == [{"id": "a", "kind": "artifact", "title": "Note A"}, {"id": "c", "kind": "window", "title": "c"}]


# ---------------------------------------------------------------- page


async def test_the_page_serves_the_interaction_logic_and_never_uses_browser_dialogs(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    assert SCENE_INTERACT_SCRIPT_MARKER not in html and "window.JarvisSceneInteract" not in PAGE_HTML.read_text(encoding="utf-8")
    assert "root.JarvisSceneInteract=api" in html
    # L'interaction est insérée après le rendu pur et avant la page qui l'utilise.
    assert html.index("root.JarvisSceneLayout=api") < html.index("root.JarvisSceneInteract=api") < html.index("function installJarvisScene")
    for source in (html, INTERACT_JS.read_text(encoding="utf-8"), PAGE_JS.read_text(encoding="utf-8")):
        # Un appel, pas une définition de méthode (`confirm(id,token){`).
        assert not re.search(r"(?<![\w.])(?:window\.)?(?:alert|confirm|prompt)\((?![^()]*\)\s*\{)", source)
    assert "function confirmDialog(" in html and "function showMenu(" in html
    assert 'role="alertdialog"' in html


def test_the_interaction_module_touches_no_dom_network_or_clock():
    source = INTERACT_JS.read_text(encoding="utf-8")
    for forbidden in ("document.", "window.add", "window.set", "fetch(", "XMLHttpRequest", "setTimeout", "Date.now", "performance.now", "localStorage"):
        assert forbidden not in source, forbidden
