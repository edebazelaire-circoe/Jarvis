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


def omega_renderer_source() -> str:
    source = WORK.read_text(encoding="utf-8")
    start = source.index("  function stopMediaStream(stream)")
    end = source.index("  const omegaRenderer=new OmegaRenderer();")
    return source[start:end] + "\nglobalThis.OmegaRenderer=OmegaRenderer;\n"


def omega_harness(body: str) -> str:
    return r"""
const VALID_STATES=new Set(['idle','listening','thinking','speaking']);
const STATE_COLORS={idle:[1,2,3],listening:[1,2,3],thinking:[1,2,3],speaking:[1,2,3]};
const STATE_LABELS={idle:'IDLE',listening:'LISTENING',thinking:'THINKING',speaking:'TALKING'};
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
const lerp=(a,b,t)=>a+(b-a)*t;
const rgba=()=>'';
const document={documentElement:{dataset:{jarvisTheme:'omega'},style:{setProperty(){}}},getElementById:()=>null};
const window={matchMedia:()=>({matches:false}),AudioContext:null,webkitAudioContext:null,removeEventListener(){}};
let getUserMedia;
const navigator={mediaDevices:{getUserMedia:options=>getUserMedia(options)}};
""" + omega_renderer_source() + body


def test_omega_microphone_stops_when_listening_ends(tmp_path: Path):
    result = run_node(
        tmp_path,
        omega_harness(r"""
let trackStops=0,contextCloses=0;
const stream={getTracks:()=>[{stop(){trackStops+=1}}]};
class AudioContext {createMediaStreamSource(){return {connect(){}}}createAnalyser(){return {fftSize:0,smoothingTimeConstant:0}}close(){contextCloses+=1}}
window.AudioContext=AudioContext;getUserMedia=async()=>stream;
(async()=>{const renderer=new OmegaRenderer();renderer.mounted=true;renderer.setSnapshot({state:'listening',online:true});
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


def test_omega_late_microphone_resolution_is_stopped_and_cannot_resurrect(tmp_path: Path):
    result = run_node(
        tmp_path,
        omega_harness(r"""
let resolve,trackStops=0,contexts=0;const pending=new Promise(done=>{resolve=done});
const stream={getTracks:()=>[{stop(){trackStops+=1}}]};
class AudioContext {constructor(){contexts+=1}createMediaStreamSource(){return {connect(){}}}createAnalyser(){return {}}close(){}}
window.AudioContext=AudioContext;getUserMedia=()=>pending;
(async()=>{const renderer=new OmegaRenderer();renderer.mounted=true;renderer.setSnapshot({state:'listening',online:true});
  renderer.setSnapshot({state:'idle',online:true});resolve(stream);await Promise.resolve();await Promise.resolve();
  process.stdout.write(JSON.stringify({state:renderer.state,status:renderer.micStatus,trackStops,contexts,stream:renderer.micStream}));
})().catch(error=>{console.error(error);process.exitCode=1});
"""),
    )

    assert result == {
        "state": "idle", "status": "idle", "trackStops": 1,
        "contexts": 0, "stream": None,
    }


def test_omega_unmount_is_idempotent_and_stops_active_capture_once(tmp_path: Path):
    result = run_node(
        tmp_path,
        omega_harness(r"""
let trackStops=0,contextCloses=0;
const stream={getTracks:()=>[{stop(){trackStops+=1}}]};
class AudioContext {createMediaStreamSource(){return {connect(){}}}createAnalyser(){return {}}close(){contextCloses+=1}}
window.AudioContext=AudioContext;getUserMedia=async()=>stream;
(async()=>{const renderer=new OmegaRenderer();renderer.mounted=true;renderer.setSnapshot({state:'listening',online:true});
  await Promise.resolve();await Promise.resolve();renderer.unmount();renderer.unmount();
  process.stdout.write(JSON.stringify({mounted:renderer.mounted,status:renderer.micStatus,trackStops,contextCloses}));
})().catch(error=>{console.error(error);process.exitCode=1});
"""),
    )

    assert result == {
        "mounted": False, "status": "idle", "trackStops": 1, "contextCloses": 1,
    }


def test_appearance_render_uses_shared_catalog_cleanup_exactly_once(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    work = WORK.read_text(encoding="utf-8")
    destroy_agent = page[page.index("function destroyAgentCatalog()") : page.index("function mountAgentCatalog")]
    destroy_voice = page[page.index("function destroyVoiceCatalog()") : page.index("function mountVoiceCatalog")]
    cleanup = page[page.index("function cleanupSettingsSurface()") : page.index("function renderTabs()")]
    install = work[work.index("  function installSettingsTab()") : work.index("  function bridgeStatusApi()")]
    result = run_node(
        tmp_path,
        r"""
let agentDestroys=0,voiceDestroys=0,baseCalls=0;
const SET={tab:'appearance',renderRevision:0,agentCatalog:{destroy(){agentDestroys+=1}},voiceCatalog:null,voiceCatalogStates:{},voiceCatalogMountedRole:null};
const TABS=[{id:'voice',label:'Voix',save:true},{id:'cli',label:'Agent / CLI',save:true}];
const modalSave={style:{}},modalSub={textContent:''},modalContent={innerHTML:''};
const appearanceHtml=()=>'<section>appearance</section>',bindAppearance=()=>{},say=()=>{};
let renderTab=async()=>{baseCalls+=1;cleanupSettingsSurface()};
"""
        + destroy_agent + destroy_voice + cleanup + install
        + r"""
(async()=>{installSettingsTab();await renderTab();await renderTab();
  SET.voiceCatalog={state:{envelope:null,error:'',query:'',sort:'',filters:{},selection:new Set()},destroy(){voiceDestroys+=1}};
  SET.voiceCatalogMountedRole='realtime';await renderTab();
  process.stdout.write(JSON.stringify({agentDestroys,voiceDestroys,baseCalls,tabs:TABS.map(tab=>tab.id)}));
})().catch(error=>{console.error(error);process.exitCode=1});
""",
    )

    assert result["agentDestroys"] == 1
    assert result["voiceDestroys"] == 1
    assert result["baseCalls"] == 0
    assert result["tabs"] == ["voice", "cli", "appearance"]


def test_omega_copy_states_that_capture_only_exists_while_listening():
    source = WORK.read_text(encoding="utf-8")

    assert "En mode Listening, sa waveform centrale utilise le microphone" in source
    assert "this.state!=='listening'" in source
