"""Logique du pointeur à mains nues (Barehands, mode test), exécutée par node.

Les gestes réels devant une caméra ne se testent pas ici. Ce qui l'est : le
rapport de pincement, l'hystérésis et l'anti-rebond du clic, la conversion des
coordonnées de la main vers l'écran, et un cycle de vie qui rend tout ce qu'il
a pris (modèle, caméra, vidéo, surimpression) quel que soit le chemin d'arrêt.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "jarvis" / "runtime" / "control_center_barehands.js"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands.cjs"
    script.write_text(
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Main synthétique : paume de 0.2 (poignet → base du majeur), pouce et index
#: écartés de `gap`, index en (x, y).
HAND = """
function hand(gap,x=.5,y=.5){
  const lm=Array.from({length:21},()=>({x:.5,y:.5,z:0}));
  lm[0]={x:.5,y:.8,z:0};lm[9]={x:.5,y:.6,z:0};
  lm[8]={x,y,z:0};lm[4]={x:x+gap,y,z:0};
  return lm;
}
"""


def test_pinch_ratio_is_scale_free_and_null_without_a_usable_hand(tmp_path):
    result = run_node(tmp_path, HAND + """
      const far=hand(.1).map(p=>({x:.5+(p.x-.5)/2,y:.5+(p.y-.5)/2,z:0}));
      out({
        near:B.pinchRatio(hand(.1),1),far:B.pinchRatio(far,1),
        aspect:B.pinchRatio(hand(.1),4/3),
        none:B.pinchRatio([],1),flat:B.pinchRatio(Array.from({length:21},()=>({x:.2,y:.2})),1),
      });
    """)
    assert result["near"] == pytest.approx(0.5)
    assert result["far"] == pytest.approx(0.5)
    assert result["aspect"] == pytest.approx(0.1 * 4 / 3 / 0.2)
    assert result["none"] is None and result["flat"] is None


def test_detector_clicks_once_per_pinch_with_hysteresis(tmp_path):
    result = run_node(tmp_path, """
      const d=B.createPinchDetector({pressRatio:.3,releaseRatio:.45,pressFrames:2,cooldownMs:0});
      const seq=[.8,.4,.2,.2,.1,.35,.2,.6,.2,.2];
      out(seq.map((r,i)=>{const s=d.update(r,i*100);return [s.state,s.click,Number(s.progress.toFixed(2))]}));
    """)
    states = [step[0] for step in result]
    clicks = [step[1] for step in result]
    assert states == ["open", "pinching", "pinching", "pressed", "pressed", "pressed", "pressed", "open", "pinching", "pressed"]
    # Un seul clic par pincement : ni en restant pincé, ni sur un faux relâchement (0.35 < release).
    assert clicks == [False, False, False, True, False, False, False, False, False, True]
    assert result[1][2] == pytest.approx(0.33, abs=0.01)
    assert result[3][2] == 1


def test_detector_debounces_a_quick_release_and_resets_when_the_hand_is_lost(tmp_path):
    result = run_node(tmp_path, """
      const d=B.createPinchDetector({pressRatio:.3,releaseRatio:.45,pressFrames:1,cooldownMs:450});
      const clicks=[];
      for(const [r,t] of [[.1,0],[.9,100],[.1,200],[.9,300],[.1,500]])clicks.push(d.update(r,t).click);
      const lost=d.update(null,600);
      out({clicks,lost,after:d.state()});
    """)
    assert result["clicks"] == [True, False, False, False, True]
    assert result["lost"] == {"state": "open", "progress": 0, "click": False}
    assert result["after"] == "open"


def test_detector_refuses_inverted_thresholds(tmp_path):
    result = run_node(tmp_path, """
      try{B.createPinchDetector({pressRatio:.5,releaseRatio:.4});out('accepted')}catch(e){out(e.name)}
    """)
    assert result == "RangeError"


def test_hand_coordinates_map_to_screen_with_mirror_margin_and_bounds(tmp_path):
    result = run_node(tmp_path, """
      const v={width:1000,height:500};
      out({
        center:B.toScreen({x:.5,y:.5},v),
        mirroredLeft:B.toScreen({x:.12,y:.12},v,{margin:.12}),
        plain:B.toScreen({x:.25,y:.75},v,{mirror:false,margin:0}),
        clamped:B.toScreen({x:-1,y:3},v,{margin:.1}),
        edge:B.toScreen({x:.95,y:.02},v,{margin:.1}),
      });
    """)
    assert result["center"] == {"x": 500, "y": 250}
    assert result["mirroredLeft"] == {"x": 1000, "y": 0}
    assert result["plain"] == {"x": 250, "y": 375}
    assert result["clamped"] == {"x": 1000, "y": 500}
    assert result["edge"] == {"x": 0, "y": 0}


def test_tracker_gives_one_token_per_hand_and_clicks_where_the_pinch_began(tmp_path):
    result = run_node(tmp_path, HAND + """
      const t=B.createHandTracker({smoothing:1,pressFrames:1,cooldownMs:0,margin:0,mirror:false});
      const f=now=>({viewport:{width:100,height:100},aspect:1,now});
      const two={landmarks:[hand(.2,.2,.2),hand(.2,.8,.8)],handedness:[[{categoryName:'Left'}],[{categoryName:'Right'}]]};
      const first=t.update(two,f(0));
      const pinching=t.update({landmarks:[hand(.07,.3,.3)],handedness:[[{categoryName:'Left'}]]},f(16));
      const pressed=t.update({landmarks:[hand(.02,.4,.4)],handedness:[[{categoryName:'Left'}]]},f(32));
      const sizeDuringGrace=t.size();
      t.update({landmarks:[]},f(1000));
      out({first:first.tokens.map(k=>[k.id,Math.round(k.x),Math.round(k.y),k.state]),
           pinching:pinching.tokens[0],pressed:pressed.tokens[0],clicks:pressed.clicks,
           sizeDuringGrace,sizeAfter:t.size()});
    """)
    assert result["first"] == [["left", 20, 20, "open"], ["right", 80, 80, "open"]]
    assert result["pinching"]["state"] == "pinching"
    # Le jeton se fige au début du pincement : le clic tombe là, pas où l'index a glissé.
    assert (round(result["pressed"]["x"]), round(result["pressed"]["y"])) == (30, 30)
    assert [(c["id"], round(c["x"]), round(c["y"])) for c in result["clicks"]] == [("left", 30, 30)]
    assert result["sizeDuringGrace"] == 2 and result["sizeAfter"] == 0


LIFECYCLE = HAND + """
function world(opts={}){
  const log=[];let frameId=0;const frames=new Map();
  const track={stopped:false,listeners:{},stop(){this.stopped=true;log.push('track.stop')},addEventListener(n,f){this.listeners[n]=f}};
  const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
  let time=0;
  const deps={
    options:{smoothing:1,pressFrames:1,cooldownMs:0,margin:0,mirror:false},
    getUserMedia:async c=>{log.push('camera.open');if(opts.gate)await opts.gate;if(opts.deny){const e=new Error('denied');e.name='NotAllowedError';throw e}return stream},
    createLandmarker:async()=>{log.push('model.load');if(opts.noAssets)throw Object.assign(new Error('x'),{code:'assets_missing'});
      return {detectForVideo:()=>opts.result||{landmarks:[]},close(){log.push('model.close')}}},
    attachVideo:async()=>({element:{},width:640,height:480,currentTime:()=>++time,dispose(){log.push('video.dispose')}}),
    overlay:{mounted:false,mount(){this.mounted=true;log.push('overlay.mount')},unmount(){if(this.mounted)log.push('overlay.unmount');this.mounted=false},render(t){log.push('render:'+t.length)},watch(w){log.push('watch:'+(w?w.progress.toFixed(2):'off'))}},
    interaction:{hover(){},click(c){log.push('click');if(opts.onClick)opts.onClick(c)},clear(){log.push('hover.clear')}},
    requestFrame:fn=>{const id=++frameId;frames.set(id,fn);return id},
    cancelFrame:id=>{frames.delete(id);log.push('frame.cancel')},
    now:()=>time*16,viewport:()=>({width:100,height:100}),
    onStatus:s=>log.push('status:'+s.state+':'+s.code),
  };
  const pump=()=>{const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn())};
  return {deps,log,track,pump,frames};
}
"""


def test_enable_then_disable_releases_camera_model_video_and_overlay(tmp_path):
    result = run_node(tmp_path, LIFECYCLE + """
      const w=world({result:{landmarks:[hand(.2)]}});
      const c=B.createController(w.deps);
      const state=await c.enable();
      const awake=await c.activate();
      w.pump();
      const running=[...w.log];w.log.length=0;
      c.disable();
      out({state,awake,running,stopped:w.log,after:c.state(),trackStopped:w.track.stopped,pendingFrames:w.frames.size});
    """)
    # Depuis la Slice 02, allumer mène à la veille ; l'interaction demande un
    # réveil. Le chemin d'acquisition, lui, est le même.
    assert result["state"] == "sleep" and result["awake"] == "active"
    assert result["running"] == [
        "status:starting:starting", "model.load", "camera.open", "overlay.mount",
        "hover.clear", "status:sleep:sleep", "watch:0.00",
        "status:active:active", "watch:off", "render:1",
    ]
    assert result["trackStopped"] is True
    assert {"frame.cancel", "track.stop", "video.dispose", "model.close", "hover.clear", "overlay.unmount"} <= set(result["stopped"])
    assert result["stopped"][-1] == "status:off:disabled"
    assert result["after"] == "off" and result["pendingFrames"] == 0


def test_denied_camera_stops_cleanly_with_a_clear_message(tmp_path):
    result = run_node(tmp_path, LIFECYCLE + """
      const w=world({deny:true});const statuses=[];
      w.deps.onStatus=s=>statuses.push(s);
      const c=B.createController(w.deps);
      await c.enable();
      out({state:c.state(),last:statuses[statuses.length-1],log:w.log});
    """)
    assert result["state"] == "error"
    assert result["last"]["code"] == "camera_denied"
    assert "Autorisez la caméra" in result["last"]["message"]
    assert "model.close" in result["log"] and "overlay.mount" not in result["log"]


def test_missing_assets_never_open_the_camera(tmp_path):
    result = run_node(tmp_path, LIFECYCLE + """
      const w=world({noAssets:true});const c=B.createController(w.deps);
      await c.enable();out({state:c.state(),log:w.log});
    """)
    assert result["state"] == "error"
    assert "camera.open" not in result["log"]
    assert result["log"][-1] == "status:error:assets_missing"


def test_disable_during_start_releases_the_late_camera_stream(tmp_path):
    result = run_node(tmp_path, LIFECYCLE + """
      let open;const gate=new Promise(r=>open=r);
      const w=world({gate});const c=B.createController(w.deps);
      const pending=c.enable();
      await new Promise(r=>setTimeout(r,0));
      c.disable();open();await pending;
      out({state:c.state(),trackStopped:w.track.stopped,log:w.log});
    """)
    assert result["state"] == "off"
    assert result["trackStopped"] is True
    assert "overlay.mount" not in result["log"]


def test_camera_unplugged_and_click_that_disables_both_stop_the_loop(tmp_path):
    result = run_node(tmp_path, LIFECYCLE + """
      const a=world();const ca=B.createController(a.deps);
      await ca.enable();a.track.listeners.ended();
      const b=world({result:{landmarks:[hand(.01)]}});let cb;
      b.deps.options={...b.deps.options};
      const onClick=()=>cb.disable();
      b.deps.interaction.click=()=>{b.log.push('click');onClick()};
      cb=B.createController(b.deps);
      await cb.enable();await cb.activate();b.pump();
      out({unplugged:[ca.state(),a.log[a.log.length-1],a.track.stopped],
           clicked:[cb.state(),b.log.includes('click'),b.frames.size,b.track.stopped]});
    """)
    assert result["unplugged"] == ["error", "status:error:camera_ended", True]
    assert result["clicked"] == ["off", True, 0, True]


def test_error_classification_covers_browser_camera_errors(tmp_path):
    result = run_node(tmp_path, """
      const c=n=>B.classifyError(Object.assign(new Error('x'),{name:n}));
      out([c('NotAllowedError'),c('SecurityError'),c('NotFoundError'),c('NotReadableError'),c('TypeError'),
           B.classifyError({code:'assets_missing'}),B.classifyError(null)]);
    """)
    assert result == ["camera_denied", "camera_denied", "camera_missing", "camera_busy", "start_failed", "assets_missing", "start_failed"]
