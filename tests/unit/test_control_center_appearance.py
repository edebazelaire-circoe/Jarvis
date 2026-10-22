from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
WORK = ROOT / "jarvis" / "runtime" / "control_center_work.js"


def run_node(tmp_path: Path, source: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "appearance-runtime.cjs"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8",
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def cosmos_renderer_source() -> str:
    source = WORK.read_text(encoding="utf-8")
    start = source.index("  function stopMediaStream(stream)")
    end = source.index("  const cosmosRenderer=new CosmosRenderer();")
    return source[start:end] + "\nglobalThis.CosmosRenderer=CosmosRenderer;\n"


def cosmos_harness(body: str) -> str:
    return r"""
const VALID_STATES=new Set(['idle','listening','thinking','speaking']);
const STATE_COLORS={idle:[1,2,3],listening:[1,2,3],thinking:[1,2,3],speaking:[1,2,3]};
const STATE_LABELS={idle:'IDLE',listening:'LISTENING',thinking:'THINKING',speaking:'TALKING'};
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
const lerp=(a,b,t)=>a+(b-a)*t;
const rgba=()=>'';
const document={documentElement:{dataset:{jarvisTheme:'cosmos'},style:{setProperty(){}}},getElementById:()=>null};
const window={matchMedia:()=>({matches:false}),AudioContext:null,webkitAudioContext:null,removeEventListener(){}};
let getUserMedia;
const navigator={mediaDevices:{getUserMedia:options=>getUserMedia(options)}};
""" + cosmos_renderer_source() + body


def test_cosmos_microphone_stops_when_listening_ends(tmp_path: Path):
    result = run_node(
        tmp_path,
        cosmos_harness(r"""
let trackStops=0,contextCloses=0;
const stream={getTracks:()=>[{stop(){trackStops+=1}}]};
class AudioContext {createMediaStreamSource(){return {connect(){}}}createAnalyser(){return {fftSize:0,smoothingTimeConstant:0}}close(){contextCloses+=1}}
window.AudioContext=AudioContext;getUserMedia=async()=>stream;
(async()=>{const renderer=new CosmosRenderer();renderer.mounted=true;renderer.setSnapshot({state:'listening',online:true});
  await Promise.resolve();await Promise.resolve();const active=renderer.micStatus;
  renderer.setSnapshot({state:'thinking',online:true});renderer.setSnapshot({state:'idle',online:true});
  process.stdout.write(JSON.stringify({active,status:renderer.micStatus,trackStops,contextCloses,stream:renderer.micStream}));
})().catch(error=>{console.error(error);process.exitCode=1});
"""),
    )

    assert result == {
        "active": "active", "status": "idle", "trackStops": 1,
        "contextCloses": 1, "stream": None,
    }


def test_cosmos_late_microphone_resolution_is_stopped_and_cannot_resurrect(tmp_path: Path):
    result = run_node(
        tmp_path,
        cosmos_harness(r"""
let resolve,trackStops=0,contexts=0;const pending=new Promise(done=>{resolve=done});
const stream={getTracks:()=>[{stop(){trackStops+=1}}]};
class AudioContext {constructor(){contexts+=1}createMediaStreamSource(){return {connect(){}}}createAnalyser(){return {}}close(){}}
window.AudioContext=AudioContext;getUserMedia=()=>pending;
(async()=>{const renderer=new CosmosRenderer();renderer.mounted=true;renderer.setSnapshot({state:'listening',online:true});
  renderer.setSnapshot({state:'idle',online:true});resolve(stream);await Promise.resolve();await Promise.resolve();
  process.stdout.write(JSON.stringify({state:renderer.state,status:renderer.micStatus,trackStops,contexts,stream:renderer.micStream}));
})().catch(error=>{console.error(error);process.exitCode=1});
"""),
    )

    assert result == {
        "state": "idle", "status": "idle", "trackStops": 1,
        "contexts": 0, "stream": None,
    }


def test_cosmos_unmount_is_idempotent_and_stops_active_capture_once(tmp_path: Path):
    result = run_node(
        tmp_path,
        cosmos_harness(r"""
let trackStops=0,contextCloses=0;
const stream={getTracks:()=>[{stop(){trackStops+=1}}]};
class AudioContext {createMediaStreamSource(){return {connect(){}}}createAnalyser(){return {}}close(){contextCloses+=1}}
window.AudioContext=AudioContext;getUserMedia=async()=>stream;
(async()=>{const renderer=new CosmosRenderer();renderer.mounted=true;renderer.setSnapshot({state:'listening',online:true});
  await Promise.resolve();await Promise.resolve();renderer.unmount();renderer.unmount();
  process.stdout.write(JSON.stringify({mounted:renderer.mounted,status:renderer.micStatus,trackStops,contextCloses}));
})().catch(error=>{console.error(error);process.exitCode=1});
"""),
    )

    assert result == {
        "mounted": False, "status": "idle", "trackStops": 1, "contextCloses": 1,
    }


def test_theme_scene_is_a_registered_section_that_applies_in_place_and_mounts_the_scene_view(tmp_path: Path):
    """Slice 06 (jarvis-settings-ui-reorganization) : plus d'onglet `appearance` injecté dans `TABS`. La section
    `theme_scene` (alias `appearance`) dessine le thème, monte les réglages de la scène dans son emplacement, applique un
    choix tout de suite sans se redessiner (la carte choisie est marquée en place) et détruit la vue de la scène."""
    work = WORK.read_text(encoding="utf-8")
    block = work[work.index("  function appearanceHtml()") : work.index("  function bridgeStatusApi()")]
    assert "TABS" not in block.replace("plus d'onglet injecté dans `TABS`", "")
    result = run_node(
        tmp_path,
        r"""
const esc=v=>String(v);const registered=[],activated=[],view={mounts:[],destroys:0};
const window={JarvisSceneViewSettings:{mount(slot){view.mounts.push(slot&&slot.slot)},destroy(){view.destroys+=1}}};
const registerSettingsSection=spec=>{registered.push(spec);return spec};
const apiObject={current:()=>'circuit-board',activate(id){activated.push(id)},
  list:()=>[{id:'circuit-board',name:'Circuit imprimé',status:'experimental',description:'',preview:'circuit'},
            {id:'cosmos',name:'Cosmos',status:'experimental',description:'',preview:'cosmos'}]};
function makeHost(){
  const host={writes:0,inputs:[],slot:null};
  Object.defineProperty(host,'innerHTML',{set(html){host.writes+=1;host.html=html;
    host.inputs=[...html.matchAll(/value="([^"]+)" (checked)?/g)].map(m=>{
      const card={on:!!m[2],classList:{toggle(name,on){if(name==='selected')card.on=on}}};
      const listeners={};return {value:m[1],checked:!!m[2],card,closest:()=>card,
        addEventListener(type,fn){listeners[type]=fn},fire(type){listeners[type]()}};
    });host.slot=html.includes('data-scene-view-slot')?'slot':null},get(){return host.html}});
  host.querySelectorAll=sel=>sel==='input[name=jarvisTheme]'?host.inputs:[];
  host.querySelector=sel=>sel==='[data-scene-view-slot]'?{slot:host.slot}:null;
  return host;
}
"""
        + block
        + r"""
installSettingsSection();
const spec=registered[0],host=makeHost();
spec.mount(host);
const cosmos=host.inputs.find(i=>i.value==='cosmos');cosmos.checked=true;cosmos.fire('change');
spec.destroy(host);
process.stdout.write(JSON.stringify({count:registered.length,id:spec.id,category:spec.category,save:spec.save,
  aliases:spec.aliases,order:spec.order,writes:host.writes,activated,mounts:view.mounts,destroys:view.destroys,
  selected:host.inputs.map(i=>[i.value,i.card.on])}));
""",
    )

    assert result["count"] == 1
    assert (result["id"], result["category"], result["save"], result["aliases"], result["order"]) == (
        "theme_scene", "interface_interactions", "self", ["appearance"], 10)
    assert result["activated"] == ["cosmos"]
    assert result["writes"] == 1, "un choix de thème s'applique sans redessiner la section"
    assert result["selected"] == [["circuit-board", False], ["cosmos", True]]
    assert result["mounts"] == ["slot"] and result["destroys"] == 1


def test_cosmos_copy_states_that_capture_only_exists_while_listening():
    source = WORK.read_text(encoding="utf-8")

    assert "En mode Listening, sa waveform centrale utilise le microphone" in source
    assert "this.state!=='listening'" in source
