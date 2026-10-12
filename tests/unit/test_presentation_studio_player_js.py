"""The page's shared playback client, by node (studio de présentation, Slices 12, 14, 23; native-studio-playback-fix Slice 09).

The module under test is the real `control_center_presentation_studio_player.js`; only the window, the clock and the network are doubles.
Since Slice 09 the client draws NOTHING (the floating band `#jvStudioBand` is retired with the run stage window: a run shows inside
Variants, `test_variants_run_js.py`). Pinned here: it creates no DOM at all and never writes markup; its poll cadence (500 ms with a
timeline, 1.5 s in a run, 5 s at rest, back-off on failure, nothing while the tab is hidden); the events Variants listens to
(`jarvis:studio-view` every view, `jarvis:studio-playback` on a start or an end, `jarvis:studio-surface` read once per surface revision,
`jarvis:studio-timeline` with the surface id and the scene loaded ahead); every command ends in a state the caller can say (applied,
refused, stage failure, timeout, unreachable Core); the follower's segment facts go to Core without a command in flight; no chained-play
toggle helper (retired with the band, Slice 15); a lost Core said once.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / "control_center_presentation_studio_player.js"

PRELUDE = r"""
const P=require(process.env.JARVIS_PLAYER_JS);
/* window double: listeners, dispatchEvent, CustomEvent; a document that throws if anything tries to create an element. */
const clock={now:1_000_000,jobs:[],seq:0};
const addJob=(fn,ms)=>{const id=++clock.seq;clock.jobs.push({id,at:clock.now+ms,fn});return id};
const timers={now:()=>clock.now,setTimeout:(fn,ms)=>addJob(fn,ms),clearTimeout:id=>{clock.jobs=clock.jobs.filter(j=>j.id!==id)}};
const tick=async()=>{for(let i=0;i<10;i++)await Promise.resolve()};
const advance=async ms=>{
  const end=clock.now+ms;
  for(;;){const due=clock.jobs.filter(j=>j.at<=end).sort((a,b)=>a.at-b.at||a.id-b.id)[0];if(!due)break;
    clock.now=due.at;clock.jobs=clock.jobs.filter(j=>j!==due);due.fn();await tick()}
  clock.now=end;await tick();
};
const events=[];
class CustomEvent{constructor(type,init){this.type=type;this.detail=init&&init.detail}}
const win={listeners:{},CustomEvent,addEventListener(t,fn){(win.listeners[t]=win.listeners[t]||[]).push(fn)},
  removeEventListener(t,fn){win.listeners[t]=(win.listeners[t]||[]).filter(f=>f!==fn)},
  dispatchEvent(ev){events.push([ev.type,JSON.parse(JSON.stringify(ev.detail===undefined?null:ev.detail))]);(win.listeners[ev.type]||[]).forEach(fn=>fn(ev));return true}};
const doc={createElement(){throw new Error('the playback client must not create DOM')},getElementById(){throw new Error('no DOM lookups')}};
const toasts=[];const logs=[];
const base={phase:'playing',running:true,run_id:'r1',role:'user_presenter',jarvis_speaks:false,position:{index:2,of:14},
  scene:{scene_id:'pss_1',title:'Chiffres',number:2,of:12},item:{item_id:'psi_2',label:'Les marges',presenter:'user'},
  elapsed:{item_ms:12000,item_target_ms:30000},problems:[],notices:[],presentation_id:'pst_1',variant_id:'psv_1',
  stage_object_id:'variants-run-r1',surface:{id:'variants-run-r1',rev:3},next:null,pending:null};
const st=(extra)=>Object.assign(JSON.parse(JSON.stringify(base)),extra||{});
const script={state:st()};
const SURFACE={surface_id:'variants-run-r1',run_id:'r1',revision:3,scene_id:'pss_1',title:'Chiffres',
  prefab:{id:'presentation-studio.p1.s1',version:1,props:{title:'x'},data:{}},overlays:[]};
const requests=[];
let hook=null;
const answer=(status,body)=>({status,body});
const request=async(url,options)=>{
  const rec={url,method:options&&options.method||'GET',body:options&&options.body?JSON.parse(options.body):null,at:clock.now};
  requests.push(rec);
  if(hook){const r=hook(rec);if(r!==undefined)return r}
  if(rec.method==='GET'&&url.endsWith('/surface'))return answer(200,{surface:script.surface===undefined?SURFACE:script.surface});
  if(rec.method==='GET'&&url.endsWith('/preload'))return answer(200,{preload:script.preload||null});
  if(rec.method==='GET')return answer(200,{state:script.state});
  return answer(200,{status:'applied',command:url.split('/').pop(),state:script.state});
};
const make=(extra)=>P.createStudioPlayer(Object.assign({document:doc,window:win,request,now:timers.now,setTimeout:timers.setTimeout,
  clearTimeout:timers.clearTimeout,toast:t=>toasts.push(t),log:(level,event,data)=>logs.push([level,event])},extra||{}));
const posts=()=>requests.filter(r=>r.method==='POST').map(r=>r.url.replace('/api/presentation-studio/playback/','')+(r.body&&Object.keys(r.body).length?JSON.stringify(r.body):''));
const gets=()=>requests.filter(r=>r.method==='GET').map(r=>r.url.replace('/api/presentation-studio/playback','')||'/');
const kinds=()=>events.map(e=>e[0]);
const consoleErrors=[];const realError=console.error;console.error=(...a)=>{consoleErrors.push(a.join(' '))};
"""


def _node(tmp_path: Path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    index = len(list(tmp_path.glob("pl-js-*.cjs")))
    script = tmp_path / f"pl-js-{index}.cjs"
    script.write_text(PRELUDE + "(async()=>{\n" + body + "\n})().then(v=>{console.error=realError;console.log(JSON.stringify(v))},"
                      "e=>{console.error=realError;console.error(e&&e.stack||e);process.exit(1)});\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120,
                          env={**os.environ, "JARVIS_PLAYER_JS": str(MODULE)})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


TIMELINE = {"scene_id": "pss_1", "composition_id": "Scene", "fps": 30, "duration_frames": 300, "anchor_id": "marker", "from_frame": 180,
            "until_frame": 299, "playing": True, "seq": 2, "play_ms": 0, "tolerance_ms": 500, "problems": []}


# ------------------------------------------------------------------ no band, no DOM, no markup

def test_the_client_draws_nothing_and_the_retired_band_is_gone(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await tick();await advance(3000);
return {view:p.view().phase,keys:Object.keys(P).sort(),api:Object.keys(p).sort()};
""")
    assert out["view"] == "playing"
    assert "BAND_ID" not in out["keys"] and "STYLE" not in out["keys"] and "KEYS" not in out["keys"], "the floating band is retired"
    assert not {"band", "handleKey", "enterFullscreen", "navigate", "stageElement", "render", "place"} & set(out["api"])
    code = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "createElement", "jvStudioBand", "keydown", "fullscreen.enter",
                      "studio-stage-"):
        assert forbidden not in code, forbidden
    for forbidden in (r"(?<![\w.])item\.(text|note)", r"step\.text", r"view\.(text|note)", r"line\.text"):
        assert not re.search(forbidden, code), forbidden


# ------------------------------------------------------------------ the poll and the events Variants listens to

def test_the_poll_cadence_follows_the_run_the_timeline_rest_failures_and_visibility(tmp_path):
    out = _node(tmp_path, f"""
script.state={{phase:'idle',running:false}};
const p=make();p.start();await tick();
const at=()=>requests.filter(r=>r.method==='GET'&&r.url==='/api/presentation-studio/playback').length;
await advance(10000);const idle=at();
script.state=st();await advance(5000);requests.length=0;
await advance(3000);const run=at();
script.state=st({{timeline:{json.dumps(TIMELINE)}}});await advance(1500);requests.length=0;
await advance(3000);const timeline=at();
hook=rec=>rec.method==='GET'&&rec.url==='/api/presentation-studio/playback'?answer(503,{{error:{{code:'core_unavailable',message:'down'}}}}):undefined;
requests.length=0;await advance(20000);const failing=at();
hook=null;p.setVisible(false);requests.length=0;await advance(30000);const hidden=at();
p.setVisible(true);await tick();const back=at();
return {{idle,run,timeline,failing,hidden,back,lost:toasts.filter(t=>t.title.includes('injoignable')).length}};
""")
    assert out["idle"] == 3, "5 s at rest (the start's read, then one at 5 s and one at 10 s)"
    assert out["run"] == 2 and out["timeline"] == 6, "1.5 s during a run, 500 ms when the score drives a Remotion scene"
    assert 3 <= out["failing"] <= 6, "a failing Core backs off (never a hot loop)"
    assert out["hidden"] == 0 and out["back"] == 1, "nothing while the tab is hidden; one read when it comes back"
    assert out["lost"] == 1, "a lost Core is said once"


def test_every_view_is_an_event_and_a_start_or_an_end_is_said_at_once(tmp_path):
    out = _node(tmp_path, """
script.state={phase:'idle',running:false};
const p=make();p.start();await tick();
script.state=st();p.adopt(script.state);await tick();
script.state={phase:'stopped',running:false,run_id:'r1',last_run:{run_id:'r1',reason:'user',problems:[]}};p.adopt(script.state);await tick();
return {kinds:kinds(),playback:events.filter(e=>e[0]==='jarvis:studio-playback').map(e=>e[1].running),
  views:events.filter(e=>e[0]==='jarvis:studio-view').map(e=>e[1].view.phase)};
""")
    assert out["playback"] == [True, False]
    assert out["views"] == ["idle", "playing", "stopped"]


def test_the_surface_is_read_once_per_revision_and_dropped_when_the_run_ends(tmp_path):
    out = _node(tmp_path, """
script.state={phase:'idle',running:false};
const p=make();p.start();await tick();
script.state=st();p.adopt(script.state);await tick();
p.adopt(st());await tick();                                             // same revision: not read again
script.surface=Object.assign({},JSON.parse(JSON.stringify(SURFACE)),{revision:4,scene_id:'pss_2'});
p.adopt(st({surface:{id:'variants-run-r1',rev:4}}));await tick();
script.surface=Object.assign({},JSON.parse(JSON.stringify(SURFACE)),{surface_id:'variants-run-r9',run_id:'r9'});
p.adopt(st({surface:{id:'variants-run-r1',rev:5}}));await tick();         // another run answered: ignored, read again next time
const stale=p.surface()&&p.surface().revision;
p.adopt({phase:'stopped',running:false});await tick();
const surfaceEvents=events.filter(e=>e[0]==='jarvis:studio-surface').map(e=>e[1].surface&&[e[1].surface.surface_id,e[1].surface.revision,e[1].surface.scene_id]);
return {reads:gets().filter(g=>g==='/surface').length,surfaceEvents,stale,after:p.surface()};
""")
    assert out["surfaceEvents"] == [["variants-run-r1", 3, "pss_1"], ["variants-run-r1", 4, "pss_2"], None]
    assert out["reads"] == 3 and out["stale"] == 4, "a surface of another run is never adopted"
    assert out["after"] is None


def test_the_timeline_names_the_run_surface_and_the_scene_loaded_ahead_is_read_once(tmp_path):
    out = _node(tmp_path, f"""
const p=make();p.start();await tick();
script.preload={{scene_id:'pss_2',title:'Suite',prefab:{{id:'presentation-studio.p1.s2',version:1,props:{{}},data:{{}}}}}};
p.adopt(st({{timeline:{json.dumps(TIMELINE)},next_scene:{{scene_id:'pss_2',prefab:'presentation-studio.p1.s2@1',rev:7}}}}));await tick();
p.adopt(st({{timeline:{json.dumps(TIMELINE)},next_scene:{{scene_id:'pss_2',prefab:'presentation-studio.p1.s2@1',rev:7}}}}));await tick();
p.adopt(st());await tick();
const tl=events.filter(e=>e[0]==='jarvis:studio-timeline').map(e=>[e[1].object_id,!!e[1].timeline,e[1].preload&&e[1].preload.scene_id]);
return {{tl,preloads:gets().filter(g=>g==='/preload').length}};
""")
    assert out["preloads"] == 1, "the scene that follows is read once per announcement"
    assert out["tl"][0] == ["variants-run-r1", True, None] and ["variants-run-r1", True, "pss_2"] in out["tl"]
    assert out["tl"][-1] == ["variants-run-r1", False, None], "a last, empty timeline when it ends"


# ------------------------------------------------------------------ commands: every end is a state the caller can say

def test_every_command_ends_in_a_state_the_caller_can_say(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await tick();
const applied=await p.command('next');
hook=rec=>rec.method==='POST'?answer(409,{status:'refused',reason:'at_end',message:'the end',state:st({phase:'ended'})}):undefined;
const refused=await p.command('next');
hook=rec=>rec.method==='POST'?answer(500,{status:'stage_failed',reason:'stage_timeout',message:'not in time',state:st({phase:'paused',problems:['stage_timeout']})}):undefined;
const failed=await p.command('next');const failedProblems=p.view().problems;
hook=rec=>rec.method==='POST'?answer(422,{status:'refused',reason:'detour_invalid',message:'bad block',state:st()}):undefined;
const unprocessable=await p.command('detour',{title:'x',prefab:{id:'x.y',version:1}});
hook=rec=>rec.method==='POST'?new Promise(()=>{}):undefined;
const pending=p.command('pause');await tick();await advance(10001);const timedOut=await pending;
hook=rec=>{if(rec.method==='POST')throw new Error('fetch failed')};
const unreachable=await p.command('resume');
return {applied:applied.status,refused:[refused.status,refused.reason],failed:[failed.status,failed.reason,failedProblems],
  unprocessable:[unprocessable.status,unprocessable.reason],timedOut:[timedOut.status,timedOut.message],unreachable:[unreachable.status,unreachable.message],
  toasts:toasts.map(t=>t.title),inflight:p.state().inflight,errors:consoleErrors.length};
""")
    assert out["applied"] == "applied"
    assert out["refused"] == ["refused", "at_end"] and out["unprocessable"] == ["refused", "detour_invalid"], "a refusal is information, no toast"
    assert out["failed"] == ["stage_failed", "stage_timeout", ["stage_timeout"]]
    assert out["timedOut"][0] == "failed" and "10 s" in out["timedOut"][1]
    assert out["unreachable"][0] == "failed" and "fetch failed" in out["unreachable"][1]
    assert out["toasts"] == ["Lecture : la scène n'a pas suivi", "Lecture : commande impossible", "Lecture : commande impossible"]
    assert out["inflight"] is None and out["errors"] == 3


def test_commands_queue_in_order_and_a_full_queue_is_said_not_lost_silently(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await tick();
let release;const gate=new Promise(r=>{release=r});
hook=rec=>rec.method==='POST'?gate.then(()=>answer(200,{status:'applied',state:script.state})):undefined;
const sent=['next','next','previous','pause','resume'].map(v=>p.command(v));
const dropped=await sent[4];
release();await Promise.all(sent.slice(0,4));
return {posts:posts(),dropped:dropped.status,stats:p.stats().dropped};
""")
    assert out["posts"] == ["next", "next", "previous", "pause"] and out["dropped"] == "dropped" and out["stats"] == 1


def test_start_run_uses_the_voice_route(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await tick();
await p.startRun('pst_1','user_presenter',{variant_id:'psv_1'});
return {posts:posts(),chain:typeof p.chain};
""")
    assert out["posts"] == ['start{"presentation_id":"pst_1","role":"user_presenter","variant_id":"psv_1"}']
    # Slice 15: the band's « ▶ Slide / ▶▶ Tout » toggle helper is retired with the band; Core's `play {scope}` verb stays.
    assert out["chain"] == "undefined"


def test_the_followers_segment_facts_go_to_core_without_a_command_in_flight_or_a_toast(tmp_path):
    out = _node(tmp_path, f"""
const p=make();p.start();await tick();
p.adopt(st({{scope:'all',timeline:{json.dumps({**TIMELINE, "auto": True})}}}));
hook=rec=>rec.method==='POST'?answer(409,{{status:'refused',reason:'stale_segment',state:st({{position:{{index:3,of:14}}}})}}):undefined;
win.dispatchEvent(new CustomEvent('jarvis:studio-segment',{{detail:{{object_id:'variants-run-r1',seq:2,event:'started'}}}}));
await tick();
win.dispatchEvent(new CustomEvent('jarvis:studio-segment',{{detail:{{seq:'2',event:'done'}}}}));
win.dispatchEvent(new CustomEvent('jarvis:studio-segment',{{detail:{{seq:2,event:'ok'}}}}));
await tick();
p.stop();
win.dispatchEvent(new CustomEvent('jarvis:studio-segment',{{detail:{{seq:3,event:'done'}}}}));
await tick();
return {{posts:posts(),inflight:p.state().inflight,toasts:toasts.length,position:p.view().position,errors:consoleErrors.length}};
""")
    assert out["posts"] == ['advance{"seq":2,"event":"started"}'], "malformed facts and facts after stop never reach Core"
    assert out["inflight"] is None and out["toasts"] == 0 and out["errors"] == 0, "a fact, never a command in flight or a notice"
    assert out["position"] == {"index": 3, "of": 14}, "the state Core gives back is adopted at once"
