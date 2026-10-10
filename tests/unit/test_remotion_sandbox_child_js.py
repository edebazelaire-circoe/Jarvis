"""L'amorce du bac à sable (`remotion_sandbox_child.js`) face à un faux lecteur Remotion, exécutée par node (Slice 12).

Prouvé : `control` avec `frame` / `until` (aller à, jouer, s'arrêter SUR l'image d'arrêt seule), l'arrêt déjà atteint, l'ordre reçu
avant que le lecteur existe, `seek` qui efface l'image d'arrêt, la position (`clock`) plafonnée et dite à chaque changement d'état,
un expéditeur étranger ignoré. Le navigateur réel le prouve de bout en bout (`test_remotion_timeline_realpage_browser.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"

HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const protocol=fs.readFileSync(PATHS.protocol,'utf8'), child=fs.readFileSync(PATHS.child,'utf8');
function world(opts){
  const o=opts||{};
  const posted=[],handlers={},calls=[];
  let nowMs=1000000;
  const player={frame:0,playing:false,listeners:{},
    seekTo(f){calls.push(['seek',f]);player.frame=f},play(){calls.push(['play']);player.playing=true},pause(){calls.push(['pause']);player.playing=false},
    isPlaying(){return player.playing},getCurrentFrame(){return player.frame},isMuted(){return true},unmute(){},
    addEventListener(name,fn){(player.listeners[name]=player.listeners[name]||[]).push(fn)},
    emit(name,detail){(player.listeners[name]||[]).forEach(fn=>fn({detail}))}};
  const parent={postMessage(m,origin){posted.push({m:JSON.parse(JSON.stringify(m)),origin})}};
  const refs=[];
  const H={react:{createElement:(type,props)=>({type,props})},
    'react-dom/client':{createRoot:()=>({render(el){refs.push(el);if(!o.noPlayer)el.props.ref(player)},unmount(){}})},
    '@remotion/player':{Player:'Player'}};
  const win={parent,__JARVIS_SANDBOX_CONFIG__:{staticBase:'/s',embedder:'http://h'},__JARVIS_HOST__:H,JarvisScene:{component:function(){}},
    addEventListener(name,fn){(handlers[name]=handlers[name]||[]).push(fn)},crypto:{}};
  win.window=win;win.globalThis=win;
  win.document={readyState:'complete',getElementById:()=>({})};
  win.performance={memory:{usedJSHeapSize:1048576}};
  win.Date={now:()=>nowMs};
  const ctx=vm.createContext(win);
  vm.runInContext(protocol,ctx);
  vm.runInContext(child,ctx);
  /* The message is built INSIDE the context: the protocol checks `Object.getPrototypeOf(x)===Object.prototype` of its own realm. */
  const send=(data,over)=>(handlers.message||[]).forEach(fn=>fn(Object.assign({source:parent,origin:'http://h',data:vm.runInContext('('+JSON.stringify(data)+')',ctx)},over||{})));
  const init=()=>send({rs:1,type:'init',composition:{id:'Scene',width:1280,height:720,fps:30,durationInFrames:300},props:{}});
  const clocks=()=>posted.map(p=>p.m).filter(m=>m.type==='clock');
  return {player,posted,calls,send,init,clocks,advance:(ms)=>{nowMs+=ms},handlers,win,refs};
}
"""


def run_child(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    paths = {"protocol": str(RUNTIME / "remotion_sandbox_protocol.js"), "child": str(RUNTIME / "remotion_sandbox_child.js")}
    script = tmp_path / f"child-{len(list(tmp_path.glob('child-*.cjs')))}.cjs"
    script.write_text(f"const PATHS={json.dumps(paths)};\n" + HARNESS + "(()=>{\n" + body + "\n})();\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout.strip() else None


def test_play_goes_to_the_frame_then_stops_by_itself_on_the_stop_frame(tmp_path):
    result = run_child(tmp_path, r"""
      const w=world();w.init();
      w.send({rs:1,type:'control',action:'play',frame:30,until:60});
      w.player.frame=45;w.player.emit('frameupdate',{frame:45});
      const midway=w.player.playing;
      w.player.frame=60;w.player.emit('frameupdate',{frame:60});
      console.log(JSON.stringify({calls:w.calls,midway,playing:w.player.playing,frame:w.player.frame}));
    """)
    assert result["calls"] == [["seek", 30], ["play"], ["pause"], ["seek", 60]]
    assert result["midway"] is True and result["playing"] is False and result["frame"] == 60


def test_a_stop_frame_already_reached_neither_plays_nor_leaves_the_segment(tmp_path):
    result = run_child(tmp_path, r"""
      const w=world();w.init();
      w.send({rs:1,type:'control',action:'play',frame:299,until:299});
      w.send({rs:1,type:'control',action:'play',until:100});          // resume past the stop frame (the player sits on 299)
      console.log(JSON.stringify({calls:w.calls,playing:w.player.playing}));
    """)
    assert [c for c in result["calls"] if c[0] == "play"] == []
    assert result["playing"] is False and result["calls"][0] == ["seek", 299]


def test_pause_with_a_frame_holds_there_and_a_seek_forgets_the_stop_frame(tmp_path):
    result = run_child(tmp_path, r"""
      const w=world();w.init();
      w.send({rs:1,type:'control',action:'pause',frame:12});
      w.send({rs:1,type:'control',action:'play',frame:0,until:50});
      w.send({rs:1,type:'control',action:'seek',frame:10});           // the author scrubbed: no stop frame any more
      w.player.frame=80;w.player.emit('frameupdate',{frame:80});
      console.log(JSON.stringify({calls:w.calls,playing:w.player.playing}));
    """)
    assert result["calls"][:2] == [["seek", 12], ["pause"]]
    assert ["pause"] not in result["calls"][4:] and result["playing"] is True, "after a seek, passing the old stop frame stops nothing"


def test_an_order_received_before_the_player_exists_is_applied_at_mount_with_its_stop_frame(tmp_path):
    result = run_child(tmp_path, r"""
      const w=world({noPlayer:true});
      w.send({rs:1,type:'control',action:'play',frame:20,until:25});
      w.init();                                                        // renders, but this world never hands a player to the ref
      const ref=w.refs[0].props.ref;
      ref(w.player);                                                   // React hands the player over later
      w.player.frame=25;w.player.emit('frameupdate',{frame:25});
      console.log(JSON.stringify({calls:w.calls,playing:w.player.playing}));
    """)
    assert result["calls"] == [["seek", 20], ["play"], ["pause"], ["seek", 25]] and result["playing"] is False


def test_the_position_is_reported_throttled_and_at_every_change_of_state(tmp_path):
    result = run_child(tmp_path, r"""
      const w=world();w.init();w.player.playing=true;
      for(let i=0;i<100;i++){w.player.frame=i;w.player.emit('frameupdate',{frame:i})}       // one instant, 100 frames
      const burst=w.clocks().length;
      w.advance(300);w.player.frame=101;w.player.emit('frameupdate',{frame:101});
      const later=w.clocks().length;
      w.advance(10);w.player.playing=false;w.player.emit('pause',{});                     // a state change is said, even 10 ms later
      const last=w.clocks().slice(-1)[0];
      const origins=[...new Set(w.posted.map(p=>p.origin))];
      console.log(JSON.stringify({burst,later,last,origins,total:w.clocks().length}));
    """)
    assert result["burst"] == 1 and result["later"] == 2 and result["total"] == 3
    assert result["last"] == {"rs": 1, "type": "clock", "frame": 101, "playing": False}
    assert result["origins"] == ["http://h"], "only ever to the embedder origin"


def test_an_order_from_another_window_or_origin_is_ignored(tmp_path):
    result = run_child(tmp_path, r"""
      const w=world();w.init();
      w.send({rs:1,type:'control',action:'play',frame:5},{source:{}});
      w.send({rs:1,type:'control',action:'play',frame:5},{origin:'http://evil.example'});
      w.send({rs:1,type:'control',action:'play',frame:5,until:2});                      // until before frame: refused whole
      w.send({rs:1,type:'control',action:'pause',until:5});
      console.log(JSON.stringify({calls:w.calls}));
    """)
    assert result["calls"] == []


def test_a_player_that_just_mounted_reports_its_position_at_once(tmp_path):
    result = run_child(tmp_path, r"""
      const w=world();w.init();
      console.log(JSON.stringify({clocks:w.clocks()}));
    """)
    assert result["clocks"] == [{"rs": 1, "type": "clock", "frame": 0, "playing": False}]
