"""Cycle de vie du Player et transport de Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 06), par node.

Deux étages, chacun avec ses cas négatifs :

1. Le séquenceur (`control_center_presentation_studio_sequencer.js`), seul maître de `f` : ouverture en pause sur l'image 0 de la scène
   choisie (la carte lue sans rien ordonner), variante sans vidéo dite et jamais « en échec », reprise à l'image exacte, « Rejouer » depuis 0,
   ⏮ ⏭ et vignette sur l'image locale 0 de la scène visée avec l'état de lecture gardé, ⏭ sans effet sur la dernière scène, saisie rapide
   (dix ⏭ = dix scènes, un seul ordre par image d'animation), messages périmés ignorés, barre à travers les scènes dans les deux sens,
   « Lire seulement cette scène » qui tient la dernière image, rechargement à chaud qui garde (scène, image) bornée à la nouvelle longueur,
   Core injoignable, démontage puis remontage, commandes qui se chevauchent.
2. Le transport de l'explorateur (`control_center_presentation_studio_explorer.js`) sur le faux DOM : une barre d'outils nommée, les noms
   des boutons, la barre `role="slider"` et ses touches, la lecture du temps de composition, « Son » coupé à l'ouverture (bascule depuis la
   Slice 08 : `test_variants_media_js.py`), le menu « ⋯ »
   et le retour du focus, « Lire » désactivé avec sa raison sur une variante sans vidéo.

Contrat : `docs/presentation-studio.md` > *Presentation experience contract* § 3, § 4, § 6 ; *Variants transport (Level 3, Slice 06)*.
La preuve dans un vrai Chrome : `test_variants_transport_browser.py`.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui
from tests.unit.test_continuous_sequencing_js import run_seq
from tests.unit.test_remotion_continuity_js import HOST_BENCH
from tests.unit.test_remotion_stage_js import READY_FLOW, run_stage_node

# Bench map (SEQ_BENCH): S1 90 frames @30, S2 900 @30, S3 75 @25 -> master 30 fps, starts 0 / 90 / 990, L = 1080.


# ------------------------------------------------------------------ 1. the sequencer

def test_variants_opens_paused_on_frame_zero_of_the_selected_scene_and_orders_nothing(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench({selected:1});
      const v=await b.seq.prepare();
      return {phase:v.phase,frame:v.frame,scene:v.scene_index,total:v.total_frames,fps:v.fps,starts:v.starts,orders:b.orders,shows:b.shows,
        preloads:b.preloads,fetches:b.fetches.length};
    """)
    assert result == {"phase": "paused", "frame": 90, "scene": 1, "total": 1080, "fps": 30, "starts": [0, 90, 990], "orders": [],
                      "shows": [], "preloads": [], "fetches": 1}


def test_a_variant_without_video_is_unavailable_with_its_reason_and_never_a_failure(tmp_path):
    result = run_seq(tmp_path, r"""
      const html=seqBench({answers:[{key:null,variant_revision:3,clock:null,problem:{code:'composition_scene_not_remotion',message:'Scène HTML',scene_id:'pss_2'}}]});
      await html.seq.prepare();const a=html.seq.view();
      await html.seq.play();await html.seq.playScene();
      const down=seqBench({answers:[Object.assign(new Error('Core injoignable'),{code:'network'}),{key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null}]});
      await down.seq.prepare();const d=down.seq.view();
      await down.seq.play();
      return {html:[a.phase,a.retryable,a.error.code,a.error.scene_index,html.fetches.length,html.orders.length],
        htmlLogs:html.logs.filter(l=>l[0]==='sequencer_failed').length,
        down:[d.phase,d.retryable,d.error.code,down.fetches.length,down.seq.view().phase,down.orders]};
    """)
    assert result["html"] == ["unavailable", False, "composition_scene_not_remotion", 1, 1, 0], "« Lire » stays disabled: not asked again"
    assert result["htmlLogs"] == 0, "no failure veil, no Error Logs row for a deck that simply has no video"
    assert result["down"] == ["unavailable", True, "network", 2, "playing", [["s1@1", "play", 0]]], "Core back: « Lire » reads the map again"


def test_resume_continues_from_the_exact_frame_and_restart_goes_back_to_frame_zero(tmp_path):
    """PX-7 / PX-10: pause holds f (no order moves it for 5 s), resume plays from that very frame; at the end « Rejouer » plays from 0."""

    result = run_seq(tmp_path, r"""
      const b=seqBench({parkAhead:true});
      await b.seq.prepare();
      await b.seq.play();b.report(5,true);b.report(47,true);
      b.seq.pause();const held=b.seq.view().frame;
      b.advance(5000);b.report(47,false);
      const ordersWhilePaused=b.orders.length;
      await b.seq.play();
      const resumed=b.orders.slice(-1)[0];
      b.seq.seek('end');b.swap();const ended=b.seq.view();
      const before=b.orders.length;
      b.advance(8000);
      const heldEnd=[b.orders.length===before,b.seq.view().phase];
      await b.seq.play();
      return {held,ordersWhilePaused,resumed,ended:[ended.phase,ended.frame],heldEnd,replay:[b.seq.view().frame,b.seq.view().phase],shows:b.shows.slice(-1)};
    """)
    assert result["held"] == 47 and result["ordersWhilePaused"] == 2, "pause holds f: one pause order, nothing after"
    assert result["resumed"] == ["s1@1", "play", 47], "resume continues from f, never a segment or scene start"
    assert result["ended"] == ["ended", 1079] and result["heldEnd"] == [True, "ended"], "End while playing: the final frame, held (§ 4.7)"
    assert result["replay"][0] == 0 and result["shows"] == [0], "« Rejouer » restarts from frame 0 (scene 1 brought back)"


def test_after_a_pause_the_players_own_halt_frame_is_held_and_resumed_from(tmp_path):
    """PX-7 in real Chrome: the last report is up to 250 ms behind the Player; it halts a few frames past `f`. That frame becomes `f` (never
    backward), so resume does not jump back; a halt reported before the pause, or after a seek, changes nothing."""

    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.prepare();await b.seq.play();b.report(2,true);b.report(40,true);
      b.seq.pause();const f=b.seq.view().frame;
      b.report(46,false);const settled=b.seq.view().frame;
      b.report(30,false);const after=b.seq.view().frame;
      await b.seq.play();
      return {f,settled,after,resume:b.orders.slice(-1)[0]};
    """)
    assert result == {"f": 40, "settled": 46, "after": 46, "resume": ["s1@1", "play", 46]}


def test_next_previous_and_a_thumbnail_land_on_the_local_frame_zero_and_keep_the_play_state(tmp_path):
    """PX-8: next -> start_(k+1); previous -> start_(k-1), from scene 1 frame 0; a thumbnail -> start_k; next on the last scene changes nothing."""

    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.prepare();
      const out={};
      b.seq.seek('next');out.nextPaused=[b.seq.view().phase,b.seq.view().frame];b.swap();
      out.order1=b.orders.slice(-1)[0];
      await b.seq.play();b.report(0,true);b.report(300,true);
      b.seq.seek('previous');out.prevPlaying=[b.seq.view().phase,b.seq.view().frame,b.seq.view().playing];b.swap();out.prevPlaying.push(b.seq.view().phase);
      out.order2=b.orders.slice(-1)[0];
      b.report(0,true);b.report(40,true);
      b.seq.seek('previous');out.fromFirst=[b.seq.view().frame,b.seq.view().playing];
      b.seq.seek('scene',2);b.swap();out.thumb=[b.seq.view().frame,b.orders.slice(-1)[0]];
      out.lastNext=b.seq.seek('next');out.lastFrame=b.seq.view().frame;
      return out;
    """)
    assert result["nextPaused"] == ["paused", 90] and result["order1"] == ["s2@1", "pause", 0], "paused stays paused on the target's frame 0"
    assert result["prevPlaying"] == ["waiting", 0, True, "playing"] and result["order2"] == ["s1@1", "play", 0], "playing continues from the target's frame 0"
    assert result["fromFirst"] == [0, True], "previous from scene 1 is frame 0"
    assert result["thumb"] == [990, ["s3@1", "play", 0]]
    assert result["lastNext"] is False and result["lastFrame"] == 990, "next on the last scene is disabled"


def test_ten_fast_next_presses_are_ten_scenes_with_one_order_per_animation_frame_and_no_drift(tmp_path):
    result = run_seq(tmp_path, r"""
      const SC=SCENES;
      const b=seqBench({raf:true});
      await b.seq.prepare();
      const frames=[];
      for(let i=0;i<10;i++){b.seq.seek('next');frames.push(b.seq.view().frame)}
      const before=b.orders.length,showsBefore=b.shows.length;
      const applied=b.frame();
      b.swap();
      const again=b.frame();
      // one press per frame: each lands exactly one scene further, never two
      const c=seqBench({raf:true});await c.seq.prepare();
      const each=[];
      for(let i=0;i<2;i++){c.seq.seek('next');c.frame();c.swap();each.push([c.seq.view().frame,c.seq.view().scene_index])}
      c.seq.seek('previous');c.seq.seek('previous');c.seq.seek('previous');c.frame();
      return {frames,before,showsBefore,applied,again,orders:b.orders,shows:b.shows,each,back:[c.seq.view().frame,c.seq.view().scene_index]};
    """)
    assert result["frames"] == [90, 990, 990, 990, 990, 990, 990, 990, 990, 990], "one scene per press, clamped on the last, never two"
    assert result["before"] == 0 and result["showsBefore"] == 0, "nothing reaches the Player before the animation frame"
    assert result["applied"] == 1 and result["again"] == 0, "one coalesced seek"
    assert result["shows"] == [2] and result["orders"] == [["s3@1", "pause", 0]], "one order for the burst, on the last target"
    assert result["each"] == [[90, 1], [990, 2]] and result["back"] == [0, 0]


def test_a_stale_clock_around_a_seek_never_moves_f(tmp_path):
    """The Player still reports its old position after a seek: before the animation frame (pending) and before it is seen where it was sent."""

    result = run_seq(tmp_path, r"""
      const b=seqBench({raf:true});
      await b.seq.prepare();await b.seq.play();b.report(2,true);b.report(70,true);
      b.seq.seek('scrub',20);
      b.report(75,true);const pending=b.seq.view().frame;
      b.frame();
      b.report(76,true);const unsynced=b.seq.view().frame;
      b.report(21,true);b.report(24,true);
      return {pending,unsynced,after:b.seq.view().frame,order:b.orders.slice(-1)[0]};
    """)
    assert result["pending"] == 20 and result["unsynced"] == 20, "an old report never moves f back over the user's seek"
    assert result["order"] == ["s1@1", "play", 20] and result["after"] == 24


def test_a_scrub_across_scene_boundaries_moves_the_player_strip_and_readout_together_both_ways(tmp_path):
    """PX-9 / § 4.8: f, the scene index and the Player target agree after every scrub, forward into scene 3 and back into scene 1."""

    result = run_seq(tmp_path, r"""
      const b=seqBench({raf:true});
      await b.seq.prepare();
      const rows=[];
      for(const target of [600,1000,45,989]){
        b.seq.seek('scrub',target);const v=b.seq.view();
        b.frame();if(b.H.pending)b.swap();
        rows.push([target,v.frame,v.scene_index,b.shows.slice(-1)[0]===undefined?null:b.shows.slice(-1)[0],b.orders.slice(-1)[0]]);
      }
      return rows;
    """)
    assert result == [[600, 600, 1, 1, ["s2@1", "pause", 510]],
                      [1000, 1000, 2, 2, ["s3@1", "pause", 8]],
                      [45, 45, 0, 0, ["s1@1", "pause", 45]],
                      [989, 989, 1, 1, ["s2@1", "pause", 899]]]


def test_read_only_this_scene_plays_it_from_frame_zero_and_holds_its_last_frame(tmp_path):
    """PX-21: no next scene is loaded or shown, nothing is ordered after the end, the play state ends paused on the scene's last frame."""

    result = run_seq(tmp_path, r"""
      const b=seqBench({selected:0,parkAhead:true});
      await b.seq.prepare();
      b.seq.seek('scrub',40);
      await b.seq.playScene();
      const start={phase:b.seq.view().phase,scope:b.seq.view().scope,orders:b.orders.slice()};
      b.playTo(0,89,10);
      const end=b.seq.view();
      const ordersAtEnd=b.orders.length,preloads=b.preloads.slice(),shows=b.shows.slice();
      b.advance(10000);b.report(89,false);
      await b.seq.play();
      return {start,end:[end.phase,end.frame,end.scope],ordersAtEnd,after:b.orders.length,preloads,shows,next:b.orders.slice(-1)[0]};
    """)
    assert result["start"]["phase"] == "playing" and result["start"]["scope"] == "scene"
    assert result["start"]["orders"] == [["s1@1", "pause", 40], ["s1@1", "play", 0]], "the scene from its frame 0, not from f"
    assert result["end"] == ["paused", 89, "all"] and result["preloads"] == [] and result["shows"] == []
    assert result["ordersAtEnd"] == result["after"] - 1, "nothing ordered after the end until the user plays again"
    assert result["next"] == ["s1@1", "play", 89], "« Lire » afterwards continues from the held frame"


def test_a_hot_reload_keeps_the_scene_and_its_frame_clamped_to_the_new_length_and_the_play_state(tmp_path):
    """PX-19 / § 4.9: playing at frame 600 of scene 2, an edit shortens it to 300 frames (a new pin): the Player on screen holds while the
    new version loads, then the new pin's Player plays from 299 (clamped), play state kept."""

    result = run_seq(tmp_path, r"""
      const answers=[{key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null}];
      const opts={parkAhead:true,answers,revision:3};
      const b=seqBench(opts);
      await b.seq.prepare();
      b.seq.seek('scene',1);b.swap();
      await b.seq.play();b.report(0,true);b.report(600,true);
      const before=b.seq.view().frame;
      SCENES[1].prefab.version=2;SCENES[1].frames=300;opts.revision=4;
      answers.push({key:'k2',variant_revision:4,clock:wireOf(SCENES,'k2'),problem:null});
      const n=b.orders.length;
      const during=await b.seq.revise();
      b.swap();
      const v=b.seq.view();
      return {before,during:[during.phase,during.frame],orders:b.orders.slice(n),after:[v.phase,v.frame,v.total_frames,v.scene_index],shows:b.shows.slice(-1)};
    """)
    assert result["before"] == 690
    assert result["during"] == ["waiting", 389], "kept as (scene 2, frame 600) clamped to its new last frame 299: f = 90 + 299"
    assert result["orders"] == [["s2@1", "pause", None], ["s2@2", "play", 299]], "held while loading, then the new pin plays on"
    assert result["after"] == ["playing", 389, 480, 1] and result["shows"] == [1]


def test_a_hot_reload_while_paused_holds_the_same_frame_and_a_removed_scene_gives_its_place(tmp_path):
    result = run_seq(tmp_path, r"""
      const answers=[{key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null}];
      const opts={answers,revision:3};
      const b=seqBench(opts);
      await b.seq.prepare();
      b.seq.seek('scrub',290);b.swap();
      SCENES[1].prefab.version=2;opts.revision=4;
      answers.push({key:'k2',variant_revision:4,clock:wireOf(SCENES,'k2'),problem:null});
      await b.seq.revise();b.swap();
      const kept=[b.seq.view().phase,b.seq.view().frame,b.orders.slice(-1)[0]];
      b.seq.seek('scene',2);b.swap();
      SCENES.splice(2,1);opts.revision=5;
      answers.push({key:'k3',variant_revision:5,clock:wireOf(SCENES,'k3'),problem:null});
      await b.seq.revise();b.swap();
      return {kept,gone:[b.seq.view().phase,b.seq.view().frame,b.seq.view().scene_index,b.orders.slice(-1)[0]],
        noPlay:b.orders.filter(o=>o[1]==='play').length};
    """)
    assert result["kept"] == ["paused", 290, ["s2@2", "pause", 200]], "paused stays paused on the same frame of the new version"
    assert result["gone"] == ["paused", 90, 1, ["s2@2", "pause", 0]], "the scene now at its place, from its start"
    assert result["noPlay"] == 0, "nothing ever plays by itself"


def test_a_pause_while_a_hot_reload_reads_its_map_keeps_the_scene_and_frame_and_lands_paused(tmp_path):
    """QA P1: `revise()` drops the map and reads the new one; a pause during that read used to leave `idle` without a map, and the next
    « Lire » restarted at the scene start. The kept (scene, local frame) and the paused intent now cross the read."""

    result = run_seq(tmp_path, r"""
      const answers=[{key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null}];
      const opts={parkAhead:true,answers,revision:3};
      const b=seqBench(opts);
      await b.seq.prepare();
      b.seq.seek('scene',1);b.swap();
      await b.seq.play();b.report(0,true);b.report(600,true);
      SCENES[1].prefab.version=2;opts.revision=4;
      let land;answers.push(new Promise(r=>{land=r}));
      const n=b.orders.length;
      const revising=b.seq.revise();
      await null;
      const reading=b.seq.view().phase;
      const paused=await b.seq.toggle();
      const again=await b.seq.toggle();   // a second press during the read does not start anything either
      land({key:'k2',variant_revision:4,clock:wireOf(SCENES,'k2'),problem:null});
      await revising;b.swap();
      const v=b.seq.view();
      const landed=[v.phase,v.frame,v.scene_index,b.orders.slice(n)];
      await b.seq.play();
      return {reading,paused:paused.phase,again:again.phase,landed,resume:b.orders.slice(-1)[0],fetches:b.fetches.length};
    """)
    assert result["reading"] == "loading" and result["paused"] == "loading" and result["again"] == "loading", "the read goes on"
    assert result["landed"] == ["paused", 690, 1, [["s2@1", "pause", None], ["s2@2", "pause", 600]]], "held on (scene 2, frame 600), paused"
    assert result["resume"] == ["s2@2", "play", 600] and result["fetches"] == 2, "« Lire » continues from the kept frame, not the scene start"


def test_a_hot_reload_read_that_fails_keeps_its_position_for_the_next_play(tmp_path):
    result = run_seq(tmp_path, r"""
      const answers=[{key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null}];
      const opts={answers,revision:3};
      const b=seqBench(opts);
      await b.seq.prepare();
      b.seq.seek('scrub',290);b.swap();
      opts.revision=4;
      answers.push(Object.assign(new Error('Core injoignable'),{code:'network'}));
      answers.push({key:'k2',variant_revision:4,clock:wireOf(SCENES,'k2'),problem:null});
      await b.seq.revise();
      const failed=[b.seq.view().phase,b.seq.view().retryable];
      await b.seq.play();b.swap();
      return {failed,v:[b.seq.view().phase,b.seq.view().frame],order:b.orders.slice(-1)[0]};
    """)
    assert result["failed"] == ["unavailable", True]
    assert result["v"] == ["playing", 290] and result["order"] == ["s2@1", "play", 200], "the next « Lire » starts at the kept frame"


def test_lost_core_never_hangs_and_overlapping_commands_start_nothing_twice(tmp_path):
    result = run_seq(tmp_path, r"""
      const out={};
      let release;
      const slow=seqBench({answers:[{key:'k1',variant_revision:3,clock:wireOf(SCENES,'k1'),problem:null}]});
      const p1=slow.seq.play(),p2=slow.seq.play(),p3=slow.seq.toggle();
      await Promise.all([p1,p2,p3]);
      out.overlap=[slow.fetches.length,slow.seq.view().phase,slow.orders];
      const down=seqBench({answers:[Object.assign(new Error('timeout after 10000 ms'),{code:'timeout'})]});
      await down.seq.play();
      out.down=[down.seq.view().phase,down.seq.view().error.code,down.seq.view().error.message.includes('timeout'),down.orders.length];
      return out;
    """)
    assert result["overlap"][0] == 1, "one map read for three overlapping commands"
    assert result["overlap"][1] == "idle" and result["overlap"][2] == [["s1@1", "pause", None]],         "the third command (a toggle while « Lire » was still reading) cancelled it: nothing started behind the user's back"
    assert result["down"] == ["failed", "timeout", True, 0], "Core unreachable is said, never a hang"


def test_unmount_and_remount_start_clean(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench();
      await b.seq.prepare();await b.seq.play();b.report(3,true);b.report(30,true);
      b.seq.reset('closed');
      const closed=[b.seq.view().phase,b.seq.view().frame,b.seq.active()];
      await b.seq.prepare();
      const reopened=[b.seq.view().phase,b.seq.view().frame,b.fetches.length];
      await b.seq.play();
      return {closed,reopened,orders:b.orders};
    """)
    assert result["closed"] == ["idle", None, False]
    assert result["reopened"] == ["paused", 0, 2], "a reopened Variants reads its map again, paused on frame 0"
    assert result["orders"] == [["s1@1", "play", 0], ["s1@1", "pause", None], ["s1@1", "play", 0]]


def test_a_pending_seek_is_superseded_by_a_play_command_and_never_applied_twice(tmp_path):
    result = run_seq(tmp_path, r"""
      const b=seqBench({raf:true});
      await b.seq.prepare();
      b.seq.seek('scrub',30);
      await b.seq.playScene();
      const n=b.orders.length;
      b.frame();
      return {orders:b.orders,late:b.orders.length-n};
    """)
    assert result["orders"] == [["s1@1", "play", 0]] and result["late"] == 0


def test_a_same_pin_scene_is_still_shown_with_its_own_values_and_name(tmp_path):
    """Two scenes on one source version share the Player: a seek to the second one shows it (values, title, strip), then orders it."""

    result = run_seq(tmp_path, r"""
      SCENES[1].prefab={id:'presentation-studio.x.s1',version:1};
      const b=seqBench();
      await b.seq.prepare();
      b.seq.seek('scene',1);
      return {shows:b.shows,orders:b.orders,scene:b.seq.view().scene_index};
    """)
    assert result == {"shows": [1], "orders": [["s1@1", "pause", 0]], "scene": 1}


# ------------------------------------------------------------------ 1b. the Player's page and host in Variants (no own bar, never plays alone)

def test_the_stage_page_embedded_in_variants_has_no_bar_and_never_plays_on_ready_and_the_run_stage_still_does(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const run=async(embed)=>{
        const b=stageBench({embed});b.stage.start();await flush();
        b.fromFrame({rs:1,type:'ready'});await flush();
        b.fromParent({rsh:1,type:'control',action:'pause',frame:0});
        const bar=b.root.descendants().filter(n=>String(n.className||'').includes('rs-bar'));
        b.doc.dispatch&&b.doc.dispatch({type:'pointermove'});
        return {bars:bar.length,plays:inboxOf(b).filter(m=>m.type==='control'&&m.action==='play').length,state:[b.stage.state().phase,b.stage.state().playing,b.stage.state().embedded],
          ready:statuses(b).some(s=>s.phase==='ready')};
      };
      return {variants:await run('variants'),stage:await run(undefined),other:await run('board')};
    """)
    assert result["variants"] == {"bars": 0, "plays": 0, "state": ["ready", False, True], "ready": True}
    assert result["stage"]["bars"] == 1 and result["stage"]["plays"] == 1, "the run stage keeps its bar and play-on-ready until Slice 09"
    assert result["other"]["bars"] == 1 and result["other"]["state"][2] is False, "an unknown embed is ignored"


def test_the_variants_host_never_plays_a_scene_by_itself_and_asks_for_the_embedded_page(tmp_path):
    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const run=async(extra)=>{
        const b=hostBench(extra);
        b.host.mount(b.slot,b.inst(b.A));const f=await b.bringUp(b.A);
        b.c.advance(5000);
        b.host.preload('stage',b.inst(b.B));const fb=await b.bringUp(b.B);b.c.advance(5000);
        return {orders:b.posted(f),ahead:b.posted(fb),src:f.src};
      };
      return {variants:await run({autoplay:false,embed:'variants'}),stage:await run({})};
    """)
    assert result["variants"]["orders"] == [["pause", 0, None]] and result["variants"]["ahead"] == [["pause", 0, None]]
    assert result["variants"]["src"].endswith("&embed=variants")
    assert result["stage"]["orders"] == [["pause", 0, None], ["play", None, None]], "the run stage keeps its grace-period play"
    assert "embed" not in result["stage"]["src"]


def test_a_follower_halt_far_past_the_stop_frame_is_not_its_end(tmp_path):
    """Slice 05 QA carry-over: the "past `until`" branch of the stop check is bounded by the same slack as the "short of it" one."""

    result = run_stage_node(tmp_path, r"""
      const Frame=require(PATHS.frame);
      const out={};
      for(const [name,halt] of [['past2',76],['past3',77],['far',200]]){
        let t=100000;const clocks=new Map(),reports=[];
        const host={control(id){clocks.delete(id);return true},clock(id){return clocks.get(id)||null},key:()=>'studio.s2@1',frame:()=>1};
        const f=Frame.createTimelineFollower({getHost:()=>host,now:()=>t,log:()=>{},onSegment:(r)=>reports.push(r),setInterval:()=>1,clearInterval:()=>{}});
        f.apply({object_id:'stage',timeline:{scene_id:'s2',composition_id:'Scene',fps:30,duration_frames:300,anchor_id:'m',from_frame:30,until_frame:74,
          playing:true,seq:1,play_ms:0,tolerance_ms:500,problems:[],auto:true,prefab:'studio.s2@1'}});
        clocks.set('stage',{frame:40,playing:true,duration:300,fps:30,at:t});f.onClock('stage');
        t+=1000;clocks.set('stage',{frame:halt,playing:false,duration:300,fps:30,at:t});
        out[name]=[f.onClock('stage'),reports.filter(r=>r.event==='done').length];
      }
      return out;
    """)
    assert result["past2"] == ["done", 1]
    assert result["past3"][1] == 0 and result["far"][1] == 0


# ------------------------------------------------------------------ 2. the Variants transport (explorer, fake DOM)

VIDEO_WORLD = r"""
world.clock=(id,doc)=>{
  const scenes=doc.scenes.map((s,i)=>({scene_id:s.scene_id,composition_id:'Scene',fps:30,duration_in_frames:90,start:i*90,length:90,transition_in:0}));
  const key='k'+id.slice(-2);
  return {key,clock:{version:1,key,fps:30,total_frames:90*scenes.length,scenes}};
};
let EX=null;
const bar=()=>q('.jvx-transport');
const slider=()=>q('[role="slider"]',bar());
const label=(name)=>q(`[aria-label="${name}"]`,bar());
const readout=()=>({time:q('.jvx-time').textContent,now:slider().getAttribute('aria-valuenow'),text:slider().getAttribute('aria-valuetext'),
  count:q('.jvx-stage-note > span').textContent,selected:q('.jvx-scene[aria-selected="true"]').dataset.scene.slice(-1),frame:EX.playback.view().frame});
seed(2);
const {ex}=await opened({fullscreen:false});EX=ex;
await env.advance(50);
"""


def test_the_transport_is_one_named_toolbar_that_opens_paused_on_frame_zero_and_shows_the_composition_time(tmp_path):
    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const toolbars=qa('[role="toolbar"]').filter(t=>t.querySelector('[data-act="continuous"]'));
const names=qa('button',bar()).filter(b=>!b.hidden).map(b=>b.getAttribute('aria-label')||b.textContent.trim());
return {toolbars:toolbars.length,label:bar().getAttribute('aria-label'),names,haspopup:label('Plus de lecture').getAttribute('aria-haspopup'),
  slider:['aria-valuemin','aria-valuemax','aria-valuenow','aria-valuetext','aria-disabled'].map(k=>slider().getAttribute(k)),
  readout:readout(),orders:prefabFake.orders,phase:ex.playback.view().phase,host:prefabFake.hosts[0].deps.autoplay+'/'+prefabFake.hosts[0].deps.embed,
  sound:[label('Son').getAttribute('aria-pressed'),label('Son').getAttribute('aria-disabled'),label('Son').getAttribute('title'),prefabFake.sounds],errors:env.errors};
""")
    assert out["toolbars"] == 1 and out["label"] == "Lecture de la vidéo"
    # Slice 10: the toolbar holds the playback controls only; « Présenter » (§ 6 #21) is on the scene row under it; « Arrêter » shows in
    # the toolbar only during a run (it stays in the stage fullscreen).
    assert out["names"] == ["Scène précédente", "Lire", "Scène suivante", "Son", "Plus de lecture"] and out["haspopup"] == "menu"
    assert out["slider"] == ["0", "269", "0", "Scène 1 sur 3, 0:00 sur 0:09", "false"]
    assert out["readout"] == {"time": "0:00 / 0:09", "now": "0", "text": "Scène 1 sur 3, 0:00 sur 0:09", "count": "Scène 1 sur 3", "selected": "1",
                              "frame": 0}
    assert out["orders"] == [] and out["phase"] == "paused", "Variants opens paused: nothing is ordered to the Player"
    assert out["host"] == "false/variants", "the preview host never autoplays and the stage page shows no bar of its own"
    # Slice 08: « Son » is a toggle, muted at opening (the preview host is told `muted` before any frame); no longer disabled.
    assert out["sound"] == ["false", None, "Activer le son (M)", [True]] and out["errors"] == []


def test_slider_keys_buttons_and_space_move_the_one_clock_and_every_readout_follows(tmp_path):
    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const out={};
slider().focus();
for(const k of ['Home','PageDown','ArrowRight','ArrowRight'])env.key(slider(),k);
out.beforeFrame=readout();out.ordersBeforeFrame=prefabFake.orders.length;
await env.advance(20);
out.scrubbed=readout();out.scrubOrders=prefabFake.orders.slice();
label('Lire').click();await env.advance(20);
const lire=q('[data-act="continuous"]');
out.playing=[ex.playback.view().phase,lire.getAttribute('aria-label'),lire.getAttribute('aria-pressed'),prefabFake.orders.slice(-1)[0]];
env.key(q('.jvx-stage'),' ');await env.advance(20);
out.paused=[ex.playback.view().phase,ex.playback.view().frame,prefabFake.orders.slice(-1)[0]];
env.key(q('.jvx-stage'),'.');await env.advance(20);
out.stepped=[ex.playback.view().frame,prefabFake.orders.slice(-1)[0]];
label('Scène suivante').click();await env.advance(20);
out.next=[readout(),label('Scène suivante').getAttribute('aria-disabled'),q('.jvx-sr').textContent];
label('Scène suivante').click();await env.advance(20);
out.last=[ex.playback.view().frame,noticeText()];
env.key(q('.jvx-stage'),'Home');await env.advance(20);
out.home=readout();
env.key(q('.jvx-stage'),'End');await env.advance(20);
out.end=[ex.playback.view().phase,ex.playback.view().frame];
return out;
""")
    assert out["beforeFrame"]["frame"] == 150 and out["beforeFrame"]["time"] == "0:05 / 0:09", "f and the readout follow the keys at once"
    assert out["ordersBeforeFrame"] == 0, "the Player is sent at the next animation frame, once"
    assert out["scrubbed"] == {"time": "0:05 / 0:09", "now": "150", "text": "Scène 2 sur 3, 0:05 sur 0:09", "count": "Scène 2 sur 3",
                               "selected": "2", "frame": 150}
    assert out["scrubOrders"] == [["pause", 60]], "one order for four keys: scene 2, local frame 60"
    assert out["playing"] == ["playing", "Pause", "true", ["play", 60]]
    assert out["paused"] == ["paused", 150, ["pause", None]]
    assert out["stepped"] == [151, ["pause", 61]], "`.` while paused: one frame forward"
    assert out["next"][0]["frame"] == 180 and out["next"][0]["selected"] == "3" and out["next"][1] == "true"
    assert out["next"][2].startswith("Scène 3 sur 3"), "a scene change made by the user is announced"
    assert out["last"] == [180, "Dernière scène."], "next on the last scene says why it does nothing"
    assert out["home"]["frame"] == 0 and out["home"]["count"] == "Scène 1 sur 3"
    assert out["end"] == ["paused", 269], "End while paused: the final frame, paused"


def test_the_overflow_menu_plays_only_this_scene_and_gives_the_focus_back(tmp_path):
    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const more=label('Plus de lecture');
more.focus();more.click();await env.advance(10);
const items=qa('.jvx-menu [role="menuitem"]').map(b=>b.textContent);
const expanded=more.getAttribute('aria-expanded');
env.key(doc.activeElement,'Escape');await env.advance(10);
const back=[doc.activeElement===more,more.getAttribute('aria-expanded'),!!q('.jvx-menu')];
q('.jvx-scene[data-scene="pss_000000000002"]').click();await env.advance(20);
more.click();await env.advance(10);
qa('.jvx-menu [role="menuitem"]')[0].click();await env.advance(20);
const v=ex.playback.view();
return {items,expanded,back,play:[v.phase,v.scope,v.frame,prefabFake.orders.slice(-1)[0]],focus:doc.activeElement===more,open:ex.isOpen(),
  runs:world.calls.filter(c=>c.url.includes('/playback')&&c.method==='POST').length};
""")
    # Slice 10: « Raccourcis clavier » (`?`) joins the overflow (§ 6 #20)
    assert out["items"] == ["Lire seulement cette scène", "Revenir au débutDébut", "Raccourcis clavier?"] and out["expanded"] == "true"
    assert out["back"] == [True, "false", False], "Escape closes the menu and the focus returns to « ⋯ »"
    assert out["play"] == ["playing", "scene", 90, ["play", 0]], "the scene on screen from its frame 0"
    assert out["focus"] is True and out["open"] is True and out["runs"] == 0, "no run, Variants stays open"


def test_a_variant_without_video_says_why_lire_is_disabled_and_the_scene_buttons_still_browse(tmp_path):
    out = run_ui(tmp_path, r"""
seed(2);
const {ex}=await opened({fullscreen:false});
await env.advance(50);
const lire=q('.jvx-transport [data-act="continuous"]');
const disabled=[lire.getAttribute('aria-disabled'),lire.title];
lire.click();await env.advance(20);
const said=noticeText();
const sl=q('.jvx-transport [role="slider"]');
const slider=[sl.getAttribute('aria-disabled'),sl.getAttribute('aria-valuenow'),q('.jvx-time').textContent];
q('.jvx-transport [aria-label="Scène suivante"]').click();await env.advance(20);
return {disabled,said,slider,title:q('.jvx-scene-title').textContent,phase:ex.playback.view().phase,
  failures:env.logs.filter(l=>l[1].includes('sequencer_failed')).length,errors:env.errors};
""")
    assert out["disabled"][0] == "true" and "présentation Remotion" in out["disabled"][1]
    assert "présentation Remotion" in out["said"], "a disabled control says its reason when activated"
    assert out["slider"] == ["true", None, ""], "no map, no position shown at all (§ 4.8)"
    assert out["title"] == "Scène 2 de 1" and out["phase"] == "unavailable"
    assert out["failures"] == 0 and out["errors"] == []


DRAG_WORLD = VIDEO_WORLD + r"""
/* 270 px for 270 frames: clientX x lands on frame round(x / 270 * 269). Pointer capture recorded (the fake DOM has none). */
const s=slider();s.rect={left:0,top:0,width:270,height:20};
const captures=[];s.setPointerCapture=(id)=>captures.push(id);
const orders=(from)=>prefabFake.orders.slice(from);
const phase=()=>ex.playback.view().phase;
"""


def test_a_pointer_drag_pauses_follows_with_one_seek_per_frame_and_gives_the_play_state_back(tmp_path):
    """§ 4.6: a drag that starts playing pauses for the drag, `f` follows every move, the Player gets one seek per animation frame, and
    the release plays again from the scrubbed frame. A drag that starts paused stays paused (QA B1: mutants M12, M13)."""

    out = run_ui(tmp_path, DRAG_WORLD + r"""
const out={};
label('Lire').click();await env.advance(20);
const o0=prefabFake.orders.length;
env.pointer(s,'pointerdown',{clientX:100});
out.down=[phase(),ex.playback.view().frame,orders(o0),captures.slice()];
out.moves=[];
for(const x of [150,200,240]){env.pointer(s,'pointermove',{clientX:x});out.moves.push([readout().frame,readout().now,readout().time])}
out.beforeFrame=orders(o0);
await env.advance(20);
out.afterFrame=orders(o0);
env.pointer(s,'pointerup',{clientX:240});await env.advance(20);
const r=readout();
out.up=[phase(),r.frame,r.now,r.time,r.count,r.selected,orders(o0).slice(-1)[0]];
// a drag that starts paused
env.key(q('.jvx-stage'),' ');await env.advance(20);
const o1=prefabFake.orders.length;
env.pointer(s,'pointerdown',{clientX:30});env.pointer(s,'pointermove',{clientX:60});await env.advance(20);
env.pointer(s,'pointerup',{clientX:60});await env.advance(20);
out.paused=[phase(),readout().frame,orders(o1),readout().count];
return out;
""")
    assert out["down"] == ["paused", 100, [["pause", None]], [1]], "pointerdown while playing pauses, captures the pointer, seeks under it"
    assert out["moves"] == [[149, "149", "0:05 / 0:09"], [199, "199", "0:07 / 0:09"], [239, "239", "0:08 / 0:09"]], "f follows every move"
    assert out["beforeFrame"] == [["pause", None]], "no seek reaches the Player before the animation frame"
    assert out["afterFrame"] == [["pause", None], ["pause", 59]], "one seek for the whole burst: scene 3, local frame 59"
    assert out["up"] == ["playing", 239, "239", "0:08 / 0:09", "Scène 3 sur 3", "3", ["play", 59]], "release plays from the scrubbed frame"
    assert out["paused"][0] == "paused" and out["paused"][1] == 60 and out["paused"][3] == "Scène 1 sur 3"
    assert not [o for o in out["paused"][2] if o[0] == "play"], "a drag that started paused stays paused on release"


def test_a_drag_cut_short_by_closing_variants_or_a_lost_capture_never_outlives_its_gesture(tmp_path):
    """QA P2: closing Variants mid-drag, `lostpointercapture` or `pointercancel` end the drag; after a reopen, hovering the slider does
    not seek and a stray pointerup does not play."""

    out = run_ui(tmp_path, DRAG_WORLD + r"""
const out={};
label('Lire').click();await env.advance(20);
env.pointer(s,'pointerdown',{clientX:100});
ex.close();await env.advance(20);
await ex.open({presentation_id:PID,fullscreen:false});await env.advance(400);
const s2=slider();s2.rect={left:0,top:0,width:270,height:20};
const o0=prefabFake.orders.length;
env.pointer(s2,'pointermove',{clientX:200});env.pointer(s2,'pointerup',{clientX:200});await env.advance(20);
out.reopened=[phase(),ex.playback.view().frame,orders(o0)];
for(const ending of ['lostpointercapture','pointercancel']){
  env.pointer(s2,'pointerdown',{clientX:50});await env.advance(20);
  env.pointer(s2,ending,{clientX:50});
  env.pointer(s2,'pointermove',{clientX:220});await env.advance(20);
  out[ending]=[phase(),ex.playback.view().frame];
}
return out;
""")
    assert out["reopened"] == ["paused", 0, []], "a reopened Variants is paused on frame 0: hover does not seek, pointerup does not play"
    assert out["lostpointercapture"] == ["paused", 50] and out["pointercancel"] == ["paused", 50], "the drag ended there: later moves do not seek"


def test_the_slider_keys_say_a_neutral_wording_while_the_map_is_read_and_the_failure_only_once_it_failed(tmp_path):
    """QA P3: « Vidéo indisponible » is for a map that really failed, never for one still being read."""

    out = run_ui(tmp_path, r"""
world.clock=(id,doc)=>{
  const scenes=doc.scenes.map((s,i)=>({scene_id:s.scene_id,composition_id:'Scene',fps:30,duration_in_frames:90,start:i*90,length:90,transition_in:0}));
  return {key:'k',clock:{version:1,key:'k',fps:30,total_frames:90*scenes.length,scenes}};
};
world.delays.push({match:(url)=>url.includes('composition-clock'),ms:3000});
seed(2);
const {ex}=await opened({fullscreen:false});
const sl=q('.jvx-transport [role="slider"]');
const reading=ex.playback.view().phase;
env.key(sl,'ArrowRight');
const said=noticeText();
await env.advance(3000);
const ready=[ex.playback.view().phase,ex.playback.view().frame];
return {reading,said,ready,title:sl.getAttribute('title')};
""")
    assert out["reading"] == "loading"
    assert out["said"] == "La position paraît dès que la vidéo est prête.", "neutral while the map is read"
    assert out["ready"] == ["paused", 0]


def test_the_slider_keys_say_the_failure_once_the_map_failed(tmp_path):
    out = run_ui(tmp_path, r"""
world.failNext.push({match:(url)=>url.includes('composition-clock'),status:503,code:'core_down',message:'Core injoignable'});
seed(2);
const {ex}=await opened({fullscreen:false});
const sl=q('.jvx-transport [role="slider"]');
env.key(sl,'ArrowRight');
return {phase:ex.playback.view().phase,said:noticeText()};
""")
    assert out["phase"] == "unavailable" and out["said"].startswith("Vidéo indisponible : "), out


#: Every gesture of continuous video in Variants (« Lire », Space, ⏭, the slider keys, « Lire seulement cette scène », End, « Rejouer »).
#: Also replayed against a real Core by `test_presentation_studio_playback_continuous_isolation.py` (Slice 07 rework, P1).
CONTINUOUS_GESTURES = r"""
label('Lire').click();await env.advance(40);
env.key(q('.jvx-stage'),' ');await env.advance(20);
label('Scène suivante').click();await env.advance(20);
slider().focus();for(const k of ['Home','PageDown','ArrowRight'])env.key(slider(),k);await env.advance(20);
const more=label('Plus de lecture');more.click();await env.advance(10);
qa('.jvx-menu [role="menuitem"]')[0].click();await env.advance(40);
env.key(q('.jvx-stage'),'End');await env.advance(20);
(label('Rejouer')||label('Lire')).click();await env.advance(40);
"""


def test_continuous_video_reads_the_map_and_never_touches_the_score_cues_or_speech(tmp_path):
    """Slice 07 (§ 5): « Lire », pause, ⏭, the slider, « Lire seulement cette scène », End and « Rejouer » drive the one composition clock
    and nothing else: after Variants opened, the page sends no command at all (no run, no cue report, no armed set, no speech, no tool). The Core side: `test_presentation_studio_playback_continuous_isolation.py`."""

    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const before=world.calls.length;
""" + CONTINUOUS_GESTURES + r"""
const after=world.calls.slice(before).map(c=>c.method+' '+c.url);
return {after,orders:prefabFake.orders.length,phase:ex.playback.view().phase,open:ex.isOpen(),errors:env.errors};
""")
    assert out["errors"] == [] and out["open"] is True and out["phase"] == "playing", out
    assert all(call.startswith("GET ") for call in out["after"]), f"continuous video sends no command: {out['after']}"
    assert not [c for c in out["after"] if any(word in c for word in ("/playback", "/cues", "/armed", "speak", "/tools"))], out["after"]
    assert out["orders"] > 0, "the measure saw the video being driven (the Player was ordered by the composition clock)"
