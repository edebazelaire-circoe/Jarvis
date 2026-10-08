"""The playback band and keyboard of the Control Center page, by node (studio de presentation, Slice 12).

The module under test is the real `control_center_presentation_studio_player.js`; only the DOM, the clock and the network are
doubles (the Slice 03 bench `_fullscreen_js_bench.cjs`). The real browser proof (real keys on the host element, real
fullscreen, real iframe) is `test_presentation_studio_player_browser.py`.

Pinned here: what the band shows and where untrusted text may go (`textContent` only), that every command has an end state
a human can act from (applied, refused, stage failure, timeout, unreachable Core), that keys act on the stage host only and
never twice, that the fullscreen module's navigation is forwarded without duplication, and the polling/lost-link rules.
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
FULLSCREEN = RUNTIME / "control_center_fullscreen.js"
BENCH = Path(__file__).parent / "_fullscreen_js_bench.cjs"

PRELUDE = r"""
const env=makeEnv();const {doc,win,timers}=env;
const P=require(process.env.JARVIS_PLAYER_JS);
const stage=env.addWindow('studio-stage-r1','Diapo');
const sceneLayer=env.scene;
const bandOf=()=>doc.getElementById(P.BAND_ID);
const textOf=el=>{let t=el.textContent||'';for(const c of el.children)t+=' '+textOf(c);return t};
const walk=(n,f)=>{f(n);n.children.forEach(c=>walk(c,f))};
const byClass=(root,cls)=>{let out=null;walk(root,n=>{if(!out&&(n.className||'').split(' ').includes(cls))out=n});return out};
const buttons=()=>{const out=[];walk(bandOf(),n=>{if(n.tagName==='BUTTON')out.push(n)});return out};
const btn=label=>buttons().find(b=>b.textContent.includes(label));
const base={phase:'playing',running:true,run_id:'r1',role:'user_presenter',jarvis_speaks:false,
  position:{index:2,of:14},scene:{scene_id:'pss_1',title:'Chiffres',section:'part1',number:2,of:12},
  item:{item_id:'psi_2',label:'Les marges',presenter:'user',kind:'speech',timing:'soft',interruption:'allow',recovery:'continue_item'},
  speaking:null,silence:false,revealed:[],elapsed:{item_ms:12000,item_target_ms:30000,item_over_target:false,run_ms:60000,run_estimated_ms:600000},
  owner:'user',armed:1,generation:2,pending:null,problems:[],
  next:{item_label:'Conclusion',scene_title:'Fin',presenter:'user',cue:{label:'Suite',armable:true,armed:true,phrases:['passons a la suite']}},
  detour:null,sequence:null,untrusted:[],presentation_id:'pst_1',variant_id:'psv_1',stage_object_id:'studio-stage-r1',
  art_direction:'checked',notices:[],mode:'presentation'};
const st=(extra)=>Object.assign(JSON.parse(JSON.stringify(base)),extra||{});
const script={state:st(),status:200};
const answer=(status,body)=>({status,body});
env.requestHook=rec=>{
  if(env.hook)return env.hook(rec);
  if(rec.method==='GET')return answer(200,{state:script.state});
  return answer(200,{status:'applied',command:rec.url.split('/').pop(),state:script.state});
};
const nav=[];let navListener=null;
const fullscreen={onNavigate(fn){navListener=fn;return ()=>{navListener=null}},calls:[],
  async enter(spec){fullscreen.calls.push(spec);return fullscreen.result||{state:'entered',object_id:spec.object_id}}};
const make=(extra)=>P.createStudioPlayer(Object.assign({document:doc,window:win,request:env.request,now:timers.now,
  setTimeout:timers.setTimeout,clearTimeout:timers.clearTimeout,setInterval:timers.setInterval,clearInterval:timers.clearInterval,
  toast:env.toast,fullscreen,log:()=>{}},extra||{}));
const posts=()=>env.posts.filter(p=>p.method==='POST').map(p=>p.url.replace('/api/presentation-studio/playback/','')+(p.body&&Object.keys(p.body).length?JSON.stringify(p.body):''));
const consoleErrors=[];const realError=console.error;console.error=(...a)=>{consoleErrors.push(a.join(' '))};
const key=(k,extra,target)=>(target||stage).dispatch('keydown',Object.assign({key:k},extra||{}));
/* The bench fires one timer per `advance`; a module that re-arms itself in an async callback needs small steps. */
const run=async(ms,step=250)=>{for(let t=0;t<ms;t+=step)await env.advance(step)};
const settle=async()=>{for(let i=0;i<6;i++)await env.tick()};
"""


def _node(tmp_path: Path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    index = len(list(tmp_path.glob("pl-js-*.cjs")))
    script = tmp_path / f"pl-js-{index}.cjs"
    script.write_text(
        f"const {{makeEnv}}=require({json.dumps(str(BENCH))});\n" + PRELUDE +
        "(async()=>{\n" + body + "\n})().then(v=>{console.error=realError;console.log(JSON.stringify(v))},"
        "e=>{console.error=realError;console.error(e&&e.stack||e);process.exit(1)});\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120,
                          env={**os.environ, "JARVIS_FULLSCREEN_JS": str(FULLSCREEN), "JARVIS_PLAYER_JS": str(MODULE)})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ what the band shows

def test_the_band_says_who_presents_where_we_are_what_comes_next_and_for_how_long(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
const b=bandOf();
return {hidden:b.hidden,text:textOf(b),phase:b.getAttribute('data-phase'),over:byClass(b,'jvsp-clock').getAttribute('data-over'),
  pause:btn('Pause')?btn('Pause').disabled:null,labels:buttons().map(x=>x.textContent)};
""")
    assert out["hidden"] is False and out["phase"] == "playing"
    for fragment in ("Vous présentez", "En cours", "Scène 2/12", "Chiffres", "élément 2/14", "Les marges", "Ensuite : Conclusion",
                     "dites « passons a la suite »", "00:12 / 00:30"):
        assert fragment in out["text"], fragment
    assert out["over"] == "0" and out["pause"] is False
    assert [label for label in out["labels"] if label] == ["◀ Précédent", "Pause", "Suivant ▶", "Plein écran", "Arrêter", "Fermer"]


def test_free_text_only_reaches_the_page_as_text(tmp_path):
    out = _node(tmp_path, """
script.state=st({scene:Object.assign({},base.scene,{title:'<img src=x onerror=alert(1)>'}),
  item:Object.assign({},base.item,{label:'<b>gras</b>'})});
const p=make();p.start();await env.tick();
const tags=[];walk(bandOf(),n=>tags.push(n.tagName));
return {tags,text:textOf(bandOf())};
""")
    assert "<img src=x onerror=alert(1)>" in out["text"] and "<b>gras</b>" in out["text"]
    assert "IMG" not in out["tags"] and "B" not in out["tags"]
    code = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    assert "innerHTML" not in code and "insertAdjacentHTML" not in code and "document.write" not in code


def test_nothing_is_shown_while_idle_and_the_clock_runs_then_freezes_when_paused(tmp_path):
    out = _node(tmp_path, """
script.state={phase:'idle',running:false};
const p=make();p.start();await env.tick();
const idle=bandOf().hidden;
const t0=timers.now();
/* A Core that keeps counting: the item's elapsed time as it would answer at each poll (paused: frozen). */
let frozen=null;
env.hook=rec=>{if(rec.method!=='GET')return answer(200,{status:'applied',state:script.state});
  const ms=frozen!==null?frozen:12000+(timers.now()-t0);
  return answer(200,{state:Object.assign({},script.state,{elapsed:Object.assign({},base.elapsed,{item_ms:ms})})})};
const clockText=()=>byClass(bandOf(),'jvsp-clock').textContent;
script.state=st();await run(6000);
const t1=clockText();
await run(3000);
const t2=clockText();
frozen=12000+(timers.now()-t0);script.state=st({phase:'paused'});await run(2000);
const p1=clockText();await run(20000);
const p2=clockText();
frozen=41000;script.state=st({phase:'playing'});await run(2000);
const over=byClass(bandOf(),'jvsp-clock').getAttribute('data-over');
return {idle,t1,t2,p1,p2,over};
""")
    assert out["idle"] is True
    assert out["t1"] != out["t2"], "a live counter, not a static label"
    assert out["p1"] == out["p2"], "frozen while paused"
    assert out["over"] == "1"


def test_the_jarvis_role_says_the_mode_is_temporary_and_the_preference_untouched(tmp_path):
    out = _node(tmp_path, """
script.state=st({role:'jarvis_presenter',jarvis_speaks:true,mode:'assistant',art_direction:'unchecked',problems:['aux_stage_failed']});
const p=make();p.start();await env.tick();
return textOf(bandOf());
""")
    assert "Jarvis présente" in out and "mode réglé sur SIMPLE pour cette lecture" in out and "préférence est inchangée" in out
    assert "Direction artistique non vérifiée" in out and "La ressource annexe n'a pas pu s'afficher" in out


# ------------------------------------------------------------------ commands always end in an actionable state

def test_a_refusal_is_information_said_in_plain_words_not_an_error(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
env.hook=rec=>rec.method==='GET'?answer(200,{state:script.state}):answer(409,{status:'refused',reason:'locked_sequence_active',
  message:'x',state:script.state,error:{code:'presentation_studio_playback_refused'}});
await p.command('next');
return {text:textOf(bandOf()),toasts:doc.toasts.length,errors:consoleErrors.length,inflight:p.state().inflight,next:btn('Suivant').disabled};
""")
    assert "séquence verrouillée" in out["text"].lower() and out["toasts"] == 0 and out["errors"] == 0
    assert out["inflight"] is None and out["next"] is False


def test_a_stage_failure_shows_its_real_cause_toasts_and_logs(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
env.hook=rec=>rec.method==='GET'?answer(200,{state:script.state}):answer(500,{status:'stage_failed',reason:'unknown_scene',
  message:'the catalogue is down',state:st({phase:'paused',problems:['stage_unknown_scene']}),error:{code:'presentation_studio_playback_stage_failed'}});
await p.command('next');
return {text:textOf(bandOf()),toasts:doc.toasts.map(t=>t.kind+':'+t.title),errors:consoleErrors,phase:bandOf().getAttribute('data-phase'),
  kind:bandOf().getAttribute('data-kind'),inflight:p.state().inflight};
""")
    assert "the catalogue is down" in out["text"] and out["phase"] == "paused" and out["kind"] == "problem"
    assert out["toasts"] == ["bad:Lecture : la scène n'a pas suivi"] and out["inflight"] is None
    assert len(out["errors"]) == 1 and "studio.stage_failed" in out["errors"][0] and "the catalogue is down" in out["errors"][0]


def test_an_unreachable_core_and_a_timeout_release_the_ui_and_say_how_long_it_waited(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
env.hook=rec=>{if(rec.method==='GET')return answer(200,{state:script.state});throw new Error('Failed to fetch')};
await p.command('pause');
const failed={text:textOf(bandOf()),inflight:p.state().inflight,toasts:doc.toasts.length,errors:consoleErrors.length};
env.hook=rec=>rec.method==='GET'?answer(200,{state:script.state}):new Promise(()=>{});   /* never answers */
const slow=p.command('next');
await settle();
await run(4000);const mid=textOf(bandOf());
await run(7000);await slow;
return {failed,mid,after:textOf(bandOf()),inflight:p.state().inflight,toasts:doc.toasts.length,errors:consoleErrors.length};
""")
    assert "Failed to fetch" in out["failed"]["text"] and out["failed"]["inflight"] is None and out["failed"]["toasts"] == 1
    assert out["failed"]["errors"] == 1
    assert "next… 4 s" in out["mid"], "a live counter while a command is in flight"
    assert "Core ne répond pas depuis 10 s" in out["after"] and out["inflight"] is None
    assert out["toasts"] == 2 and out["errors"] == 2


def test_rapid_commands_are_serialised_and_bounded(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
let release=null;const held=new Promise(r=>{release=r});
let first=true;
env.hook=rec=>{if(rec.method==='GET')return answer(200,{state:script.state});
  if(first){first=false;return held.then(()=>answer(200,{status:'applied',state:script.state}))}
  return answer(200,{status:'applied',state:script.state})};
const run=[];for(let i=0;i<7;i++)run.push(p.command('next'));
await env.tick();
const whileHeld=posts().length;
release();await Promise.all(run);await env.tick();
return {whileHeld,total:posts().length,dropped:p.stats().dropped};
""")
    assert out["whileHeld"] == 1, "one command in flight at a time"
    assert out["total"] == 4 and out["dropped"] == 3, "bounded queue: the rest is dropped and counted, never piled up"


# ------------------------------------------------------------------ keyboard on the host element, never twice

def test_keys_act_on_the_stage_host_with_the_same_routes_as_the_voice(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
const events=[];
for(const k of ['ArrowRight',' ','ArrowLeft','PageUp','Home','End','p','Escape','q']){events.push([k,key(k).defaultPrevented]);await settle()}
return {events,posts:posts(),bound:stage.getAttribute('tabindex'),stageOnly:sceneLayer.listeners.keydown||null};
""")
    assert [k for k, prevented in out["events"] if prevented] == ["ArrowRight", " ", "ArrowLeft", "PageUp", "Home", "End", "p", "Escape"]
    assert out["posts"] == ['next', 'next', 'previous', 'previous', 'goto{"position":1}', 'goto{"position":14}', 'pause', 'pause']
    assert out["bound"] == "-1" and out["stageOnly"] is None


def test_p_toggles_between_pause_and_resume_and_escape_only_pauses_a_playing_run(tmp_path):
    out = _node(tmp_path, """
script.state=st({phase:'paused'});
const p=make();p.start();await env.tick();
key('p');key('Escape');await env.tick();
return posts();
""")
    assert out == ["resume"], "Escape never resumes and never acts on a paused run"


def test_modifiers_text_fields_defaultprevented_and_idle_runs_are_ignored(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
const input=doc.createElement('input');stage.appendChild(input);
const r={ctrl:key('ArrowRight',{ctrlKey:true}).defaultPrevented,alt:key('ArrowRight',{altKey:true}).defaultPrevented,
  meta:key('ArrowRight',{metaKey:true}).defaultPrevented,field:key('ArrowRight',{},input).defaultPrevented};
let capturing=true;
stage.addEventListener('keydown',e=>{if(capturing)e.preventDefault()},true);   /* like the fullscreen module's capture handler */
key('ArrowRight');await settle();capturing=false;
const before=posts().length;
script.state={phase:'idle',running:false};await run(6000);
r.idle=key('ArrowRight').defaultPrevented;
return {r,before,after:posts().length,posted:posts()};
""")
    assert out["r"] == {"ctrl": False, "alt": False, "meta": False, "field": False, "idle": False}
    assert out["before"] == 0 and out["after"] == 0, "no command from an ignored key"


def test_fullscreen_navigation_is_forwarded_once_and_enter_uses_the_host_with_host_keys(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
for(const a of [{action:'next',key:'ArrowRight'},{action:'previous'},{action:'first'},{action:'last'}]){navListener(a);await settle()}
const navPosts=posts();
fullscreen.result={state:'unsupported',reason:'pas de plein ecran'};
await btn('Plein').dispatch('click');
await env.tick();
const unsupported=textOf(bandOf());
fullscreen.result={state:'entered'};
btn('Plein').dispatch('click');await env.tick();
return {navPosts,calls:fullscreen.calls,unsupported};
""")
    assert out["navPosts"] == ['next', 'previous', 'goto{"position":1}', 'goto{"position":14}']
    assert out["calls"] == [{"object_id": "studio-stage-r1", "keys": "host"}] * 2
    assert "Plein écran indisponible" in out["unsupported"]


def test_the_key_handler_follows_the_stage_window_and_is_removed_with_the_run(tmp_path):
    out = _node(tmp_path, """
const other=env.addWindow('studio-stage-r2','Autre');
const p=make();p.start();await env.tick();
key('ArrowRight');await env.tick();
const first=posts().length;
script.state=st({stage_object_id:'studio-stage-r2',run_id:'r2'});await run(2000);
key('ArrowRight',{},stage);await env.tick();
const old=posts().length;
key('ArrowRight',{},other);await env.tick();
const now=posts().length;
script.state={phase:'stopped',running:false,run_id:'r2',last_run:{run_id:'r2',reason:'user',problems:[]}};await run(2000);
key('ArrowRight',{},other);await env.tick();
return {first,old,now,final:posts().length,tabindex:other.getAttribute('tabindex')};
""")
    assert (out["first"], out["old"], out["now"], out["final"]) == (1, 1, 2, 2)
    assert out["tabindex"] == "-1"


def test_a_stage_window_that_appears_after_the_state_gets_the_keys_at_once(tmp_path):
    out = _node(tmp_path, """
script.state=st({stage_object_id:'studio-stage-late',run_id:'rl'});
const p=make();p.start();await settle();
const early=posts().length;                                  /* the run is known, the window is not on screen yet */
const late=env.addWindow('studio-stage-late','Tard');
key('ArrowRight',{},late);await settle();
return {early,after:posts(),elsewhere:key('ArrowRight',{},stage).defaultPrevented};
""")
    assert out["early"] == 0 and out["after"] == ["next"]
    assert out["elsewhere"] is False, "another window never gets the keys of the run"


# ------------------------------------------------------------------ polling, lost link, stopped notices

def test_polling_is_fast_while_running_slow_while_idle_and_backs_off_on_failure(tmp_path):
    out = _node(tmp_path, """
script.state={phase:'idle',running:false};
const p=make();p.start();await env.tick();
const gets=()=>env.posts.filter(x=>x.method==='GET').length;
const g0=gets();await run(5200);const idleGets=gets()-g0;
script.state=st();await run(5200);
const g1=gets();await run(6000);const activeGets=gets()-g1;
env.hook=rec=>{throw new Error('down')};
const g2=gets();await run(30000);const failing=gets()-g2;
return {idleGets,activeGets,failing};
""")
    assert out["idleGets"] == 1, "idle: one read per ~5 s"
    assert out["activeGets"] >= 3, "running: about every 1.5 s"
    assert 1 <= out["failing"] <= 5, "failures back off instead of hammering Core"


def test_a_lost_core_is_said_once_with_its_duration_and_the_recovery_is_logged(tmp_path):
    out = _node(tmp_path, """
const logs=[];const p=make({log:(l,e,d)=>logs.push(e)});p.start();await env.tick();
env.hook=rec=>{throw new Error('ECONNREFUSED')};
await run(12000);
const lost=textOf(bandOf());const toasts=doc.toasts.length;
await run(12000);
const again=doc.toasts.length;
env.hook=null;await run(20000);
return {lost,toasts,again,after:textOf(bandOf()),logs:[...new Set(logs)],errors:consoleErrors.length};
""")
    assert "Core ne répond plus depuis" in out["lost"] and "périmé" in out["lost"]
    assert out["toasts"] == 1 and out["again"] == 1, "once, not on every failed poll"
    assert "Core ne répond plus" not in out["after"] and "studio.link_restored" in out["logs"]
    assert out["errors"] == 1


def test_a_stop_that_left_a_problem_stays_until_closed_and_a_clean_stop_fades(tmp_path):
    out = _node(tmp_path, """
script.state=st();
const p=make();p.start();await env.tick();
script.state={phase:'stopped',running:false,run_id:'r1',last_run:{run_id:'r1',reason:'mode_changed_by_user',problems:['mode_restore_failed']}};
await run(6000);
const shown=!bandOf().hidden;const text=textOf(bandOf());
await run(60000,1000);const stillThere=!bandOf().hidden;
btn('Fermer').dispatch('click');const closed=bandOf().hidden;
script.state=st({run_id:'r2'});await run(2000);
script.state={phase:'stopped',running:false,run_id:'r2',last_run:{run_id:'r2',reason:'user',problems:[]}};
await run(6000);const cleanShown=!bandOf().hidden;
await run(20000);const cleanFaded=bandOf().hidden;
return {shown,text,stillThere,closed,cleanShown,cleanFaded};
""")
    assert out["shown"] and "mode changé par vous" in out["text"] and "pas pu être rétabli" in out["text"]
    assert out["stillThere"] is True and out["closed"] is True
    assert out["cleanShown"] is True and out["cleanFaded"] is True


def test_the_page_has_no_dependency_on_the_frame_protocol_and_no_innerhtml():
    source = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    for forbidden in ("postMessage", "contentWindow", "sandbox", "srcdoc", "eval(", "new Function", "alert(", "confirm(", "prompt("):
        assert forbidden not in code, forbidden
    for verb in ("start", "stop", "pause", "resume", "next", "previous", "goto"):
        assert f"'{verb}'" in code, f"the page calls the {verb} route"
