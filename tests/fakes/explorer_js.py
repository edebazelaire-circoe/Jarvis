"""Banc node de l'explorateur de variantes (studio de présentation, Slice 18).

Un script `.cjs` écrit dans `tmp_path` charge les VRAIS modules (`control_center_presentation_studio_explorer_core.js` et
`control_center_presentation_studio_explorer.js`) dans un faux DOM (`explorer_dom.cjs`) avec une horloge pilotée et un réseau scripté ;
la valeur rendue par le corps est imprimée en JSON. La preuve dans un vrai navigateur est `test_presentation_studio_explorer_browser.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CORE_JS = RUNTIME / "control_center_presentation_studio_explorer_core.js"
EXPLORER_JS = RUNTIME / "control_center_presentation_studio_explorer.js"
CMP_CORE_JS = RUNTIME / "control_center_presentation_studio_explorer_compare_core.js"
CMP_WORLD = Path(__file__).with_name("explorer_compare_world.cjs")
DOM = Path(__file__).with_name("explorer_dom.cjs")
WORLD = Path(__file__).with_name("explorer_world.cjs")

PRELUDE = r"""
const {makeEnv}=require(process.env.JARVIS_EXPLORER_DOM);
const C=require(process.env.JARVIS_EXPLORER_CORE);
const CC=require(process.env.JARVIS_EXPLORER_CMPCORE);
"""

PRELUDE_CONTROLLER = r"""
const env=makeEnv();
const {doc,win,timers}=env;
const {makeWorld,PID,vid,iso}=require(process.env.JARVIS_EXPLORER_WORLD);
const X=require(process.env.JARVIS_EXPLORER_JS);
const world=makeWorld(env);
const {installCompare}=require(process.env.JARVIS_EXPLORER_CMPWORLD);
const cmpWorld=installCompare(env,world);
const HOST='jvStudioExplorer';
const q=(sel,root)=>(root||doc).querySelector(sel);
const qa=(sel,root)=>[...(root||doc).querySelectorAll(sel)];
const host=()=>doc.getElementById(HOST);
const rowsOf=(tree)=>qa('.jvx-row',tree||q('.jvx-tree'));
const rowFor=(n)=>q(`.jvx-row[data-id="${vid(n)}"]`);
const numbers=(tree)=>rowsOf(tree).map(r=>Number(r.dataset.id.slice(-8)));
const act=(name)=>q(`.jvx-actions [data-act="${name}"]`);
const noticeText=()=>q('.jvx-notice-text').textContent;
const player={playing:false};
/* Le module plein écran de la page (Slice 03), réduit à ce que l'explorateur appelle : `enter` entre ou arme, `state`, `cancel`. */
const fsFake={calls:[],armed:null,cancelled:0,mode:'enter',
  async enter(spec){
    fsFake.calls.push(spec);
    if(fsFake.mode==='enter'){env.enterFullscreen(host());return {state:'entered',object_id:spec.object_id}}
    if(fsFake.mode==='arm'){fsFake.armed='abcd1234';return {state:'needs_gesture',object_id:spec.object_id}}
    if(fsFake.mode==='unsupported')return {state:'unsupported',code:'fullscreen_unsupported'};
    if(fsFake.mode==='throw')throw new Error('boum');
    return {state:'refused',code:'fullscreen_denied',reason:'le navigateur refuse'};
  },
  state(){return {state:fsFake.armed?'needs_gesture':'exited',armed:fsFake.armed?{id:fsFake.armed,remainingMs:20000}:null}},
  cancel(){fsFake.armed=null;fsFake.cancelled++},
};
/* Le runtime des prefabs (Slice 03 de la fondation) : l'explorateur n'appelle que `createPrefabHost({mode:'preview'})`, `mount`, `unmount`, `destroy`. */
const prefabFake={hosts:[],mounts:[],unmounts:0,destroyed:0,failMount:null,
  bundleFetcher(fn){return fn},
  createPrefabHost(deps){
    const record={mode:deps.mode,deps};prefabFake.hosts.push(record);
    return {mount(slot,instance){
        if(prefabFake.failMount)throw new Error(prefabFake.failMount);
        prefabFake.mounts.push({object_id:instance.object_id,prefab:instance.prefab,title:instance.title,props:instance.props,data:instance.data,slot});
      },unmount(){prefabFake.unmounts++},destroy(){prefabFake.destroyed++},has(){return true}};
  }};
const base=(extra)=>Object.assign({document:doc,window:win,fetch:env.fetch,setTimeout:timers.setTimeout,clearTimeout:timers.clearTimeout,setInterval:timers.setInterval,
  clearInterval:timers.clearInterval,now:timers.now,requestAnimationFrame:timers.requestAnimationFrame,toast:env.toast,console:env.console,
  storage:win.localStorage,fullscreen:fsFake,prefabHost:prefabFake,playing:()=>player.playing,report:false},extra||{});
const make=(extra)=>X.createStudioExplorer(base(extra));
/* Un arbre de démonstration : 1 -> 2 -> 3, 1 -> 4 -> 5, 1 -> 6 (7 .. n en éventail sous 6). */
const seed=(count,shape)=>{
  world.add(null);
  for(let i=2;i<=count;i++){
    const parent=shape==='chain'?i-1:shape==='fan'?1:i<=3?i-1:i===4?1:i===5?4:i===6?1:6;
    world.add(parent);
  }
  return world;
};
const opened=async(options,extra)=>{
  const ex=make(extra);
  const result=await ex.open(Object.assign({presentation_id:PID},options||{}));
  await env.advance(400);      /* l'aperçu attend 120 ms de calme avant de lire la variante */
  return {ex,result};
};
"""

def run_node(tmp_path: Path, body: str, *, controller: bool = False, timeout: int = 120) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    index = len(list(tmp_path.glob("ex-js-*.cjs")))
    script = tmp_path / f"ex-js-{index}.cjs"
    prelude = PRELUDE + (PRELUDE_CONTROLLER if controller else "")
    script.write_text(prelude + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),"
                      "e=>{console.error(e&&e.stack||e);process.exit(1)});\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False,
                          env={**os.environ, "JARVIS_EXPLORER_DOM": str(DOM), "JARVIS_EXPLORER_CORE": str(CORE_JS),
                               "JARVIS_EXPLORER_JS": str(EXPLORER_JS), "JARVIS_EXPLORER_WORLD": str(WORLD),
                               "JARVIS_EXPLORER_CMPCORE": str(CMP_CORE_JS), "JARVIS_EXPLORER_CMPWORLD": str(CMP_WORLD)})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def run_ui(tmp_path: Path, body: str, *, timeout: int = 120) -> object:
    """`run_node` avec le contrôleur, le faux DOM, le Core minuscule et les doubles (`make`, `opened`, `seed`, `world`, `fsFake`, `prefabFake`...)."""

    return run_node(tmp_path, body, controller=True, timeout=timeout)
