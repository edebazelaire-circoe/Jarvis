"""Côté navigateur de la ligne de temps Remotion (handoff jarvis-remotion-presentation-integration, Slice 12), exécuté par node.

Prouvé : le suiveur applique la `timeline` de la vue de Core (aller au segment, jouer jusqu'à l'image d'arrêt, pause, reprise sans
revenir en arrière, ordre jamais rejoué), le rattrapage de dérive est borné (en retard seulement, un par seconde, cinq par segment),
une position falsifiée ou périmée ne provoque rien d'inattendu, la page de la scène relaie la position au plus 4 fois par seconde
après l'avoir bornée à la composition, et un cadre ou une page étrangère ne peut pas la fausser.
Contrat : `docs/presentation-studio.md` > *Remotion timeline bridge*, `docs/remotion-isolation.md` § 11.
"""

from __future__ import annotations

from tests.unit.test_remotion_stage_js import READY_FLOW, run_stage_node

FOLLOWER = r"""
function bench(opts){
  const o=opts||{};
  let t=100000;const orders=[],logs=[],intervals=[];
  const clocks=new Map();
  const host={ready:o.ready!==false,control(id,action,frame,until){if(!host.ready)return false;orders.push({id,action,frame,until});clocks.delete(id);return true},
    clock(id){return clocks.get(id)||null}};
  const follower=Frame.createTimelineFollower({getHost:()=>o.noHost?null:host,now:()=>t,log:(l,k,d)=>logs.push({l,k,d}),
    setInterval:(fn,ms)=>{intervals.push({fn,ms,on:true});return intervals.length},clearInterval:(i)=>{intervals[i-1].on=false}});
  const tl=(over)=>Object.assign({scene_id:'s2',composition_id:'Scene',fps:30,duration_frames:300,anchor_id:'marker',from_frame:180,until_frame:299,
    playing:true,seq:1,play_ms:0,tolerance_ms:500,problems:[]},over||{});
  return {follower,host,orders,logs,intervals,clocks,tl,advance:(ms)=>{t+=ms},now:()=>t,
    show:(over,id)=>follower.apply({object_id:id||'studio-stage-r1',timeline:tl(over)}),
    report:(frame,playing,age)=>clocks.set('studio-stage-r1',{frame,playing:playing!==false,duration:300,fps:30,at:t-(age||0)})};
}
"""


async def test_a_new_segment_seeks_to_its_start_and_plays_up_to_its_stop_frame_once(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      const first=b.show(), again=b.show(), same=b.show({play_ms:40});
      return {first,again,same,orders:b.orders,applied:b.follower.stats().applied};
    """)
    assert result["first"] == "segment" and result["again"] == "same" and result["same"] == "same"
    assert result["orders"] == [{"id": "studio-stage-r1", "action": "play", "frame": 180, "until": 299}]     # one order, never replayed
    assert result["applied"] == 1


async def test_a_hold_segment_pauses_on_its_frame_and_a_new_sequence_number_seeks_again(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show({anchor_id:null,from_frame:0,until_frame:0,playing:false,seq:1});
      b.show({seq:2});
      b.show({anchor_id:'intro',from_frame:30,until_frame:119,seq:3});
      return b.orders;
    """)
    assert result == [
        {"id": "studio-stage-r1", "action": "pause", "frame": 0},
        {"id": "studio-stage-r1", "action": "play", "frame": 180, "until": 299},
        {"id": "studio-stage-r1", "action": "play", "frame": 30, "until": 119}]


async def test_pause_holds_where_the_player_is_and_resume_continues_without_seeking_back(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      b.advance(2000);
      const paused=b.show({playing:false,play_ms:2000});
      b.advance(30000);
      const resumed=b.show({playing:true,play_ms:2000});
      return {paused,resumed,orders:b.orders.slice(1)};
    """)
    assert result["paused"] == "paused" and result["resumed"] == "playing"
    assert result["orders"] == [{"id": "studio-stage-r1", "action": "pause"},
                                {"id": "studio-stage-r1", "action": "play", "until": 299}]       # no frame: nowhere to seek back to


async def test_a_frame_that_is_not_ready_is_retried_by_the_tick_until_it_is(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench({ready:false});
      const first=b.show();
      const stuck=b.follower.tick();
      b.host.ready=true;
      const later=b.follower.tick();
      return {first,stuck,later,orders:b.orders,pending:b.follower.stats().pending,state:b.follower.state()};
    """)
    assert result["first"] == "pending" and result["stuck"] == "pending" and result["later"] == "segment"
    assert result["orders"] == [{"id": "studio-stage-r1", "action": "play", "frame": 180, "until": 299}]
    assert result["state"]["pending"] is False


async def test_the_end_of_the_run_clears_the_follower_and_stops_its_timer(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      const timers=b.intervals.filter(i=>i.on).length;
      const none=b.follower.apply({object_id:'studio-stage-r1',timeline:null});
      return {timers,none,after:b.intervals.filter(i=>i.on).length,state:b.follower.state(),orders:b.orders.length};
    """)
    assert (result["timers"], result["none"], result["after"], result["orders"]) == (1, "none", 0, 1)
    assert result["state"]["objectId"] is None


async def test_an_invalid_or_hostile_timeline_gives_no_order(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      const bad=[{fps:0},{fps:121},{from_frame:-1},{until_frame:5},{from_frame:300,until_frame:300},{duration_frames:200000},{seq:'1'},{playing:1},
                 {tolerance_ms:1},{play_ms:-5},{until_frame:1.5}];
      const out=bad.map(o=>b.show(o));
      const noObject=b.follower.apply({object_id:null,timeline:b.tl()});
      return {out,noObject,orders:b.orders.length,invalid:b.follower.stats().invalid};
    """)
    assert result["out"] == ["invalid"] * 11 and result["noObject"] == "none"
    assert result["orders"] == 0 and result["invalid"] == 11


async def test_without_a_host_nothing_happens_and_nothing_throws(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench({noHost:true});
      return [b.show(), b.follower.tick()];
    """)
    assert result == ["no_host", "idle"]


# ------------------------------------------------------------------ drift against the master clock

async def test_a_player_that_falls_behind_core_is_caught_up_once_a_second_at_most(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show({play_ms:400});                       // 400 ms of start latency are allowed for, not corrected
      b.advance(1000);
      b.report(180+30,true);                        // 1 s later the player is exactly where a player started at the seek should be
      const ok=b.follower.tick();
      b.advance(1000);
      b.report(180+30,true,0);                      // 2 s later it is still on the same frame: 1 s (30 frames) behind
      const first=b.follower.tick();
      b.report(180+31,true,0);
      b.advance(300);
      const tooSoon=b.follower.tick();
      return {ok,first,tooSoon,orders:b.orders.slice(1)};
    """)
    assert result["ok"] == "ok" and result["first"] == "corrected" and result["tooSoon"] == "waiting"
    assert result["orders"] == [{"id": "studio-stage-r1", "action": "play", "frame": 240, "until": 299}]


async def test_a_player_that_is_ahead_is_left_alone_it_waits_on_its_stop_frame(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      b.advance(500);
      b.report(299,false);
      return {r:b.follower.tick(),orders:b.orders.length,ahead:b.follower.stats().ahead};
    """)
    assert result == {"r": "ahead", "orders": 1, "ahead": 1}


async def test_corrections_are_bounded_per_segment_and_the_giving_up_is_logged(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      const seen=[];
      for(let i=0;i<9;i++){b.advance(1100);b.report(180,true,0);seen.push(b.follower.tick())}
      const warned=b.logs.filter(x=>x.k==='timeline.drift_uncorrectable').length;
      b.show({seq:2,anchor_id:'end',from_frame:240,until_frame:299,play_ms:0});    // a new segment gets a fresh allowance
      b.advance(1100);b.report(240,true,0);
      return {seen,warned,corrections:b.follower.stats().corrections,fresh:b.follower.state().gaveUp};
    """)
    assert result["seen"][:5] == ["corrected"] * 5 and result["seen"][5] == "gave_up" and set(result["seen"][5:]) == {"gave_up"}
    assert result["warned"] == 1 and result["corrections"] == 5 and result["fresh"] is False


async def test_a_stale_or_missing_position_report_never_triggers_a_correction(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      b.advance(5000);
      const missing=b.follower.tick();
      b.report(180,true,4000);                      // a report from four seconds ago: not evidence of anything
      const stale=b.follower.tick();
      return {missing,stale,orders:b.orders.length};
    """)
    assert result == {"missing": "no_clock", "stale": "no_clock", "orders": 1}


async def test_a_paused_core_corrects_nothing_even_if_the_player_is_far_away(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      b.show({playing:false,play_ms:100});
      b.advance(10000);
      b.report(299,false,0);
      return {r:b.follower.tick(),orders:b.orders.map(o=>o.action)};
    """)
    assert result == {"r": "idle", "orders": ["play", "pause"]}


async def test_a_lying_player_can_only_make_the_follower_seek_inside_its_own_segment(tmp_path):
    """A hostile scene reports frame 0 forever to be seeked, or frame 10**9: neither leaves the segment nor reaches Core."""

    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      const targets=[];
      for(let i=0;i<8;i++){b.advance(1100);b.report(0,true,0);b.follower.tick()}
      b.orders.slice(1).forEach(o=>targets.push([o.frame,o.until]));
      const parsed=Frame.parseClock({source:{},origin:'http://x',data:{rsh:1,type:'clock',frame:1e9,playing:true,duration:300,fps:30}},{contentWindow:{}},'http://x');
      return {targets,parsed,maxFrame:Math.max(...targets.map(t=>t[0]))};
    """)
    assert all(frame <= until == 299 for frame, until in result["targets"]) and result["maxFrame"] <= 299
    assert len(result["targets"]) <= 5, "bounded: at most five corrections for the segment"
    assert result["parsed"] == {"ok": False, "reason": "foreign_source"}


# ------------------------------------------------------------------ the message from the scene page

async def test_the_scene_page_clock_is_accepted_only_from_its_own_frame_with_exact_bounded_fields(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const mine={contentWindow:{}}, other={contentWindow:{}};
      const good={rsh:1,type:'clock',frame:10,playing:true,duration:90,fps:30};
      const ev=(data,o)=>Object.assign({source:mine.contentWindow,origin:'http://127.0.0.1:17654',data},o||{});
      const P=(e)=>{const r=Frame.parseClock(e,mine,'http://127.0.0.1:17654');return r.ok?'ok':r.reason};
      return {
        ok:P(ev(good)),foreign:P(ev(good,{source:other.contentWindow})),origin:P(ev(good,{origin:'http://evil.example'})),
        extra:P(ev({...good,token:'x'})),neg:P(ev({...good,frame:-1})),past:P(ev({...good,frame:90})),str:P(ev({...good,frame:'3'})),
        float:P(ev({...good,frame:1.5})),playing:P(ev({...good,playing:'yes'})),fps:P(ev({...good,fps:0})),big:P(ev({...good,duration:10**6})),
        wrongType:P(ev({...good,type:'status'})),version:P(ev({...good,rsh:2})),arr:P(ev([good])),nothing:P(null)};
    """)
    assert result == {"ok": "ok", "foreign": "foreign_source", "origin": "bad_origin", "extra": "extra_field", "neg": "bad_clock",
                      "past": "bad_clock", "str": "bad_clock", "float": "bad_clock", "playing": "bad_clock", "fps": "bad_clock",
                      "big": "bad_clock", "wrongType": "bad_message", "version": "bad_message", "arr": "bad_message",
                      "nothing": "foreign_source"}


async def test_the_host_message_for_a_control_order_is_exact(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const H=(t,f)=>{try{return Frame.hostMessage(t,f)}catch(e){return 'refused: '+e.message}};
      return {play:H('control',{action:'play',frame:3,until:9}),pause:H('control',{action:'pause',frame:3}),seek:H('control',{action:'seek',frame:3}),
        untilOnPause:H('control',{action:'pause',until:9}),untilBefore:H('control',{action:'play',frame:9,until:3}),
        float:H('control',{action:'play',frame:1.5}),huge:H('control',{action:'play',until:10**9}),neg:H('control',{action:'seek',frame:-1}),
        extra:H('control',{action:'play',speed:2})};
    """)
    assert result["play"] == {"rsh": 1, "type": "control", "action": "play", "frame": 3, "until": 9}
    assert result["pause"]["frame"] == 3 and result["seek"]["frame"] == 3
    for bad in ("untilOnPause", "untilBefore", "float", "huge", "neg", "extra"):
        assert str(result[bad]).startswith("refused"), bad


# ------------------------------------------------------------------ the scene page relays, clamps and rate-limits

async def test_the_page_relays_the_players_position_clamped_and_at_most_four_times_a_second(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      await flush();
      const clocks=()=>b.parent.posted.map(p=>p.message).filter(m=>m.type==='clock');
      b.fromFrame({rs:1,type:'clock',frame:10,playing:true});
      for(let i=0;i<20;i++){b.c.advance(10);b.fromFrame({rs:1,type:'clock',frame:11+i,playing:true})}
      const burst=clocks().length;
      b.c.advance(1100);                                                   // the watchdog's own window (12 a second) has emptied
      b.fromFrame({rs:1,type:'clock',frame:40,playing:true});
      b.fromFrame({rs:1,type:'clock',frame:41,playing:false});         // a change of state is always said
      const last=clocks()[clocks().length-1];
      return {burst,total:clocks().length,last,first:clocks()[0],targets:[...new Set(b.parent.posted.filter(p=>p.message.type==='clock').map(p=>p.target))]};
    """)
    assert result["burst"] <= 3 and result["total"] <= 6
    assert result["first"] == {"rsh": 1, "type": "clock", "frame": 10, "playing": True, "duration": 90, "fps": 30}
    assert result["last"]["playing"] is False and result["last"]["frame"] == 41
    assert result["targets"] == ["http://127.0.0.1:17654"], "only ever to the Control Center's own origin"


async def test_a_forged_clock_from_the_frame_is_refused_by_the_watchdog_and_never_relayed(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      await flush();
      const clocks=()=>b.parent.posted.map(p=>p.message).filter(m=>m.type==='clock');
      b.fromFrame({rs:1,type:'clock',frame:10**7,playing:true});             // far beyond any composition
      b.fromFrame({rs:1,type:'clock',frame:-5,playing:true});
      b.fromFrame({rs:1,type:'clock',frame:5,playing:'true'});
      b.fromFrame({rs:1,type:'clock',frame:5,playing:true,token:'abc'});
      b.fromFrame({rs:1,type:'clock',frame:80,playing:true},'http://127.0.0.1:17654');   // an origin the frame can never have
      const refused=b.stage.state().supervisor.refused;
      return {relayed:clocks().length,refused};
    """)
    assert result["relayed"] == 0
    assert result["refused"]["bad_clock"] == 3 and result["refused"]["extra_field"] == 1 and result["refused"]["bad_origin"] == 1


async def test_a_frame_that_reports_past_the_end_is_clamped_inside_the_composition(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      await flush();
      // 108000 is a legal protocol frame but the composition has 90: the page never shows or relays more than the last frame.
      b.fromFrame({rs:1,type:'clock',frame:100000,playing:true});
      const m=b.parent.posted.map(p=>p.message).filter(x=>x.type==='clock');
      return {m,frame:b.stage.state().frame};
    """)
    assert result["m"][0]["frame"] == 89 and result["frame"] == 89


async def test_the_page_forwards_a_play_order_with_a_frame_and_a_stop_frame_clamped_to_the_composition(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      await flush();
      const mark=b.frame().contentWindow.posted.length;
      b.fromParent({rsh:1,type:'control',action:'play',frame:30,until:60});
      b.fromParent({rsh:1,type:'control',action:'play',frame:1000,until:5000});
      b.fromParent({rsh:1,type:'control',action:'pause',frame:12});
      b.fromParent({rsh:1,type:'control',action:'pause',until:12});              // until is for play only: dropped
      b.fromParent({rsh:1,type:'control',action:'play',speed:2});                // an unknown field: the whole message is refused
      b.fromParent({rsh:1,type:'control',action:'play',frame:30},'http://evil.example');
      return b.frame().contentWindow.posted.slice(mark).map(p=>p.message);
    """)
    assert result == [
        {"rs": 1, "type": "control", "action": "play", "frame": 30, "until": 60},
        {"rs": 1, "type": "control", "action": "play", "frame": 89, "until": 89},
        {"rs": 1, "type": "control", "action": "pause", "frame": 12},
        {"rs": 1, "type": "control", "action": "pause"}]


# ------------------------------------------------------------------ QA rework: the host mounts another Player

async def test_a_new_player_incarnation_gets_the_segment_applied_again(tmp_path):
    """Hot-reload swap, \"Recharger la scène\", watchdog restart: the new Player is paused on frame 0 and was never ordered."""

    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      let incarnation=1;b.host.frame=()=>incarnation;
      b.show();
      const same=b.show();
      incarnation=2;                                         // the host says `ready` for another Player
      const again=b.show();
      incarnation=3;                                         // and once more, noticed by the tick this time
      const ticked=b.follower.tick();
      const hold=b.show({anchor_id:null,from_frame:0,until_frame:0,playing:false,seq:2});
      incarnation=4;
      const heldAgain=b.follower.tick();
      return {same,again,ticked,hold,heldAgain,orders:b.orders.map(o=>[o.action,o.frame,o.until]),remounted:b.follower.stats().remounted};
    """)
    assert result["same"] == "same" and result["again"] == "segment" and result["hold"] == "segment"
    assert result["orders"] == [["play", 180, 299], ["play", 180, 299], ["play", 180, 299], ["pause", 0, None], ["pause", 0, None]]
    assert result["remounted"] == 3 and result["ticked"] in ("segment", "pending")


async def test_a_player_that_stays_silent_is_ordered_again_a_few_times_then_left_alone(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      const seen=[];
      for(let i=0;i<30;i++){b.advance(500);seen.push(b.follower.tick())}
      return {orders:b.orders.length,resent:b.follower.stats().resent,warned:b.logs.filter(x=>x.k==='timeline.resent').length,
              last:seen[seen.length-1]};
    """)
    assert result["orders"] == 1 + 3 and result["resent"] == 3 and result["warned"] == 3 and result["last"] == "no_clock"


async def test_a_player_that_reports_is_never_ordered_again_for_silence(tmp_path):
    result = run_stage_node(tmp_path, FOLLOWER + r"""
      const b=bench();
      b.show();
      for(let i=0;i<20;i++){b.advance(500);b.report(180+Math.round(15*(i+1)),true,0);b.follower.tick()}
      return {orders:b.orders.length,resent:b.follower.stats().resent};
    """)
    assert result == {"orders": 1, "resent": 0}
