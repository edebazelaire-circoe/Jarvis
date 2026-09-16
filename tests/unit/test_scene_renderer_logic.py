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

from jarvis.domain.scene import SCENE_FRAME_HALF_HEIGHT, SCENE_FRAME_HALF_WIDTH
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
    for text in (SCENE_FRAME_NOTE, BRAIN_DISPLAY_PROMPT):
        assert f"x -{SCENE_FRAME_HALF_WIDTH}..{SCENE_FRAME_HALF_WIDTH}" in text
        assert f"y -{SCENE_FRAME_HALF_HEIGHT}..{SCENE_FRAME_HALF_HEIGHT}" in text
        assert "centre" in text and "coin haut gauche" in text
    frame_lines = [line for line in BRAIN_DISPLAY_PROMPT.splitlines() if "Repère" in line]
    assert len(frame_lines) == 1 and "haut gauche ≈ x -150, y -80" in frame_lines[0]


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
      for(let i=0;i<400;i++)objects.push(obj(`claude:${i}`,'agent'));
      for(let i=0;i<100;i++)objects.push(obj(`brain-artifact-${i}`,'artifact',{origin:'brain'}));
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

    assert result["placed"] == 504 and result["outside"] == 0
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
    assert result["window"]["items"] == [
        {"label": "TAP", "ref": "TP123", "url": ""},
        {"label": "Site", "ref": "", "url": "https://example.com"},
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
        sig('a4',{category:'blocked',exec_state:'blocked',payload:{title:'blocked',summary:'',items:[]}})];
      const relations=[rel('a1','explains','a1','s1'),rel('a3','explains','a3','s3'),rel('a4','explains','a4','s4'),
        rel('not-a-signal','explains','a2','s2')];
      const s=state(objects,relations);
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1280,720));
      return Object.fromEntries(vm.nodes.filter(n=>n.signal).map(n=>[n.id,[n.live,n.urgency,n.tone]]));
    """)

    assert result == {
        "a1": [True, "high", "error"],
        "a2": [False, "none", "error"],  # retiré : garde sa catégorie, n'est plus vivant
        "a3": [True, "low", "interrupted"],
        "a4": [True, "medium", "blocked"],
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
    assert "if(window.JarvisScene)JarvisScene.gate(s.scene);" in html
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
    for selector in (".topbar", ".voicehint", ".dock", ".panel", ".live-banner", ".bgpills", ".overlay", ".toasts", ".bgpop", ".ctxmenu"):
        assert _z(html, selector) > scene, selector
    for selector in (".topbar", ".dock", ".panel", ".live-banner", ".bgpills"):
        assert _z(work, f'html[data-jarvis-theme="omega"] {selector}') > scene, selector
    assert _z(barehands, "#jarvisHands") == 2147483000
    # Relative order of the controls kept from before the registry.
    assert _z(html, ".topbar") <= _z(html, ".dock") < _z(html, ".panel") < _z(html, ".live-banner") < _z(html, ".bgpills")
