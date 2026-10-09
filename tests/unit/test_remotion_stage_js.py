"""La page de la scène Remotion et sa délégation par l'hôte des fenêtres (Slice 10), exécutées par node avec un faux DOM.

Prouvé ici (le navigateur réel le prouve de bout en bout dans `test_remotion_player_realpage_browser.py`) :
- `tick()` du chien de garde toutes les 250 ms tant qu'un cadre est monté, jamais sans cadre ; jeton de ping fort (128 bits) ;
- un cadre figé est retiré, la raison est dite en clair avec « Recharger la scène », et recharger recommence proprement ;
- le cadre est créé avec exactement `IFRAME_ATTRIBUTES` (jamais `allow-same-origin`), `src` posé avant l'insertion ;
- un échec typé de Core (moteur indisponible, erreur de compilation avec fichier:ligne, délai) est dit à l'écran, jamais un repli ;
- les valeurs de la scène sont fusionnées avec les défauts, coalescées, et seule la fenêtre parente les pilote ;
- l'hôte des fenêtres monte la page de la scène pour un paquet `{kind: "remotion"}` et jamais un `srcdoc` HTML.
Contrat : `docs/remotion-isolation.md` § 10.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain import remotion_sandbox as sb
from tests.fakes.prefab_js import HOST_JS, LAYOUT_JS, PRELUDE, PROTOCOL_JS, SHIM_JS

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
STAGE_JS = RUNTIME / "control_center_remotion_stage.js"
FRAME_JS = RUNTIME / "control_center_remotion_frame.js"
SANDBOX_PROTOCOL_JS = RUNTIME / "remotion_sandbox_protocol.js"

EXTRA = r"""
const RS=require(PATHS.rs_protocol);
const Stage=require(PATHS.stage);
const Frame=require(PATHS.frame);
FakeEl.prototype.append=function(...nodes){nodes.forEach(n=>this.appendChild(typeof n==='string'?new FakeText(n):n))};
FakeEl.prototype.contains=function(n){return n===this||this.descendants().includes(n)};
FakeEl.prototype.replaceChild=function(n,o){const at=this.childNodes.indexOf(o);if(at<0)throw new Error('not a child');if(n.parentNode)n.parentNode.removeChild(n);this.childNodes.splice(at,1,n);n.parentNode=this;o.parentNode=null;return o};
const ORIGIN='http://127.0.0.1:17654';
const DESCRIPTOR={kind:'remotion',engine:'remotion',prefab_id:'presentation-studio.p000000000001.s000000000001',version:1,title:'Scene',
  page_url:'http://127.77.0.2:17655/page/scene-'+'2'.repeat(32)+'/host-'+'1'.repeat(32),
  composition:{id:'Scene',width:1280,height:720,fps:30,durationInFrames:90},defaults:{title:'Bonjour',accent:'#3366ff'},engine_drift:false};
const ATTRS=D.attrs;
/* Banc de la page de la scène : document, fenêtre, parent, horloge à intervalles, fetch scripté, comptes rendus. */
function stageBench(opts){
  const o=opts||{};
  const doc=new FakeDocument(),win=new FakeWindow(),c=clock();
  const root=doc.createElement('div');root.id='stage';doc.body.appendChild(root);
  const parent={posted:[],postMessage(m,t){this.posted.push({message:JSON.parse(JSON.stringify(m)),target:t})}};
  const intervals=[];let seq=1000;
  const reports=[],logs=[],fetches=[];
  const response=(o.response)||{status:200,body:DESCRIPTOR};
  const deps={document:doc,window:win,parentWindow:parent,origin:ORIGIN,prefabId:DESCRIPTOR.prefab_id,version:1,iframeAttributes:ATTRS,
    fetch:async(url,init)=>{fetches.push(url);if(o.never)return new Promise(()=>{});
      if(o.fetchError)throw new Error(o.fetchError);
      return {ok:response.status<400,status:response.status,json:async()=>response.body}},
    now:c.now,setTimeout:c.setTimeout,clearTimeout:c.clearTimeout,
    setInterval:(fn,ms)=>{const id=++seq;intervals.push({id,ms,fn,active:true});return id},
    clearInterval:(id)=>{const i=intervals.find(x=>x.id===id);if(i)i.active=false},
    log:(l,k,d)=>logs.push({level:l,key:k,data:d}),report:async(r)=>{reports.push(r)}};
  const stage=Stage.createStage(deps);
  const frame=()=>doc.body.descendants().find(n=>n.tagName==='IFRAME')||null;
  const fromFrame=(data,origin)=>win.dispatch({source:frame().contentWindow,origin:origin||'null',data});
  const fromParent=(data,origin,source)=>win.dispatch({source:source||parent,origin:origin||ORIGIN,data});
  const tickAll=(ms,step)=>{for(let t=0;t<ms;t+=step||250){c.advance(step||250);intervals.filter(i=>i.active&&i.ms<=(step||250)).forEach(i=>i.fn())}};
  const text=()=>root.descendants().map(n=>n.childNodes.filter(k=>k.nodeType===3).map(k=>k.data).join('')).filter(Boolean).join(' | ');
  return {doc,win,parent,c,intervals,reports,logs,fetches,stage,frame,fromFrame,fromParent,tickAll,text,root,deps};
}
const inboxOf=(b)=>b.frame().contentWindow.posted.map(p=>p.message);
const statuses=(b)=>b.parent.posted.map(p=>p.message).filter(m=>m.type==='status');
"""


def run_stage_node(tmp_path: Path, body: str, data=None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    paths = {"layout": str(LAYOUT_JS), "protocol": str(PROTOCOL_JS), "host": str(HOST_JS), "shim": str(SHIM_JS),
             "rs_protocol": str(SANDBOX_PROTOCOL_JS), "stage": str(STAGE_JS), "frame": str(FRAME_JS)}
    index = len(list(tmp_path.glob("stage-js-*.cjs")))
    data_file = tmp_path / f"stage-js-{index}.json"
    data_file.write_text(json.dumps({"attrs": sb.IFRAME_ATTRIBUTES, **(data or {})}), encoding="utf-8")
    script = tmp_path / f"stage-js-{index}.cjs"
    script.write_text(
        f"const PATHS={json.dumps(paths)};\nconst D=JSON.parse(require('fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        + PRELUDE + EXTRA + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),e=>{console.error(e&&e.stack||e);process.exit(1)});\n",
        encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


READY_FLOW = r"""
  const b=stageBench();b.stage.start();await flush();
  const frame=b.frame();
  b.fromFrame({rs:1,type:'ready'});
"""


async def test_the_frame_is_created_with_exactly_the_contract_attributes_and_src_before_insertion(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const b=stageBench();
      let srcWhenInserted=null;
      const originalAppend=FakeEl.prototype.replaceChildren;
      FakeEl.prototype.replaceChildren=function(...nodes){nodes.forEach(n=>{if(n.tagName==='IFRAME')srcWhenInserted=n.src||null});return originalAppend.apply(this,nodes)};
      b.stage.start();await flush();
      const f=b.frame();
      return {attrs:f.attributes,srcWhenInserted,src:f.src,fetch:b.fetches,first:statuses(b).map(s=>s.phase)};
    """)
    assert result["attrs"]["sandbox"] == "allow-scripts"
    assert result["attrs"]["allow"] == "" and result["attrs"]["referrerpolicy"] == "no-referrer"
    assert "allow-same-origin" not in json.dumps(result["attrs"])
    assert result["srcWhenInserted"] == result["src"] and result["src"].startswith("http://127.77.0.2:17655/page/scene-")
    assert result["fetch"] == ["/api/remotion/player/presentation-studio.p000000000001.s000000000001/1"]
    assert result["first"][0] == "shell" and "preparing" in result["first"] and "mounting" in result["first"]


async def test_tick_runs_every_250_ms_while_a_frame_is_mounted_and_never_without_one(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      const ticking=b.intervals.filter(i=>i.active&&i.ms===250).length;
      const before=b.fetches.length;
      await flush();
      const sent=inboxOf(b).map(m=>m.type);
      b.tickAll(2000);
      const afterTicks=inboxOf(b).filter(m=>m.type==='ping');
      b.stage.setProps({title:'x'});
      return {ticking,sent,pings:afterTicks.length,token:afterTicks[0]&&afterTicks[0].n,state:b.stage.state().phase};
    """)
    assert result["ticking"] == 1, "one 250 ms interval drives the watchdog"
    assert result["sent"][:2] == ["init", "control"], "init props, then the autoplay order"
    assert result["pings"] >= 1
    token = result["token"]
    assert len(token) == 32 and all(c in "0123456789abcdef" for c in token), "the default strongToken: 128 bits, 32 hex chars"
    assert result["state"] == "ready"


async def test_a_frozen_frame_is_removed_the_reason_is_said_and_reload_starts_again(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      b.tickAll(1000);                       // a ping goes out, no pong ever comes back
      b.tickAll(4000);
      const state=b.stage.state();
      const parentStatus=statuses(b).filter(s=>s.phase==='killed');
      const panel=b.text();
      const frameGone=b.frame()===null;
      const button=b.root.descendants().find(n=>n.tagName==='BUTTON'&&n.textContent==='Recharger la scène');
      const reports=b.reports.map(r=>[r.event,r.reason]);
      button.click();await flush();
      const again=b.frame();
      return {phase:state.phase,killed:state.killedReason,parentStatus,panel,frameGone,hasButton:!!button,reports,
              reloaded:!!again&&again!==frame,fetches:b.fetches.length,generation:b.stage.state().generation};
    """)
    assert result["phase"] == "killed" and result["killed"] == "unresponsive" and result["frameGone"]
    assert "La scène ne répond plus depuis 3 s" in result["panel"] and "Recharger la scène" in result["panel"]
    assert result["hasButton"] and result["parentStatus"] and result["parentStatus"][0]["reason"] == "unresponsive"
    assert ["killed", "unresponsive"] in result["reports"], "journalised remotion.sandbox.killed through the report route"
    assert result["reloaded"] and result["fetches"] == 2 and result["generation"] == 2


async def test_a_message_from_another_window_is_not_the_frames_and_never_drives_the_stage(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      const stranger={postMessage(){}};
      b.win.dispatch({source:stranger,origin:'null',data:{rs:1,type:'pong',n:'aaaaaaaa',frame:7,dropped:0}});
      b.fromParent({rsh:1,type:'props',props:{title:'Un autre'}},'http://evil.test');                    // wrong origin
      b.fromParent({rsh:1,type:'props',props:{title:'Un autre'}},ORIGIN,stranger);                       // wrong source
      b.fromParent({rsh:1,type:'props',props:{title:'Un autre'},extra:1});                               // extra field
      b.c.advance(100);b.tickAll(100,16);
      const propsSent=inboxOf(b).filter(m=>m.type==='props');
      b.fromParent({rsh:1,type:'props',props:{title:'Le bon'}});b.tickAll(100,16);
      const good=inboxOf(b).filter(m=>m.type==='props');
      return {strangerPong:b.stage.state().supervisor.pongs,propsSent:propsSent.length,good:good.length&&good[0].props};
    """)
    assert result["strangerPong"] == 0 and result["propsSent"] == 0
    assert result["good"] == {"title": "Le bon", "accent": "#3366ff"}, "the descriptor defaults sit under the scene values"


async def test_values_changing_fast_are_coalesced_and_merged_with_the_defaults(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      b.fromParent({rsh:1,type:'props',props:{accent:'#ff0000'}});
      b.fromParent({rsh:1,type:'props',props:{accent:'#00ff00'}});
      b.fromParent({rsh:1,type:'props',props:{accent:'#0000ff',title:'Bleu'}});
      b.c.advance(40);
      const sent=inboxOf(b).filter(m=>m.type==='props');
      const init=inboxOf(b).find(m=>m.type==='init');
      return {sent:sent.map(m=>m.props),init:init.props,composition:init.composition};
    """)
    assert result["sent"] == [{"title": "Bleu", "accent": "#0000ff"}], "one message for a burst, the last values win"
    assert result["init"] == {"title": "Bonjour", "accent": "#3366ff"}
    assert result["composition"] == {"id": "Scene", "width": 1280, "height": 720, "fps": 30, "durationInFrames": 90}


async def test_play_pause_seek_and_cue_reach_the_frame_only_once_mounted_and_stay_inside_the_composition(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const b=stageBench();b.stage.start();await flush();
      const early=b.stage.control('play');                       // not mounted yet: refused, nothing sent
      b.fromFrame({rs:1,type:'ready'});
      b.stage.control('pause');b.stage.control('seek',1000);b.stage.control('seek',-5);b.stage.control('play');
      b.fromParent({rsh:1,type:'control',action:'seek',frame:10});
      b.fromParent({rsh:1,type:'cue',name:'reveal_title',frame:30});
      b.fromParent({rsh:1,type:'cue',name:'Not A Name',frame:30});
      const sent=inboxOf(b).filter(m=>m.type==='control'||m.type==='cue');
      return {early,sent:sent.map(m=>[m.type,m.action||m.name,m.frame===undefined?null:m.frame])};
    """)
    assert result["early"] is False
    assert result["sent"] == [["control", "play", None], ["control", "pause", None], ["control", "seek", 89], ["control", "seek", 0],
                              ["control", "play", None], ["control", "seek", 10], ["cue", "reveal_title", 30]]


async def test_an_engine_that_is_not_ready_is_said_with_its_repair_and_no_frame_is_ever_created(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const body={error:{code:'presentation_studio_engine_unavailable',message:'remotion is unavailable: the Remotion capability is not_installed. Repair: install or repair the Remotion capability'}};
      const b=stageBench({response:{status:409,body}});b.stage.start();await flush();
      return {frame:b.frame(),panel:b.text(),phase:b.stage.state().phase,status:statuses(b).pop(),reports:b.reports.map(r=>r.event)};
    """)
    assert result["frame"] is None and result["phase"] == "failed"
    assert "Remotion n’est pas disponible" in result["panel"] and "not_installed" in result["panel"] and "Repair" in result["panel"]
    assert "Réessayer" in result["panel"]
    assert result["status"]["phase"] == "failed" and result["status"]["reason"] == "presentation_studio_engine_unavailable"
    assert result["reports"] == ["failed"]


async def test_a_compile_error_shows_the_file_line_and_column(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const body={error:{code:'compile_source_error',message:'src/Scene.tsx:3:5: Unexpected token',
        diagnostics:[{file:'src/Scene.tsx',line:3,column:5,text:'Unexpected token'}]}};
      const b=stageBench({response:{status:422,body}});b.stage.start();await flush();
      return {panel:b.text(),frame:b.frame()};
    """)
    assert result["frame"] is None
    assert "La scène ne compile pas" in result["panel"] and "src/Scene.tsx:3:5" in result["panel"] and "Unexpected token" in result["panel"]


async def test_a_wait_has_a_live_counter_and_a_deadline_after_which_the_user_can_act(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const b=stageBench({never:true});b.stage.start();await flush();
      b.tickAll(3000,1000);
      const waiting=b.text();
      b.c.advance(150000);await flush();
      return {waiting,after:b.text(),phase:b.stage.state().phase,status:statuses(b).pop()};
    """)
    assert "Préparation de la scène Remotion… 3 s" in result["waiting"], "THAT it runs, WHAT it does, HOW LONG"
    assert result["phase"] == "failed" and "150 s" in result["after"] and "Réessayer" in result["after"]
    assert result["status"]["phase"] == "failed"


async def test_an_unreachable_core_is_a_visible_failure_not_an_empty_frame(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const b=stageBench({fetchError:'connection refused'});b.stage.start();await flush();
      return {panel:b.text(),frame:b.frame()};
    """)
    assert result["frame"] is None and "Core est injoignable" in result["panel"] and "connection refused" in result["panel"]


async def test_a_second_load_of_the_frame_is_a_navigation_and_removes_it(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const b=stageBench();b.stage.start();await flush();
      const f=b.frame();
      f.load();                 // the sandbox page itself
      const alive=b.stage.state().phase;
      f.load();                 // a navigation away: refused by frame-src, and removed here as well
      return {alive,after:b.stage.state().phase,killed:b.stage.state().killedReason,frame:b.frame()};
    """)
    assert result["alive"] == "mounting" and result["after"] == "killed" and result["killed"] == "protocol_abuse" and result["frame"] is None


async def test_the_audio_hint_follows_the_frame_not_a_guess(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      b.tickAll(1000);
      const ping=inboxOf(b).filter(m=>m.type==='ping')[0];
      b.fromFrame({rs:1,type:'pong',n:ping.n,frame:12,dropped:0,heap:5,muted:true});
      const muted=b.text();
      b.tickAll(1000);
      const ping2=inboxOf(b).filter(m=>m.type==='ping')[1];
      b.fromFrame({rs:1,type:'pong',n:ping2.n,frame:24,dropped:0,heap:5,muted:false});
      return {muted,unmuted:b.text(),frame:b.stage.state().frame};
    """)
    assert "Son coupé" in result["muted"] and "Son actif" in result["unmuted"] and result["frame"] == 24


# ------------------------------------------------------------------ pure parts

async def test_a_message_of_the_parent_is_accepted_only_from_the_parent_with_exact_fields(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const parent={};const ok=(data,o,s)=>Stage.parseParentMessage({source:s||parent,origin:o||ORIGIN,data},parent,ORIGIN).ok;
      return [ok({rsh:1,type:'props',props:{}}),ok({rsh:1,type:'teardown'}),ok({rsh:2,type:'props',props:{}}),ok({rsh:1,type:'init',props:{}}),
              ok({rsh:1,type:'props',props:{},x:1}),ok({rsh:1,type:'props',props:{}},'null'),ok({rsh:1,type:'props',props:{}},ORIGIN,{}),
              ok({rsh:1,type:'control',action:'play'}),ok(null)];
    """)
    assert result == [True, True, False, False, False, False, False, True, False]


async def test_failures_of_core_become_titled_states_with_bounded_diagnostics(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const f=(status,code,extra)=>Stage.failureOf(status,{error:Object.assign({code,message:'m'},extra||{})});
      const many=Array.from({length:50},(_,i)=>({file:'src/a.tsx',line:i,column:1,text:'t'}));
      return [f(409,'presentation_studio_engine_unavailable').title,f(422,'compile_import_refused').title,f(400,'invalid_definition').title,
              f(404,'unknown_prefab').title,f(500,'compile_compiler_failed').title,f(502,'weird').title,
              f(422,'compile_source_error',{diagnostics:many}).diagnostics.length,Stage.failureOf(500,null).code];
    """)
    assert result == ["Remotion n’est pas disponible", "La scène ne compile pas", "La source de la scène est refusée", "Scène introuvable",
                      "La scène ne compile pas", "La scène ne peut pas être jouée", 20, "http_500"]


# ------------------------------------------------------------------ the window host mounts the stage, never an HTML srcdoc

async def test_the_window_host_mounts_the_stage_page_for_a_remotion_bundle_and_never_a_srcdoc(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const bundle={kind:'remotion',id:'presentation-studio.p000000000001.s000000000001',version:1,title:'Scene'};
      const b=bench({bundles:{'presentation-studio.p000000000001.s000000000001@1':bundle}});
      b.win.location={origin:ORIGIN};
      const s=b.slot();
      b.host.mount(s,{object_id:'obj_1',title:'Scene',prefab:{id:bundle.id,version:1},props:{title:'Bonjour'},data:{ignored:1}});
      await flush();
      const frame=s.children.find(n=>n.tagName==='IFRAME');
      const info={src:frame.src,srcdoc:frame.srcdocWrites.length,sandbox:frame.getAttribute('sandbox'),stage:frame.getAttribute('data-remotion-stage'),
                  cls:frame.className,state:b.host.state('obj_1'),iframes:s.children.filter(n=>n.tagName==='IFRAME').length};
      const post=(data,origin)=>b.win.dispatch({source:frame.contentWindow,origin:origin===undefined?ORIGIN:origin,data});
      post({rsh:1,type:'status',phase:'shell'});
      const afterShell=frame.contentWindow.posted.map(p=>p.message);
      post({rsh:1,type:'status',phase:'ready',composition:{width:1280,height:720,fps:30,durationInFrames:90}});
      b.clock.advance(300);
      const ready=b.host.state('obj_1');
      b.host.update('obj_1',{title:'Autre'},{ignored:2});
      const afterUpdate=frame.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props').map(m=>m.props);
      const controlled=[b.host.control('obj_1','pause'),b.host.control('obj_1','seek',12),b.host.cue('obj_1','reveal_title',30),b.host.control('missing','play')];
      const sent=frame.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='control'||m.type==='cue');
      const forged=b.host.state('obj_1');
      post({rsh:1,type:'status',phase:'ready'},'null');           // wrong origin: dropped
      return {info,afterShell,ready,afterUpdate,controlled,sent,forged,dropped:b.host.stats().dropped,style:frame.style.aspectRatio};
    """)
    info = result["info"]
    assert info["src"] == "/remotion-stage?id=presentation-studio.p000000000001.s000000000001&v=1"
    assert info["srcdoc"] == 0 and info["sandbox"] is None, "the stage page is trusted and unsandboxed; the untrusted code is one frame deeper"
    assert info["stage"] == "1" and "sc-remotion-frame" in info["cls"] and info["iframes"] == 1
    assert result["afterShell"] == [{"rsh": 1, "type": "props", "props": {"title": "Bonjour"}}]
    assert result["ready"] == "ready" and result["afterUpdate"] == [{"title": "Bonjour"}, {"title": "Autre"}]
    assert result["controlled"] == [True, True, True, False]
    assert result["sent"] == [{"rsh": 1, "type": "control", "action": "pause"}, {"rsh": 1, "type": "control", "action": "seek", "frame": 12},
                              {"rsh": 1, "type": "cue", "name": "reveal_title", "frame": 30}]
    assert result["dropped"] == 1 and result["style"] == "1280 / 720"


async def test_the_window_host_shows_a_failed_or_killed_stage_with_the_reload_band_and_reports_the_outcome(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const bundle={kind:'remotion',id:'presentation-studio.p000000000001.s000000000001',version:1,title:'Scene'};
      const outcomes=[];
      const b=bench({bundles:{[bundle.id+'@1']:bundle}});
      b.win.location={origin:ORIGIN};
      const s=b.slot();
      b.host.mount(s,{object_id:'obj_1',title:'Scene',prefab:{id:bundle.id,version:1}});await flush();
      const frame=s.children.find(n=>n.tagName==='IFRAME');
      b.win.dispatch({source:frame.contentWindow,origin:ORIGIN,data:{rsh:1,type:'status',phase:'killed',reason:'unresponsive',message:'La scène ne répond plus depuis 3 s : elle a été retirée.'}});
      const band=s.byClass('sc-prefab-error')[0];
      const text=band&&band.textContent;
      const state=b.host.state('obj_1');
      const before=b.fetches.length;
      band.find(n=>n.tagName==='BUTTON').click();await flush();b.clock.advance(100);
      const frames=s.children.filter(n=>n.tagName==='IFRAME').length;
      return {text,state,counters:b.host.counters('obj_1'),frames,logs:b.logs.filter(l=>l.key==='scene.prefab_error').map(l=>l.data.reason)};
    """)
    assert "La scène ne répond plus depuis 3 s" in result["text"] and "Recharger" in result["text"]
    assert result["state"] == "error" and result["logs"] == ["killed"]
    assert result["counters"]["failed"] == 1 and result["counters"]["starts"] == 2
    assert result["frames"] == 1, "reload replaced the frame, it did not stack another one"
