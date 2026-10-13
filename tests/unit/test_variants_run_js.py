"""A presentation run INSIDE Variants (handoff jarvis-remotion-native-studio-playback-fix, Slice 09), by node.

The floating viewer (the Board run stage window `studio-stage-<run_id>` and the band `#jvStudioBand`) is retired: Core shows a run on a
memory surface (`variants-run-<run_id>`) and Variants mounts it in ITS Player (`control_center_presentation_studio_run.js` +
`control_center_presentation_studio_explorer.js`). Two levels, each with negative cases:

1. The run adapter on the REAL prefab host (`control_center_prefab_host.js`) configured as Variants configures it (`autoplay: false`,
   `embed: 'variants'`) and the REAL timeline follower (`control_center_remotion_frame.js`):
   - Finding 7 of Slice 07 is impossible by construction: a scene entered by a `next` posted to Core (a cue, the voice) is never played
     by the host's own grace play before the band's poll brings Core's order; the Player waits on frame 0 until Core's timeline orders it,
     then plays the entry ONCE from frame 0. The control group (the retired run stage's configuration) shows the race it had;
   - a detour is an overlay inside the stage; a scene whose timeline Core could not read plays once, unguided; the end clears everything.
2. The explorer in run mode on the fake DOM: a run Core started opens Variants (windowed, never fullscreen, once per run) instead of
   closing it; the tree and actions are inert (« Présentation en cours »); the transport is the run's (pause / resume, previous / next item,
   the slider read-only « La partition mène la présentation », « Arrêter »); the § 4.15 presenter keys; a thumbnail is `goto {scene_id}`;
   the presenter strip; « Présenter » starts a run; closing Variants pauses a playing run and never reopens it by itself; another
   presentation is refused while a run plays; the run's frame events reach Core; the end gives the video back.

Contract: `docs/presentation-studio.md` > *2026-10 § 2*, *§ 4.15*, *§ 5*, *Variants run surface (Level 3, Slice 09)*.
"""

from __future__ import annotations

import json

from tests.fakes.explorer_js import run_ui
from tests.unit.test_remotion_continuity_js import HOST_BENCH
from tests.unit.test_remotion_stage_js import RUNTIME, run_stage_node

RUN_JS = json.dumps(str(RUNTIME / "control_center_presentation_studio_run.js"))

ADAPTER = HOST_BENCH + r"""
const RunM=require(""" + RUN_JS + r""");
const key=(p)=>p+'@1';
const tl=(prefab,seq,from,until,extra)=>Object.assign({scene_id:'pss',composition_id:'Scene',fps:30,duration_frames:150,anchor_id:null,from_frame:from,
  until_frame:until,playing:true,seq,play_ms:0,tolerance_ms:500,problems:[],prefab:key(prefab),auto:false},extra||{});
const surface=(prefab,rev,sceneId,extra)=>Object.assign({surface_id:'variants-run-r1',run_id:'r1',revision:rev,scene_id:sceneId,title:sceneId,
  prefab:{id:prefab,version:1,props:{title:'x'},data:{}},overlays:[]},extra||{});
function runBench(hostExtra){
  const b=hostBench(hostExtra);
  const segs=[],logs=[];
  /* The follower ticks on the bench's clock (never a real interval). */
  b.c.setInterval=(fn,ms)=>{const id={};const loop=()=>{id.t=b.c.setTimeout(()=>{fn();loop()},ms)};loop();return id};
  b.c.clearInterval=(id)=>{if(id)b.c.clearTimeout(id.t)};
  const overlay=b.doc.createElement('div');b.doc.body.appendChild(overlay);
  const a=RunM.createRunAdapter({host:()=>b.host,slot:()=>b.slot,overlaySlot:()=>overlay,frames:Frame,onSegment:r=>segs.push(r),
    log:(k,d,l)=>logs.push([k,l]),now:b.c.now,setInterval:b.c.setInterval,clearInterval:b.c.clearInterval});
  /* The host's onLive / onClock go to the adapter, as the explorer wires them. */
  b.host=H.createPrefabHost(Object.assign({document:b.doc,window:b.win,now:b.c.now,setTimeout:b.c.setTimeout,clearTimeout:b.c.clearTimeout,
    swapPrefix:'presentation-studio.',log:()=>{},onLive:(id)=>a.onLive(id),onClock:(id)=>a.onClock(id),
    fetchBundle:(id)=>Promise.resolve({kind:'remotion',id,version:1,title:id.slice(-2)})},hostExtra||{}));
  /* The bench clock jumps to the end of an `advance` before it runs what is due: real time is walked in 50 ms steps. */
  const walk=(ms)=>{for(let t=0;t<ms;t+=50)b.c.advance(50)};
  /* A real Player reports its clock about four times a second while it plays: the frame `f` plays from `from` for `ms`. */
  const plays=(f,from,ms)=>{for(let t=0;t<ms;t+=250){b.say(f,{type:'clock',frame:Math.min(149,from+Math.round(t*30/1000)),playing:true,duration:150,fps:30});walk(250)}};
  return Object.assign(b,{a,segs,logs,overlay,walk,plays});
}
"""


# ------------------------------------------------------------------ 1. the run adapter on the real host

def explorer_host_options(tmp_path):
    """The options the REAL explorer passes to `createPrefabHost` for its Player (the one a run is mounted in), read on the fake DOM: only
    the plain values (the callbacks, the document and the window are the explorer's own wiring)."""
    return run_ui(tmp_path / "explorer", RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await showView(runView());
      fakePlayer.surf=SURF;fire('jarvis:studio-surface',{surface:SURF});await env.advance(200);
      const deps=prefabFake.hosts[0].deps,plain={};
      for(const [k,v] of Object.entries(deps))if(v===null||['string','number','boolean'].includes(typeof v))plain[k]=v;
      return plain;
    """)


def test_finding_7_a_scene_entered_by_a_core_next_is_never_played_before_cores_order_and_never_replayed(tmp_path):
    """Slice 07, Finding 7 (owner Slice 09): the run stage's host started its own grace play 450 ms after the frame was ready, before the band's
    1.5 s poll brought Core's order; the order then replayed the entry from frame 0 (78 -> 0). In Variants the host never plays by itself and
    the embedded stage page never plays on ready, so the only play a scene ever gets is Core's, from frame 0: the race cannot happen.

    The host is configured with the options the REAL explorer passes (read from it, never written here): a self-playing Variants Player
    (`autoplay: true`) fails this test."""

    (tmp_path / "explorer").mkdir()
    options = explorer_host_options(tmp_path)
    assert options.get("autoplay") is False, f"run mode: the explorer's Player never plays by itself ({options})"
    assert options.get("embed") == "variants"

    result = run_stage_node(tmp_path, ADAPTER + r"""
      const run=async(config)=>{
        const b=runBench(config);
        b.a.applySurface(surface(b.A,1,'pss_1'));
        const fa=await b.bringUp(b.A);
        b.walk(400);
        b.a.applyTimeline({object_id:'variants-run-r1',timeline:tl(b.A,1,0,149)});    // the first scene: Core's order
        b.say(fa,{type:'clock',frame:78,playing:true,duration:150,fps:30});
        /* A cue / the voice posts `next` to Core: the surface shows scene B at once; Core's timeline arrives with the next poll (1.5 s). */
        b.a.applySurface(surface(b.B,2,'pss_2'));
        const fb=await b.bringUp(b.B);
        b.walk(2600);                               // measured in Slice 07: Core's order reached the stage 2.6 s after the host's own play
        const beforeOrder=b.posted(fb).slice();
        b.say(fb,{type:'clock',frame:beforeOrder.some(p=>p[0]==='play')?45:0,playing:beforeOrder.some(p=>p[0]==='play'),duration:150,fps:30});
        b.a.applyTimeline({object_id:'variants-run-r1',timeline:tl(b.B,2,0,149)});
        b.plays(fb,0,3000);
        return {a:b.posted(fa),beforeOrder,b:b.posted(fb),key:b.host.key('variants-run-r1')};
      };
      return {variants:await run(D.explorer),retired:await run({})};
    """, {"explorer": options})
    v = result["variants"]
    assert v["beforeOrder"] == [["pause", 0, None]], "Variants: nothing plays the entered scene before Core's order (no grace play)"
    assert v["b"] == [["pause", 0, None], ["play", 0, 149]], "one play, Core's, from frame 0: the entry is played once, never replayed"
    assert v["a"] == [["pause", 0, None], ["play", 0, 149]], "the scene left was never re-ordered"
    assert v["key"].endswith("s000000000002@1")
    r = result["retired"]
    assert ["play", None, None] in r["beforeOrder"], "control group: the retired run stage's host played by itself before Core's order"
    assert r["b"][-1] == ["play", 0, 149], "... and Core's order then replayed the entry from frame 0 (the 78 -> 0 jump of Finding 7)"


def test_the_adapter_mounts_overlays_inside_the_stage_plays_an_unreadable_timeline_once_and_clears_everything(tmp_path):
    result = run_stage_node(tmp_path, ADAPTER + r"""
      const b=runBench({autoplay:false,embed:'variants'});
      b.a.applySurface(surface(b.A,1,'pss_1',{overlays:[{overlay_id:'variants-run-r1-a1',title:'Annexe',visible:false,
        prefab:{id:'lab.counter',version:1,props:{},data:{}}}]}));
      const hiddenMounted=b.overlay.children.length;
      b.a.applySurface(surface(b.A,2,'pss_1',{overlays:[{overlay_id:'variants-run-r1-a1',title:'Annexe',visible:true,
        prefab:{id:'presentation-studio.p000000000001.s000000000009',version:1,props:{},data:{}}}]}));
      await flush();
      const shown=b.overlay.children.length;
      const owns=[b.a.owns('variants-run-r1'),b.a.owns('variants-run-r1-a1'),b.a.owns('studio-explorer-preview'),b.a.owns('variants-run-r2')];
      b.a.applySurface(surface(b.A,3,'pss_1'));
      const retired=b.host.key('variants-run-r1-a1')?1:0;
      /* Core could not read the timeline of this scene: it plays ONCE from frame 0, unguided, and never twice for the same revision. */
      const f=await b.bringUp(b.A);
      b.a.setUnresolved('pss_1');b.a.setUnresolved('pss_1');b.a.onLive('variants-run-r1');
      const unguided=b.posted(f);
      b.a.setUnresolved('pss_other');
      b.a.applySurface(null);
      return {hiddenMounted,shown,owns,retired,unguided,stats:b.a.stats(),after:[b.a.objectId(),b.a.surface(),b.host.key('variants-run-r1')]};
    """)
    assert result["hiddenMounted"] == 0, "an overlay hidden at birth is not mounted"
    assert result["shown"] >= 1 and result["owns"] == [True, True, False, False]
    assert result["retired"] == 0, "return: the overlay is gone, the frame underneath stays"
    assert result["unguided"] == [["pause", 0, None], ["play", 0, None]] and result["stats"]["unguided"] == 1
    assert result["after"][:2] == [None, None] and result["stats"]["cleared"] == 1


# ------------------------------------------------------------------ 2. the explorer in run mode (fake DOM)

RUN_UI = r"""
const {FakeEvent}=require(process.env.JARVIS_EXPLORER_DOM);
const SCENES=['pss_000000000001','pss_000000000002','pss_000000000003'];
const fakePlayer={v:{phase:'idle',running:false},surf:null,commands:[],starts:[],reply:null,
  view(){return this.v},surface(){return this.surf},state(){return {linkLostSince:null}},
  async command(verb,body){this.commands.push([verb,body||{}]);return this.reply?this.reply(verb,body):{status:'applied',state:this.v}},
  async startRun(pid,role,extra){this.starts.push([pid,role,extra||{}]);return this.startReply||{status:'applied'}}};
const runView=(extra)=>Object.assign({phase:'playing',running:true,run_id:'r1',role:'user_presenter',jarvis_speaks:false,position:{index:1,of:4},
  scene:{scene_id:SCENES[0],title:'Scène 1 de 1',number:1,of:3},item:{item_id:'psi_1',label:'Intro',presenter:'user'},
  elapsed:{item_ms:3000,item_target_ms:8000},presentation_id:PID,variant_id:vid(1),stage_object_id:'variants-run-r1',
  surface:{id:'variants-run-r1',rev:1},problems:[],notices:[],pending:null,next:{item_label:'Suite',cue:null},sequence:null},extra||{});
const SURF={surface_id:'variants-run-r1',run_id:'r1',revision:1,scene_id:SCENES[0],title:'Scène 1',prefab:{id:'lab.dial',version:1,props:{},data:{}},overlays:[]};
const fire=(name,detail)=>win.dispatchEvent(new FakeEvent(name,{detail,bubbles:false}));
const showView=async(view)=>{fakePlayer.v=view;fire('jarvis:studio-view',{view});await env.advance(500)};
const transport=()=>q('.jvx-transport');
const named=(label)=>[...qa('button',transport())].find(b=>(b.getAttribute('aria-label')||b.textContent).trim()===label);
const strip=()=>q('.jvx-presenter');
const textIn=n=>{let t=n.textContent||'';for(const c of n.children||[])t+=' '+textIn(c);return t};
"""


def test_a_run_core_started_opens_variants_windowed_once_and_hosts_it_inertly(tmp_path):
    result = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await showView(runView());
      const opened=ex.isOpen();
      fakePlayer.surf=SURF;fire('jarvis:studio-surface',{surface:SURF});await env.advance(200);
      const mounts=prefabFake.mounts.map(m=>m.object_id);
      const play=q('[data-act="continuous"]'),slider=q('[role="slider"]');
      const model=ex.run.model();
      const state={inertTree:q('.jvx-treepane').inert,inertActions:q('.jvx-actions').inert,chip:!q('.jvx-treepane .jvx-chip[data-tone="accent"]').hidden,
        play:[play.getAttribute('aria-label'),play.getAttribute('aria-pressed')],prev:named('Élément précédent')!==undefined,
        next:named('Élément suivant')!==undefined,slider:[slider.getAttribute('aria-disabled'),slider.getAttribute('title')],stop:!q('[data-act="stop_run"]').hidden,
        present:q('[data-act="present"]').hidden,strip:[strip().hidden,textIn(strip())],
        count:q('.jvx-scene-count').textContent,fullscreen:fsFake.calls.length};
      /* the same run seen again (every poll) never opens it twice; closing Variants pauses the playing run and keeps it closed */
      await showView(runView());
      ex.close({reason:'user'});await env.advance(100);
      await showView(runView({phase:'paused'}));
      return {opened,mounts,state,model:[model.role,model.where],closedStays:ex.isOpen(),commands:fakePlayer.commands,toasts:env.toasts.map(t=>t.title)};
    """)
    assert result["opened"] is True, "a run Core started opens Variants instead of closing it"
    assert "variants-run-r1" in result["mounts"], "Variants mounts the run's surface in its Player"
    s = result["state"]
    assert s["inertTree"] is True and s["inertActions"] is True and s["chip"] is True, "tree and actions inert, « Présentation en cours »"
    assert s["play"] == ["Pause", "true"] and s["prev"] and s["next"]
    assert s["slider"][0] == "true" and "partition mène la présentation" in s["slider"][1], "§ 5: the scrubber is read-only during a run"
    assert s["stop"] is True and s["present"] is True
    assert s["strip"][0] is False and "Vous présentez" in s["strip"][1] and "Scène 1/3 · élément 1/4" in s["strip"][1] and "Partition" in s["strip"][1]
    assert s["count"] == "Scène 1 sur 3" and s["fullscreen"] == 0, "opened windowed: starting a run never enters fullscreen"
    assert result["model"] == ["Vous présentez", "Scène 1/3 · élément 1/4"]
    assert result["closedStays"] is False, "a run is opened once: closed by the user, it stays closed"
    assert result["commands"] == [["pause", {}]], "closing Variants pauses a playing run (no surface: it never goes on unseen)"
    assert "Présentation en pause" in result["toasts"]


def test_the_presenter_transport_keys_and_thumbnails_move_the_score_never_the_video(tmp_path):
    result = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await showView(runView());
      fakePlayer.surf=SURF;fire('jarvis:studio-surface',{surface:SURF});await env.advance(200);
      const stage=q('.jvx-stage');
      q('[data-act="continuous"]').click();await env.advance(50);
      named('Élément suivant').click();await env.advance(50);
      named('Élément précédent').click();await env.advance(50);
      for(const k of [' ','ArrowRight','PageUp','Home','End','s']){env.key(stage,k);await env.advance(50)}
      env.key(stage,',');await env.advance(50);const said=noticeText();
      q('[data-scene="'+SCENES[2]+'"]').click();await env.advance(50);
      env.key(q('[role="slider"]'),'ArrowRight');await env.advance(50);const scrubSaid=noticeText();
      fakePlayer.reply=(verb)=>verb==='next'?{status:'refused',reason:'at_end',message:'end'}:{status:'applied'};
      named('Élément suivant').click();await env.advance(50);const refused=noticeText();
      q('[data-act="stop_run"]').click();await env.advance(50);
      return {commands:fakePlayer.commands,said,scrubSaid,refused,sequencerOrders:prefabFake.orders};
    """)
    assert result["commands"] == [["pause", {}], ["next", {}], ["previous", {}], ["pause", {}], ["next", {}], ["previous", {}],
                                  ["goto", {"position": 1}], ["goto", {"position": 4}], ["goto", {"scene_id": "pss_000000000003"}],
                                  ["next", {}], ["stop", {}]], result["commands"]
    assert "Aucune séquence verrouillée" in result["said"] or "partition mène" in result["said"]
    assert "partition mène" in result["scrubSaid"], "the slider never seeks during a run"
    assert result["refused"] == "La présentation est terminée.", "Core's refusal said in plain words"
    assert result["sequencerOrders"] == [], "the continuous-video sequencer never orders the run's Player"


def test_presenter_starts_a_run_here_and_a_run_of_another_presentation_refuses_opening_it(tmp_path):
    result = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await ex.open({presentation_id:PID,fullscreen:false});await env.advance(400);
      const presentDisabled=q('[data-act="present"]').getAttribute('aria-disabled');
      q('[data-act="present"]').click();await env.advance(50);
      const items=qa('[role="menuitem"]').map(b=>b.textContent.trim());
      qa('[role="menuitem"]').find(b=>b.textContent.includes('Jarvis présente')).click();await env.advance(50);
      const other=runView({presentation_id:'pst_'+'f'.repeat(32)});
      ex.close({});fakePlayer.v=other;
      const refused=await ex.open({presentation_id:PID,fullscreen:false});
      return {presentDisabled,items,starts:fakePlayer.starts,ids:[PID,vid(1)],refused:[refused.state,refused.code,refused.reason]};
    """)
    assert result["presentDisabled"] == "false"
    assert result["items"] == ["Vous présentez", "Jarvis présente", "Répétition"]
    pid, vid = result["ids"]
    assert result["starts"] == [[pid, "jarvis_presenter", {"variant_id": vid}]], "« Présenter › Jarvis présente » on the variant on screen"
    assert result["refused"][0] == "refused" and result["refused"][1] == "explorer_run_in_progress"
    assert "Variantes la montre" in result["refused"][2]


def test_the_end_of_the_run_gives_the_video_back_and_a_new_run_is_hosted_again(tmp_path):
    result = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await showView(runView());
      fakePlayer.surf=SURF;fire('jarvis:studio-surface',{surface:SURF});await env.advance(200);
      const unmountsBefore=prefabFake.unmounts;
      await showView({phase:'stopped',running:false,run_id:'r1',last_run:{run_id:'r1',reason:'user',problems:['mode_restore_failed']}});
      await env.advance(400);
      const after={open:ex.isOpen(),inert:q('.jvx-treepane').inert,stop:q('[data-act="stop_run"]').hidden,present:q('[data-act="present"]').hidden,
        strip:strip().hidden,notice:noticeText(),play:q('[data-act="continuous"]').getAttribute('aria-label'),unmounted:prefabFake.unmounts>unmountsBefore,
        preview:prefabFake.mounts.slice(-1)[0].object_id,run:ex.run.view()};
      await showView(runView({run_id:'r2',stage_object_id:'variants-run-r2',surface:{id:'variants-run-r2',rev:1}}));
      return {after,second:ex.run.view()&&ex.run.view().run_id};
    """)
    a = result["after"]
    assert a["open"] is True and a["inert"] is False and a["stop"] is True and a["present"] is False and a["strip"] is True
    assert "Présentation arrêtée" in a["notice"] and "mode d'interaction" in a["notice"], "the end and its problem are said"
    assert a["play"] == "Lire" and a["unmounted"] is True and a["preview"] == "studio-explorer-preview" and a["run"] is None
    assert result["second"] == "r2"


def test_the_runs_frame_posts_its_events_and_reports_its_mount_to_the_hot_reload(tmp_path):
    result = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await showView(runView());
      fakePlayer.surf=SURF;fire('jarvis:studio-surface',{surface:SURF});await env.advance(200);
      const deps=prefabFake.hosts[0].deps;
      env.route('/api/prefabs/events',()=>({status:200,body:{outcome:'applied',revision:2}}));
      const answer=await deps.postEvent({object_id:'variants-run-r1',prefab:{id:'lab.dial',version:1},event:'incremented',payload:{count:2},basis:{count:1}});
      const outcomes=[];globalThis.JarvisStudioReload={instance:{hostOutcome:async(info)=>{outcomes.push(info.object_id)}}};
      deps.onOutcome({object_id:'variants-run-r1',prefab:{id:'presentation-studio.p.s1',version:2},outcome:'mounted'});
      deps.onOutcome({object_id:'studio-explorer-preview',prefab:{id:'presentation-studio.p.s1',version:2},outcome:'mounted'});
      await env.advance(50);
      return {posts:[deps.posts('variants-run-r1'),deps.posts('studio-explorer-preview')],answer,
        sent:env.requests.filter(r=>r.url==='/api/prefabs/events').map(r=>r.body.object_id),outcomes};
    """)
    assert result["posts"] == [True, False], "only the run's frame posts; the preview never writes"
    assert result["answer"] == {"outcome": "applied", "revision": 2} and result["sent"] == ["variants-run-r1"]
    assert result["outcomes"] == ["variants-run-r1"], "the run frame's mount is reported to the hot reload; the preview's is not"


def test_the_mode_hud_stays_live_during_a_run_and_the_page_under_variants_stays_inert(tmp_path):
    """Slice 09 rework (agent 0's decision): Variants is modal (the page under it is inert) except what lives beside it. The interaction-mode
    HUD (`data-keep-live="run"`, nested in `#app` like the real page) stays live during a run — « Refusé par la voix » and the way out of
    PRESENTATION stay usable — and is inert again when the run ends with Variants still open; closing Variants gives everything back."""

    result = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const app=doc.createElement('div'),hud=doc.createElement('div'),face=doc.createElement('div'),rail=doc.createElement('div');
      hud.setAttribute('data-keep-live','run');rail.setAttribute('data-keep-live','true');
      app.appendChild(face);app.appendChild(hud);doc.body.appendChild(app);doc.body.appendChild(rail);
      const look=()=>({app:!!app.inert,hud:!!hud.inert,face:!!face.inert,rail:!!rail.inert,run:doc.documentElement.classList.contains('jvx-run')});
      const ex=make({player:fakePlayer});
      await ex.open({presentation_id:PID,fullscreen:false});await env.advance(400);
      const before=look();
      await showView(runView());
      const during=look();
      await showView({phase:'stopped',running:false,run_id:'r1',last_run:{run_id:'r1',reason:'user',problems:[]}});await env.advance(400);
      const ended=look();
      await showView(runView({run_id:'r2',stage_object_id:'variants-run-r2',surface:{id:'variants-run-r2',rev:1}}));
      const again=look();
      ex.close({reason:'user'});await env.advance(100);
      return {before,during,ended,again,closed:look()};
    """)
    assert result["before"] == {"app": True, "hud": False, "face": False, "rail": False, "run": False}, "no run: the whole page is under the modal"
    assert result["during"] == {"app": False, "hud": False, "face": True, "rail": False, "run": True}, \
        "during a run the HUD is live (its container is not inert, its siblings are) and drawn above Variants (`jvx-run`)"
    assert result["ended"] == result["before"], "the run ended, Variants still open: the HUD is under the modal again"
    assert result["again"] == result["during"]
    assert result["closed"] == {"app": False, "hud": False, "face": False, "rail": False, "run": False}


def test_closing_variants_pauses_the_run_in_every_active_phase(tmp_path):
    """Slice 09 rework: closing Variants during a run never lets it go on unseen. `playing` and `resuming` pause at once; a `detour`
    (Core refuses `pause` there) is paused as soon as Core's view leaves it for this run, once; `paused` / `ended` send nothing; reopening
    Variants on the run cancels a pause-on-return."""

    result = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const out={};
      for(const phase of ['playing','resuming','detour','paused','ended']){
        const ex=make({player:fakePlayer});
        fakePlayer.commands=[];
        await showView(runView({run_id:'r-'+phase,phase}));
        ex.close({reason:'user'});await env.advance(100);
        const atClose=fakePlayer.commands.slice();
        let afterReturn=null;
        if(phase==='detour'){
          await showView(runView({run_id:'r-'+phase,phase:'detour'}));       // still in the detour: nothing yet
          const still=fakePlayer.commands.slice();
          await showView(runView({run_id:'r-'+phase,phase:'resuming'}));     // the detour returned: pause, once
          await showView(runView({run_id:'r-'+phase,phase:'playing'}));
          afterReturn={still,after:fakePlayer.commands.slice()};
        }
        out[phase]={atClose,afterReturn,open:ex.isOpen()};
        ex.destroy&&ex.destroy();
      }
      /* Reopened on the run before the detour returns: the user sees it, no pause is sent. */
      const ex=make({player:fakePlayer});fakePlayer.commands=[];
      await showView(runView({run_id:'r-back',phase:'detour'}));
      ex.close({reason:'user'});await env.advance(100);
      await ex.open({presentation_id:PID,fullscreen:false});await env.advance(400);
      await showView(runView({run_id:'r-back',phase:'detour'}));
      await showView(runView({run_id:'r-back',phase:'resuming'}));
      out.reopened=fakePlayer.commands.slice();
      out.toasts=env.toasts.map(t=>t.title);
      return out;
    """)
    assert result["playing"]["atClose"] == [["pause", {}]]
    assert result["resuming"]["atClose"] == [["pause", {}]], "resuming: the run is paused, never left to play unseen"
    d = result["detour"]
    assert d["atClose"] == [] and d["afterReturn"]["still"] == [], "in a detour Core refuses pause: nothing is sent while it lasts"
    assert d["afterReturn"]["after"] == [["pause", {}]], "the detour returned: paused once, never again"
    assert result["paused"]["atClose"] == [] and result["ended"]["atClose"] == []
    assert all(not result[p]["open"] for p in ("playing", "resuming", "detour", "paused", "ended")), "a closed Variants stays closed"
    assert result["reopened"] == [], "Variants reopened on the run: no pause-on-return"
    assert "Présentation en pause au retour" in result["toasts"]
