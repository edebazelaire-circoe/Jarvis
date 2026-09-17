"""Rendu de la scène constellation dans le Control Center (handoff
jarvis-constellation-scene-runtime, Slice 05).

Prouvé en exécutant avec node les fichiers mêmes que la page reçoit :
`control_center_scene_layout.js` (repère, AutoResolver, modèle de vue, registre
des validations) et la partie pure de `control_center_scene_page.js` (boucle de
long-poll et validation des placements, minuteries et requêtes simulées).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import pytest

from jarvis.domain.scene import SCENE_FRAME_HALF_HEIGHT, SCENE_FRAME_HALF_WIDTH, SCENE_SAFE_AREA
from jarvis.runtime.claude_local import BRAIN_DISPLAY_PROMPT
from jarvis.runtime.control_center import (
    SCENE_LAYOUT_SCRIPT_MARKER,
    SCENE_PAGE_SCRIPT_MARKER,
    ControlCenter,
)
from jarvis.runtime.display_mcp import SCENE_FRAME_NOTE

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
CLIENT_JS = RUNTIME / "control_center_scene.js"
LAYOUT_JS = RUNTIME / "control_center_scene_layout.js"
PAGE_JS = RUNTIME / "control_center_scene_page.js"
PAGE_HTML = RUNTIME / "control_center.html"

#: Outils communs aux scripts node : fabrique d'objets et d'états comme les
#: donne `JarvisSceneClient.fromSnapshot`, fausses minuteries et requêtes.
PRELUDE = r"""
const S=require(PATHS.client),L=require(PATHS.layout),P=require(PATHS.page);
function obj(id,kind,extra){
  const layer={agent:100,job:100,artifact:120,window:220,attention:300,group:50}[kind];
  return Object.assign({schema_version:1,object_id:id,kind,category:kind,exec_state:'running',
    representation:kind==='window'?'window':kind==='artifact'?'capsule':'point',geometry:null,layer,order:0,
    visibility:'visible',disposition:'active',constraints:{placed_by:'runtime',pinned_by_user:false},origin:'runtime',
    work_ref:null,payload:{title:id,summary:'',items:[]}},extra||{});
}
function rel(id,kind,from,to){return {relation_id:id,kind,from_id:from,to_id:to,layer:50}}
function state(objects,relations,revision){
  return {scene_id:'scene',epoch:'e1',revision:revision||1,objects:new Map(objects.map(o=>[o.object_id,o])),
    relations:new Map((relations||[]).map(r=>[r.relation_id,r])),archived_ids:new Set()};
}
const plain=layout=>({placements:Object.fromEntries(layout.placements),resolved:layout.resolved});
const center=b=>({x:b.x+b.w/2,y:b.y+b.h/2});
const dist=(a,b)=>{const p=center(a),q=center(b);return Math.hypot(p.x-q.x,p.y-q.y)};
const overlap=(a,b)=>Math.min(a.x+a.w,b.x+b.w)>Math.max(a.x,b.x)&&Math.min(a.y+a.h,b.y+b.h)>Math.max(a.y,b.y);
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve()};
const T={now:0,seq:0,timers:new Map(),
  set(fn,ms){const id=++this.seq;this.timers.set(id,{at:this.now+Math.max(0,ms),fn});return id},
  clear(id){this.timers.delete(id)},
  pending(){return [...this.timers.values()].map(t=>t.at-this.now).sort((a,b)=>a-b)},
  async advance(ms){
    const end=this.now+ms;
    for(;;){
      let next=null;
      for(const [id,t] of this.timers)if(t.at<=end&&(!next||t.at<next[1].at))next=[id,t];
      if(!next)break;
      this.timers.delete(next[0]);this.now=next[1].at;next[1].fn();await flush();
    }
    this.now=end;await flush();
  }};
function snapshotBody(objects,revision,epoch){
  return {source:'core',core_reachable:true,scene:{state:'ready',code:null,saturated:false,objects:objects.length,object_limit:512},
    scene_id:'scene',epoch:epoch||'e1',revision,
    snapshot:{schema_version:1,scene_id:'scene',revision,objects,relations:[],archived_ids:[]},error:null};
}
function patchesBody(from,objects,epoch){
  return {source:'core',core_reachable:true,scene:{state:'ready',code:null},scene_id:'scene',epoch:epoch||'e1',
    revision:from+objects.length,resync_required:false,more:false,
    patches:objects.map((o,i)=>({schema_version:1,revision:from+i+1,ops:[{op:'put_object',object:o}]})),error:null};
}
function loopHarness(){
  const calls=[],views=[],logs=[];
  const loop=P.createSceneLoop({client:S,
    request:(path,options)=>new Promise((resolve,reject)=>{
      const call={path,timeoutMs:options.timeoutMs,resolve,reject,aborted:false};
      options.signal.addEventListener('abort',()=>{call.aborted=true;const e=new Error('aborted');e.name='AbortError';reject(e)});
      calls.push(call);
    }),
    setTimeout:(fn,ms)=>T.set(fn,ms),clearTimeout:id=>T.clear(id),now:()=>T.now,random:()=>.5,
    createAbort:()=>new AbortController(),onUpdate:v=>views.push(v),log:(level,event,data)=>logs.push([level,event])});
  const open=()=>calls.filter(c=>!c.done&&!c.aborted);
  const answer=async body=>{const c=open()[0];c.done=true;c.resolve(body);await flush()};
  const fail=async error=>{const c=open()[0];c.done=true;c.reject(error);await flush()};
  return {loop,calls,views,logs,open,answer,fail};
}
"""


def run_node(tmp_path: Path, body: str, data: Any = None) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    paths = {"client": str(CLIENT_JS), "layout": str(LAYOUT_JS), "page": str(PAGE_JS)}
    index = len(list(tmp_path.glob("scene-render-*.cjs")))
    data_file = tmp_path / f"scene-render-{index}.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / f"scene-render-{index}.cjs"
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


# ---------------------------------------------------------------- repère


def test_the_frame_matches_the_domain_and_maps_any_window_without_distortion(tmp_path):
    result = run_node(tmp_path, r"""
      const out={frame:L.FRAME};
      for(const [w,h] of [[1920,1080],[1280,720],[1000,1000],[3440,1440],[390,844]]){
        const vp=L.viewport(w,h);
        out[`${w}x${h}`]={scale:vp.scale,visible:vp.visible,topLeft:L.toScreen(vp,{x:-160,y:-90,w:320,h:180}),
          origin:L.toScreen(vp,{x:0,y:0,w:10,h:10})};
      }
      return out;
    """)

    assert result["frame"] == {"halfWidth": SCENE_FRAME_HALF_WIDTH, "halfHeight": SCENE_FRAME_HALF_HEIGHT}
    full = result["1920x1080"]
    assert full["scale"] == 6 and full["topLeft"] == {"left": 0, "top": 0, "width": 1920, "height": 1080}
    assert full["origin"]["left"] == 960 and full["origin"]["top"] == 540  # (0,0) = centre de la fenêtre
    assert result["1280x720"]["scale"] == 4
    # Carré : le cadre de référence tient en largeur, plus de scène en hauteur.
    square = result["1000x1000"]
    assert square["scale"] == 3.125 and square["visible"]["x1"] == 160 and square["visible"]["y1"] == 160
    assert square["topLeft"]["width"] == 1000 and square["topLeft"]["top"] == 218.8
    # Très large : plus de scène en largeur, jamais d'étirement (même échelle sur x et y).
    wide = result["3440x1440"]
    assert wide["scale"] == 8 and wide["visible"]["x1"] == 215 and wide["visible"]["y1"] == 90
    for size in result.values():
        if "visible" in size:
            assert size["visible"]["x1"] >= SCENE_FRAME_HALF_WIDTH and size["visible"]["y1"] >= SCENE_FRAME_HALF_HEIGHT


def test_the_frame_is_told_to_the_brain_in_the_inspect_legend_and_the_prompt():
    x0, y0, x1, y1 = SCENE_SAFE_AREA
    for text in (SCENE_FRAME_NOTE, BRAIN_DISPLAY_PROMPT):
        assert f"zone sûre x {x0}..{x1}, y {y0}..{y1}" in text
        assert "centre" in text and "coin haut gauche" in text and "sous les commandes" in text
    assert f"x -{SCENE_FRAME_HALF_WIDTH}..{SCENE_FRAME_HALF_WIDTH}, y -{SCENE_FRAME_HALF_HEIGHT}..{SCENE_FRAME_HALF_HEIGHT}" in SCENE_FRAME_NOTE
    frame_lines = [line for line in BRAIN_DISPLAY_PROMPT.splitlines() if "Repère" in line]
    assert len(frame_lines) == 1
    line = frame_lines[0]
    assert f"x + w ≤ {x1}, y + h ≤ {y1}" in line and "x ±160 et y ±90" in line
    # L'exemple « haut gauche » du prompt et une note lisible tiennent dans la zone sûre.
    example = re.search(r"haut gauche ≈ x (-?\d+), y (-?\d+)", line)
    ex, ey = int(example.group(1)), int(example.group(2))
    assert x0 <= ex and y0 <= ey and ex + 60 <= x1 and ey + 36 <= y1


def test_the_safe_area_matches_the_domain_and_sits_inside_the_frame(tmp_path):
    result = run_node(tmp_path, "return {safe:L.SAFE_AREA,frame:L.FRAME,face:L.FACE_ZONE};")
    x0, y0, x1, y1 = SCENE_SAFE_AREA
    assert result["safe"] == {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
    assert -SCENE_FRAME_HALF_WIDTH < x0 < x1 < SCENE_FRAME_HALF_WIDTH
    assert -SCENE_FRAME_HALF_HEIGHT < y0 < y1 < SCENE_FRAME_HALF_HEIGHT


# ----------------------------------------------------------- AutoResolver


def test_pins_and_explicit_placements_are_kept_and_their_overlap_preserved(tmp_path):
    result = run_node(tmp_path, r"""
      const pinned=obj('pin','artifact',{geometry:{x:-20,y:-10,w:40,h:7},constraints:{placed_by:'user',pinned_by_user:true}});
      const brainA=obj('brainA','window',{geometry:{x:-20,y:-12,w:60,h:36},constraints:{placed_by:'brain',pinned_by_user:false},origin:'brain'});
      const brainB=obj('brainB','window',{geometry:{x:-10,y:-2,w:60,h:36},constraints:{placed_by:'brain',pinned_by_user:false},origin:'brain'});
      const committed=obj('done','agent',{geometry:{x:-65,y:-3,w:6,h:6},constraints:{placed_by:'resolver',pinned_by_user:false}});
      const free=obj('free','agent');
      const s=state([pinned,brainA,brainB,committed,free]);
      const layout=L.resolveLayout(s);
      return {layout:plain(layout),commits:L.commitCandidates(s,layout,new Map(),0).map(c=>c.command)};
    """)

    placements = result["layout"]["placements"]
    assert placements["pin"] == {"x": -20, "y": -10, "w": 40, "h": 7}
    assert placements["brainA"] == {"x": -20, "y": -12, "w": 60, "h": 36}
    assert placements["brainB"] == {"x": -10, "y": -2, "w": 60, "h": 36}  # chevauchement explicite gardé
    assert placements["done"] == {"x": -65, "y": -3, "w": 6, "h": 6}
    assert result["layout"]["resolved"] == ["free"]
    free = placements["free"]
    assert not (free["x"] < -59 and free["x"] + free["w"] > -65 and free["y"] < 3 and free["y"] + free["h"] > -3)
    assert result["commits"] == [
        {"schema_version": 1, "op": "set_geometry", "object_id": "free", "geometry": free, "placed_by": "resolver"}
    ]


def test_the_resolver_is_deterministic_and_independent_of_the_window(tmp_path):
    result = run_node(tmp_path, r"""
      const build=()=>{
        const objects=[],relations=[];
        for(let i=0;i<60;i++)objects.push(obj(`claude:${i}`,i%7===0?'job':'agent',{work_ref:{source:'claude',external_id:String(i)}}));
        for(let i=1;i<60;i+=3)relations.push(rel(`parent_of!claude:${i}`,'parent_of',`claude:${i-1}`,`claude:${i}`));
        for(let i=0;i<60;i+=10){objects.push(obj(`attention!claude:${i}`,'attention',{category:'failed',work_ref:{source:'claude',external_id:String(i)}}));
          relations.push(rel(`attention!claude:${i}`,'explains',`attention!claude:${i}`,`claude:${i}`))}
        for(let i=0;i<8;i++)objects.push(obj(`brain-artifact-${i}`,'artifact',{origin:'brain'}));
        return state(objects,relations);
      };
      const a=plain(L.resolveLayout(build())),b=plain(L.resolveLayout(build()));
      return {same:JSON.stringify(a)===JSON.stringify(b),count:a.resolved.length,
        integers:Object.values(a.placements).every(p=>[p.x,p.y,p.w,p.h].every(Number.isInteger))};
    """)

    assert result == {"same": True, "count": 74, "integers": True}


def test_parent_cycles_are_tolerated_and_children_sit_near_their_parent(tmp_path):
    result = run_node(tmp_path, r"""
      const objects=['root','a','b','c','loop1','loop2','self'].map(id=>obj(id,'agent'));
      const relations=[rel('r-a','parent_of','root','a'),rel('a-b','parent_of','a','b'),rel('b-c','parent_of','b','c'),
        rel('c-a','parent_of','c','a'),rel('l1','parent_of','loop1','loop2'),rel('l2','parent_of','loop2','loop1')];
      const s=state(objects,relations);
      const anchors=L.anchorsOf(s);
      const depths=Object.fromEntries(objects.map(o=>[o.object_id,L.depthOf(anchors,o.object_id)]));
      const layout=L.resolveLayout(s),p=id=>layout.placements.get(id);
      return {depths,resolved:layout.resolved.length,
        near:{a:dist(p('a'),p('root')),b:dist(p('b'),p('a')),c:dist(p('c'),p('b')),loop:Math.min(dist(p('loop1'),p('loop2')),dist(p('loop2'),p('loop1')))}};
    """)

    assert result["resolved"] == 7
    assert max(result["depths"].values()) < 64
    for name, distance in result["near"].items():
        assert distance <= 24, (name, distance)


def test_a_signal_sits_next_to_its_star_live_or_retired(tmp_path):
    result = run_node(tmp_path, r"""
      const objects=[],relations=[];
      for(let i=0;i<24;i++)objects.push(obj(`claude:${i}`,'agent',{work_ref:{source:'claude',external_id:String(i)}}));
      objects.push(obj('attention!claude:5','attention',{category:'failed',exec_state:'failed',work_ref:{source:'claude',external_id:'5'}}));
      relations.push(rel('attention!claude:5','explains','attention!claude:5','claude:5'));
      objects.push(obj('attention!claude:17','attention',{category:'failed',exec_state:'running',work_ref:{source:'claude',external_id:'17'}}));
      const layout=L.resolveLayout(state(objects,relations)),p=id=>layout.placements.get(id);
      const nearest=id=>Math.min(...objects.filter(o=>o.kind==='agent').map(o=>dist(p(id),p(o.object_id))));
      return {live:dist(p('attention!claude:5'),p('claude:5')),retired:dist(p('attention!claude:17'),p('claude:17')),
        liveNearest:nearest('attention!claude:5'),retiredNearest:nearest('attention!claude:17')};
    """)

    assert result["live"] <= 16 and result["live"] == result["liveNearest"]
    assert result["retired"] <= 16 and result["retired"] == result["retiredNearest"]


def test_a_full_scene_is_placed_inside_the_safe_area_without_same_layer_overlap(tmp_path):
    result = run_node(tmp_path, r"""
      const objects=[];
      for(let i=0;i<448;i++)objects.push(obj(`claude:${i}`,'agent'));
      for(let i=0;i<60;i++)objects.push(obj(`brain-artifact-${i}`,'artifact',{origin:'brain'}));
      for(let i=0;i<4;i++)objects.push(obj(`brain-window-${i}`,'window',{origin:'brain'}));
      const started=Date.now();
      const layout=L.resolveLayout(state(objects));
      const ms=Date.now()-started,boxes=objects.map(o=>[o,layout.placements.get(o.object_id)]);
      let overlaps=0,outside=0;
      for(const [o,b] of boxes){
        if(b.x<L.SAFE_AREA.x0||b.y<L.SAFE_AREA.y0||b.x+b.w>L.SAFE_AREA.x1||b.y+b.h>L.SAFE_AREA.y1)outside++;
      }
      for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++)
        if(boxes[i][0].layer===boxes[j][0].layer&&overlap(boxes[i][1],boxes[j][1]))overlaps++;
      return {ms,work:layout.work,placed:layout.resolved.length,overlaps,outside,budget:L.WORK_BUDGET};
    """)

    assert result["placed"] == 512 and result["outside"] == 0
    assert result["overlaps"] == 0
    assert result["work"] < result["budget"]
    assert result["ms"] < 2000


def test_the_resolver_work_is_bounded_in_a_pathological_scene(tmp_path):
    result = run_node(tmp_path, r"""
      const objects=[];
      for(let i=0;i<256;i++)objects.push(obj(`brain-window-fixed-${i}`,'window',{origin:'brain',geometry:{x:-150,y:-80,w:290,h:160},constraints:{placed_by:'brain',pinned_by_user:false}}));
      for(let i=0;i<256;i++)objects.push(obj(`brain-window-${i}`,'window',{origin:'brain'}));
      const started=Date.now();
      const layout=L.resolveLayout(state(objects));
      return {ms:Date.now()-started,work:layout.work,placed:layout.resolved.length,budget:L.WORK_BUDGET,
        again:JSON.stringify(plain(layout))===JSON.stringify(plain(L.resolveLayout(state(objects))))};
    """)

    assert result["placed"] == 256 and result["again"] is True
    assert result["work"] <= result["budget"] + 600
    assert result["ms"] < 3000


def test_hidden_objects_are_neither_placed_nor_rendered(tmp_path):
    result = run_node(tmp_path, r"""
      const s=state([obj('shown','agent'),obj('hidden','agent',{visibility:'hidden'}),
        obj('hiddenPlaced','window',{visibility:'hidden',geometry:{x:0,y:0,w:10,h:10}})],[rel('p','parent_of','shown','hidden')]);
      const layout=L.resolveLayout(s),vm=L.viewModel(s,layout,L.viewport(1280,720));
      return {placed:[...layout.placements.keys()],nodes:vm.nodes.map(n=>n.id),edges:vm.edges.length,hidden:vm.hidden,
        commits:L.commitCandidates(s,layout,new Map(),0).map(c=>c.objectId)};
    """)

    assert result == {"placed": ["shown"], "nodes": ["shown"], "edges": 0, "hidden": 2, "commits": ["shown"]}


# --------------------------------------------------------- modèle de vue


def test_one_identity_across_point_capsule_and_window(tmp_path):
    result = run_node(tmp_path, r"""
      const payload={title:'Recherche Lisbonne',summary:'Vols\nHôtels',items:[{label:'TAP',ref:'TP123'},{label:'Site',url:'https://example.com'}]};
      const out={};
      for(const representation of ['point','capsule','window']){
        const s=state([obj('brain-artifact-1','artifact',{representation,payload,category:'research',origin:'brain',
          geometry:{x:10,y:10,w:60,h:36},constraints:{placed_by:'brain',pinned_by_user:false}})]);
        const n=L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080)).nodes[0];
        out[representation]={id:n.id,representation:n.representation,tone:n.tone,title:n.title,summary:n.summary,items:n.items,box:n.box,cx:n.cx};
      }
      return out;
    """)

    assert {v["id"] for v in result.values()} == {"brain-artifact-1"}
    assert {v["tone"] for v in result.values()} == {"research"}
    assert result["point"]["summary"] == "" and result["point"]["items"] == []
    assert result["capsule"]["title"] == "Recherche Lisbonne" and result["capsule"]["summary"] == ""
    assert result["window"]["summary"] == "Vols\nHôtels"
    # Slice 07 : une URL validée devient un lien ouvrable (`href` normalisé, hôte affiché), plus un texte.
    assert result["window"]["items"] == [
        {"label": "TAP", "ref": "TP123", "url": "", "href": "", "host": ""},
        {"label": "Site", "ref": "", "url": "", "href": "https://example.com/", "host": "example.com"},
    ]
    assert result["window"]["box"] == {"left": 1020, "top": 600, "width": 360, "height": 216}
    assert result["point"]["cx"] == 1200  # centre de la boîte, même position quelle que soit la forme


def test_live_signals_follow_the_relation_and_process_stopped_is_low_urgency(tmp_path):
    result = run_node(tmp_path, r"""
      const star=id=>obj(id,'agent',{exec_state:'failed'});
      const sig=(id,extra)=>obj(id,'attention',extra);
      const objects=[star('s1'),star('s2'),star('s3'),star('s4'),
        sig('a1',{category:'failed',exec_state:'failed',payload:{title:'TimeoutError',summary:'',items:[]}}),
        sig('a2',{category:'failed',exec_state:'running',payload:{title:'TimeoutError',summary:'',items:[]}}),
        sig('a3',{category:'interrupted',exec_state:'interrupted',payload:{title:'process_stopped',summary:'',items:[]}}),
        sig('a4',{category:'blocked',exec_state:'blocked',payload:{title:'blocked',summary:'',items:[]}}),
        star('s5'),sig('a5',{category:'interrupted',exec_state:'interrupted',origin:'brain',payload:{title:'process_stopped',summary:'',items:[]}}),
        star('s6'),sig('a6',{category:'failed',exec_state:'failed',payload:{title:'process_stopped',summary:'',items:[]}})];
      const relations=[rel('a1','explains','a1','s1'),rel('a3','explains','a3','s3'),rel('a4','explains','a4','s4'),
        rel('not-a-signal','explains','a2','s2'),rel('a5','explains','a5','s5'),rel('a6','explains','a6','s6')];
      const s=state(objects,relations);
      const labels={process_stopped:'processus arrêté'};
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1280,720),{errorLabels:labels});
      return Object.fromEntries(vm.nodes.filter(n=>n.signal).map(n=>[n.id,[n.live,n.urgency,n.tone,n.title]]));
    """)

    assert result == {
        "a1": [True, "high", "error", "TimeoutError"],
        "a2": [False, "none", "error", "TimeoutError"],  # retiré : garde sa catégorie, n'est plus vivant
        "a3": [True, "low", "interrupted", "processus arrêté"],
        "a4": [True, "medium", "blocked", "bloqué"],
        # Basse urgence : signal du runtime, catégorie interrompue et classe process_stopped.
        "a5": [True, "medium", "interrupted", "process_stopped"],
        "a6": [True, "high", "error", "processus arrêté"],
    }


def test_completed_work_stays_rendered_with_a_secondary_cue_only(tmp_path):
    result = run_node(tmp_path, r"""
      const objects=['running','completed','failed','cancelled','interrupted'].map(e=>obj(`claude:${e}`,'agent',{exec_state:e}));
      const s=state(objects);
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1280,720));
      return vm.nodes.map(n=>[n.id,n.exec,n.tone]);
    """)

    assert [row[1] for row in result] == ["running", "completed", "failed", "cancelled", "interrupted"]
    assert {row[2] for row in result} == {"agent"}  # la couleur reste la catégorie


def test_saturation_hint_offscreen_count_and_stacking(tmp_path):
    result = run_node(tmp_path, r"""
      const objects=[];
      for(let i=0;i<510;i++)objects.push(obj(`claude:${i}`,'agent'));
      objects.push(obj('far','window',{origin:'brain',geometry:{x:900,y:0,w:60,h:36},constraints:{placed_by:'brain',pinned_by_user:false},layer:1000,order:1000000}));
      objects.push(obj('low','window',{origin:'brain',geometry:{x:0,y:0,w:60,h:36},constraints:{placed_by:'brain',pinned_by_user:false},layer:0,order:-1000000}));
      const full=state(objects),partial=state(objects.slice(0,100));
      const vm=L.viewModel(full,L.resolveLayout(full),L.viewport(1920,1080));
      const small=L.viewModel(partial,L.resolveLayout(partial),L.viewport(1920,1080));
      return {capacity:vm.capacity,offscreen:vm.offscreen,smallCapacity:small.capacity,
        stack:{far:vm.nodes.find(n=>n.id==='far').stack,low:vm.nodes.find(n=>n.id==='low').stack},
        ordering:[L.stackOf(100,5)<L.stackOf(100,6),L.stackOf(100,1000000)<L.stackOf(101,-1000000),L.stackOf(300,0)>L.stackOf(220,999)]};
    """)

    assert result["capacity"] == {"objects": 512, "limit": 512, "saturated": True}
    assert result["smallCapacity"] == {"objects": 100, "limit": 512, "saturated": False}
    assert result["offscreen"] == 1
    assert result["stack"]["low"] == 1 and result["stack"]["far"] < 2**31 - 1
    assert result["ordering"] == [True, True, True]


def test_scene_text_is_neutralised_for_display(tmp_path):
    rlo, lri, pdi, zwsp, zwj, bom, lsep, psep, delete, c1, bell = (
        chr(0x202E), chr(0x2066), chr(0x2069), chr(0x200B), chr(0x200D), chr(0xFEFF), chr(0x2028), chr(0x2029),
        chr(0x7F), chr(0x85), chr(0x07),
    )
    data = {
        "title": f"fac{rlo}ture{zwsp}.exe{bom} ok{lsep}suite{bell}",
        "summary": f"ligne 1{lsep}ligne 2{psep}{lri}usurpé{pdi}\tfin{delete}{c1}\r\nderni{zwj}ère",
        "label": f"lien{rlo}gpj.exe",
        "category": f"re{zwsp}search",
    }
    result = run_node(tmp_path, r"""
      const s=state([obj('w','window',{origin:'brain',category:D.category,geometry:{x:0,y:0,w:60,h:36},
        constraints:{placed_by:'brain',pinned_by_user:false},
        payload:{title:D.title,summary:D.summary,items:[{label:D.label,ref:D.label}]}})]);
      const n=L.viewModel(s,L.resolveLayout(s),L.viewport(1280,720)).nodes[0];
      return {title:n.title,summary:n.summary,label:n.items[0].label,category:n.category,aria:n.label,
        long:L.cleanLine('x'.repeat(500),160).length};
    """, data)

    ranges = ((0x00, 0x08), (0x0B, 0x1F), (0x7F, 0x9F), (0x61C, 0x61C), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2069), (0x2028, 0x2029), (0xFEFF, 0xFEFF))
    forbidden = re.compile("[" + "".join(re.escape(chr(lo)) + "-" + re.escape(chr(hi)) for lo, hi in ranges) + "]")
    for key in ("title", "summary", "label", "category", "aria"):
        assert not forbidden.search(result[key]), (key, result[key])
    assert result["title"] == "facture.exe ok suite"
    assert result["summary"] == "ligne 1\nligne 2\nusurpé fin\ndernière"
    assert result["label"] == "liengpj.exe"
    assert result["category"] == "research"
    assert result["long"] == 160


# ------------------------------------------------ validation des placements


COMMITTER = r"""
function committerHarness(respond){
  const posts=[];
  const committer=P.createResolverCommitter({layout:L,setTimeout:(fn,ms)=>T.set(fn,ms),clearTimeout:id=>T.clear(id),
    now:()=>T.now,random:()=>0,settleMs:500,batch:32,log:()=>{},
    post:async command=>{posts.push(command);return respond(command)}});
  return {committer,posts};
}
const applied=()=>({status:200,body:{outcome:'applied',reason:null}});
"""


def test_each_unplaced_object_is_committed_once_and_domain_refusals_are_final(tmp_path):
    result = run_node(tmp_path, COMMITTER + r"""
      const reasons={a:()=>applied(),b:()=>({status:200,body:{outcome:'rejected_authority',reason:'explicit_placement'}}),
        c:()=>({status:200,body:{outcome:'rejected_authority',reason:'pinned_by_user'}}),d:()=>({status:200,body:{outcome:'duplicate',reason:null}})};
      const {committer,posts}=committerHarness(command=>reasons[command.object_id]());
      const s=state(['a','b','c','d'].map(id=>obj(id,'agent')));
      const layout=L.resolveLayout(s);
      committer.update({state:s,layout,leader:true,healthy:true});
      await T.advance(400);const early=posts.length;
      await T.advance(200);const first=posts.map(p=>[p.object_id,p.placed_by,p.op]);
      // L'état tenu n'a pas encore reçu les patchs : rien n'est renvoyé.
      for(let i=0;i<5;i++){committer.update({state:s,layout:L.resolveLayout(s),leader:true,healthy:true});await T.advance(5000)}
      return {early,first,total:posts.length,stats:committer.stats(),timers:T.pending().length};
    """)

    assert result["early"] == 0  # attente de stabilisation avant un lot
    assert result["first"] == [[i, "resolver", "set_geometry"] for i in "abcd"]
    assert result["total"] == 4
    assert result["stats"]["applied"] == 1 and result["stats"]["refused"] == 2 and result["stats"]["duplicate"] == 1
    assert result["stats"]["pending"] == 0 and result["timers"] == 0


def test_a_commit_that_was_not_applied_is_retried_at_most_three_times(tmp_path):
    result = run_node(tmp_path, COMMITTER + r"""
      const {committer,posts}=committerHarness(()=>({status:503,body:{error:{code:'command_not_sent',message:'x'}}}));
      const s=state([obj('a','agent'),obj('b','agent')]);
      committer.update({state:s,layout:L.resolveLayout(s),leader:true,healthy:true});
      const times=[];
      for(let i=0;i<80;i++){const before=posts.length;await T.advance(500);for(const p of posts.slice(before))times.push([T.now,p.object_id])}
      return {times,stats:committer.stats(),ledger:[...committer.ledger().values()].map(e=>[e.status,e.attempts,e.outcome])};
    """)

    # Un envoi non confirmé suspend tous les envois (2 s, puis 8 s) ; trois
    # envois par objet au plus, puis abandon.
    assert result["times"] == [[500, "a"], [2500, "a"], [10500, "a"], [18500, "b"], [20500, "b"], [28500, "b"]]
    assert result["ledger"] == [["done", 3, "gave_up"], ["done", 3, "gave_up"]]
    assert result["stats"]["sent"] == 6 and result["stats"]["pending"] == 0


def test_only_a_healthy_leader_commits_and_a_placement_seen_meanwhile_is_not_sent(tmp_path):
    result = run_node(tmp_path, COMMITTER + r"""
      const {committer,posts}=committerHarness(()=>applied());
      const s=state([obj('a','agent'),obj('b','agent')]);
      const layout=L.resolveLayout(s);
      committer.update({state:s,layout,leader:false,healthy:true});await T.advance(3000);
      const follower=posts.length;
      committer.update({state:s,layout,leader:true,healthy:false});await T.advance(3000);
      const unhealthy=posts.length;
      committer.update({state:s,layout,leader:true,healthy:true});
      // Avant la fin de l'attente, un patch (autre onglet, cerveau) place `a`.
      const placed=state([obj('a','agent',{geometry:{x:100,y:50,w:6,h:6},constraints:{placed_by:'brain',pinned_by_user:false}}),obj('b','agent')],[],2);
      await T.advance(100);
      committer.update({state:placed,layout:L.resolveLayout(placed),leader:true,healthy:true});
      await T.advance(3000);
      return {follower,unhealthy,sent:posts.map(p=>p.object_id)};
    """)

    assert result == {"follower": 0, "unhealthy": 0, "sent": ["b"]}


def test_a_second_tab_sees_the_committed_geometry_and_two_tabs_never_move_an_object(tmp_path):
    result = run_node(tmp_path, COMMITTER + r"""
      // Faux Core : même règle que le réducteur pour une validation du résolveur.
      let objects=[];for(let i=0;i<20;i++)objects.push(obj(`claude:${i}`,'agent'));
      let revision=1;const moves=[];
      const core=command=>{
        const i=objects.findIndex(o=>o.object_id===command.object_id);const o=objects[i];
        const same=o.geometry&&JSON.stringify(o.geometry)===JSON.stringify(command.geometry);
        if(same)return {status:200,body:{outcome:'duplicate',reason:null}};
        if(o.geometry&&o.constraints.placed_by!=='resolver')return {status:200,body:{outcome:'rejected_authority',reason:'explicit_placement'}};
        if(o.geometry)moves.push(o.object_id);
        objects[i]={...o,geometry:command.geometry,constraints:{placed_by:'resolver',pinned_by_user:false}};revision++;
        return {status:200,body:{outcome:'applied',reason:null}};
      };
      const tabA=committerHarness(core),tabB=committerHarness(core);
      // Deux onglets sans verrou partagé (repli), même état lu : sorties identiques.
      const seen=state(objects);
      tabA.committer.update({state:seen,layout:L.resolveLayout(seen),leader:true,healthy:true});
      tabB.committer.update({state:seen,layout:L.resolveLayout(seen),leader:true,healthy:true});
      await T.advance(5000);
      const firstRound={a:tabA.posts.length,b:tabB.posts.length,moves:moves.length};
      // Un troisième onglet ouvert après : il lit la géométrie validée et n'envoie rien.
      const tabC=committerHarness(core);const later=state(objects,[],revision);
      tabC.committer.update({state:later,layout:L.resolveLayout(later),leader:true,healthy:true});
      await T.advance(5000);
      return {firstRound,third:tabC.posts.length,placed:objects.every(o=>o.geometry&&o.constraints.placed_by==='resolver'),
        stableAcrossReload:JSON.stringify(plain(L.resolveLayout(later)).placements)===JSON.stringify(Object.fromEntries(objects.map(o=>[o.object_id,o.geometry])))};
    """)

    assert result["firstRound"]["moves"] == 0
    assert result["third"] == 0
    assert result["placed"] is True and result["stableAcrossReload"] is True


def test_commit_verdicts(tmp_path):
    result = run_node(tmp_path, r"""
      const cases=[[200,{outcome:'applied'}],[200,{outcome:'invalid',reason:'unknown_object'}],[503,{error:{code:'command_not_sent'}}],
        [503,{error:{code:'core_unreachable'}}],[504,{error:{code:'core_timeout'}}],[0,null],[400,{error:{code:'invalid_request'}}],
        [403,{error:{code:'scene_actor_forbidden'}}],[502,{error:{code:'core_refused'}}]];
      return cases.map(([status,body])=>{const v=L.classifyCommit(status,body);return [v.settle,v.reason]});
    """)

    assert [row[0] for row in result] == ["done", "done", "retry", "retry", "retry", "retry", "done", "done", "done"]
    assert result[2][1] == "command_not_sent" and result[6][1] == "invalid_request"


# ------------------------------------------------------------------ boucle


def test_the_loop_loads_a_snapshot_then_holds_exactly_one_long_poll(tmp_path):
    result = run_node(tmp_path, r"""
      const h=loopHarness();
      h.loop.setEnabled(true);await flush();
      const first=h.calls.map(c=>c.path);
      await h.answer(snapshotBody([],0));
      const second=h.open().map(c=>[c.path,c.timeoutMs]);
      await h.answer(patchesBody(0,[obj('claude:1','agent')]));
      const afterPatch={open:h.open().length,path:h.open()[0].path,revision:h.loop.view().state.revision,objects:h.loop.view().state.objects.size};
      await h.answer({...patchesBody(1,[]),revision:1});
      return {first,second,afterPatch,phase:h.loop.view().phase,open:h.open().length,maxOpen:1};
    """)

    assert result["first"] == ["/api/scene"]
    assert result["second"] == [["/api/scene/patches?scene_id=scene&epoch=e1&after=0&wait_s=25", 40000]]
    assert result["afterPatch"] == {"open": 1, "path": "/api/scene/patches?scene_id=scene&epoch=e1&after=1&wait_s=25", "revision": 1, "objects": 1}
    assert result["phase"] == "polling" and result["open"] == 1


def test_a_hidden_tab_aborts_its_long_poll_and_catches_up_with_patches_when_visible(tmp_path):
    result = run_node(tmp_path, r"""
      const h=loopHarness();
      h.loop.setEnabled(true);await flush();
      await h.answer(snapshotBody([obj('claude:1','agent')],4));
      const poll=h.open()[0];
      h.loop.setVisible(false);await flush();
      const hidden={aborted:poll.aborted,open:h.open().length,phase:h.loop.view().phase};
      await T.advance(120000);
      const whileHidden=h.calls.length;
      h.loop.setVisible(true);await flush();
      const resumed=h.open().map(c=>c.path);
      await h.answer(patchesBody(4,[obj('claude:2','agent')]));
      return {hidden,whileHidden,resumed,revision:h.loop.view().state.revision,objects:h.loop.view().state.objects.size};
    """)

    assert result["hidden"] == {"aborted": True, "open": 0, "phase": "paused"}
    assert result["whileHidden"] == 2
    assert result["resumed"] == ["/api/scene/patches?scene_id=scene&epoch=e1&after=4&wait_s=25"]
    assert result["revision"] == 5 and result["objects"] == 2


def test_a_busy_control_center_is_retried_after_its_delay_without_rereading_the_snapshot(tmp_path):
    result = run_node(tmp_path, r"""
      const h=loopHarness();
      h.loop.setEnabled(true);await flush();
      await h.answer(snapshotBody([],0));
      await h.answer({source:'core',core_reachable:null,scene:null,scene_id:null,epoch:null,revision:null,resync_required:false,more:false,patches:[],
        error:{code:'patch_waits_busy',message:'Trop d attentes'},retry_after_ms:1000});
      const waiting={phase:h.loop.view().phase,open:h.open().length,health:h.loop.view().health.level};
      await T.advance(1100);const before=h.calls.length;
      await T.advance(200);
      return {waiting,before,after:h.calls.map(c=>c.path.split('?')[0])};
    """)

    assert result["waiting"] == {"phase": "waiting", "open": 0, "health": "ok"}
    assert result["before"] == 2  # 1000 ms + 125 ms de gigue (hasard 0,5)
    assert result["after"] == ["/api/scene", "/api/scene/patches", "/api/scene/patches"]


def test_failures_back_off_with_jitter_and_the_first_success_restores(tmp_path):
    result = run_node(tmp_path, r"""
      const h=loopHarness();
      h.loop.setEnabled(true);await flush();
      const delays=[];
      for(let i=0;i<7;i++){
        const e=new Error('Failed to fetch');e.name='TypeError';
        await h.fail(e);
        delays.push(T.pending()[0]);
        await T.advance(T.pending()[0]);
      }
      const degraded=h.loop.view().health;
      await h.answer({source:'core',core_reachable:false,scene:null,scene_id:null,epoch:null,revision:null,snapshot:null,
        error:{code:'core_unreachable',message:'Core injoignable'}});
      const coreDown=[h.loop.view().health.code,T.pending()[0]];
      await T.advance(T.pending()[0]);
      await h.answer(snapshotBody([],0));
      return {delays,degraded:[degraded.level,degraded.code,degraded.since],coreDown,restored:h.loop.view().health.level,
        logs:h.logs.filter(l=>l[1].startsWith('scene.view_')).map(l=>l[1]),
        jitter:[P.backoffDelay(1,()=>0),P.backoffDelay(1,()=>1),P.backoffDelay(20,()=>1)]};
    """)

    assert result["delays"] == [1000, 2000, 4000, 8000, 16000, 30000, 30000]
    assert result["degraded"] == ["degraded", "TypeError", 0]
    assert result["coreDown"] == ["core_unreachable", 30000]
    assert result["restored"] == "ok"
    assert result["logs"] == ["scene.view_degraded", "scene.view_restored"]  # une entrée par transition, pas par essai
    assert result["jitter"] == [750, 1250, 37500]


def test_a_core_restart_resyncs_and_repeated_resyncs_back_off(tmp_path):
    result = run_node(tmp_path, r"""
      const h=loopHarness();
      h.loop.setEnabled(true);await flush();
      await h.answer(snapshotBody([obj('claude:1','agent')],7,'e1'));
      await h.answer({...patchesBody(7,[],'e2'),revision:1});
      const afterRestart=h.open().map(c=>c.path);
      await h.answer(snapshotBody([obj('claude:1','agent')],1,'e2'));
      const state=h.loop.view().state;
      // Réponses toujours incohérentes : plus de deux resynchronisations de suite → repli.
      for(let i=0;i<3;i++){
        await h.answer({...patchesBody(1,[],'e2'),resync_required:true});
        if(h.open().length===0)break;
        await h.answer(snapshotBody([obj('claude:1','agent')],1,'e2'));
      }
      return {afterRestart,epoch:state.epoch,revision:state.revision,open:h.open().length,pending:T.pending()};
    """)

    assert result["afterRestart"] == ["/api/scene"]
    assert result["epoch"] == "e2" and result["revision"] == 1
    assert result["open"] == 0 and result["pending"] == [1000]


def test_the_flag_off_sends_nothing_and_turning_it_off_aborts_and_forgets(tmp_path):
    result = run_node(tmp_path, r"""
      const h=loopHarness();
      h.loop.setVisible(true);h.loop.setEnabled(false);
      await T.advance(60000);
      const off=h.calls.length;
      h.loop.setEnabled(true);await flush();
      await h.answer(snapshotBody([obj('claude:1','agent')],3));
      const poll=h.open()[0];
      h.loop.setEnabled(false);await flush();
      await T.advance(60000);
      const view=h.loop.view();
      h.loop.stop();h.loop.setEnabled(true);await flush();
      return {off,aborted:poll.aborted,calls:h.calls.length,phase:view.phase,state:view.state,stopped:h.loop.view().phase,
        gate:[P.gateEnabled(undefined),P.gateEnabled({enabled:false,source:'settings'}),P.gateEnabled({enabled:'true'}),P.gateEnabled({enabled:true,source:'env'})]};
    """)

    assert result["off"] == 0
    assert result["aborted"] is True and result["calls"] == 2
    assert result["phase"] == "off" and result["state"] is None and result["stopped"] == "stopped"
    assert result["gate"] == [False, False, False, True]


# ------------------------------------------------------------------- page


async def test_the_page_injects_the_renderer_and_gates_it_on_the_status_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SCENE_ENABLED", raising=False)
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert SCENE_LAYOUT_SCRIPT_MARKER in html and SCENE_PAGE_SCRIPT_MARKER in html
    # La page ne touche à la scène que par l'interrupteur lu dans /api/status.
    # Isolé : une erreur de la scène ne casse jamais le statut ; un échec du
    # statut prévient la scène (reprise immédiate au retour).
    assert "try{if(window.JarvisScene)JarvisScene.gate(s.scene,s.scene_limits)}catch(sceneError){console.error('[scène] scene.gate_failed',sceneError)}" in html
    assert "try{if(window.JarvisScene)JarvisScene.statusLost()}catch(_sceneError)" in html
    assert 'id="sceneLayer"' not in html

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    served = (await control.index(None)).text
    for marker, source in ((SCENE_LAYOUT_SCRIPT_MARKER, LAYOUT_JS), (SCENE_PAGE_SCRIPT_MARKER, PAGE_JS)):
        assert marker not in served
        assert source.read_text(encoding="utf-8") in served
    assert served.index(CLIENT_JS.read_text(encoding="utf-8")) < served.index(LAYOUT_JS.read_text(encoding="utf-8")) < served.index(PAGE_JS.read_text(encoding="utf-8"))

    status = json.loads((await control.status(None)).text)
    assert status["scene"] == {"enabled": False, "source": "settings"}
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": True}}), encoding="utf-8")
    assert json.loads((await control.status(None)).text)["scene"] == {"enabled": True, "source": "settings"}

    # Parties pures : ni DOM, ni réseau, ni minuterie hors du bloc navigateur.
    layout = LAYOUT_JS.read_text(encoding="utf-8")
    page_core = PAGE_JS.read_text(encoding="utf-8").split("Bloc navigateur")[0]
    for source in (layout, page_core):
        code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        for forbidden in ("document.", "window.", "fetch(", "setInterval", "XMLHttpRequest", "addEventListener", "innerHTML", "localStorage"):
            assert forbidden not in code, forbidden
    # Le texte de la scène n'entre dans le DOM que par textContent.
    assert "innerHTML" not in PAGE_JS.read_text(encoding="utf-8")


def _z(css: str, selector: str) -> int:
    match = re.search(re.escape(selector) + r"\{[^}]*?z-index:(\d+)", css)
    assert match, selector
    return int(match.group(1))


def test_the_scene_layer_sits_above_the_face_and_below_every_control():
    html = PAGE_HTML.read_text(encoding="utf-8")
    work = (RUNTIME / "control_center_work.js").read_text(encoding="utf-8")
    page = PAGE_JS.read_text(encoding="utf-8")
    barehands = (RUNTIME / "control_center_barehands.js").read_text(encoding="utf-8")
    scene = _z(page, ".scene")
    assert scene == 20
    assert _z(html, ".face") < scene and _z(work, "#omegaFace") < scene
    for selector in (".topbar", ".voicehint", ".dock", ".panel", ".live-banner", ".bgpills", ".overlay", ".toasts", ".bgpop", ".ctxmenu", ".tl", ".cdialog-back"):
        assert _z(html, selector) > scene, selector
    # Chronologie de conversation (modale plein écran, intégration de main) :
    # au-dessus de tous les contrôles de la page, sous les menus, toasts et
    # confirmations qui peuvent s'ouvrir par-dessus.
    for selector in (".dock", ".panel", ".live-banner", ".bgpills"):
        assert _z(html, ".tl") > _z(html, selector) and _z(html, ".tl") > _z(work, f'html[data-jarvis-theme="omega"] {selector}'), selector
    assert _z(html, ".tl") < _z(html, ".overlay") < _z(html, ".toasts") < _z(html, ".ctxmenu") < _z(html, ".cdialog-back")
    for selector in (".topbar", ".dock", ".panel", ".live-banner", ".bgpills"):
        assert _z(work, f'html[data-jarvis-theme="omega"] {selector}') > scene, selector
    assert _z(barehands, "#jarvisHands") == 2147483000
    # Relative order of the controls kept from before the registry.
    assert _z(html, ".topbar") <= _z(html, ".dock") < _z(html, ".panel") < _z(html, ".live-banner") < _z(html, ".bgpills")


def test_animations_are_bounded_with_urgent_signals_first(tmp_path):
    result = run_node(tmp_path, r"""
      const objects=[],relations=[];
      for(let i=0;i<60;i++)objects.push(obj(`claude:${i}`,'agent',{exec_state:'running'}));
      for(let i=0;i<5;i++){objects.push(obj(`attention!claude:${i}`,'attention',{category:'failed',exec_state:'failed'}));relations.push(rel(`attention!claude:${i}`,'explains',`attention!claude:${i}`,`claude:${i}`))}
      for(let i=5;i<8;i++){objects.push(obj(`attention!claude:${i}`,'attention',{category:'blocked',exec_state:'blocked'}));relations.push(rel(`attention!claude:${i}`,'explains',`attention!claude:${i}`,`claude:${i}`))}
      const s=state(objects,relations);
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080));
      const animated=vm.nodes.filter(n=>n.animate);
      /* La page ne propose que les nœuds dont l'état vient de changer. */
      const fresh=new Set(['claude:59','attention!claude:6']);
      const quiet=L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080),{animatable:n=>fresh.has(n.id)});
      return {count:animated.length,max:L.MAX_ANIMATED,signals:animated.filter(n=>n.signal).length,
        firstStar:animated.find(n=>!n.signal).id,stillRunning:vm.nodes.filter(n=>!n.signal&&!n.animate).length,
        freshOnly:quiet.nodes.filter(n=>n.animate).map(n=>n.id).sort(),none:L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080),{animatable:()=>false}).nodes.filter(n=>n.animate).length};
    """)

    assert result == {"count": 24, "max": 24, "signals": 8, "firstStar": "claude:0", "stillRunning": 44,
                      "freshOnly": ["attention!claude:6", "claude:59"], "none": 0}


def test_small_boxes_are_drawn_compact_without_touching_the_scene(tmp_path):
    result = run_node(tmp_path, r"""
      const win=obj('w','window',{origin:'brain',geometry:{x:0,y:0,w:64,h:40},constraints:{placed_by:'brain',pinned_by_user:false}});
      const cap=obj('c','artifact',{origin:'brain',geometry:{x:-100,y:0,w:24,h:7},constraints:{placed_by:'brain',pinned_by_user:false}});
      const s=state([win,cap]);
      const at=(w,h)=>Object.fromEntries(L.viewModel(s,L.resolveLayout(s),L.viewport(w,h)).nodes.map(n=>[n.id,[n.representation,n.shape,n.compact,n.summary===''&&n.items.length===0]]));
      return {big:at(1920,1080),small:at(800,1000),tiny:at(400,600),
        commits:L.commitCandidates(s,L.resolveLayout(s),new Map(),0).length,repr:[...s.objects.values()].map(o=>o.representation)};
    """)

    assert result["big"] == {"w": ["window", "window", False, True], "c": ["capsule", "capsule", False, True]}
    assert result["small"] == {"w": ["window", "capsule", True, True], "c": ["capsule", "point", True, True]}
    assert result["tiny"]["w"][1] == "capsule" and result["tiny"]["c"][1] == "point"
    assert result["commits"] == 0 and result["repr"] == ["window", "capsule"]


def test_arrow_keys_move_between_nodes_in_spatial_order(tmp_path):
    result = run_node(tmp_path, r"""
      const n=(id,cx,cy)=>({id,cx,cy});
      const nodes=[n('c',500,100),n('a',100,100),n('b',300,110),n('d',100,400),n('e',320,390)];
      return {order:L.spatialOrder(nodes).map(x=>x.id),
        right:L.nextFocus(nodes,'a','ArrowRight'),rightAgain:L.nextFocus(nodes,'b','ArrowRight'),end:L.nextFocus(nodes,'c','ArrowRight'),
        down:L.nextFocus(nodes,'a','ArrowDown'),up:L.nextFocus(nodes,'e','ArrowUp'),left:L.nextFocus(nodes,'e','ArrowLeft'),
        home:L.nextFocus(nodes,'e','Home'),last:L.nextFocus(nodes,'a','End'),missing:L.nextFocus(nodes,'gone','ArrowDown'),
        none:L.nextFocus([],'a','ArrowDown')};
    """)

    assert result == {"order": ["a", "b", "c", "d", "e"], "right": "b", "rightAgain": "c", "end": "c", "down": "d",
                      "up": "b", "left": "d", "home": "a", "last": "e", "missing": "a", "none": None}


# ------------------------------------------------- meneur et suiveurs


ROLES = r"""
function tabHarness(bus,name){
  const h=loopHarness();
  /* Reconstruire la boucle avec diffusion vers le bus partagé. */
  const calls=h.calls,views=h.views,logs=h.logs;
  const loop=P.createSceneLoop({client:S,
    request:(path,options)=>new Promise((resolve,reject)=>{
      const call={path,timeoutMs:options.timeoutMs,resolve,reject,aborted:false,tab:name};
      options.signal.addEventListener('abort',()=>{call.aborted=true;const e=new Error('aborted');e.name='AbortError';reject(e)});
      calls.push(call);
    }),
    setTimeout:(fn,ms)=>T.set(fn,ms),clearTimeout:id=>T.clear(id),now:()=>T.now,random:()=>.5,
    createAbort:()=>new AbortController(),onUpdate:v=>views.push(v),log:(level,event,data)=>logs.push([level,event]),
    broadcast:message=>bus.push({...message,from:name})});
  return {...h,loop,name};
}
function deliver(bus,tabs){
  const pending=bus.splice(0);
  for(const message of pending)for(const tab of tabs)if(tab.name!==message.from)tab.loop.receive(message);
  return pending.length;
}
const longPolls=tab=>tab.calls.filter(c=>c.path.includes('/api/scene/patches')&&c.path.endsWith('wait_s=25'));
const shortReads=tab=>tab.calls.filter(c=>!c.path.endsWith('wait_s=25')).map(c=>c.path.replace(/scene_id=scene&epoch=e\d&/,''));
"""


def test_only_the_leader_long_polls_and_followers_apply_its_broadcasts(tmp_path):
    result = run_node(tmp_path, ROLES + r"""
      const bus=[];
      const leader=tabHarness(bus,'A'),follower=tabHarness(bus,'B'),other=tabHarness(bus,'C');
      leader.loop.setRole('leader');follower.loop.setRole('follower');other.loop.setRole('follower');
      for(const t of [leader,follower,other])t.loop.setEnabled(true);
      await flush();
      await leader.answer(snapshotBody([],0));
      await follower.answer(snapshotBody([],0));
      await other.answer(snapshotBody([],0));
      deliver(bus,[leader,follower,other]);await flush();
      const idle={follower:follower.loop.view().phase,open:[leader.open().length,follower.open().length,other.open().length]};
      /* Rafale : 3 réponses de patchs du meneur. */
      for(let r=0;r<3;r++){
        await leader.answer(patchesBody(r,[obj(`claude:${r}`,'agent')]));
        deliver(bus,[leader,follower,other]);await flush();
      }
      await T.advance(120000);deliver(bus,[leader,follower,other]);await flush();
      return {idle,
        revisions:[leader,follower,other].map(t=>t.loop.view().state.revision),
        objects:[follower,other].map(t=>[...t.loop.view().state.objects.keys()]),
        longPolls:[leader,follower,other].map(t=>longPolls(t).length),
        followerRequests:shortReads(follower),
        leaderBroadcasts:leader.loop.view().stats.broadcasts,
        received:follower.loop.view().stats.received};
    """)

    assert result["idle"] == {"follower": "following", "open": [1, 0, 0]}
    assert result["revisions"] == [3, 3, 3]
    assert result["objects"] == [["claude:0", "claude:1", "claude:2"]] * 2
    assert result["longPolls"][1:] == [0, 0]  # jamais de requête longue chez un suiveur
    assert result["longPolls"][0] >= 4
    # 120 s sans message du meneur (sa requête pend) : le chien de garde relit
    # les patchs manqués par une lecture courte, jamais un instantané.
    assert result["followerRequests"][0] == "/api/scene"
    assert all(path.endswith("after=3&wait_s=0") for path in result["followerRequests"][1:])
    assert result["received"] >= 6


def test_a_follower_catches_up_a_gap_with_a_short_read(tmp_path):
    result = run_node(tmp_path, ROLES + r"""
      const bus=[];
      const leader=tabHarness(bus,'A'),follower=tabHarness(bus,'B');
      leader.loop.setRole('leader');follower.loop.setRole('follower');
      leader.loop.setEnabled(true);follower.loop.setEnabled(true);await flush();
      await leader.answer(snapshotBody([],0));await follower.answer(snapshotBody([],0));
      deliver(bus,[leader,follower]);await flush();
      /* Deux réponses du meneur ; la première diffusion est perdue. */
      await leader.answer(patchesBody(0,[obj('x1','agent')]));bus.splice(0);
      await leader.answer(patchesBody(1,[obj('x2','agent')]));
      deliver(bus,[leader,follower]);await flush();
      const catching=follower.open().map(c=>c.path.replace(/scene_id=scene&epoch=e1&/,''));
      await follower.answer(patchesBody(0,[obj('x1','agent'),obj('x2','agent')]));
      return {catching,phase:follower.loop.view().phase,revision:follower.loop.view().state.revision,
        objects:[...follower.loop.view().state.objects.keys()],longPolls:longPolls(follower).length};
    """)

    assert result["catching"] == ["/api/scene/patches?after=0&wait_s=0"]
    assert result == {**result, "phase": "following", "revision": 2, "objects": ["x1", "x2"], "longPolls": 0}


def test_leader_handover_mid_burst_misses_no_patch(tmp_path):
    result = run_node(tmp_path, ROLES + r"""
      const bus=[];
      const a=tabHarness(bus,'A'),b=tabHarness(bus,'B');
      a.loop.setRole('leader');b.loop.setRole('follower');
      a.loop.setEnabled(true);b.loop.setEnabled(true);await flush();
      await a.answer(snapshotBody([],0));await b.answer(snapshotBody([],0));deliver(bus,[a,b]);await flush();
      await a.answer(patchesBody(0,[obj('p1','agent')]));deliver(bus,[a,b]);await flush();
      /* Rafale en cours : le meneur disparaît avant de diffuser la révision 2. */
      await a.answer(patchesBody(1,[obj('p2','agent')]));bus.splice(0);
      a.loop.stop();
      b.loop.setRole('leader');await flush();
      const takeover=b.open().map(c=>c.path.replace(/scene_id=scene&epoch=e1&/,''));
      await b.answer(patchesBody(1,[obj('p2','agent'),obj('p3','agent')]));
      return {takeover,revision:b.loop.view().state.revision,objects:[...b.loop.view().state.objects.keys()],
        next:b.open().map(c=>c.path.replace(/scene_id=scene&epoch=e1&/,'')),role:b.loop.view().role,
        snapshots:b.calls.filter(c=>c.path==='/api/scene').length};
    """)

    assert result["takeover"] == ["/api/scene/patches?after=1&wait_s=25"]
    assert result["revision"] == 3 and result["objects"] == ["p1", "p2", "p3"]
    assert result["next"] == ["/api/scene/patches?after=3&wait_s=25"]
    assert result["role"] == "leader" and result["snapshots"] == 1


def test_followers_resync_on_a_new_epoch_and_mirror_the_leader_outage(tmp_path):
    result = run_node(tmp_path, ROLES + r"""
      const bus=[];
      const a=tabHarness(bus,'A'),b=tabHarness(bus,'B');
      a.loop.setRole('leader');b.loop.setRole('follower');
      a.loop.setEnabled(true);b.loop.setEnabled(true);await flush();
      await a.answer(snapshotBody([obj('k','agent')],5));await b.answer(snapshotBody([obj('k','agent')],5));deliver(bus,[a,b]);await flush();
      /* Core injoignable : le meneur se replie et le dit. */
      await a.answer({source:'core',core_reachable:false,scene:null,error:{code:'core_unreachable',message:'Core injoignable'}});
      deliver(bus,[a,b]);await flush();
      const mirrored=[b.loop.view().health.level,b.loop.view().health.code,b.open().length];
      /* Core redémarré : nouvelle époque. */
      await T.advance(T.pending()[0]);
      await a.answer({...patchesBody(5,[],'e2'),revision:1});
      await a.answer(snapshotBody([obj('k','agent')],1,'e2'));
      deliver(bus,[a,b]);await flush();
      const followerRead=b.open().map(c=>c.path.replace(/scene_id=scene&/,''));
      await b.answer({...patchesBody(5,[],'e2'),revision:1});
      await b.answer(snapshotBody([obj('k','agent')],1,'e2'));
      return {mirrored,followerRead,epoch:b.loop.view().state.epoch,health:b.loop.view().health.level,
        followerRequests:b.calls.map(c=>c.path.split('?')[0]+(c.path.includes('wait_s=')?'?wait_s='+c.path.split('wait_s=')[1]:''))};
    """)

    assert result["mirrored"] == ["degraded", "core_unreachable", 0]
    assert result["followerRead"] == ["/api/scene/patches?epoch=e1&after=5&wait_s=0"]
    assert result["epoch"] == "e2" and result["health"] == "ok"
    assert result["followerRequests"] == ["/api/scene", "/api/scene/patches?wait_s=0", "/api/scene"]


def test_status_back_retries_at_once_instead_of_waiting_the_backoff(tmp_path):
    result = run_node(tmp_path, r"""
      const h=loopHarness();
      h.loop.setEnabled(true);await flush();
      for(let i=0;i<6;i++){const e=new Error('Failed to fetch');e.name='TypeError';await h.fail(e);if(i<5)await T.advance(T.pending()[0])}
      const waitingFor=T.pending()[0];
      const first=h.loop.retryNow();await flush();
      const open=h.open().map(c=>c.path);
      const second=h.loop.retryNow();
      await h.answer(snapshotBody([],0));
      return {waitingFor,first,open,second,phase:h.loop.view().phase,health:h.loop.view().health.level};
    """)

    assert result["waitingFor"] == 30000
    assert result["first"] is True and result["open"] == ["/api/scene"]
    assert result["second"] is False  # rien en attente
    assert result["phase"] == "polling" and result["health"] == "ok"


def test_messages_of_another_shape_are_ignored(tmp_path):
    result = run_node(tmp_path, r"""
      return [P.validMessage(null),P.validMessage({v:2,type:'tick'}),P.validMessage({v:1,type:'patches',scene_id:'s',epoch:'e'}),
        P.validMessage({v:1,type:'tick',scene_id:'s',epoch:'e',revision:'3',health:{}}),
        P.validMessage({v:1,type:'tick',scene_id:'s',epoch:'e',revision:3,health:{level:'ok'}}),
        P.validMessage({v:1,type:'patches',scene_id:'s',epoch:'e',body:{patches:[]}}),P.validMessage({v:1,type:'eval',code:'x'})];
    """)

    assert result == [False, False, False, False, True, True, False]


def test_a_follower_behind_a_silent_leader_is_stale_for_at_most_about_40_seconds(tmp_path):
    result = run_node(tmp_path, r"""
      /* Chronologie de qa05r_watchdog.cjs : suiveur chargé à t=0, dernier
         message du meneur à t=1 s, changement dans Core à t=1,1 s. */
      const h=loopHarness();
      h.loop.setRole('follower');h.loop.setEnabled(true);await flush();
      await h.answer(snapshotBody([],0));
      const tickMsg=rev=>({v:1,type:'tick',scene_id:'scene',epoch:'e1',revision:rev,health:{level:'ok',code:null},objectLimit:512});
      await T.advance(1000);h.loop.receive(tickMsg(0));
      await T.advance(100);
      const changeAt=T.now;let seenAt=null;
      for(let i=0;i<200&&seenAt===null;i++){
        await T.advance(500);
        if(h.open().length){seenAt=T.now;await h.answer(patchesBody(0,[obj('x','agent')]))}
      }
      const stalenessS=(seenAt-changeAt)/1000;
      /* Meneur toujours muet : au plus une lecture par tranche de 35 s. */
      const before=h.calls.length;
      for(let i=0;i<240;i++){await T.advance(500);if(h.open().length)await h.answer({...patchesBody(1,[]),revision:1})}
      const silentReads=h.calls.length-before;
      /* Meneur qui annonce sa révision toutes les 25 s : aucune lecture. */
      const g=loopHarness();
      g.loop.setRole('follower');g.loop.setEnabled(true);await flush();
      await g.answer(snapshotBody([],0));
      for(let s=0;s<300;s+=25){await T.advance(25000);g.loop.receive(tickMsg(0))}
      return {stalenessS,revision:h.loop.view().state.revision,silentReads,tickingReads:g.calls.length-1,
        timers:[P.FOLLOWER_SILENCE_MS,P.FOLLOWER_CHECK_MS]};
    """)

    assert result["stalenessS"] <= 40 and result["revision"] == 1
    assert result["silentReads"] <= 4  # 120 s de silence : lectures espacées de 35 s au moins
    assert result["tickingReads"] == 0
    assert result["timers"] == [35000, 5000]


def test_a_lock_granted_to_a_hidden_tab_is_given_back_at_once(tmp_path):
    result = run_node(tmp_path, r"""
      /* Faux Web Locks : un seul détenteur, file dans l'ordre, abandon par signal. */
      function fakeLocks(){
        let holder=null;const queue=[];
        const grant=entry=>{holder=entry;Promise.resolve(entry.cb({name:'l'})).then(()=>{holder=null;next()})};
        const next=()=>{while(!holder&&queue.length){const e=queue.shift();if(!e.aborted){grant(e);e.resolve()}}};
        return {request(name,opts,cb){
          return new Promise((resolve,reject)=>{
            if(opts.ifAvailable){if(holder){Promise.resolve(cb(null)).then(resolve);return}grant({cb});resolve();return}
            const entry={cb,resolve,aborted:false};
            if(opts.signal)opts.signal.addEventListener('abort',()=>{entry.aborted=true;const e=new Error('aborted');e.name='AbortError';reject(e)});
            queue.push(entry);next();
          });
        },held:()=>!!holder};
      }
      const locks=fakeLocks();
      const tab=(name,visible)=>{const t={name,visible,roles:[],logs:[]};
        t.lead=P.createLeadership({locks,name:'jarvis.scene.leader',createAbort:()=>new AbortController(),log:(l,e)=>t.logs.push(e),
          isVisible:()=>t.visible,isEnabled:()=>true,onRole:r=>t.roles.push(r)});return t};
      const a=tab('A',true),b=tab('B',true);
      await a.lead.decide();await flush();
      await b.lead.decide();await flush();
      const start={a:[a.lead.held(),[...a.roles]],b:[b.lead.held(),b.lead.queued(),[...b.roles]]};
      /* B devient caché avant que A rende le verrou : le verrou lui arrive quand même
         (course), il doit le rendre aussitôt et rester suiveur. */
      b.visible=false;
      const c=tab('C',true);await c.lead.decide();await flush();
      a.lead.release();await flush();await flush();
      return {start,afterRelease:{b:[b.lead.held(),b.roles,b.logs],c:[c.lead.held(),c.roles]}};
    """)

    assert result["start"] == {"a": [True, ["leader"]], "b": [False, True, ["follower"]]}
    b_held, b_roles, b_logs = result["afterRelease"]["b"]
    assert b_held is False and b_roles == ["follower", "follower"] and "scene.leader_declined" in b_logs
    assert result["afterRelease"]["c"] == [True, ["follower", "leader"]]  # le suivant visible prend le relais


def test_runtime_signals_stack_with_their_star_and_covered_alerts_are_counted(tmp_path):
    result = run_node(tmp_path, r"""
      const g=(x,y,w,h)=>({geometry:{x,y,w,h},constraints:{placed_by:'brain',pinned_by_user:false}});
      const objects=[
        obj('claude:a','agent',{exec_state:'failed',...g(-100,-10,6,6)}),
        obj('attention!claude:a','attention',{category:'failed',exec_state:'failed',...g(-96,-14,4,4)}),
        obj('claude:b','agent',{exec_state:'blocked',...g(60,-10,6,6)}),
        obj('attention!claude:b','attention',{category:'blocked',exec_state:'blocked',...g(64,-14,4,4)}),
        obj('claude:c','agent',{exec_state:'failed',...g(100,40,6,6)}),
        obj('attention!claude:c','attention',{category:'failed',exec_state:'failed',...g(104,36,4,4)}),
        obj('brain-note','attention',{origin:'brain',category:'failed',exec_state:'unknown',layer:300,...g(-98,-8,4,4)}),
        obj('brain-window-1','window',{origin:'brain',layer:220,...g(-120,-30,60,40)}),
        obj('brain-window-2','window',{origin:'brain',layer:220,...g(40,-30,60,40)}),
      ];
      const relations=[rel('attention!claude:a','explains','attention!claude:a','claude:a'),rel('attention!claude:b','explains','attention!claude:b','claude:b'),
        rel('attention!claude:c','explains','attention!claude:c','claude:c'),rel('brain-explains','explains','brain-note','claude:a')];
      const s=state(objects,relations);
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1280,720));
      const n=id=>vm.nodes.find(x=>x.id===id);
      return {signalA:n('attention!claude:a').stack-n('claude:a').stack,signalC:n('attention!claude:c').stack-n('claude:c').stack,
        brainNote:n('brain-note').stack===L.stackOf(300,0),windowAboveSignal:n('brain-window-1').stack>n('attention!claude:a').stack,
        brainAboveWindow:n('brain-note').stack>n('brain-window-1').stack,covered:vm.coveredSignals};
    """)

    assert result["signalA"] == 1 and result["signalC"] == 1
    assert result["brainNote"] is True and result["brainAboveWindow"] is True  # attention du cerveau : sa couche
    assert result["windowAboveSignal"] is True
    # a (échec) sous la fenêtre 1, b (bloqué) sous la fenêtre 2, c libre ; la note du cerveau ne compte pas.
    assert result["covered"] == {"high": 1, "medium": 1}
