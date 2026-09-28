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
    SCENE_SAFE_AREA,
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


def test_the_frame_and_safe_area_match_the_domain_and_the_renderer(tmp_path):
    result = run_node(tmp_path, "return {frame:I.FRAME,safe:I.SAFE_AREA,layoutSafe:Lay.SAFE_AREA,max:I.MAX_SIZE.capsule,capsuleMax:Lay.CAPSULE_MAX};")
    assert result["frame"] == {"halfWidth": SCENE_FRAME_HALF_WIDTH, "halfHeight": SCENE_FRAME_HALF_HEIGHT}
    x0, y0, x1, y1 = SCENE_SAFE_AREA
    assert result["safe"] == {"x0": x0, "y0": y0, "x1": x1, "y1": y1} == result["layoutSafe"]
    assert result["max"] == result["capsuleMax"]


def test_drag_follows_the_hand_and_resize_keeps_the_minimum_and_maximum_sizes(tmp_path):
    """Depuis le 22/09/2026, `dragBox` et `resizeBox` ne bornent plus que ce
    qui appartient à la boîte — sa taille. Où la main peut l'emmener est une
    question d'écran, à laquelle répond la tenue (`createHold`,
    `test_scene_hold_contract.py`). Ils bornaient à l'ellipse du tour et à la
    zone sûre, deux murs invisibles au milieu d'un grand écran."""
    result = run_node(tmp_path, r"""
      const vp=Lay.viewport(1920,1080);   // 6 px par unité
      const start={x:-20,y:-10,w:40,h:7};
      return {
        units:I.pxToUnits(vp,60,-30),
        moved:I.dragBox(start,10,-5),
        pastRight:I.dragBox(start,1000,0),
        grow:I.resizeBox({x:-40,y:-20,w:64,h:40},20,10,'window'),
        growPastEdge:I.resizeBox({x:100,y:40,w:30,h:24},500,500,'window'),
        shrinkBelowMin:I.resizeBox({x:0,y:0,w:64,h:40},-500,-500,'window'),
        capsuleMin:I.resizeBox({x:0,y:0,w:40,h:7},-500,-500,'capsule'),
        capsuleMax:I.resizeBox({x:-100,y:0,w:40,h:7},500,500,'capsule'),
        huge:I.clampBox({x:-500,y:-500,w:5000,h:5000},'window'),
        noisy:I.dragBox({x:0.1,y:0.2,w:6,h:6},0.123456,0.987654),
      };
    """)
    assert result["units"] == {"dx": 10, "dy": -5}
    assert result["moved"] == {"x": -10, "y": -15, "w": 40, "h": 7}
    # Plus d'ellipse sous la main : la boîte va où la main l'emmène.
    assert result["pastRight"] == {"x": 980, "y": -10, "w": 40, "h": 7}
    assert result["grow"] == {"x": -40, "y": -20, "w": 84, "h": 50}
    # Le coin haut gauche ne bouge jamais ; la taille s'arrête au maximum de la forme.
    assert result["growPastEdge"] == {"x": 100, "y": 40, "w": 290, "h": 140}
    assert result["shrinkBelowMin"] == {"x": 0, "y": 0, "w": 40, "h": 24}
    assert result["capsuleMin"] == {"x": 0, "y": 0, "w": 16, "h": 5}
    assert result["capsuleMax"] == {"x": -100, "y": 0, "w": 160, "h": 10}
    # Les actions du menu, elles, restent dans la zone sûre, comme le résolveur.
    assert result["huge"] == {"x": -152, "y": -72, "w": 290, "h": 140}
    # L'aperçu suit la main sans marches : seule la place enregistrée passe sur
    # la grille du dixième, au lâcher (`holdPlace`).
    assert result["noisy"]["x"] == pytest.approx(0.223456) and result["noisy"]["y"] == pytest.approx(1.187654)


def test_move_keeps_the_size_and_resize_keeps_the_corner(tmp_path):
    """Vérifié en propriété et non sur quelques exemples : sur des milliers de
    boîtes et de gestes tirés au sort, pour chaque forme —

    - **déplacer ne touche jamais à la taille**, au bit près (même une capsule
      plus haute que son maximum, ce que `CAPSULE_MAX` prévoit au rendu) ;
    - **redimensionner par le coin bas droit ne touche jamais au coin haut
      gauche** ;
    - la taille d'un redimensionnement est sur la grille du dixième d'unité.

    Le tour n'entre plus dans la géométrie d'un geste (22/09/2026) : une place
    qui ne tient pas sur son tour ne tourne pas, elle n'est plus ramenée.
    """
    result = run_node(tmp_path, r"""
      let seed=7;const rnd=()=>(seed=(seed*1103515245+12345)%2147483648)/2147483648;
      const R=(a,b)=>a+(b-a)*rnd();
      const onGrid=v=>Math.abs(v*10-Math.round(v*10))<1e-6;
      const fails={moveSize:0,resizeCorner:0,grid:0};
      let cases=0;
      for(let i=0;i<4000;i++){
        for(const rep of ['point','capsule','window']){
          cases++;
          const size=rep==='point'?{w:6,h:6}:rep==='capsule'?{w:R(16,160),h:R(5,10)}:{w:R(40,200),h:R(24,120)};
          const start=I.clampBox({x:R(-160,140),y:R(-80,70),...size},rep);
          const moved=I.dragBox(start,R(-300,300),R(-200,200));
          if(moved.w!==start.w||moved.h!==start.h)fails.moveSize++;
          if(rep==='point')continue;
          const resized=I.resizeBox(start,R(-100,200),R(-50,100),rep);
          if(resized.x!==start.x||resized.y!==start.y)fails.resizeCorner++;
          if(![resized.w,resized.h].every(onGrid))fails.grid++;
        }
      }
      /* Le cas qui échappait à la borne de taille : une capsule plus haute que
         son maximum (fenêtre passée en capsule), simplement déplacée. */
      const tall=I.dragBox({x:10,y:10,w:40,h:24},3.7,-2.2);
      /* Une capsule qu'on élargit vers le bord : le coin reste, la largeur suit. */
      const widened=I.resizeBox({x:60,y:0,w:40,h:7},60,0,'capsule');
      return {cases,fails,tall,widened};
    """)
    assert result["cases"] == 12000
    assert result["fails"] == {"moveSize": 0, "resizeCorner": 0, "grid": 0}
    assert result["tall"]["w"] == 40 and result["tall"]["h"] == 24
    assert result["tall"]["x"] == pytest.approx(13.7) and result["tall"]["y"] == pytest.approx(7.8)
    assert result["widened"] == {"x": 60, "y": 0, "w": 100, "h": 7}


def test_the_grid_of_stored_places_matches_the_renderer(tmp_path):
    """La grille du dixième d'unité existe en deux exemplaires : ce module
    borne les tailles dessus, le rendu y pose la place enregistrée au lâcher
    (`holdPlace`). Même garde que pour `SAFE_AREA` : une parité, pas une
    promesse."""
    result = run_node(tmp_path, "return {interact:I.QUANTUM,layout:Lay.QUANTUM};")
    assert result["interact"] == result["layout"] == 10


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
        edge:I.applyKey({x:120,y:0,w:10,h:6},k('ArrowRight',{shiftKey:true,ctrlKey:true}),'point'),
        pushedPast:I.applyKey({x:150,y:0,w:6,h:6},k('ArrowRight',{shiftKey:true,ctrlKey:true}),'point'),
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
    # Un pas du clavier est un pas : c'est la tenue, comme pour la souris, qui
    # l'arrête au bord de l'écran visible (`test_scene_hold_contract.py`).
    assert result["edge"] == {"x": 130, "y": 0, "w": 10, "h": 6}
    assert result["pushedPast"] == {"x": 160, "y": 0, "w": 6, "h": 6}


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
    assert result["edge"] == {"x": 74, "y": 28, "w": 64, "h": 40}


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
      const acts=id=>{const m=I.menuModel(st,id,{finished:3});return m.items.map(it=>it==='-'?'-':`${it.act}${it.disabled?'(off)':''}${it.note?'(note)':''}${it.danger?'!':''}`)};
      return {jobRun:acts('job:run'),jobDone:acts('job:done'),claudeRun:acts('claude:run'),claudeBad:acts('claude:bad'),
        signal:acts('attention!claude:bad'),note:acts('note'),oddJob:acts('odd:job'),
        noFinished:I.menuModel(st,'job:done',{finished:0}).items.filter(it=>it!=='-').map(it=>it.act),
        title:I.menuModel(st,'note',{title:'Résumé'}).title,missing:I.menuModel(st,'absent',{}),
        badLabel:I.menuModel(st,'claude:bad',{}).items.find(it=>it.act==='archive').label,
        claudeRunLabel:I.menuModel(st,'claude:run',{}).items.find(it=>it.act==='stop-unavailable').label,
        finishedLabels:[1,3].map(n=>I.menuModel(st,'job:done',{finished:n}).items.find(it=>it.act==='archive-finished').label)};
    """)
    assert result["jobRun"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "stop!", "archive!", "archive-finished!"]
    assert result["jobDone"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "archive!", "archive-finished!"]
    # Sous-agent du brain en cours : jamais d'arrêt, une entrée désactivée le dit.
    assert result["claudeRun"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "stop-unavailable(note)", "archive!", "archive-finished!"]
    assert "stop" not in result["claudeRun"]
    # Étoile liée à son signal : la constellation (2 objets) s'offre au menu ;
    # une étoile sans attache n'a pas l'entrée (jobRun, claudeRun, note).
    assert result["claudeBad"] == ["rep:capsule", "rep:window", "-", "unpin", "hide", "select-constellation", "-", "archive!", "archive-finished!"]
    assert result["badLabel"] == "Archiver avec son signal…"
    assert result["signal"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "select-constellation", "-", "archive!", "archive-finished!"]
    # Fenêtre du brain : pas d'arrêt ni d'archivage groupé depuis son menu.
    assert result["note"] == ["rep:point", "rep:capsule", "-", "pin", "hide", "-", "archive!"]
    # Un job dont le travail n'est pas un job Core (source claude) n'a pas d'arrêt.
    assert "stop-unavailable(note)" in result["oddJob"] and "stop!" not in result["oddJob"]
    assert "archive-finished" not in result["noFinished"]
    assert result["title"] == "Résumé" and result["missing"] is None
    assert result["claudeRunLabel"] == "Arrêt impossible : sous-agent du brain"
    # Même nom que la confirmation (« Archiver 3 objets »).
    assert result["finishedLabels"] == ["Archiver les travaux terminés (1 objet)…", "Archiver les travaux terminés (3 objets)…"]


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
      out.rollback=P.rollback('b',t2);
      out.afterRollback=P.overlay(base).objects.get('b').visibility;
      P.confirm('a',t1,11);
      out.drop=P.drop('a',t1,'pinned');
      out.aAfterDrop=P.overlay(base).objects.get('a').constraints.pinned_by_user;
      P.confirm('c',t3,12);
      out.pruneEarly=P.prune({...base,revision:10},2000);
      out.pruneReached=P.prune({...base,revision:12},2000).map(e=>e.id).sort();
      P.begin('b',{visibility:'hidden'},2000);
      out.pruneExpired=P.prune({...base,revision:12},2000+30001).map(e=>[e.id,e.reason]);
      out.size=P.size();
      const v=P.version();P.begin('zz',{visibility:'hidden'},0);
      out.missingIgnored=P.overlay(base)===base;out.versionMoves=P.version()>v;
      return out;
    """)
    assert result["same"] is True
    assert result["drawn"] == {"a": {"x": 50, "y": 5, "w": 40, "h": 7}, "aPinned": True, "b": "hidden", "c": False, "baseUntouched": True}
    assert result["rollback"] is True and result["afterRollback"] == "visible"
    assert result["drop"] is True and result["aAfterDrop"] is False
    assert result["pruneEarly"] == []
    assert result["pruneReached"] == ["a", "c"]
    assert result["pruneExpired"] == [["b", "expired"]]
    assert result["size"] == 0 and result["missingIgnored"] is True and result["versionMoves"] is True


def test_a_refused_newer_change_never_undoes_an_older_accepted_one_not_yet_received(tmp_path):
    """Reprise QA (point 8) : une opération par couche. Déplacement accepté à la révision 11 mais pas
    encore reçu, puis masquage refusé : la position et l'épingle restent dessinées, sans clignoter,
    jusqu'à ce que l'état tenu atteigne 11."""

    result = run_node(tmp_path, r"""
      const base=state([obj('a','window',{geometry:{x:0,y:0,w:64,h:40}})],[],10);
      const P=I.createPending(30000);
      const frames=[];
      const snap=()=>{const o=P.overlay(base).objects.get('a');frames.push([o.geometry.x,o.constraints.pinned_by_user,o.visibility])};
      const move=P.begin('a',{geometry:{x:30,y:0,w:64,h:40},pinned:true},0);snap();
      P.confirm('a',move,11);snap();
      const hide=P.begin('a',{visibility:'hidden'},10);snap();
      out={refusedRollback:P.rollback('a',hide)};snap();
      out.staleConfirm=P.confirm('a',hide,12);
      out.early=P.prune({...base,revision:10},20).length;snap();
      out.reached=P.prune({...base,revision:11},30).map(e=>e.id);
      out.frames=frames;out.size=P.size();
      return out;
    """)
    assert result["refusedRollback"] is True and result["staleConfirm"] is False
    assert result["frames"] == [
        [30, True, "visible"], [30, True, "visible"], [30, True, "hidden"], [30, True, "visible"], [30, True, "visible"],
    ]
    assert result["early"] == 0 and result["reached"] == ["a"] and result["size"] == 0


def test_command_responses_are_read_in_user_words(tmp_path):
    result = run_node(tmp_path, r"""
      const c=I.classifyResponse;
      return {
        applied:c(200,{outcome:'applied',reason:null,revision:7}),duplicate:c(200,{outcome:'duplicate',revision:7}),
        refused:c(200,{outcome:'rejected_authority',reason:'pinned_by_user',revision:7}),
        bulk:c(200,{outcome:'invalid',reason:'not_bulk_archivable',revision:7}),
        unknownReason:c(200,{outcome:'invalid',reason:'something_new',revision:7}),
        timeout:c(504,{error:{code:'core_timeout',message:'Core n’a pas répondu en 10 s'}}),
        notSentConnect:c(503,{error:{code:'core_unreachable',message:'Core injoignable, commande non envoyée : Cannot connect to host 127.0.0.1:53381 ssl:default'}}),
        lost:c(503,{error:{code:'core_unreachable',message:'Liaison à Core perdue (Connection reset) : issue inconnue, relire la scène.'}}),
        notSent:c(503,{error:{code:'command_not_sent',message:'Commande non envoyée'}}),
        garbage:c(502,null),teapot:c(418,{error:{code:'odd',message:'I am a teapot'}}),
        network:I.networkFailure(new TypeError('Failed to fetch')),
        pageTimeout:I.networkFailure(Object.assign(new Error('pas de réponse en 15 s'),{code:'timeout'})),
      };
    """)
    assert result["applied"]["ok"] is True and result["applied"]["revision"] == 7 and result["applied"]["message"] == ""
    assert result["duplicate"]["ok"] is True
    assert result["refused"]["message"] == "refusé : l'objet est épinglé" and result["refused"]["unknown"] is False
    assert "n’est plus un travail terminé" in result["bulk"]["message"]
    assert result["unknownReason"]["message"] == "refusé : something_new"
    assert result["timeout"]["unknown"] is True and result["timeout"]["code"] == "core_timeout"
    # Connexion refusée : rien n'est parti. Liaison coupée après l'envoi : issue inconnue.
    assert result["notSentConnect"]["unknown"] is False and result["notSentConnect"]["message"] == "Core injoignable : rien n’a été envoyé."
    assert result["lost"]["unknown"] is True and "issue inconnue" in result["lost"]["message"]
    assert result["notSent"]["unknown"] is False and "rien n’a été envoyé" in result["notSent"]["message"]
    # Le texte brut (anglais, adresses) ne va jamais à l'écran, seulement dans `detail`.
    for key in ("timeout", "notSentConnect", "lost", "notSent", "garbage", "teapot", "network", "pageTimeout"):
        assert "Cannot connect" not in result[key]["message"] and "teapot" not in result[key]["message"], key
    assert "Cannot connect" in result["notSentConnect"]["detail"]
    assert result["garbage"]["code"] == "http_502" and result["garbage"]["unknown"] is True
    assert result["teapot"]["message"] == "Erreur 418 du Control Center." and result["teapot"]["unknown"] is False
    # Une requête `fetch` sans réponse a pu partir : jamais « rien n'a été envoyé ».
    assert result["network"]["unknown"] is True and "issue inconnue" in result["network"]["message"]
    assert result["pageTimeout"]["unknown"] is True and result["pageTimeout"]["code"] == "timeout"


def test_stop_outcomes_are_worded_honestly(tmp_path):
    result = run_node(tmp_path, r"""const out=Object.fromEntries(['cancelled','already_terminal','cancel_requested','cleanup_unknown','odd'].map(o=>[o,I.stopOutcome(o)]));
      out.completedWon=I.stopOutcome('already_terminal','completed');out.failedWon=I.stopOutcome('already_terminal','failed');return out;""")
    assert result["cancelled"]["terminal"] is True and result["cancelled"]["title"] == "Tâche arrêtée"
    assert result["already_terminal"]["terminal"] is True
    # L'issue du worker a gagné la course contre l'arrêt : dite telle quelle (décision PM).
    assert result["completedWon"] == {"title": "La tâche s’était déjà terminée", "sub": "Elle a fini normalement.", "kind": "info", "terminal": True}
    assert result["failedWon"]["sub"] == "Elle a fini en échec."
    assert result["cancel_requested"]["terminal"] is False and "pas encore confirmé" in result["cancel_requested"]["sub"]
    assert result["cleanup_unknown"] == {"title": "Arrêt demandé, nettoyage non confirmé",
                                         "sub": "Le job reste en cours tant que son exécution n’est pas nettoyée.", "kind": "warn", "terminal": False}
    assert "termine l’annulation" not in json.dumps(result, ensure_ascii=False)
    assert result["odd"]["kind"] == "warn" and result["odd"]["terminal"] is False


def test_focus_moves_to_the_reading_neighbour_after_a_removal_and_coarse_pointers_need_a_longer_drag(tmp_path):
    result = run_node(tmp_path, r"""
      const order=['a','b','c','d'];
      return {
        middle:I.focusAfterRemoval(order,['b'],'b'),last:I.focusAfterRemoval(order,['d'],'d'),
        cascade:I.focusAfterRemoval(order,['b','c'],'b'),all:I.focusAfterRemoval(order,order,'a'),
        unknownCurrent:I.focusAfterRemoval(order,['a'],'zz'),
        mouse:I.dragThreshold('mouse',false),barehands:I.dragThreshold('mouse',true),touch:I.dragThreshold('touch',false),pen:I.dragThreshold('pen',false),
      };
    """)
    assert (result["middle"], result["last"], result["cascade"], result["all"], result["unknownCurrent"]) == ("c", "c", "d", None, "b")
    assert (result["mouse"], result["barehands"], result["touch"], result["pen"]) == (4, 10, 10, 10)


def test_resolver_commits_are_computed_on_the_held_state_never_on_the_optimistic_overlay(tmp_path):
    """Reprise QA (MAJOR-2) : une place libérée seulement par une modification en attente (qui peut être
    refusée) n'est jamais validée par le résolveur."""

    result = run_node(tmp_path, r"""
      const b=obj('b','agent');
      const alone=Lay.resolveLayout(state([b]));
      const spot=alone.placements.get('b');                        // place préférée de B quand elle est libre
      const held=state([obj('a','agent',{geometry:{...spot},constraints:{placed_by:'user',pinned_by_user:false}}),b],[],20);
      const P=I.createPending(30000);
      P.begin('a',{geometry:{x:100,y:40,w:6,h:6},pinned:true},0);  // l'utilisateur éloigne A (pas encore confirmé)
      const drawn=P.overlay(held);
      const drawnLayout=Lay.resolveLayout(drawn);
      const commitOn=I.commitLayout(held,drawn,drawnLayout,Lay.resolveLayout);
      const same=I.commitLayout(held,held,Lay.resolveLayout(held),()=>{throw new Error('pas de nouveau calcul')});
      const candidates=Lay.commitCandidates(held,commitOn,new Map(),0);
      const overlay=Lay.commitCandidates(held,drawnLayout,new Map(),0);
      return {spot,drawnB:drawnLayout.placements.get('b'),committed:candidates.map(c=>c.command.geometry),wouldHave:overlay.map(c=>c.command.geometry),
        reused:!!same,nullHeld:I.commitLayout(null,null,null,Lay.resolveLayout)};
    """)
    spot = {key: result["spot"][key] for key in ("x", "y", "w", "h")}
    assert result["drawnB"] == spot and result["wouldHave"] == [spot]  # ce que la version fautive validait
    assert len(result["committed"]) == 1 and result["committed"][0] != spot
    assert result["reused"] is True and result["nullHeld"] is None


def test_a_capsule_is_drawn_at_capsule_size_inside_a_larger_stored_box(tmp_path):
    """Reprise QA (point 12) : fenêtre épinglée passée en capsule par le cerveau → capsule de hauteur
    naturelle, centrée dans la boîte stockée ; rendu seulement."""

    result = run_node(tmp_path, r"""
      const box={x:-32,y:-20,w:64,h:40};
      const st=state([obj('w','window',{representation:'capsule',geometry:{...box},constraints:{placed_by:'user',pinned_by_user:true}}),
        obj('c','artifact',{representation:'capsule',geometry:{x:0,y:30,w:80,h:7}}),
        obj('wide','artifact',{representation:'capsule',geometry:{x:-150,y:50,w:280,h:8}}),
        obj('p','agent',{representation:'point',geometry:{...box}})]);
      const layout=Lay.resolveLayout(st),vp=Lay.viewport(1920,1080);
      const model=Lay.viewModel(st,layout,vp,{});
      const by=Object.fromEntries(model.nodes.map(n=>[n.id,{shape:n.shape,box:n.box,cx:n.cx,cy:n.cy}]));
      return {by,drawn:Lay.drawnBox('capsule',box),window:Lay.drawnBox('window',box),stored:st.objects.get('w').geometry};
    """)
    assert result["drawn"] == {"x": -32, "y": -3.5, "w": 64, "h": 7}
    assert result["window"] == {"x": -32, "y": -20, "w": 64, "h": 40}
    by = result["by"]
    assert by["w"]["shape"] == "capsule" and by["w"]["box"]["height"] == 42 and by["w"]["box"]["width"] == 384
    assert (by["w"]["cx"], by["w"]["cy"]) == (960, 540)  # centre de la boîte stockée
    assert by["c"]["box"] == {"left": 960, "top": 720, "width": 480, "height": 42}  # capsule ordinaire inchangée
    assert by["wide"]["box"]["width"] == 960 and by["wide"]["box"]["left"] == 960 - 150 * 6 + (280 - 160) / 2 * 6
    assert (by["p"]["cx"], by["p"]["cy"]) == (960, 540)
    assert result["stored"] == {"x": -32, "y": -20, "w": 64, "h": 40}


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


def test_a_user_geometry_is_confirmed_only_after_its_last_step_so_the_preview_never_snaps_back(tmp_path):
    """Reprise QA finale (MINOR-R2) : épingle (révision 21) puis position (révision 22). Tant que la
    position n'est pas rendue, l'élagage à la révision 21 ne retire pas l'aperçu."""

    result = run_node(tmp_path, r"""
      const base=state([obj('w','window',{geometry:{x:0,y:0,w:64,h:40},constraints:{placed_by:'brain',pinned_by_user:false}})],[],20);
      const P=I.createPending(30000);
      const token=P.begin('w',{geometry:{x:30,y:10,w:64,h:40},pinned:true},0);
      const sent=[],frames=[];let revision=20;let releaseGeometry;
      const gate=new Promise(r=>{releaseGeometry=r});
      const send=async command=>{
        sent.push(command.op);revision++;const mine=revision;
        if(command.op==='set_geometry')await gate;
        return {ok:true,outcome:'applied',revision:mine};
      };
      const running=I.commitGeometry({id:'w',box:{x:30,y:10,w:64,h:40},wasPinned:false,placed:true,send,pending:P,token});
      for(let i=0;i<5;i++)await Promise.resolve();
      const held={...base,revision:21};                  // le patch de l'épingle est arrivé
      const pruned=P.prune(held,10).length;
      frames.push(P.overlay(held).objects.get('w').geometry.x);
      releaseGeometry();
      const outcome=await running;
      frames.push(P.overlay(held).objects.get('w').geometry.x);
      const early=P.prune(held,20).length;
      const reached=P.prune({...base,revision:22},30).length;
      const unplaced=I.geometrySteps(false,false),pinned=I.geometrySteps(true,true);
      // échec de la position après l'épingle : désépinglage compensatoire et retrait de la couche
      const Q=I.createPending(30000);const t2=Q.begin('w',{geometry:{x:1,y:1,w:64,h:40},pinned:true},0);const sent2=[];
      const failing=await I.commitGeometry({id:'w',box:{x:1,y:1,w:64,h:40},wasPinned:false,placed:true,pending:Q,token:t2,
        send:async c=>{sent2.push(c.op);return c.op==='set_geometry'?{ok:false,outcome:'failed',code:'core_timeout',unknown:true}:{ok:true,outcome:'applied',revision:40}}});
      return {sent,pruned,frames,outcome,early,reached,unplaced,pinned,sent2,failing:{ok:failing.ok,step:failing.step,rolledBack:failing.rolledBack,undo:!!failing.undo},qSize:Q.size()};
    """)
    assert result["sent"] == ["pin", "set_geometry"]
    assert result["pruned"] == 0 and result["frames"] == [30, 30]  # jamais de retour à x = 0
    assert result["outcome"] == {"ok": True, "steps": ["pin", "geometry"], "revision": 22, "pinned": True}
    assert result["early"] == 0 and result["reached"] == 1
    assert result["unplaced"] == ["geometry", "pin", "geometry"] and result["pinned"] == ["geometry"]
    assert result["sent2"] == ["pin", "set_geometry", "unpin"]
    assert result["failing"] == {"ok": False, "step": "geometry", "rolledBack": True, "undo": True} and result["qSize"] == 0


def test_a_confirmation_over_the_conversation_timeline_stays_clickable_and_gives_everything_back(tmp_path):
    """Intégration de main : deux modales `inert` (chronologie, confirmation Slice 08).

    La chronologie rend inerte chaque enfant de `body` sauf elle, y compris le
    panneau de confirmation caché. Une confirmation ouverte par-dessus doit
    rester cliquable, rendre la chronologie inerte, puis tout rendre à la
    fermeture : la chronologie redevient active et le panneau retrouve l'état
    que la chronologie lui avait donné (qu'elle rétablira en se fermant).
    """

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    html = PAGE_HTML.read_text(encoding="utf-8")
    source = html[html.index("const CONFIRM="):html.index("$('#confirmGo').addEventListener")]
    script = tmp_path / "confirm-over-timeline.cjs"
    script.write_text(
        # Le balayage `inert` exempte la surimpression des mains par le contrat
        # Bare Hands (Slice 01), plus par un identifiant recopié : le module de
        # contrats est donc chargé ici comme la page le charge.
        f"const JarvisBarehandsContracts=require({json.dumps(str(RUNTIME / 'control_center_barehands_contracts.js'))});\n"
        + r"""
const el=(id,extra)=>Object.assign({id,tagName:'DIV',inert:false,hidden:true,textContent:'',isConnected:true,
  classList:{toggle(){}},replaceChildren(){},append(){},focus(){}},extra||{});
const nodes={app:el('app',{hidden:false}),timeline:el('timeline'),confirmBack:el('confirmBack'),confirmDialog:el('confirmDialog'),
  confirmTitle:el('confirmTitle'),confirmBody:el('confirmBody'),confirmGo:el('confirmGo'),confirmCancel:el('confirmCancel'),
  toasts:el('toasts'),jarvisHands:el('jarvisHands'),script:el('',{tagName:'SCRIPT'})};
const children=['app','timeline','confirmBack','toasts','jarvisHands','script'].map(k=>nodes[k]);
const document={body:{children},activeElement:nodes.app,createElement:()=>el('li')};
const $=sel=>nodes[sel.slice(1)];
function closeMenu(){}
""" + source + r"""
const inert=()=>children.filter(n=>n.inert).map(n=>n.id||n.tagName);
/* La chronologie s'ouvre : même règle que control_center_timeline.js. */
const timelineInerted=children.filter(n=>n!==nodes.timeline&&!n.inert&&n.tagName!=='SCRIPT');
for(const n of timelineInerted)n.inert=true;
nodes.timeline.hidden=false;
const out={timelineOpen:inert()};
const pending=confirmDialog({title:'t',lines:['l']});
out.withConfirm=inert();out.backClickable=!nodes.confirmBack.inert&&!nodes.confirmBack.hidden;
finishConfirm(false);
out.afterCancel=inert();
for(const n of timelineInerted)n.inert=false;
out.afterTimelineClose=inert();
pending.then(v=>{out.resolved=v;console.log(JSON.stringify(out))});
""", encoding="utf-8")
    result = json.loads(subprocess.run([node, str(script)], capture_output=True, text=True, check=True, timeout=60).stdout)

    assert result["timelineOpen"] == ["app", "confirmBack", "toasts", "jarvisHands"]
    assert result["withConfirm"] == ["app", "timeline", "toasts", "jarvisHands"] and result["backClickable"]
    assert result["afterCancel"] == result["timelineOpen"]
    assert result["afterTimelineClose"] == [] and result["resolved"] is False


def test_an_unknown_star_since_restart_offers_no_stop_and_says_why(tmp_path):
    """Slice 10 : ni arrêt ni « arrêt impossible » sur une étoile d'état inconnu ; une note le dit."""

    result = run_node(tmp_path, r"""
      const st=state([
        obj('job:u','job',{exec_state:'unknown',work_ref:{source:'job',external_id:'u'}}),
        obj('claude:u','agent',{exec_state:'unknown',work_ref:{source:'claude',external_id:'u'}}),
        obj('note','artifact',{origin:'brain',exec_state:'unknown'}),
      ]);
      const acts=id=>I.menuModel(st,id,{finished:2}).items.map(it=>it==='-'?'-':`${it.act}${it.note?'(note)':''}${it.danger?'!':''}`);
      return {job:acts('job:u'),agent:acts('claude:u'),note:acts('note'),
        label:I.menuModel(st,'job:u',{}).items.find(it=>it.act==='state-unknown').label,
        bulk:I.bulkSelection(st).ids};
    """)

    assert result["job"] == ["rep:capsule", "rep:window", "-", "pin", "hide", "-", "state-unknown(note)", "archive!", "archive-finished!"]
    assert result["agent"] == result["job"]
    assert "state-unknown(note)" not in result["note"]
    assert result["label"] == "État inconnu depuis le redémarrage de Core"
    assert result["bulk"] == []  # jamais archivé en groupe : son travail peut reprendre


# ===========================================================================
# Sélection multiple
# ===========================================================================


def test_a_band_takes_what_it_touches_whichever_way_it_is_drawn(tmp_path):
    """Demande du 19/09/2026 : « quand je clique dans le vide et que je drague,
    faire une sélection multiple ». Le rectangle se tire dans les quatre sens,
    prend ce qu'il touche — les boîtes **dessinées**, celles que l'utilisateur
    encercle, et non les places enregistrées, que le tour a déplacées — et un
    appui qui ne bouge pas n'en est pas un."""

    result = run_node(tmp_path, r"""
      const boxes=[
        {id:'a',left:100,top:100,width:20,height:20},
        {id:'b',left:300,top:260,width:20,height:20},
        {id:'loin',left:900,top:900,width:20,height:20},
        /* Juste effleuré par le coin du rectangle : il compte. */
        {id:'bord',left:320,top:280,width:40,height:40},
      ];
      const band=I.bandBox({x:320,y:280},{x:90,y:90});
      const inverse=I.bandBox({x:90,y:90},{x:320,y:280});
      const tap=I.bandBox({x:400,y:400},{x:403,y:402});
      return {band,sameBothWays:JSON.stringify(band)===JSON.stringify(inverse),
        started:I.bandStarted(band),tapStarted:I.bandStarted(tap),
        hits:I.bandHits(band,boxes).sort(),tapHits:I.bandHits(tap,boxes),
        min:I.BAND_MIN_PX};
    """)

    assert result["band"] == {"left": 90, "top": 90, "width": 230, "height": 190}
    # Tiré vers le haut à gauche ou vers le bas à droite : le même rectangle.
    assert result["sameBothWays"] is True
    assert result["started"] is True and result["tapStarted"] is False
    assert result["hits"] == ["a", "b", "bord"]
    # Un appui qui tremble de trois pixels reste un clic : il ne prend rien.
    assert result["tapHits"] == [] and result["min"] >= 4


def test_control_click_adds_and_removes_without_losing_the_order(tmp_path):
    """Demande du 19/09/2026 : « Ctrl-clic pour sélectionner plusieurs éléments,
    ou en désélectionner ». L'ordre d'entrée est gardé : la dernière entrée est
    l'ancre du menu et des flèches, et retirer un objet du milieu ne la change
    pas."""

    result = run_node(tmp_path, r"""
      const first=I.nextSelection([],['a'],'toggle');
      const second=I.nextSelection(first,['b'],'toggle');
      const third=I.nextSelection(second,['c'],'toggle');
      const middleGone=I.nextSelection(third,['b'],'toggle');
      const backAgain=I.nextSelection(middleGone,['b'],'toggle');
      return {first,second,third,middleGone,backAgain,
        /* Un rectangle tenu avec Ctrl s'ajoute, sans doublon. */
        added:I.nextSelection(['a','b'],['b','d'],'add'),
        /* Sans modificateur, il remplace. */
        replaced:I.nextSelection(['a','b'],['d','e'],'replace'),
        /* Une entrée vide ne casse rien. */
        empty:I.nextSelection(['a'],[],'replace'),
        junk:I.nextSelection(null,[null,'','a','a'],'add')};
    """)

    assert result["third"] == ["a", "b", "c"]
    assert result["middleGone"] == ["a", "c"]
    # Repris, il revient à la fin : c'est lui que l'utilisateur vient de désigner.
    assert result["backAgain"] == ["a", "c", "b"]
    assert result["added"] == ["a", "b", "d"]
    assert result["replaced"] == ["d", "e"]
    assert result["empty"] == [] and result["junk"] == ["a"]
