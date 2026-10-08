"""The playback band and keyboard in a REAL headless Chrome (studio de presentation, Slice 12).

Page: a stage window (`[data-object-id]`, title, a **real** prefab frame mounted by the real `JarvisPrefabHost`), the real
`control_center_fullscreen.js` and the real `control_center_presentation_studio_player.js`. Only Core is a script in the page
(a tiny stand-in that answers the playback routes and logs the verbs it receives); the HTTP chain to the real Core is
`test_presentation_studio_playback_routes.py`. Keys and clicks are real CDP input events (so the Fullscreen API gets its
user activation), same harness as the Slice 03 proof.

Proved, measured:
- the band shows who presents, where we are, what is next, a ticking clock; untrusted markup in a title stays text;
- real keys on the HOST element drive exactly the verbs the voice uses; the same keys with the focus elsewhere do nothing;
- a real click on "Plein écran" enters fullscreen on the stage host (`keys:"host"`), the band is not on screen in it,
  and in fullscreen each key acts ONCE (the fullscreen module's navigation and the host handler never double up);
- leaving fullscreen brings the band back and the run is unchanged;
- a stage failure shows its real cause in the band, a toast and the console.

Not provable headless (Human check, `docs/OPERATIONS.md`): the physical Esc key, a real second screen, the look on a projector.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.fakes.prefab_js import catalogue_bundles
from tests.unit.test_fullscreen_browser import _chrome

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
HARNESS = Path(__file__).parent / "_fullscreen_browser.mjs"


def _inline(name: str) -> str:
    return (RUNTIME / name).read_text(encoding="utf-8")


PAGE = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>studio player proof</title>
<style>
html,body{margin:0;background:#101820;font:14px system-ui,sans-serif;color:#cde}
#trigger{position:absolute;left:10px;top:10px;height:36px}
#stage{position:absolute;left:60px;top:80px;width:420px;height:300px}
.win{position:absolute;left:0;top:0;width:420px;height:300px;box-sizing:border-box;display:flex;flex-direction:column;
  background:#0b1620;border:2px solid #2a8;border-radius:12px;box-shadow:0 8px 30px #000}
.win .sc-title{flex:none;height:30px;padding:6px 10px;box-sizing:border-box}
.win .handle{flex:none;height:10px;background:#2a8}
</style>
<button id="trigger" type="button">Declencheur</button>
<div id="stage"></div>
<script>__PROTOCOL__</script>
<script>__HOST__</script>
<script>window.__toasts=[];function toast(t){window.__toasts.push(t)}</script>
<script>__FULLSCREEN__</script>
<script>
/* A stand-in for Core's playback routes: same shapes as `PlaybackResult.to_dict()`, and it logs the verbs it receives. */
const core=window.__core={log:[],fail:false,pos:1,phase:'playing',title:'Scene un',hostile:false};
const real=window.fetch.bind(window);
const reply=(status,body)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
function view(){
  return {phase:core.phase,running:true,run_id:'r1',role:'user_presenter',jarvis_speaks:false,
    position:{index:core.pos,of:14},scene:{scene_id:'pss_1',title:core.hostile?'<img src=x onerror="window.__xss=1">':core.title+' '+core.pos,
      section:'',number:core.pos,of:12},
    item:{item_id:'psi_1',label:'Item '+core.pos,presenter:'user',kind:'speech',timing:'soft',interruption:'allow',recovery:'continue_item'},
    silence:false,revealed:[],elapsed:{item_ms:(Date.now()-core.t0)||0,item_target_ms:30000,item_over_target:false,run_ms:0,run_estimated_ms:0},
    next:{item_label:'Item '+(core.pos+1),scene_title:'Suite',presenter:'user',cue:{label:'Suite',armable:true,armed:true,phrases:['passons a la suite']}},
    problems:[],notices:[],stage_object_id:'obj_stage',art_direction:'checked',mode:'presentation',armed:1,generation:1};
}
core.t0=Date.now();
window.fetch=async(url,init)=>{
  const u=String(url);
  if(!u.startsWith('/api/presentation-studio/playback'))return real(url,init);
  const verb=u.slice('/api/presentation-studio/playback'.length).replace(/^\\//,'');
  if(!verb)return reply(200,{state:view()});
  const body=init&&init.body?JSON.parse(init.body):{};
  core.log.push(verb+(body.position?':'+body.position:''));
  if(core.fail&&verb==='next')
    return reply(500,{status:'stage_failed',command:verb,reason:'prefab_unavailable',message:'the catalogue is down',state:view(),
      error:{code:'presentation_studio_playback_stage_failed'}});
  if(verb==='next')core.pos=Math.min(14,core.pos+1);
  if(verb==='previous')core.pos=Math.max(1,core.pos-1);
  if(verb==='goto')core.pos=body.position;
  if(verb==='pause')core.phase='paused';
  if(verb==='resume')core.phase='playing';
  return reply(200,{status:'applied',command:verb,state:view()});
};
</script>
<script>__PLAYER__</script>
<script>
const BUNDLE=__BUNDLE__;
const host=JarvisPrefabHost.createPrefabHost({document,window,log:()=>{},fetchBundle:async()=>JSON.parse(JSON.stringify(BUNDLE))});
const el=document.createElement('div');el.className='win';el.id='win1';el.dataset.objectId='obj_stage';el.tabIndex=-1;
const head=document.createElement('div');head.className='sc-title';head.textContent='Scene';el.appendChild(head);
const slot=JarvisPrefabHost.sceneSlot(el,true);
const handle=document.createElement('div');handle.className='handle';el.appendChild(handle);
document.getElementById('stage').appendChild(el);
host.mount(slot,{object_id:'obj_stage',title:'Scene',prefab:{id:'test.counter',version:1},props:{label:'Count'},data:{count:3,notes:'n'}});
window.__probe=()=>{
  const band=document.getElementById('jvStudioBand');
  const r=band.getBoundingClientRect();
  const mid=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
  return {hidden:band.hidden,text:band.textContent,fs:document.fullscreenElement&&document.fullscreenElement.id,
    bandVisibleAtItsPlace:!!mid&&band.contains(mid),active:document.activeElement&&(document.activeElement.id||document.activeElement.tagName),
    img:!!band.querySelector('img'),xss:window.__xss===undefined?null:window.__xss,tabindex:el.getAttribute('tabindex'),
    sandbox:el.querySelector('iframe').getAttribute('sandbox'),allow:el.querySelector('iframe').getAttribute('allow'),
    phase:band.getAttribute('data-phase'),clock:band.querySelector('.jvsp-clock').textContent};
};
</script></html>
"""


@pytest.fixture
async def page(tmp_path):
    bundles = await catalogue_bundles(tmp_path, "test.counter")
    html = (PAGE.replace("__PROTOCOL__", _inline("control_center_prefab_protocol.js"))
            .replace("__HOST__", _inline("control_center_prefab_host.js"))
            .replace("__FULLSCREEN__", _inline("control_center_fullscreen.js"))
            .replace("__PLAYER__", _inline("control_center_presentation_studio_player.js"))
            .replace("__BUNDLE__", json.dumps(bundles["test.counter@1"])))
    out = tmp_path / "studio-player-proof.html"
    out.write_text(html, encoding="utf-8")
    return out


def _drive(page: Path, plan: list) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run([node, str(HARNESS), str(page), _chrome(), json.dumps(plan)],
                          capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
                          env={**os.environ})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


READY = {"until": "!!document.getElementById('jvStudioBand') && !document.getElementById('jvStudioBand').hidden "
                  "&& document.querySelector('#win1 iframe') && window.__probe().text.includes('Scene un')", "ms": 8000}
LOG = {"value": "log", "expr": "window.__core.log.slice()"}
FOCUS_STAGE = {"click": "#win1 .sc-title"}
#: The click moves focus asynchronously: a real user takes tens of ms to reach for a key, the CDP driver does not.
FOCUSED = {"until": "document.activeElement && document.activeElement.id === 'win1'", "ms": 3000}


def probe(name: str) -> dict:
    return {"value": name, "expr": "window.__probe()"}


async def test_the_band_shows_the_run_and_untrusted_markup_stays_text(page):
    result = _drive(page, [
        READY, probe("shown"),
        {"eval": "window.__core.hostile=true"}, {"until": "window.__probe().text.includes('<img')", "ms": 6000}, {"wait": 100},
        probe("hostile")])
    out = result["reads"]
    assert "failed" not in out, out.get("failed")
    shown = out["shown"]
    for fragment in ("Vous présentez", "En cours", "Scène 1/12", "Scene un 1", "Ensuite : Item 2", "dites « passons a la suite »"):
        assert fragment in shown["text"], fragment
    assert shown["sandbox"] == "allow-scripts" and shown["allow"] is None, "the frame is untouched by the player"
    hostile = out["hostile"]
    assert "<img src=x" in hostile["text"] and hostile["img"] is False and hostile["xss"] is None
    assert result["errors"] == []


async def test_real_keys_on_the_host_drive_the_verbs_and_the_same_keys_elsewhere_do_nothing(page):
    result = _drive(page, [
        READY,
        {"eval": "document.getElementById('trigger').focus()"},
        {"key": "ArrowRight"}, {"key": "Home"}, {"wait": 250}, {"value": "elsewhere", "expr": "window.__core.log.slice()"},
        FOCUS_STAGE, FOCUSED, {"wait": 150}, {"value": "focused", "expr": "document.activeElement.id"},
        {"key": "ArrowRight"}, {"wait": 150}, {"key": " "}, {"wait": 150}, {"key": "ArrowLeft"}, {"wait": 150},
        {"key": "Home"}, {"wait": 150}, {"key": "End"}, {"wait": 150}, {"key": "p"}, {"wait": 200},
        probe("paused"), {"key": "p"}, {"wait": 200}, {"key": "Escape"}, {"wait": 200}, LOG, probe("end")])
    out = result["reads"]
    assert "failed" not in out, out.get("failed")
    assert out["elsewhere"] == [], "keys outside the stage host never reach the run"
    assert out["focused"] == "win1"
    assert out["log"] == ["next", "next", "previous", "goto:1", "goto:14", "pause", "resume", "pause"]
    assert out["paused"]["phase"] == "paused" and "En pause" in out["paused"]["text"]
    assert out["end"]["tabindex"] == "-1"
    assert result["errors"] == []


async def test_fullscreen_from_the_band_uses_the_host_each_key_acts_once_and_the_band_comes_back(page):
    result = _drive(page, [
        READY, probe("before"),
        {"click": "#jvStudioBand .jvsp-full"}, {"until": "!!document.fullscreenElement", "ms": 5000}, {"wait": 300},
        probe("entered"),
        {"key": "ArrowRight"}, {"wait": 150}, {"key": " "}, {"wait": 150}, {"key": "ArrowLeft"}, {"wait": 150},
        {"key": "Home"}, {"wait": 150}, {"key": "End"}, {"wait": 150}, {"key": "p"}, {"wait": 250},
        LOG, probe("paused_in_fs"),
        {"key": "Escape"}, {"until": "!document.fullscreenElement", "ms": 5000}, {"wait": 400}, probe("after"), LOG,
        {"value": "fsstate", "expr": "JarvisFullscreen.state().state"}])
    out = result["reads"]
    assert "failed" not in out, out.get("failed")
    assert out["before"]["bandVisibleAtItsPlace"] is True
    entered = out["entered"]
    assert entered["fs"] == "win1", "the HOST element is fullscreen (the frame cannot fullscreen itself)"
    assert entered["bandVisibleAtItsPlace"] is False, "the band is not on screen in fullscreen"
    assert entered["sandbox"] == "allow-scripts" and entered["allow"] is None
    # exactly one command per key: the fullscreen module's capture handler and the host handler never double up
    assert out["log"] == ["next", "next", "previous", "goto:1", "goto:14", "pause"]
    assert out["paused_in_fs"]["phase"] == "paused"
    after = out["after"]
    assert after["fs"] is None and after["bandVisibleAtItsPlace"] is True and "En pause" in after["text"]
    assert out["fsstate"] == "exited"
    assert result["errors"] == []


async def test_a_stage_failure_is_in_the_band_the_toast_and_the_console(page):
    result = _drive(page, [
        READY, FOCUS_STAGE, FOCUSED, {"wait": 150}, {"eval": "window.__core.fail=true"}, {"key": "ArrowRight"},
        {"until": "window.__probe().text.includes('the catalogue is down')", "ms": 5000}, {"wait": 200},
        probe("after_fail"), {"value": "toasts", "expr": "window.__toasts.map(t=>t.kind+':'+t.title)"}])
    out = result["reads"]
    assert "failed" not in out, out.get("failed")
    assert "La scène n'a pas suivi : the catalogue is down" in out["after_fail"]["text"]
    assert out["toasts"] == ["bad:Lecture : la scène n'a pas suivi"]
    errors = [line for line in result["console"] if line.startswith("error ")]
    assert len(errors) == 1 and "studio.stage_failed" in errors[0] and "the catalogue is down" in errors[0]
    assert result["errors"] == [], "no uncaught page error"
