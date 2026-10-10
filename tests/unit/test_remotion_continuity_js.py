"""Lecture continue côté navigateur (handoff jarvis-remotion-presentation-integration, Slice 23), exécuté par node avec un faux DOM.

Le suiveur de ligne de temps et l'hôte des cadres, ce qui faisait « saccader » une lecture :

- le suiveur n'ordonne jamais au cadre qui part (celui de la scène précédente) le segment de la scène suivante ;
- un Player arrêté sur son image d'arrêt n'est pas un Player muet : il n'est plus jamais relancé depuis le début de son segment ;
- en lecture enchaînée le suiveur DIT ce qui s'est passé (segment commencé, image d'arrêt atteinte), sans ordre ni rattrapage par saut ;
- l'hôte démarre chaque Player en pause sur l'image 0, le laisse jouer seul après un court délai si rien ne l'ordonne, charge la
  scène suivante à côté (en pause) et la prend sur-le-champ quand la partition y arrive.
La preuve dans un vrai Chrome est `test_remotion_continuity_realpage_browser.py`.
Contrat : `docs/presentation-studio.md` > *Remotion timeline bridge* > *Chained playback*, `docs/remotion-isolation.md` § 11.7.
"""

from __future__ import annotations

from tests.unit.test_remotion_stage_js import run_stage_node

FOLLOWER = r"""
function bench(opts){
  const o=opts||{};
  let t=100000;const orders=[],logs=[],reports=[],intervals=[];
  const clocks=new Map();let key='studio.s2@1',incarnation=1;
  const host={control(id,action,frame,until){orders.push({id,action,frame,until});clocks.delete(id);return true},
    clock(id){return clocks.get(id)||null},key:()=>key,frame:()=>incarnation};
  const follower=Frame.createTimelineFollower({getHost:()=>host,now:()=>t,log:(l,k,d)=>logs.push({l,k,d}),onSegment:(r)=>reports.push(r),
    setInterval:(fn,ms)=>{intervals.push({fn,ms,on:true});return intervals.length},clearInterval:(i)=>{intervals[i-1].on=false}});
  const tl=(over)=>Object.assign({scene_id:'s2',composition_id:'Scene',fps:30,duration_frames:300,anchor_id:'marker',from_frame:30,until_frame:74,
    playing:true,seq:1,play_ms:0,tolerance_ms:500,problems:[],auto:true,prefab:'studio.s2@1'},over||{});
  return {follower,host,orders,logs,reports,tl,advance:(ms)=>{t+=ms},now:()=>t,setKey:(k)=>{key=k},setIncarnation:(n)=>{incarnation=n},
    show:(over)=>follower.apply({object_id:'stage',timeline:tl(over)}),
    report:(frame,playing)=>clocks.set('stage',{frame,playing,duration:300,fps:30,at:t})};
}
"""


async def test_the_frame_of_the_previous_scene_is_never_ordered_the_segment_of_the_next_one(tmp_path):
    """The bug: while the next scene loaded beside, its segment was ordered to the frame still on screen, which replayed from frame 0."""

    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();                                                    // scene 2 plays its segment
      b.show({scene_id:'s3',prefab:'studio.s3@1',seq:2,from_frame:0,until_frame:29});   // Core moved on; the window still shows scene 2
      const waiting=b.follower.tick();
      b.advance(5000);
      const stillWaiting=b.follower.tick();
      b.setKey('studio.s3@1');b.setIncarnation(2);                // the host swapped the frames
      const swapped=b.follower.refresh('stage');
      return {waiting,stillWaiting,swapped,orders:b.orders.map(o=>[o.action,o.frame,o.until]),waits:b.follower.stats().swapWaits};
    """)
    assert result["waiting"] == "swap_wait" and result["stillWaiting"] == "swap_wait" and result["swapped"] == "segment"
    assert result["orders"] == [["play", 30, 74], ["play", 0, 29]], "one order per frame, each to its own scene"
    assert result["waits"] >= 1


async def test_a_player_halted_on_its_stop_frame_is_never_ordered_again_and_the_page_is_told_once(tmp_path):
    """The bug: the silence of a halted Player looked like a Player that never answered; its segment replayed every ~3 s."""

    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      b.report(40,true);b.follower.onClock('stage');
      b.advance(1000);
      b.report(74,false);const done=b.follower.onClock('stage');
      const ticks=[];
      for(let i=0;i<40;i++){b.advance(500);ticks.push(b.follower.tick())}      // 20 s of a Player that sits on its stop frame
      return {done,orders:b.orders.length,reports:b.reports,resent:b.follower.stats().resent,last:ticks[ticks.length-1]};
    """)
    assert result["done"] == "done" and result["last"] == "done"
    assert result["orders"] == 1 and result["resent"] == 0
    assert result["reports"] == [{"object_id": "stage", "seq": 1, "scene_id": "s2", "event": "started"},
                                 {"object_id": "stage", "seq": 1, "scene_id": "s2", "event": "done"}]


async def test_a_stale_report_of_another_segment_or_a_player_never_seen_moving_is_not_a_finished_segment(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      b.report(29,false);const other=b.follower.onClock('stage');          // the previous segment's stop frame, arriving late
      b.report(74,false);const unseen=b.follower.onClock('stage');          // on the stop frame, but never seen moving
      return {other,unseen,done:b.reports.filter(r=>r.event==='done').length};
    """)
    assert result["done"] == 0 and result["other"] != "done" and result["unseen"] != "done"


async def test_a_player_that_never_started_is_ordered_again_a_few_times_then_left_alone(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      const seen=[];
      b.report(30,false);                                                   // it answered once, then sat halted short of the stop frame
      for(let i=0;i<20;i++){b.advance(1000);seen.push(b.follower.tick())}
      return {orders:b.orders.length,resent:b.follower.stats().resent,last:seen[seen.length-1]};
    """)
    assert result["resent"] == 3 and result["orders"] == 4 and result["last"] in ("halted", "no_clock")


async def test_in_a_chained_play_a_slow_player_is_never_caught_up_by_a_seek(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      const seen=[];
      for(let i=0;i<10;i++){b.advance(1100);b.report(31,true);seen.push(b.follower.tick())}    // far behind Core's clock, still playing
      b.advance(100);
      return {orders:b.orders.length,corrections:b.follower.stats().corrections,seen:[...new Set(seen)]};
    """)
    assert result["orders"] == 1 and result["corrections"] == 0 and result["seen"] == ["ok"]


async def test_a_manual_run_is_never_told_to_core_and_still_catches_up(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show({auto:false});
      b.advance(2000);b.report(31,true);
      const first=b.follower.tick();
      b.report(74,false);b.follower.onClock('stage');
      return {first,reports:b.reports.length,orders:b.orders.length};
    """)
    assert result["reports"] == 0, "nothing is said to the page in a manual run"
    assert result["first"] == "corrected" and result["orders"] == 2


async def test_a_resumed_segment_continues_and_a_new_incarnation_of_the_same_scene_is_ordered_again(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      b.advance(1000);
      b.show({playing:false,play_ms:1000});
      b.advance(30000);
      b.show({playing:true,play_ms:1000});
      b.setIncarnation(2);
      const again=b.follower.tick();
      return {orders:b.orders.map(o=>[o.action,o.frame,o.until]),again,started:b.reports.filter(r=>r.event==='started').length};
    """)
    assert result["orders"] == [["play", 30, 74], ["pause", None, None], ["play", None, 74], ["play", 30, 74]]
    assert result["started"] == 2 and result["again"] == "segment"


# ------------------------------------------------------------------ the host: first image, preload, take-over

HOST_BENCH = r"""
const ORIGIN='http://127.0.0.1:17654';
const A='presentation-studio.p000000000001.s000000000001',B='presentation-studio.p000000000001.s000000000002';
function hostBench(extra){
  const doc=new FakeDocument(),win=new FakeWindow(),c=clock(),logs=[],outcomes=[],lives=[],clocksHeard=[];
  win.location={origin:ORIGIN};
  const bundle=(id)=>({kind:'remotion',id,version:1,title:id.slice(-2)});
  const host=H.createPrefabHost(Object.assign({document:doc,window:win,now:c.now,setTimeout:c.setTimeout,clearTimeout:c.clearTimeout,
    swapPrefix:'presentation-studio.',log:(k,d)=>logs.push({key:k,data:d}),onOutcome:(o)=>outcomes.push(o),onLive:(id)=>lives.push(id),
    onClock:(id)=>clocksHeard.push(id),fetchBundle:(id)=>Promise.resolve(bundle(id))},extra||{}));
  const slot=doc.createElement('div');doc.body.appendChild(slot);
  const inst=(prefab,over)=>Object.assign({object_id:'stage',title:'T',prefab:{id:prefab,version:1},props:{title:'x'},data:{}},over||{});
  const frames=()=>slot.children.filter(n=>n.tagName==='IFRAME');
  const frameOf=(prefab)=>frames().find(f=>(f.attributes.title||'').includes(prefab))||null;
  const say=(f,data)=>win.dispatch({source:f.contentWindow,origin:ORIGIN,data:Object.assign({rsh:1},data)});
  const status=(f,phase,extra)=>say(f,Object.assign({type:'status',phase},extra||{}));
  const COMP={width:1280,height:720,fps:30,durationInFrames:150};
  const posted=(f)=>f.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='control').map(m=>[m.action,m.frame,m.until]);
  const bringUp=async(prefab)=>{
    await flush();const f=frameOf(prefab);
    status(f,'shell');status(f,'mounting',{composition:COMP});status(f,'ready',{composition:COMP});
    say(f,{type:'clock',frame:0,playing:false,duration:150,fps:30});
    return f;
  };
  return {doc,win,c,host,slot,inst,frames,frameOf,say,status,bringUp,posted,logs,outcomes,lives,clocksHeard,A,B};
}
"""


async def test_a_player_starts_paused_on_its_first_image_and_plays_alone_after_the_grace_period_unless_ordered(tmp_path):
    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const free=hostBench();
      free.host.mount(free.slot,free.inst(free.A));
      const f=await free.bringUp(free.A);
      const atReady=free.posted(f);
      free.c.advance(449);const before=free.posted(f).length;
      free.c.advance(2);
      const afterGrace=free.posted(f);
      const ordered=hostBench();
      ordered.host.mount(ordered.slot,ordered.inst(ordered.A));
      const g=await ordered.bringUp(ordered.A);
      const orderedAt=ordered.host.control('stage','play',30,74);
      ordered.c.advance(5000);
      return {atReady,before,afterGrace,orderedAt,orderedPosts:ordered.posted(g),lives:[free.lives,ordered.lives]};
    """)
    assert result["atReady"] == [["pause", 0, None]], "the first thing the Player is told: wait on the first image"
    assert result["before"] == 1 and result["afterGrace"] == [["pause", 0, None], ["play", None, None]]
    assert result["orderedAt"] is True and result["orderedPosts"] == [["pause", 0, None], ["play", 30, 74]], "an order cancels the grace period"
    assert result["lives"] == [["stage"], ["stage"]], "the page's follower is told the moment a Player is live"


async def test_the_next_scene_loads_beside_the_live_one_paused_and_takes_its_place_at_once_when_the_score_gets_there(tmp_path):
    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench();
      b.host.mount(b.slot,b.inst(b.A));
      const live=await b.bringUp(b.A);
      b.c.advance(2000);                                           // the live scene is mounted and playing
      b.lives.length=0;
      const accepted=b.host.preload('stage',b.inst(b.B));
      const again=b.host.preload('stage',b.inst(b.B));
      const sameScene=b.host.preload('stage',b.inst(b.A));
      const other=b.host.preload('stage',b.inst('another.prefab'));
      const next=await b.bringUp(b.B);
      b.c.advance(2000);                                           // far beyond SETTLE_MS: it still waits
      const waiting={key:b.host.key('stage'),pending:b.host.pendingKey('stage'),parked:b.host.parked('stage'),
        stagedClass:next.className.includes('sc-prefab-staged'),postedToNext:b.posted(next),outcomes:b.outcomes.length,
        liveStillPlaying:!live.style.visibility,clockHeard:b.clocksHeard.length};
      const mounted=b.host.mount(b.slot,b.inst(b.B,{props:{title:'x'}}));    // the score reached scene B (same values)
      b.c.advance(1);
      const swapped={key:b.host.key('stage'),pending:b.host.pendingKey('stage'),stagedClass:next.className.includes('sc-prefab-staged'),
        oldHidden:live.style.visibility,lives:b.lives.slice(),outcomes:b.outcomes.map(o=>[o.prefab.id.slice(-2),o.outcome]),
        remounts:b.host.counters('stage').remounts};
      b.c.advance(5000);
      return {accepted,again,sameScene,other,waiting,mounted,swapped,afterGrace:b.posted(next)};
    """)
    assert (result["accepted"], result["again"], result["sameScene"], result["other"]) == (True, False, False, False)
    waiting = result["waiting"]
    assert waiting["key"].endswith("s000000000001@1") and waiting["pending"].endswith("s000000000002@1")
    assert waiting["parked"] is True and waiting["stagedClass"] is True and waiting["outcomes"] == 1, "the live scene's own report only"
    assert waiting["postedToNext"] == [["pause", 0, None]], "the staged Player was never told to play"
    assert waiting["liveStillPlaying"] is True
    assert result["mounted"] is False, "no new frame: the preloaded one is taken"
    swapped = result["swapped"]
    assert swapped["key"].endswith("s000000000002@1") and swapped["pending"] is None and swapped["stagedClass"] is False
    assert swapped["oldHidden"] == "hidden" and swapped["lives"] == ["stage"] and swapped["remounts"] == 1
    assert swapped["outcomes"][-1] == ["02", "mounted"], "the scene is reported as mounted when it is on screen, not when it was preloaded"
    assert result["afterGrace"] == [["pause", 0, None], ["play", None, None]], "nobody ordered it: it plays on its own after the grace period"


async def test_values_that_changed_while_it_waited_are_rendered_before_the_preloaded_scene_takes_over(tmp_path):
    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench();
      b.host.mount(b.slot,b.inst(b.A));
      await b.bringUp(b.A);
      b.c.advance(2000);
      b.host.preload('stage',b.inst(b.B,{props:{title:'old'}}));
      const next=await b.bringUp(b.B);
      b.c.advance(2000);
      b.host.mount(b.slot,b.inst(b.B,{props:{title:'new'}}));
      const early=b.host.key('stage');
      b.c.advance(H.PROPS_SETTLE_MS||120);
      return {early,late:b.host.key('stage'),props:next.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props').length};
    """)
    assert result["early"].endswith("s000000000001@1") and result["late"].endswith("s000000000002@1")


async def test_a_staged_frame_does_not_drive_the_follower_and_a_preload_without_a_live_window_does_nothing(tmp_path):
    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench();
      const none=b.host.preload('stage',b.inst(b.B));
      b.host.mount(b.slot,b.inst(b.A));
      const early=b.host.preload('stage',b.inst(b.B));                // the live frame is not ready yet
      const live=await b.bringUp(b.A);
      b.c.advance(2000);
      b.clocksHeard.length=0;
      b.host.preload('stage',b.inst(b.B));
      const next=await b.bringUp(b.B);
      b.say(next,{type:'clock',frame:3,playing:true,duration:150,fps:30});
      const staged=b.clocksHeard.length;
      b.say(live,{type:'clock',frame:90,playing:true,duration:150,fps:30});
      return {none,early,staged,live:b.clocksHeard.length,stats:b.host.stats().staging};
    """)
    assert result["none"] is False and result["early"] is False
    assert result["staged"] == 0 and result["live"] == 1 and result["stats"] == 1
