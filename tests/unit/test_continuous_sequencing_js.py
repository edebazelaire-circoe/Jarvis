"""Lecture continue d'une variante (handoff jarvis-remotion-native-studio-playback-fix, Slice 05), exécutée par node avec un faux DOM.

Deux choses, chacune avec ses cas négatifs :

1. Les défauts de passage de main de l'hôte des cadres (`control_center_prefab_host.js`), relevés par la Slice 03 (`FINDINGS.md`) :
   - la prise de la fenêtre différée de la scène entrée était jetée par le préchargement suivant (`preload` -> `dropNext`) ;
   - la scène d'après se préchargeait avant que la scène entrée ait pris la fenêtre ;
   - les valeurs de la scène suivante partaient dans le Player qui sort (image hybride) ;
   - une scène qu'on a demandé de montrer et qui échoue restait cachée derrière la précédente (maintenant : son échec prend la fenêtre).
2. Le séquenceur de Variantes (`control_center_presentation_studio_sequencer.js`) : chaque scène joue sa longueur AUTHORED, la suivante
   commence sur son image 0 à la frontière, l'attente est visible, l'échec nomme la scène et ne la saute jamais, la dernière image est
   tenue, « Rejouer » repart de f = 0, la clé de la carte est obligatoire et un écart avec l'aperçu est relu une fois puis dit.

Contrat : `docs/presentation-studio.md` > *Presentation experience contract* § 3-§ 4, *Composition clock (Level 3)*.
La preuve dans un vrai Chrome : `test_presentation_continuous_playback_browser.py`.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_remotion_continuity_js import HOST_BENCH
from tests.unit.test_remotion_sandbox_child_js import run_child
from tests.unit.test_remotion_stage_js import run_stage_node

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
PATHS = {"seq": str(RUNTIME / "control_center_presentation_studio_sequencer.js"), "clock": str(RUNTIME / "control_center_composition_clock.js")}

C = "presentation-studio.p000000000001.s000000000003"


# ------------------------------------------------------------------ 1. the host: hand-over defects

async def test_a_deferred_takeover_survives_the_next_preload_which_starts_once_the_scene_took_the_window(tmp_path):
    """Slice 03 defect A: scene B was claimed (takeover deferred), then the preload of C dropped it; the window waited forever."""

    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const C='""" + C + r"""';
      const b=hostBench();
      b.host.mount(b.slot,b.inst(b.A));await b.bringUp(b.A);b.c.advance(2000);
      b.host.preload('stage',b.inst(b.B));const fb=await b.bringUp(b.B);b.c.advance(400);   // B loaded ahead, parked
      b.host.mount(b.slot,b.inst(b.B));                     // the score reaches B: takeover deferred to the next turn
      const queued=b.host.preload('stage',b.inst(C));        // the view of B already names C: BEFORE B took the window
      const during={key:b.host.key('stage'),pending:b.host.pendingKey('stage'),frames:b.frames().length,hidden:[fb.getAttribute('aria-hidden'),fb.inert]};
      b.c.advance(1);
      const after={key:b.host.key('stage'),pending:b.host.pendingKey('stage'),lives:b.lives.length,bOnScreen:!fb.className.includes('sc-prefab-staged'),
        hidden:[fb.getAttribute('aria-hidden'),fb.inert]};
      return {queued,during,after,logs:b.logs.map(l=>l.key).filter(k=>k.includes('preload'))};
    """)
    assert result["queued"] is True
    assert result["during"]["key"].endswith("s000000000001@1") and result["during"]["pending"].endswith("s000000000002@1"), "B is still the frame beside"
    assert result["during"]["frames"] == 2, "C is not loaded while B has not taken the window"
    assert result["during"]["hidden"] == ["true", True] and result["after"]["hidden"] == [None, False], "a waiting frame is inert and unannounced"
    after = result["after"]
    assert after["key"].endswith("s000000000002@1") and after["bOnScreen"] is True, "B took the window"
    assert after["pending"].endswith("s000000000003@1"), "and C is loaded ahead right after"
    assert "scene.prefab_preload_queued" in result["logs"] and "scene.prefab_preloaded" in result["logs"]


async def test_the_scene_after_next_waits_for_a_scene_that_is_still_loading_and_a_newer_request_replaces_the_queued_one(tmp_path):
    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const C='""" + C + r"""',D='presentation-studio.p000000000001.s000000000004';
      const b=hostBench();
      b.host.mount(b.slot,b.inst(b.A));await b.bringUp(b.A);b.c.advance(2000);
      b.host.mount(b.slot,b.inst(b.B));await flush();     // B claimed, not preloaded: it loads beside A
      const first=b.host.preload('stage',b.inst(C));
      const second=b.host.preload('stage',b.inst(D));             // the latest wish wins
      const loadingFrames=b.frames().length;
      await b.bringUp(b.B);b.c.advance(400);                      // B settles and takes the window by itself
      return {first,second,loadingFrames,key:b.host.key('stage'),pending:b.host.pendingKey('stage')};
    """)
    assert result["first"] is True and result["second"] is True
    assert result["loadingFrames"] == 2, "nothing is preloaded behind a scene that has not taken the window"
    assert result["key"].endswith("s000000000002@1") and result["pending"].endswith("s000000000004@1")


async def test_the_values_of_the_incoming_scene_never_reach_the_outgoing_player(tmp_path):
    """Slice 03 'hybrid frame': S2's frame 239 was shown with S3's title and colour for 78 s."""

    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench();
      const props=(f)=>f.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props').map(m=>m.props.title);
      b.host.mount(b.slot,b.inst(b.A,{props:{title:'A'}}));const fa=await b.bringUp(b.A);b.c.advance(2000);
      b.host.preload('stage',b.inst(b.B,{props:{title:'B'}}));const fb=await b.bringUp(b.B);b.c.advance(400);
      b.host.mount(b.slot,b.inst(b.B,{props:{title:'B2'}}));     // entered with newer values
      b.host.update('stage',{title:'B3'},{});                      // the scene stream patches the window before the swap
      const beforeSwap={a:props(fa),b:props(fb),key:b.host.key('stage')};
      b.c.advance(200);
      b.host.update('stage',{title:'B4'},{});
      return {beforeSwap,a:props(fa),b:props(fb),key:b.host.key('stage')};
    """)
    assert result["beforeSwap"]["key"].endswith("s000000000001@1")
    assert result["a"] == ["A"], f"the outgoing Player got the next scene's values: {result['a']}"
    assert result["b"] == ["B", "B2", "B3", "B4"] and result["key"].endswith("s000000000002@1")


async def test_a_new_version_of_the_same_scene_still_keeps_both_frames_current(tmp_path):
    """Negative case: a hot reload (same prefab, new version) is not a scene change; values reach the live frame and the new one."""

    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench();
      const props=(f)=>f.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props').map(m=>m.props.title);
      b.host.mount(b.slot,b.inst(b.A,{props:{title:'v1'}}));const fa=await b.bringUp(b.A);b.c.advance(2000);
      b.host.mount(b.slot,b.inst(b.A,{prefab:{id:b.A,version:2},props:{title:'v1'}}));await flush();
      const f2=b.frames()[1];
      const COMP={width:1280,height:720,fps:30,durationInFrames:150};
      b.status(f2,'shell');
      b.host.update('stage',{title:'edit'},{});
      return {a:props(fa),two:props(f2)};
    """)
    assert result["a"] == ["v1", "edit"] and result["two"] == ["v1", "edit"]


async def test_a_scene_the_window_was_told_to_show_that_fails_takes_the_window_with_its_failure(tmp_path):
    """Another scene (`scene_id` differs, or loaded ahead): its failure is shown in place of the previous scene, never hidden behind it."""

    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const run=async(ahead)=>{
        const b=hostBench();
        b.host.mount(b.slot,b.inst(b.A,{scene_id:'s1'}));const fa=await b.bringUp(b.A);b.c.advance(2000);
        if(ahead){b.host.preload('stage',b.inst(b.B));await flush();b.host.mount(b.slot,b.inst(b.B))}
        else{b.host.mount(b.slot,b.inst(b.B,{scene_id:'s2'}));await flush()}
        const fb=b.frameOf(b.B);
        b.status(fb,'shell');b.status(fb,'failed',{reason:'compile_failed',message:'Scene.tsx(3,1): boom',title:'La scène ne compile pas'});
        return {key:b.host.key('stage'),state:b.host.state('stage'),bShown:!fb.className.includes('sc-prefab-staged'),aHidden:fa.style.visibility,
          outcomes:b.outcomes.map(o=>[o.prefab.id.slice(-2),o.outcome,o.message])};
      };
      return {cold:await run(false),ahead:await run(true)};
    """)
    for case in ("cold", "ahead"):
        got = result[case]
        assert got["key"].endswith("s000000000002@1") and got["state"] == "error", case
        assert got["bShown"] is True and got["aHidden"] == "hidden", f"{case}: the failure is on screen, the previous scene is gone"
        assert got["outcomes"][-1] == ["02", "failed", "Scene.tsx(3,1): boom"], case


async def test_a_new_pin_of_the_same_scene_that_fails_leaves_the_live_frame_alone(tmp_path):
    """Negative case: the hot-reload rule (Slice 06 of the Studio) is unchanged; without a different `scene_id` a new pin is a new version."""

    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench();
      b.host.mount(b.slot,b.inst(b.A,{scene_id:'s1'}));await b.bringUp(b.A);b.c.advance(2000);
      b.host.mount(b.slot,b.inst(b.B,{scene_id:'s1'}));await flush();
      const fb=b.frameOf(b.B);
      b.status(fb,'failed',{reason:'compile_failed',message:'boom'});
      return {key:b.host.key('stage'),state:b.host.state('stage'),pending:b.host.pendingKey('stage')};
    """)
    assert result["key"].endswith("s000000000001@1") and result["state"] == "ready" and result["pending"] is None


async def test_a_scene_loaded_ahead_that_fails_leaves_the_live_scene_alone(tmp_path):
    """Negative case: nobody asked to show it yet; it is dropped and loads again at its turn."""

    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench();
      b.host.mount(b.slot,b.inst(b.A));await b.bringUp(b.A);b.c.advance(2000);
      b.host.preload('stage',b.inst(b.B));await flush();
      const fb=b.frameOf(b.B);
      b.status(fb,'failed',{reason:'compile_failed',message:'boom'});
      return {key:b.host.key('stage'),state:b.host.state('stage'),pending:b.host.pendingKey('stage')};
    """)
    assert result["key"].endswith("s000000000001@1") and result["state"] == "ready" and result["pending"] is None


def test_the_sandbox_player_never_loops_and_holds_its_last_frame(tmp_path):
    """The Slice 03 control group: `loop:false` alone jumps back to frame 0 at the end; both settings are required."""

    result = run_child(tmp_path, r"""
      const w=world();w.init();
      const props=w.refs[w.refs.length-1].props;
      console.log(JSON.stringify({loop:props.loop,move:props.moveToBeginningWhenEnded}));
    """)
    assert result == {"loop": False, "move": False}


# ------------------------------------------------------------------ 2. the Variants sequencer

SEQ_BENCH = r"""
const Seq=require(D.paths.seq),Clock=require(D.paths.clock);
const SCENES=[
  {id:'pss_1',title:'Un',prefab:{id:'presentation-studio.x.s1',version:1},props:{},data:{},fps:30,frames:90},
  {id:'pss_2',title:'Deux',prefab:{id:'presentation-studio.x.s2',version:1},props:{},data:{},fps:30,frames:900},   // 30 s
  {id:'pss_3',title:'Trois',prefab:{id:'presentation-studio.x.s3',version:1},props:{},data:{},fps:25,frames:75},
];
function wireOf(scenes,key){
  const map=Clock.build(scenes.map(s=>({scene_id:s.id,composition_id:'Scene',fps:s.fps,duration_in_frames:s.frames})));
  return {version:1,key,fps:map.fps,total_frames:map.total_frames,scenes:map.scenes.map(s=>({scene_id:s.scene_id,composition_id:s.composition_id,fps:s.fps,
    duration_in_frames:s.duration_in_frames,start:s.start,length:s.length,transition_in:s.transition_in}))};
}
function seqBench(opts){
  const o=opts||{};
  let t=1000;const timers=[];const orders=[],preloads=[],shows=[],logs=[],views=[],fetches=[];
  const key=(s)=>`${s.prefab.id}@${s.prefab.version}`;
  const H={live:null,pending:null,pk:false,st:'ready',now:null,
    key:()=>H.live,state:()=>H.st,pendingKey:()=>H.pending,parked:()=>H.pk,clock:()=>H.now,
    control(id,action,frame){orders.push([H.live&&H.live.slice(-4),action,frame===undefined?null:frame]);H.now=null;return H.st==='ready'},
    preload(id,inst){preloads.push(inst.prefab.id.slice(-2));H.pending=`${inst.prefab.id}@${inst.prefab.version}`;H.pk=!!o.parkAhead;return true}};
  const answers=o.answers||[{key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null}];
  let changedVariant=0;
  const rafs=[];   // `o.raf`: seeks reach the Player at the next animation frame (`b.frame()`), as in the page (Slice 06)
  const seq=Seq.createSequencer({objectId:'preview',host:()=>H,now:()=>t,requestFrame:o.raf?(fn)=>{rafs.push(fn)}:undefined,
    setTimeout:(fn,ms)=>{timers.push({at:t+ms,fn});return timers.length},clearTimeout:(i)=>{if(timers[i-1])timers[i-1].fn=null},
    log:(k,d,l)=>logs.push([k,l||'info']),scenes:()=>SCENES,revision:()=>o.revision===undefined?3:o.revision,selectedIndex:()=>o.selected||0,
    fetchClock:async()=>{fetches.push(1);const a=answers[Math.min(fetches.length-1,answers.length-1)];if(a instanceof Error)throw a;return a},
    show:(i)=>{shows.push(i);const want=key(SCENES[i]);if(want===H.live)return;H.pending=want},
    variantChanged:()=>{changedVariant++},changed:(v)=>views.push(v.phase),rest:o.rest});
  H.live=key(SCENES[o.selected||0]);
  const advance=(ms)=>{t+=ms;for(const x of timers.slice()){if(x.fn&&x.at<=t){const fn=x.fn;x.fn=null;fn()}}};
  /* The host swaps the frames: the pending scene is live, its Player sits paused on frame 0. */
  const swap=()=>{H.live=H.pending;H.pending=null;H.pk=false;H.st='ready';seq.onLive('preview')};
  /* The live Player reports a position. */
  const report=(frame,playing)=>{H.now={frame,playing,duration:SCENES.find(s=>key(s)===H.live).frames,fps:30,at:t};seq.onClock('preview')};
  const playTo=(from,to,step)=>{for(let f=from;f<=to;f+=step){report(Math.min(f,to),f<to)}report(to,false)};
  const frame=()=>{const due=rafs.splice(0);due.forEach(fn=>fn());return due.length};
  return {seq,H,orders,preloads,shows,logs,views,fetches,advance,swap,report,playTo,frame,key,changedVariant:()=>changedVariant,SCENES,o};
}
"""


def run_seq(tmp_path: Path, body: str):
    return run_stage_node(tmp_path, SEQ_BENCH + body, {"paths": PATHS})


async def test_every_scene_plays_its_authored_length_and_the_next_one_starts_on_its_frame_zero(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench({parkAhead:true});
      await b.seq.play();
      const start={orders:b.orders.slice(),preloads:b.preloads.slice(),phase:b.seq.view().phase};
      b.playTo(0,89,10);                                         // scene 1 (3 s) to its last frame
      const atBoundary={phase:b.seq.view().phase,shows:b.shows.slice(),frame:b.seq.view().frame};
      b.swap();                                                   // the preloaded scene 2 takes the window
      b.report(0,true);
      for(let i=0;i<60;i++){b.advance(1000);b.report(i*10,true)}   // 60 s of wall time, the Player reporting: no timer ever moves a scene
      b.playTo(0,600,30);                                         // 20 s into the 30 s scene, past any 8 s target
      const mid={phase:b.seq.view().phase,scene:b.seq.view().scene_index,frame:b.seq.view().frame,shows:b.shows.length};
      b.playTo(600,899,30);
      b.swap();b.report(0,true);b.playTo(0,74,5);
      const end=b.seq.view();
      const ordersAtEnd=b.orders.length;
      b.report(74,false);b.advance(10000);
      return {start,atBoundary,mid,end:{phase:end.phase,frame:end.frame,total:end.total_frames},orders:b.orders,ordersAtEnd,
        after:b.orders.length,shows:b.shows,boundaries:b.seq.stats().boundaries};
    """)
    assert result["start"]["orders"] == [["s1@1", "play", 0]] and result["start"]["preloads"] == ["s2"]
    assert result["atBoundary"]["shows"] == [1] and result["atBoundary"]["frame"] == 90, "f moved to start_1 exactly"
    assert result["mid"] == {"phase": "playing", "scene": 1, "frame": 690, "shows": 1}, "the 30 s scene is never cut"
    assert result["orders"] == [["s1@1", "play", 0], ["s2@1", "play", 0], ["s3@1", "play", 0]], "each scene from its local frame 0, once"
    # master fps 30: S3 at 25 fps for 75 frames -> 90 master frames; L = 90 + 900 + 90
    assert result["end"] == {"phase": "ended", "frame": 1079, "total": 1080}
    assert result["after"] == result["ordersAtEnd"], "the final frame is held: nothing replays or wraps"
    assert [(x["from"], x["to"], x["ready_ahead"]) for x in result["boundaries"]] == [(0, 1, True), (1, 2, True)]


async def test_replay_restarts_from_frame_zero_and_plays_the_same_way(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench({parkAhead:true});
      await b.seq.play();b.playTo(0,89,30);b.swap();b.report(0,true);b.playTo(0,899,100);b.swap();b.report(0,true);b.playTo(0,74,25);
      const label=b.seq.view().phase;
      const before=b.orders.length;
      await b.seq.play();                                          // « Rejouer »
      const first=b.seq.view();
      b.swap();
      return {label,replay:b.orders.slice(before),shows:b.shows.slice(-1),frame:first.frame,phase:b.seq.view().phase,fetches:b.fetches.length};
    """)
    assert result["label"] == "ended" and result["frame"] == 0 and result["shows"] == [0]
    assert result["replay"] == [["s1@1", "play", 0]] and result["phase"] == "playing"
    assert result["fetches"] == 1, "the same map: replay is deterministic, nothing re-read"


async def test_a_clock_sent_before_the_order_reached_the_player_never_ends_the_scene(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.play();
      b.report(89,false);                                          // the preview had played to its end before « Lire »: a stale report
      const stale={phase:b.seq.view().phase,shows:b.shows.length,frame:b.seq.view().frame};
      b.report(3,true);b.report(40,true);
      return {stale,frame:b.seq.view().frame};
    """)
    assert result["stale"] == {"phase": "playing", "shows": 0, "frame": 0}
    assert result["frame"] == 40


async def test_a_scene_not_ready_at_the_boundary_holds_the_outgoing_frame_with_a_visible_wait_then_starts_at_zero(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench();                                          // the scene ahead is still loading (not parked)
      await b.seq.play();b.playTo(0,89,30);
      const at=b.seq.view();
      b.advance(100);const early=b.seq.view().waiting_visible;
      b.advance(2400);const later=b.seq.view();
      const ordersWhileWaiting=b.orders.length;
      b.swap();
      return {at:{phase:at.phase,scene:at.scene_index},early,later:{visible:later.waiting_visible,ms:later.waiting_ms,phase:later.phase},
        ordersWhileWaiting,orders:b.orders,views:[...new Set(b.views)],boundary:b.seq.stats().boundaries[0]};
    """)
    assert result["at"] == {"phase": "waiting", "scene": 1}
    assert result["early"] is False, "a normal boundary never flashes the indicator"
    assert result["later"]["visible"] is True and result["later"]["ms"] == 2500 and result["later"]["phase"] == "waiting"
    assert result["ordersWhileWaiting"] == 1, "nothing is ordered to the outgoing Player: it holds its last frame"
    assert result["orders"][-1] == ["s2@1", "play", 0]
    assert result["boundary"]["gap_ms"] == 2500 and result["boundary"]["ready_ahead"] is False


async def test_a_scene_that_fails_to_load_stops_playback_on_it_named_and_is_never_skipped(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.play();b.playTo(0,89,30);
      b.seq.onOutcome({object_id:'preview',prefab:{id:'presentation-studio.x.s2',version:1},outcome:'failed',reason:'compile_failed',message:'Scene.tsx(3,1): boom'});
      const v=b.seq.view();
      b.advance(120000);
      const showsAfter=b.shows.slice();
      await b.seq.retry();
      return {phase:v.phase,error:v.error,frame:v.frame,showsAfter,retryShows:b.shows.slice(),retryPhase:b.seq.view().phase,
        errors:b.logs.filter(l=>l[1]==='error').map(l=>l[0])};
    """)
    assert result["phase"] == "failed" and result["frame"] == 90, "paused at the failed scene's start"
    assert result["error"] == {"code": "scene_failed", "message": "Scene.tsx(3,1): boom", "scene_index": 1, "scene_id": "pss_2", "scene_title": "Deux"}
    assert result["showsAfter"] == [1], "never a skip to scene 3"
    assert result["retryShows"] == [1, 1] and result["retryPhase"] == "waiting"
    assert "sequencer_failed" in result["errors"]


async def test_pause_holds_the_frame_and_play_resumes_from_it(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.play();b.report(5,true);b.report(40,true);
      b.seq.pause();
      const paused=b.seq.view();
      b.advance(5000);b.report(40,false);
      await b.seq.play();
      return {paused:{phase:paused.phase,frame:paused.frame},orders:b.orders};
    """)
    assert result["paused"] == {"phase": "paused", "frame": 40}
    assert result["orders"] == [["s1@1", "play", 0], ["s1@1", "pause", None], ["s1@1", "play", 40]]


async def test_the_map_needs_its_key_and_a_map_that_does_not_match_the_preview_is_read_again_once_then_said(tmp_path):
    result = run_seq(tmp_path, r"""
      const ok={key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null};
      const out={};
      let b=seqBench({answers:[{key:'other',variant_revision:3,clock:wireOf(SCENES,'k1')}]});
      await b.seq.play();out.foreign=[b.seq.view().phase,b.seq.view().error.code,b.orders.length];
      b=seqBench({answers:[{variant_revision:3,clock:wireOf(SCENES,'k1')}]});
      await b.seq.play();out.keyless=[b.seq.view().phase,b.seq.view().error.code,b.orders.length];
      b=seqBench({answers:[Object.assign({},ok,{variant_revision:2}),ok]});
      await b.seq.play();out.once=[b.seq.view().phase,b.fetches.length,b.orders.length];
      b=seqBench({answers:[Object.assign({},ok,{variant_revision:2})]});
      await b.seq.play();out.changed=[b.seq.view().phase,b.seq.view().error.code,b.fetches.length,b.orders.length,b.changedVariant()];
      b=seqBench({answers:[{key:'k1',variant_revision:3,clock:null,problem:{code:'composition_scene_not_remotion',message:'Scène HTML',scene_id:'pss_2'}}]});
      await b.seq.play();out.problem=[b.seq.view().phase,b.seq.view().error,b.orders.length];
      b=seqBench({answers:[Object.assign(new Error('Core injoignable'),{code:'network'})]});
      await b.seq.play();out.down=[b.seq.view().phase,b.seq.view().error.code,b.orders.length];
      return out;
    """)
    assert result["foreign"] == ["failed", "composition_wire_mismatch", 0]
    assert result["keyless"] == ["failed", "composition_key_required", 0]
    assert result["once"] == ["playing", 2, 1], "a stale map is read again once, then plays"
    assert result["changed"] == ["idle", "variant_changed", 2, 0, 1], "never played with a stale map; the preview is read again"
    assert result["problem"][0] == "failed" and result["problem"][2] == 0
    assert result["problem"][1] == {"code": "composition_scene_not_remotion", "message": "Scène HTML", "scene_index": 1, "scene_id": "pss_2",
                                    "scene_title": "Deux"}
    assert result["down"] == ["failed", "network", 0]


async def test_choosing_a_scene_goes_to_its_start_and_keeps_the_play_state(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.play();b.report(5,true);
      b.seq.seekScene(2);                                          // a thumbnail while playing
      const playing=b.seq.view();
      b.swap();
      b.seq.pause();
      b.seq.seekScene(0);                                          // while paused
      const paused=b.seq.view();
      b.swap();
      return {playing:[playing.phase,playing.frame],paused:[paused.phase,paused.frame],orders:b.orders};
    """)
    assert result["playing"] == ["waiting", 990] and result["paused"] == ["paused", 0]
    assert result["orders"] == [["s1@1", "play", 0], ["s3@1", "play", 0], ["s3@1", "pause", None], ["s1@1", "pause", 0]]


async def test_a_scene_held_at_its_start_shows_its_representative_still_but_plays_from_its_start(tmp_path):
    """presentation-edition-v1 Slice 09 (PM decision): a scene chosen while nothing plays shows its representative still (the host's
    `restFrame`, not its blank first frame); the clock stays at the scene's start and « Lire » plays it from frame 0. Never during a run."""

    result = run_seq(tmp_path, r"""
      const b=seqBench({rest:()=>true});
      b.H.restFrame=()=>45;
      await b.seq.play();b.report(5,true);b.seq.pause();
      b.seq.seekScene(2);b.swap();
      const held={phase:b.seq.view().phase,frame:b.seq.view().frame,last:b.orders.slice(-1)[0]};
      await b.seq.play();
      const played=b.orders.slice(-1)[0];
      const r=seqBench({rest:()=>false});r.H.restFrame=()=>45;
      await r.seq.play();r.report(5,true);r.seq.pause();r.seq.seekScene(2);r.swap();
      return {held,played,run:r.orders.slice(-1)[0]};
    """)
    assert result["held"] == {"phase": "paused", "frame": 990, "last": ["s3@1", "pause", 45]}, "the still is shown, the clock stays at the start"
    assert result["played"] == ["s3@1", "play", 0], "« Lire » plays the scene from its beginning"
    assert result["run"] == ["s3@1", "pause", 0], "no rest when the page says so (a run)"


async def test_the_real_host_and_the_sequencer_hand_over_without_a_hybrid_frame(tmp_path):
    """Both together, the real `control_center_prefab_host.js` and the sequencer: 3 scenes, preload, swap, frame 0, final hold."""

    result = run_stage_node(tmp_path, HOST_BENCH + SEQ_BENCH.split("function seqBench")[0] + r"""
      const C='""" + C + r"""';
      let seq=null;
      const b=hostBench({onLive:(id)=>seq&&seq.onLive(id),onClock:(id)=>seq&&seq.onClock(id),onOutcome:(o)=>seq&&seq.onOutcome(o)});
      const deck=[{id:'pss_1',title:'Un',prefab:{id:b.A,version:1},props:{title:'one'},data:{},fps:30,frames:150},
                  {id:'pss_2',title:'Deux',prefab:{id:b.B,version:1},props:{title:'two'},data:{},fps:30,frames:150},
                  {id:'pss_3',title:'Trois',prefab:{id:C,version:1},props:{title:'three'},data:{},fps:30,frames:150}];
      seq=Seq.createSequencer({objectId:'stage',host:()=>b.host,now:b.c.now,setTimeout:b.c.setTimeout,clearTimeout:b.c.clearTimeout,
        scenes:()=>deck,revision:()=>1,fetchClock:async()=>({key:'k',variant_revision:1,clock:wireOf(deck,'k')}),
        show:(i)=>b.host.mount(b.slot,b.inst(deck[i].prefab.id,{props:deck[i].props})),changed:()=>{}});
      b.host.mount(b.slot,b.inst(b.A,{props:deck[0].props}));const fa=await b.bringUp(b.A);
      await seq.play();
      const fb=await b.bringUp(b.B);b.c.advance(400);                 // scene 2 loaded ahead, parked
      const tick=(f,frame,playing)=>b.say(f,{type:'clock',frame,playing,duration:150,fps:30});
      tick(fa,2,true);tick(fa,80,true);tick(fa,149,false);         // scene 1 ends
      const aPropsAtEnd=fa.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props').map(m=>m.props.title);
      b.c.advance(1);                                                   // the deferred takeover
      const fc=await b.bringUp(C);b.c.advance(400);
      tick(fb,1,true);tick(fb,149,false);b.c.advance(1);
      tick(fc,0,true);tick(fc,149,false);
      return {aProps:aPropsAtEnd,a:b.posted(fa),bOrders:b.posted(fb),cOrders:b.posted(fc),view:seq.view(),bounds:seq.stats().boundaries.map(x=>[x.from,x.to,x.ready_ahead])};
    """, {"paths": PATHS})
    assert result["aProps"] == ["one"], "scene 1 never showed scene 2's values"
    assert result["a"][-1] == ["play", 0, None]
    assert result["bOrders"] == [["pause", 0, None], ["play", 0, None]] and result["cOrders"] == [["pause", 0, None], ["play", 0, None]]
    assert result["view"]["phase"] == "ended" and result["view"]["frame"] == 449
    assert result["bounds"] == [[0, 1, True], [1, 2, True]]


async def test_a_player_that_ends_one_or_two_frames_short_of_its_last_frame_ends_the_scene(tmp_path):
    """Slice 05 rework, B1: Remotion stops on 88 (or 87) of 0..89 when a frame is dropped. The sequencer waited for 89 and stayed
    `playing` forever with « Pause » on screen; it now takes a Player halted by itself that close to the end as the end of the scene."""

    result = run_seq(tmp_path, r"""
      const out={};
      for(const halt of [88,87]){
        const b=seqBench({parkAhead:true});
        await b.seq.play();b.report(5,true);b.report(60,true);
        b.report(halt,false);
        const v=b.seq.view();
        b.swap();b.report(0,true);b.playTo(0,899,100);b.swap();b.report(0,true);b.report(30,true);
        b.report(73,false);                                        // the last scene too: 0..74 at 25 fps, halted one short
        out[halt]={boundary:[v.phase,v.scene_index,v.frame],shows:b.shows,end:[b.seq.view().phase,b.seq.view().frame]};
      }
      return out;
    """)
    for halt in ("88", "87"):
        assert result[halt]["boundary"] == ["waiting", 1, 90], halt
        assert result[halt]["shows"] == [1, 2] and result[halt]["end"] == ["ended", 1079], halt


async def test_a_player_halted_further_back_or_paused_by_the_user_does_not_end_the_scene(tmp_path):
    """Negative cases: 3 frames short is not an end; after the user's pause a halted clock near the end changes nothing."""

    result = run_seq(tmp_path, r"""
      const b=seqBench({parkAhead:true});
      await b.seq.play();b.report(5,true);b.report(60,true);
      b.report(86,false);
      const short3=[b.seq.view().phase,b.seq.view().frame,b.shows.length];
      b.report(87,true);
      b.seq.pause();b.report(88,false);
      return {short3,paused:[b.seq.view().phase,b.seq.view().frame,b.shows.length]};
    """)
    assert result["short3"] == ["playing", 86, 0]
    # Slice 06: the Player's own halt frame after the pause becomes `f` (88, resume starts there); the scene is still not ended
    assert result["paused"] == ["paused", 88, 0]


async def test_a_stale_or_earlier_clock_in_the_middle_of_a_scene_never_moves_the_frame_back(tmp_path):
    """QA mutant M12: the guard on `f` is the only thing that stops a backward clock mid-scene (§ 4.2: no return to an earlier frame)."""

    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.play();b.report(5,true);b.report(40,true);
      b.report(20,true);const back=b.seq.view().frame;
      b.report(39,false);const halted=b.seq.view().frame;
      b.report(41,true);
      return {back,halted,on:b.seq.view().frame};
    """)
    assert result == {"back": 40, "halted": 40, "on": 41}


async def test_retry_after_a_scene_failed_to_load_reloads_it_in_the_real_host_and_playback_goes_on(tmp_path):
    """Slice 05 rework, B2, on the real `control_center_prefab_host.js`: « Réessayer » showed the same pin again, which the host took for
    "already there"; the scene stayed in error and the wait pill counted forever. Retry now loads the failed scene again."""

    result = run_stage_node(tmp_path, HOST_BENCH + SEQ_BENCH.split("function seqBench")[0] + r"""
      let seq=null;
      const b=hostBench({onLive:(id)=>seq&&seq.onLive(id),onClock:(id)=>seq&&seq.onClock(id),onOutcome:(o)=>{b2.outcomes.push(o);seq&&seq.onOutcome(o)}});
      const b2={outcomes:[]};
      const deck=[{id:'pss_1',title:'Un',prefab:{id:b.A,version:1},props:{title:'one'},data:{},fps:30,frames:150},
                  {id:'pss_2',title:'Deux',prefab:{id:b.B,version:1},props:{title:'two'},data:{},fps:30,frames:150}];
      seq=Seq.createSequencer({objectId:'stage',host:()=>b.host,now:b.c.now,setTimeout:b.c.setTimeout,clearTimeout:b.c.clearTimeout,
        scenes:()=>deck,revision:()=>1,fetchClock:async()=>({key:'k',variant_revision:1,clock:wireOf(deck,'k')}),
        show:(i)=>b.host.mount(b.slot,b.inst(deck[i].prefab.id,{scene_id:deck[i].id,props:deck[i].props})),changed:()=>{}});
      const tick=(f,frame,playing)=>b.say(f,{type:'clock',frame,playing,duration:150,fps:30});
      const up=(f)=>{const C={width:1280,height:720,fps:30,durationInFrames:150};
        b.status(f,'shell');b.status(f,'mounting',{composition:C});b.status(f,'ready',{composition:C});tick(f,0,false)};
      b.host.mount(b.slot,b.inst(b.A,{scene_id:'pss_1',props:deck[0].props}));const fa=await b.bringUp(b.A);b.c.advance(2000);
      await seq.play();await flush();
      b.status(b.frames()[b.frames().length-1],'failed',{reason:'compile_failed',message:'Scene.tsx(3,1): boom'});   // loaded ahead: dropped
      tick(fa,2,true);tick(fa,149,false);await flush();                                    // the boundary: scene 2 is asked for, loads again
      const fb=b.frames()[b.frames().length-1];
      b.status(fb,'shell');b.status(fb,'failed',{reason:'compile_failed',message:'Scene.tsx(3,1): boom'});
      const failed={phase:seq.view().phase,scene:seq.view().error&&seq.view().error.scene_index,state:b.host.state('stage'),key:b.host.key('stage')};
      const framesBefore=b.frames().length;
      await seq.retry();await flush();
      const fresh=b.frames()[b.frames().length-1];
      const retrying={phase:seq.view().phase,state:b.host.state('stage'),newFrame:fresh!==fb};
      up(fresh);b.c.advance(400);
      const live={phase:seq.view().phase,orders:b.posted(fresh)};
      tick(fresh,1,true);tick(fresh,149,false);
      return {failed,retrying,live,end:[seq.view().phase,seq.view().frame],framesBefore,
        outcomes:b2.outcomes.map(o=>[o.prefab.id.slice(-2),o.outcome])};
    """, {"paths": PATHS})
    assert result["failed"] == {"phase": "failed", "scene": 1, "state": "error", "key": "presentation-studio.p000000000001.s000000000002@1"}
    assert result["retrying"] == {"phase": "waiting", "state": "loading", "newFrame": True}, "a fresh load of the failed scene"
    assert result["live"]["phase"] == "playing" and result["live"]["orders"] == [["pause", 0, None], ["play", 0, None]]
    assert result["end"] == ["ended", 299]
    assert result["outcomes"] == [["01", "mounted"], ["02", "failed"], ["02", "failed"], ["02", "mounted"]], "the ahead load, the shown one, the retry"
