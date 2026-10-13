"""Son, plein écran de la scène et touches de Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 08), par node.

Chaque étage avec ses cas négatifs :

1. `control_center_presentation_studio_stage_media.js` (sans DOM) : la carte § 4.15, le son voulu (muet à l'ouverture, refus dit une fois,
   levée), la surimpression du plein écran (se cache en lecture après `CHROME_HIDE_MS`, reste en pause, au focus, menu ouvert).
2. L'amorce du bac à sable (`remotion_sandbox_child.js`) face à un faux Player : `sound {muted}` appliqué, refusé et DIT quand le navigateur
   ne le permet pas (ni geste ni délégation), levé par un vrai geste dans la scène, recoupé quand la lecture se fige ; Remotion qui se coupe
   lui-même est un refus ; une fenêtre sans avis garde l'ancienne règle (un clic active le son) ; seules les touches `KEYS`, vraies et sans
   modificateur, sont relayées ; pas de balises audio partagées.
3. La page de la scène : le son voulu gardé et redonné à chaque Player (rechargement compris), `audio` relayé, une touche de la scène relayée
   SEULEMENT quand la scène a le focus, champs exacts.
4. L'hôte des fenêtres : le son voulu va au seul cadre vivant (jamais au cadre préchargé), suit l'échange ; `audio` / `key` d'un cadre
   préchargé ignorés ; message mal formé jeté.
5. L'explorateur sur le faux DOM : « Son » bascule (aria-pressed, hôte), `M`, le refus dit (avis, pastille, bouton), « Plein écran » et `F`
   visent la SCÈNE, `Échap` imbriqué dans ce plein écran (jamais une pause, jamais une fermeture), le focus rendu à l'ouvreur, une touche
   relayée n'agit que si le focus est dans la scène.

Contrat : `docs/presentation-studio.md` > *Variants media and fullscreen (Level 3, Slice 08)*. Vrai Chrome : `test_variants_media_fullscreen_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.fakes.explorer_js import run_ui
from tests.unit.test_remotion_continuity_js import HOST_BENCH
from tests.unit.test_remotion_sandbox_child_js import HARNESS
from tests.unit.test_remotion_stage_js import READY_FLOW, run_stage_node
from tests.unit.test_variants_transport_js import VIDEO_WORLD

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def run_plain(tmp_path: Path, body: str):
    script = tmp_path / f"media-{len(list(tmp_path.glob('media-*.cjs')))}.cjs"
    script.write_text(f"""const M=require({json.dumps(str(RUNTIME / 'control_center_presentation_studio_stage_media.js'))});
const P=require({json.dumps(str(RUNTIME / 'remotion_sandbox_protocol.js'))});
const R=require({json.dumps(str(RUNTIME / 'control_center_remotion_frame.js'))});
(async()=>{{{body}}})().then(v=>process.stdout.write(JSON.stringify(v)),e=>{{console.error(e&&e.stack||e);process.exit(1)}});
""", encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ 1. the stage media controllers

def test_one_key_map_for_the_stage_the_transport_and_the_keys_a_scene_passes_on(tmp_path):
    out = run_plain(tmp_path, """
      const keys=[' ','ArrowRight','PageDown','ArrowLeft','PageUp','Home','End',',','.','f','F','m','M','Escape','s','?','ArrowUp','Tab','Enter'];
      return {map:keys.map(k=>[k,M.keyAction(k)]),protocol:P.KEYS,frame:R.KEYS,proto:M.keyAction('__proto__')};
    """)
    assert dict(out["map"]) == {" ": "toggle", "ArrowRight": "next", "PageDown": "next", "ArrowLeft": "previous", "PageUp": "previous",
                                "Home": "home", "End": "end", ",": "step_back", ".": "step_forward", "f": "fullscreen", "F": "fullscreen",
                                "m": "sound", "M": "sound", "Escape": "escape", "s": None, "?": None, "ArrowUp": None, "Tab": None, "Enter": None}
    assert out["proto"] is None
    # the keys a scene may pass on are exactly the keys of the map, in the sandbox protocol and in the window's stage parser
    assert sorted(out["protocol"]) == sorted(out["frame"]) == sorted(k for k, v in out["map"] if v)


def test_the_sound_starts_muted_says_a_refusal_once_and_clears_it_when_the_scene_plays_audibly(tmp_path):
    out = run_plain(tmp_path, """
      const calls=[],said=[],logs=[],announced=[];let changes=0;
      const host={sound(m){calls.push(m);return 1}};
      const s=M.createSound({host:()=>host,log:(k,d,l)=>logs.push([k,l||'info']),say:(k,t)=>said.push([k,t]),announce:t=>announced.push(t),changed:()=>changes++});
      s.attach();const opening=s.view();
      s.toggle();const on=s.view();
      s.onAudio({muted:true,blocked:true});s.onAudio({muted:true,blocked:true});const blocked=s.view();const saidOnce=said.length;
      s.onAudio({muted:false,blocked:false});const lifted=s.view();
      s.toggle();const off=s.view();
      s.onAudio({muted:true,blocked:true});const ignoredWhenOff=s.view();
      const none=M.createSound({host:()=>null,log:(k,d,l)=>logs.push([k,l||'info']),say:(k,t)=>said.push([k,t]),announce:()=>{},changed:()=>{}});
      none.toggle();
      return {calls,opening,on,blocked,saidOnce,lifted,off,ignoredWhenOff,noHost:none.view(),said,announced,logs,changes};
    """)
    assert out["calls"] == [True, False, True], "muted at opening, then the user's wish, every time"
    assert out["opening"]["on"] is False and out["opening"]["title"] == "Activer le son (M)" and out["opening"]["pill"] == ""
    assert out["on"]["pressed"] is True and out["on"]["title"] == "Couper le son (M)"
    assert out["blocked"]["blocked"] is True and "cliquez une fois dans l'image" in out["blocked"]["title"] and out["blocked"]["pill"]
    assert out["saidOnce"] == 1 and out["said"][0][0] == "failed" and "Cliquez une fois dans l'image" in out["said"][0][1], "said once, with what to do"
    assert out["lifted"]["blocked"] is False and out["lifted"]["pill"] == ""
    assert out["off"]["on"] is False and out["ignoredWhenOff"]["blocked"] is False, "a refusal while muted is no refusal"
    assert out["noHost"]["on"] is False and out["said"][-1][0] == "failed" and "pas disponible" in out["said"][-1][1], "never a silent no-op"
    assert out["announced"][:2] == ["Son activé.", "Son coupé."]
    assert ["sound_blocked", "warn"] in out["logs"]


def test_the_fullscreen_transport_hides_itself_only_while_playing_and_comes_back_on_a_poke(tmp_path):
    out = run_plain(tmp_path, """
      let t=0,timers=[],seq=0,applied=[];let playing=true,pinned=false;
      const c=M.createChrome({setTimeout:(fn,ms)=>{const id=++seq;timers.push({id,at:t+ms,fn});return id},clearTimeout:id=>{timers=timers.filter(x=>x.id!==id)},
        apply:h=>applied.push(h),playing:()=>playing,pinned:()=>pinned});
      const advance=ms=>{t+=ms;for(const x of timers.filter(x=>x.at<=t)){timers=timers.filter(y=>y!==x);x.fn()}};
      c.poke();const inactive=applied.length;
      c.enter();const entered=c.view();advance(2499);const before=c.view().hidden;advance(1);const hidden=c.view();
      c.poke();const poked=c.view();advance(2500);const again=c.view().hidden;
      playing=false;c.sync();const paused=c.view();advance(10000);const pausedLater=c.view().hidden;
      playing=true;c.sync();advance(2500);const resumed=c.view().hidden;
      c.poke();pinned=true;advance(5000);const pinnedLater=c.view().hidden;pinned=false;
      c.exit();const exited=c.view();advance(10000);
      return {inactive,entered,before,hidden,poked,again,paused,pausedLater,resumed,pinnedLater,exited,applied,pending:timers.length};
    """)
    assert out["inactive"] == 0, "outside fullscreen nothing is hidden or shown"
    assert out["entered"]["active"] is True and out["entered"]["hidden"] is False
    assert out["before"] is False and out["hidden"]["hidden"] is True, "hidden exactly CHROME_HIDE_MS after the last poke while playing"
    assert out["poked"]["hidden"] is False and out["again"] is True
    assert out["paused"]["hidden"] is False and out["pausedLater"] is False, "paused: the transport stays"
    assert out["resumed"] is True
    assert out["pinnedLater"] is False, "focus in the transport or a menu open: it stays"
    assert out["exited"] == {"active": False, "hidden": False, "armed": False, "shows": out["exited"]["shows"], "hides": out["exited"]["hides"]}
    assert out["pending"] == 0, "no timer outlives the fullscreen"


# ------------------------------------------------------------------ 2. the sandbox child

CHILD_PATCHED = (HARNESS
                 .replace("isMuted(){return true},unmute(){},",
                          "muted:true,isMuted(){return player.muted},unmute(){calls.push(['unmute']);player.muted=false},"
                          "mute(){calls.push(['mute']);player.muted=true},")
                 .replace("win.document={readyState:'complete',getElementById:()=>({})};",
                          "win.document={readyState:'complete',getElementById:()=>({}),visibilityState:'visible',"
                          "featurePolicy:{allowsFeature:(f)=>f==='autoplay'&&!!o.delegated}};"
                          "win.navigator={userActivation:{get hasBeenActive(){return !!o.activated}}};"
                          "const later=[];win.setTimeout=(fn,ms)=>{later.push({fn,at:nowMs+ms})};"
                          "win.__fire=()=>{for(const x of later.splice(0))if(x.at<=nowMs)x.fn();else later.push(x)};"))
assert CHILD_PATCHED != HARNESS and CHILD_PATCHED.count("player.muted") >= 2, "the child harness changed: update CHILD_PATCHED"


def run_child(tmp_path: Path, body: str):
    paths = {"protocol": str(RUNTIME / "remotion_sandbox_protocol.js"), "child": str(RUNTIME / "remotion_sandbox_child.js")}
    script = tmp_path / f"child-{len(list(tmp_path.glob('child-*.cjs')))}.cjs"
    script.write_text(f"const PATHS={json.dumps(paths)};\n" + CHILD_PATCHED + "(()=>{\n" + body + "\n})();\n", encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


CHILD_COMMON = r"""
const audio=w=>w.posted.map(p=>p.m).filter(m=>m.type==='audio').map(m=>[m.muted,m.blocked]);
const keysOut=w=>w.posted.map(p=>p.m).filter(m=>m.type==='key').map(m=>m.key);
const gesture=(w,type,extra)=>(w.handlers[type]||[]).forEach(fn=>fn(Object.assign({isTrusted:true,key:'x'},extra||{})));
"""


def test_the_child_applies_the_wish_and_says_a_refusal_instead_of_unmuting_against_the_browser(tmp_path):
    out = run_child(tmp_path, CHILD_COMMON + r"""
      const ok=world({delegated:true});ok.init();
      ok.send({rs:1,type:'sound',muted:false});ok.send({rs:1,type:'sound',muted:true});
      const okCalls=ok.calls.filter(c=>c[0]==='mute'||c[0]==='unmute');
      const no=world({});no.init();
      no.send({rs:1,type:'sound',muted:false});const refused={audio:audio(no),muted:no.player.muted};
      gesture(no,'pointerdown');const lifted={audio:audio(no),muted:no.player.muted};
      const own=world({activated:true});own.init();own.send({rs:1,type:'sound',muted:false});
      const early=world({delegated:true});early.send({rs:1,type:'sound',muted:false});const beforePlayer=early.calls.length;early.init();
      const props=ok.refs[0].props;
      console.log(JSON.stringify({okCalls,okAudio:audio(ok),okMuted:ok.player.muted,refused,lifted,own:[own.player.muted,audio(own)],
        beforePlayer,early:[early.player.muted,audio(early)],shared:props.numberOfSharedAudioTags,initiallyMuted:props.initiallyMuted}));
    """)
    assert out["okCalls"] == [["unmute"], ["mute"]] and out["okAudio"] == [[False, False], [True, False]] and out["okMuted"] is True
    assert out["refused"] == {"audio": [[True, True]], "muted": True}, "no gesture, no delegation: never unmuted, the refusal is said"
    assert out["lifted"] == {"audio": [[True, True], [False, False]], "muted": False}, "a real gesture in the scene lifts the refusal"
    assert out["own"] == [False, [[False, False]]], "a frame that already had a gesture of its own may sound"
    assert out["beforePlayer"] == 0 and out["early"] == [False, [[False, False]]], "a wish before the Player exists is applied at mount"
    assert out["shared"] == 0 and out["initiallyMuted"] is True


def test_the_child_re_mutes_a_player_frozen_by_a_refused_audio_context_and_treats_remotions_own_mute_as_a_refusal(tmp_path):
    out = run_child(tmp_path, CHILD_COMMON + r"""
      const w=world({delegated:true});w.init();
      w.send({rs:1,type:'sound',muted:false});
      w.send({rs:1,type:'control',action:'play'});w.player.emit('play');
      w.advance(1500);w.win.__fire();
      const frozen={audio:audio(w),muted:w.player.muted};
      const m=world({delegated:true});m.init();m.send({rs:1,type:'sound',muted:false});
      m.send({rs:1,type:'control',action:'play'});m.player.emit('play');
      m.advance(500);m.player.emit('frameupdate',{frame:15});m.advance(1000);m.win.__fire();
      const moving={audio:audio(m),muted:m.player.muted};
      m.player.muted=true;m.player.emit('mutechange',{isMuted:true});
      const selfMuted=audio(m);
      console.log(JSON.stringify({frozen,moving,selfMuted}));
    """)
    assert out["frozen"] == {"audio": [[False, False], [True, True]], "muted": True}, "a frozen image while unmuted: muted again and said"
    assert out["moving"] == {"audio": [[False, False]], "muted": False}, "a moving image keeps its sound"
    assert out["selfMuted"] == [[False, False], [True, True]], "Remotion muting itself is a refusal, said"


def test_the_stall_watchdog_never_re_mutes_a_player_the_user_paused(tmp_path):
    """Rework M7: unmuted, played, then paused; the image stops on purpose. 1.5 s later the Player keeps its sound and nothing is said."""

    out = run_child(tmp_path, CHILD_COMMON + r"""
      const seen=w=>({playing:w.player.playing,muted:w.player.muted,audio:audio(w),mutes:w.calls.filter(c=>c[0]==='mute').length});
      // unmute, play, pause before the image moved: the watchdog armed by `play` fires on a Player the user paused
      const w=world({delegated:true});w.init();
      w.send({rs:1,type:'sound',muted:false});
      w.send({rs:1,type:'control',action:'play'});w.player.emit('play');
      w.advance(200);w.send({rs:1,type:'control',action:'pause'});w.player.emit('pause');
      w.advance(1600);w.win.__fire();w.advance(1600);w.win.__fire();
      // « Son » pressed while the Player is paused: the image does not move, on purpose
      const p=world({delegated:true});p.init();
      p.send({rs:1,type:'sound',muted:false});p.advance(1600);p.win.__fire();
      console.log(JSON.stringify({played:seen(w),pausedUnmute:seen(p)}));
    """)
    for name in ("played", "pausedUnmute"):
        seen = out[name]
        assert seen["playing"] is False, f"{name}: the bench really has a paused Player"
        assert seen["muted"] is False and seen["mutes"] == 0, f"{name}: a paused Player keeps the sound the user asked for ({seen})"
        assert seen["audio"] == [[False, False]], f"{name}: no `audio {{blocked: true}}` for a pause ({seen})"


def test_a_frame_without_a_wish_keeps_the_old_rule_and_a_wish_is_never_contradicted_by_a_click(tmp_path):
    out = run_child(tmp_path, CHILD_COMMON + r"""
      const legacy=world({});legacy.init();gesture(legacy,'pointerdown');gesture(legacy,'pointerdown',{isTrusted:false});
      const wished=world({delegated:true});wished.init();wished.send({rs:1,type:'sound',muted:true});gesture(wished,'pointerdown');
      const fake=world({});fake.init();fake.send({rs:1,type:'sound',muted:false});gesture(fake,'pointerdown',{isTrusted:false});
      wished.send({rs:1,type:'teardown'});
      console.log(JSON.stringify({legacy:legacy.player.muted,wished:wished.player.muted,fake:[fake.player.muted,audio(fake)],
        bad:(()=>{const b=world({});b.init();b.send({rs:1,type:'sound',muted:'no'});b.send({rs:1,type:'sound',muted:false,extra:1});return [b.player.muted,audio(b)]})()}));
    """)
    assert out["legacy"] is False, "before Variants said anything (the run stage): a click in the scene turns the sound on, as before"
    assert out["wished"] is True, "the page asked for silence: a click in the scene does not overrule it"
    assert out["fake"] == [True, [[True, True]]], "an untrusted event is no gesture"
    assert out["bad"] == [True, []], "a malformed `sound` is dropped"


def test_only_the_transport_keys_typed_for_real_and_without_modifiers_leave_the_scene(tmp_path):
    out = run_child(tmp_path, CHILD_COMMON + r"""
      const w=world({});w.init();
      for(const key of [' ','ArrowRight','m','F','Escape','a','Tab','Enter','?',','])gesture(w,'keydown',{key});
      gesture(w,'keydown',{key:' ',isTrusted:false});gesture(w,'keydown',{key:'ArrowLeft',ctrlKey:true});gesture(w,'keydown',{key:'m',altKey:true});
      console.log(JSON.stringify({keys:keysOut(w),origins:[...new Set(w.posted.filter(p=>p.m.type==='key').map(p=>p.origin))]}));
    """)
    assert out["keys"] == [" ", "ArrowRight", "m", "F", "Escape", ","]
    assert out["origins"] == ["http://h"], "only to the embedder's origin"


def test_the_protocol_bounds_the_new_messages(tmp_path):
    out = run_plain(tmp_path, """
      const SRC={},OK=d=>({source:SRC,origin:'null',data:d});
      const child=[{rs:1,type:'audio',muted:true,blocked:false},{rs:1,type:'audio',muted:'x',blocked:false},{rs:1,type:'audio',muted:true},
        {rs:1,type:'key',key:' '},{rs:1,type:'key',key:'a'},{rs:1,type:'key',key:' ',extra:1}].map(d=>{const r=P.parseChildMessage(OK(d),SRC);return r.ok||r.reason});
      const host=[{rs:1,type:'sound',muted:false},{rs:1,type:'sound'},{rs:1,type:'sound',muted:1}].map(d=>{const r=P.parseHostMessage({source:SRC,origin:'http://h',data:d},SRC,'http://h');return r.ok||r.reason});
      let t=0;const sup=P.createSupervisor({now:()=>t,send:()=>{},kill:()=>{}});sup.accept(OK({rs:1,type:'ready'}),SRC);
      const keys=[];for(let i=0;i<25;i++)keys.push(sup.accept(OK({rs:1,type:'key',key:'.'}),SRC).ok);
      const st=sup.state();
      return {child,host,accepted:keys.filter(Boolean).length,dropped:st.keyDropped,violations:st.violations};
    """)
    assert out["child"] == [True, "bad_audio", "bad_audio", True, "bad_key", "extra_field"]
    assert out["host"] == [True, "bad_sound", "bad_sound"]
    assert out["accepted"] == 20 and out["dropped"] == 5 and out["violations"] == 0, "keys capped per second, never a violation"


def test_the_window_parsers_of_audio_and_key_refuse_another_source_another_origin_and_an_extra_field(tmp_path):
    """Defence in depth (rework polish): `parseAudio` / `parseKey` of `control_center_remotion_frame.js`."""

    out = run_plain(tmp_path, """
      const W={},iframe={contentWindow:W},O='http://127.0.0.1:1';
      const ev=(data,over)=>Object.assign({source:W,origin:O,data:Object.assign({rsh:1},data)},over||{});
      const r=x=>x.ok?x:x.reason;
      const audio={type:'audio',muted:true,blocked:false},key={type:'key',key:' '};
      return {
        audio:[R.parseAudio(ev(audio),iframe,O),R.parseAudio(ev(audio,{source:{}}),iframe,O),R.parseAudio(ev(audio,{origin:'http://evil'}),iframe,O),
          R.parseAudio(ev(Object.assign({extra:1},audio)),iframe,O),R.parseAudio(ev(key),iframe,O)].map(r),
        key:[R.parseKey(ev(key),iframe,O),R.parseKey(ev(key,{source:{}}),iframe,O),R.parseKey(ev(key,{origin:'http://evil'}),iframe,O),
          R.parseKey(ev(Object.assign({extra:1},key)),iframe,O),R.parseKey(ev({type:'key',key:'a'}),iframe,O)].map(r)};
    """)
    assert out["audio"] == [{"ok": True, "audio": {"muted": True, "blocked": False}}, "foreign_source", "bad_origin", "extra_field", "bad_message"]
    assert out["key"] == [{"ok": True, "key": " "}, "foreign_source", "bad_origin", "extra_field", "bad_key"]


# ------------------------------------------------------------------ 3. the stage page

async def test_the_stage_page_keeps_the_wish_for_every_player_relays_audio_and_relays_a_key_only_with_the_focus(tmp_path):
    result = run_stage_node(tmp_path, r"""
      const b=stageBench({embed:'variants'});b.stage.start();await flush();
      b.fromParent({rsh:1,type:'sound',muted:false});const beforeReady=inboxOf(b).filter(m=>m.type==='sound').length;
      b.fromFrame({rs:1,type:'ready'});await flush();
      const atReady=inboxOf(b).filter(m=>m.type==='sound');
      b.fromFrame({rs:1,type:'audio',muted:false,blocked:false});
      const relayed=b.parent.posted.map(p=>p.message).filter(m=>m.type==='audio');
      b.fromFrame({rs:1,type:'key',key:'m'});const unfocused=b.parent.posted.map(p=>p.message).filter(m=>m.type==='key').length;
      b.frame().focus();b.fromFrame({rs:1,type:'key',key:'m'});
      const own=b.doc.dispatch('keydown',{key:'f',target:b.root});const listeners=(b.doc.listeners.keydown||[]).length;const ownTarget=b.doc.dispatch('keydown',{key:' ',target:{tagName:'BUTTON'}});
      const keys=b.parent.posted.map(p=>p.message).filter(m=>m.type==='key');
      b.fromParent({rsh:1,type:'sound',muted:true,extra:1});
      b.stage.prepare();await flush();b.fromFrame({rs:1,type:'ready'});await flush();
      const afterRetry=inboxOf(b).filter(m=>m.type==='sound');
      return {listeners,beforeReady,atReady,relayed,unfocused,keys,own:own.defaultPrevented,button:ownTarget.defaultPrevented,afterRetry,state:b.stage.state()};
    """)
    assert result["beforeReady"] == 0 and result["atReady"] == [{"rs": 1, "type": "sound", "muted": False}], "kept, then given at ready"
    assert result["relayed"] == [{"rsh": 1, "type": "audio", "muted": False, "blocked": False}]
    assert result["unfocused"] == 0 and result["state"]["keysRefused"] == 1, "a scene without the focus cannot press a key"
    assert [k["key"] for k in result["keys"]] == ["m", "f"] and result["own"] is True, "the scene's key, then a key typed in the page itself"
    assert result["button"] is False, "a focused button keeps Space"
    assert result["afterRetry"] == [{"rs": 1, "type": "sound", "muted": False}], "a malformed wish is ignored; the kept one goes to the new Player"
    assert result["state"]["soundWanted"] is True


async def test_the_run_stage_relays_no_keys_and_says_nothing_until_asked(tmp_path):
    result = run_stage_node(tmp_path, READY_FLOW + r"""
      await flush();b.frame().focus();b.fromFrame({rs:1,type:'key',key:' '});
      return {keys:b.parent.posted.map(p=>p.message).filter(m=>m.type==='key').length,sound:inboxOf(b).filter(m=>m.type==='sound').length,
        listeners:(b.doc.listeners.keydown||[]).length};
    """)
    assert result == {"keys": 0, "sound": 0, "listeners": 0}, "outside Variants: no wish, no key relay, no key listener (until Slice 09)"


# ------------------------------------------------------------------ 4. the window host

async def test_the_host_sends_the_wish_to_the_live_frame_only_and_follows_the_swap(tmp_path):
    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const sounds=[],keys=[];
      const b=hostBench({onSound:(id,a)=>sounds.push([id,a.muted,a.blocked]),onKey:(id,k)=>keys.push([id,k])});
      const sent=f=>f.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='sound').map(m=>m.muted);
      const before=b.host.sound(true);
      b.host.mount(b.slot,b.inst(b.A));const live=await b.bringUp(b.A);b.c.advance(2000);
      b.host.sound(false);
      const preloaded=b.host.preload('stage',b.inst(b.B));const next=await b.bringUp(b.B);b.c.advance(2000);
      const stagedBefore=sent(next);
      b.say(next,{type:'audio',muted:false,blocked:false});b.say(next,{type:'key',key:' '});
      const fromStaged=[sounds.length,keys.length];
      b.say(live,{type:'audio',muted:true,blocked:true});b.say(live,{type:'key',key:'m'});b.say(live,{type:'key',key:'z'});
      b.say(live,{type:'audio',muted:true});
      const swapped=b.host.mount(b.slot,b.inst(b.B));b.c.advance(1);
      return {preloaded,swapped,key:b.host.key('stage'),before,live:sent(live),stagedBefore,afterSwap:sent(next),fromStaged,sounds,keys,wanted:b.host.soundWanted(),audio:b.host.audio('stage'),
        dropped:b.logs.filter(l=>l.key==='scene.prefab_message_dropped').map(l=>l.data.reason)};
    """)
    assert result["preloaded"] is True and result["swapped"] is False and result["key"].endswith("s000000000002@1"), "the preloaded frame took the window"
    assert result["before"] == 0, "no frame yet: kept for the next ones"
    assert result["live"] == [True, False], "muted at ready, then the wish"
    assert result["stagedBefore"] == [], "a frame loaded ahead stays muted"
    assert result["afterSwap"] == [False], "the wish follows the scene that takes the window"
    assert result["fromStaged"] == [0, 0], "a staged frame's sound and keys are not the page's"
    assert result["sounds"] == [["stage", True, True]] and result["keys"] == [["stage", "m"]]
    assert result["wanted"] is True and "bad_key" in result["dropped"] and "bad_audio" in result["dropped"]


async def test_toggling_the_sound_while_a_frame_is_loaded_ahead_never_reaches_the_preloaded_frame(tmp_path):
    """Rework M1b: « Son » pressed (on, off, on) AFTER the next scene is preloaded; only the live frame hears it."""

    result = run_stage_node(tmp_path, HOST_BENCH + r"""
      const b=hostBench({onSound:()=>{},onKey:()=>{}});
      const sent=f=>f.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='sound').map(m=>m.muted);
      b.host.sound(true);
      b.host.mount(b.slot,b.inst(b.A));const live=await b.bringUp(b.A);b.c.advance(2000);
      b.host.preload('stage',b.inst(b.B));const next=await b.bringUp(b.B);b.c.advance(2000);
      const staged=b.host.parked('stage')||!!b.host.pendingKey('stage');
      const counts=[b.host.sound(false),b.host.sound(true),b.host.sound(false)];
      const nextWhileStaged=sent(next);
      b.host.mount(b.slot,b.inst(b.B));b.c.advance(1);
      return {staged,counts,live:sent(live),nextWhileStaged,nextAfterSwap:sent(next)};
    """)
    assert result["staged"] is True, "the bench really has a frame loaded ahead"
    assert result["counts"] == [1, 1, 1], "each toggle reaches exactly one frame: the live one"
    assert result["live"] == [True, False, True, False]
    assert result["nextWhileStaged"] == [], "the preloaded frame never receives `sound`"
    assert result["nextAfterSwap"] == [False], "it gets the current wish only once it takes the window"


# ------------------------------------------------------------------ 5. the explorer

def test_son_and_m_toggle_the_sound_and_a_refusal_is_said_on_the_button_the_image_and_the_notice(tmp_path):
    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const son=()=>label('Son');
const host=prefabFake.hosts[0];
const view=()=>({pressed:son().getAttribute('aria-pressed'),title:son().title,state:son().getAttribute('data-sound'),
  pill:q('.jvx-stage-sound').hidden?'':q('.jvx-stage-sound').textContent,notice:noticeText()});
const opening=view();
son().click();const on=view();
host.deps.onSound('studio-explorer-preview',{muted:true,blocked:true});const blocked=view();
host.deps.onSound('studio-explorer-preview',{muted:false,blocked:false});const lifted=view();
q('.jvx-stage').focus();env.key(q('.jvx-stage'),'m');const viaM=view();
env.key(q('.jvx-stage'),'M');const viaShiftM=view();
host.deps.onSound('another-object',{muted:true,blocked:true});const other=view();
return {opening,on,blocked,lifted,viaM,viaShiftM,other,sounds:prefabFake.sounds};
""")
    assert out["opening"]["pressed"] == "false" and out["opening"]["pill"] == ""
    assert out["on"]["pressed"] == "true" and out["on"]["title"] == "Couper le son (M)"
    assert out["blocked"]["state"] == "blocked" and "cliquez une fois dans l'image" in out["blocked"]["pill"]
    assert "Cliquez une fois dans l'image" in out["blocked"]["notice"] and "Autoriser" in out["blocked"]["notice"]
    assert out["lifted"]["state"] is None and out["lifted"]["pill"] == ""
    assert out["viaM"]["pressed"] == "false" and out["viaShiftM"]["pressed"] == "true"
    assert out["other"]["state"] is None
    assert out["sounds"] == [True, False, True, False], "muted at opening, then each toggle"


def test_plein_ecran_and_f_put_the_stage_in_fullscreen_escape_leaves_it_without_closing_and_the_focus_returns(tmp_path):
    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const fsBtn=q('.jvx-top-actions .jvx-btn');
const theater=q('.jvx-theater');
fsFake.calls.length=0;
fsBtn.focus();fsBtn.click();await env.advance(50);
const entered={calls:fsFake.calls.map(c=>[c.object_id,c.keys,c.display||'current']),element:doc.fullscreenElement===theater,mode:ex.state().mode,
  focusOnStage:doc.activeElement===q('.jvx-stage'),chrome:theater.getAttribute('data-chrome'),view:ex.playback.fullscreen()};
env.key(q('.jvx-stage'),'Escape');await env.advance(50);
const afterEscape={element:doc.fullscreenElement,open:ex.isOpen(),focusBack:doc.activeElement===fsBtn,phase:ex.playback.view().phase,notice:noticeText()};
env.key(fsBtn,'Escape');await env.advance(10);const graceKept=ex.isOpen();
await env.advance(500);
q('.jvx-stage').focus();env.key(q('.jvx-stage'),'f');await env.advance(50);
const viaF={element:doc.fullscreenElement===theater};
env.key(q('.jvx-stage'),'F');await env.advance(50);
const leftViaF={element:doc.fullscreenElement,focusBack:doc.activeElement===q('.jvx-stage')};
await env.advance(500);q('.jvx-stage').focus();env.key(q('.jvx-stage'),'Escape');await env.advance(50);
return {entered,afterEscape,graceKept,viaF,leftViaF,closedAfter:ex.isOpen()};
""")
    entered = out["entered"]
    assert entered["calls"] == [["studio-explorer-stage", "none", "current"]] and entered["element"] is True and entered["mode"] == "fullscreen"
    assert entered["focusOnStage"] is True and entered["chrome"] is None and entered["view"] == {"mode": "fullscreen", "kind": "stage"}
    assert out["afterEscape"]["element"] is None and out["afterEscape"]["open"] is True, "Échap in the stage fullscreen leaves it, never closes"
    assert out["afterEscape"]["focusBack"] is True and out["afterEscape"]["phase"] == "paused" and "Plein écran quitté" in out["afterEscape"]["notice"]
    assert out["graceKept"] is True, "the Échap that just left fullscreen, delivered late, closes nothing"
    assert out["viaF"]["element"] is True and out["leftViaF"]["element"] is None and out["leftViaF"]["focusBack"] is True
    assert out["closedAfter"] is False, "the next Échap closes Variants"


def test_escape_in_the_stage_fullscreen_while_playing_leaves_it_and_never_pauses(tmp_path):
    """Rework M4: playing, stage fullscreen, Échap reaches the page (on the stage, on the page body, relayed by the focused scene)."""

    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const theater=q('.jvx-theater'),fsBtn=q('.jvx-top-actions .jvx-btn');
await ex.playback.play();await env.advance(100);
const runs=[];
const deliver={stage:()=>env.key(q('.jvx-stage'),'Escape'),page:()=>env.key(doc.body,'Escape'),
  scene:()=>{q('.jvx-stage').focus();prefabFake.hosts[0].deps.onKey('studio-explorer-preview','Escape')}};
for(const [name,fn] of Object.entries(deliver)){
  fsBtn.click();await env.advance(50);
  const entered=doc.fullscreenElement===theater,before=ex.playback.view().phase;
  fn();await env.advance(50);
  runs.push({name,entered,before,left:doc.fullscreenElement===null,phase:ex.playback.view().phase,open:ex.isOpen()});
  await env.advance(500);
}
return {runs,pauses:prefabFake.orders.filter(o=>o[0]==='pause').length};
""")
    for run in out["runs"]:
        assert run["entered"] is True and run["before"] == "playing", run
        assert run["left"] is True and run["open"] is True, run
        assert run["phase"] == "playing", f"Échap ({run['name']}) in the stage fullscreen must never pause: {run}"
    assert out["pauses"] == 0, "no pause order ever reached the Player"


def test_sound_is_muted_again_when_variants_is_reopened_in_the_same_page(tmp_path):
    """Rework M10: sound on, Variants closed, reopened without a reload: « Son » not pressed and the host told `muted`."""

    out = run_ui(tmp_path, VIDEO_WORLD + r"""
label('Son').click();
const on={pressed:label('Son').getAttribute('aria-pressed'),sounds:prefabFake.sounds.slice()};
ex.close({reason:'test'});await env.advance(50);
const closed=ex.isOpen();
const marker=prefabFake.sounds.length;
await ex.open({presentation_id:PID,fullscreen:false});await env.advance(400);
return {on,closed,reopened:ex.isOpen(),pressed:label('Son').getAttribute('aria-pressed'),title:label('Son').title,
  told:prefabFake.sounds.slice(marker),view:ex.playback.sound()};
""")
    assert out["on"]["pressed"] == "true" and out["on"]["sounds"][-1] is False, "the bench really turned the sound on"
    assert out["closed"] is False and out["reopened"] is True
    assert out["pressed"] == "false" and out["title"] == "Activer le son (M)" and out["view"]["on"] is False
    assert out["told"] and all(m is True for m in out["told"]), "the host is told `muted` at the reopening, never `false`"


def test_the_focus_opener_is_kept_only_when_the_stage_fullscreen_really_starts(tmp_path):
    """Rework polish: a refused or merely armed request keeps no opener; the stage fullscreen that starts later gives the focus to « Plein écran »."""

    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const theater=q('.jvx-theater'),fsBtn=q('.jvx-top-actions .jvx-btn');
const row=q('.jvx-row');
const cycle=async(mode)=>{
  fsFake.mode=mode;row.focus();fsBtn.click();await env.advance(50);
  const entered=doc.fullscreenElement===theater;
  env.enterFullscreen(theater);await env.advance(20);   // the fullscreen starts later, by another way (the armed prompt's click)
  env.leaveFullscreen();await env.advance(500);
  return {entered,focusOnButton:doc.activeElement===fsBtn,focusOnRow:doc.activeElement===row};
};
const refused=await cycle('refuse');
const armed=await cycle('arm');fsFake.armed=null;
fsFake.mode='enter';row.focus();fsBtn.click();await env.advance(50);const realEntered=doc.fullscreenElement===theater;
env.leaveFullscreen();await env.advance(50);
return {refused,armed,real:{entered:realEntered,focusOnRow:doc.activeElement===row}};
""")
    for name in ("refused", "armed"):
        assert out[name]["entered"] is False, out
        assert out[name]["focusOnButton"] is True and out[name]["focusOnRow"] is False, f"{name}: no stale opener ({out[name]})"
    assert out["real"] == {"entered": True, "focusOnRow": True}, "a fullscreen that really starts gives the focus back to its opener"


def test_fullscreen_keeps_the_play_state_and_the_transport_hides_while_playing(tmp_path):
    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const theater=q('.jvx-theater');
await ex.playback.play();await env.advance(100);
const before=ex.playback.view();
q('.jvx-top-actions .jvx-btn').click();await env.advance(50);
const inFs=ex.playback.view();
await env.advance(2600);const hidden=theater.getAttribute('data-chrome');
env.pointer(q('.jvx-catch'),'pointermove');const shown=theater.getAttribute('data-chrome');
await env.advance(2600);
ex.playback.pause();await env.advance(50);const pausedChrome=theater.getAttribute('data-chrome');
await env.advance(5000);const pausedLater=theater.getAttribute('data-chrome');
env.leaveFullscreen();await env.advance(50);
return {before:[before.phase,before.frame],inFs:[inFs.phase,inFs.frame],orders:prefabFake.orders,hidden,shown,pausedChrome,pausedLater,
  after:theater.getAttribute('data-chrome'),chrome:ex.playback.chrome()};
""")
    assert out["before"][0] == "playing" and out["inFs"][0] == "playing" and out["inFs"][1] == out["before"][1], "entering changes neither f nor the play state"
    assert out["hidden"] == "hidden" and out["shown"] is None, "hides itself while playing, comes back on a move"
    assert out["pausedChrome"] is None and out["pausedLater"] is None, "paused: stays"
    assert out["after"] is None and out["chrome"]["active"] is False


def test_a_key_from_the_scene_acts_once_only_while_the_focus_is_in_the_stage(tmp_path):
    out = run_ui(tmp_path, VIDEO_WORLD + r"""
const hook=prefabFake.hosts[0].deps.onKey;
q('.jvx-top-actions .jvx-btn').focus();
hook('studio-explorer-preview',' ');await env.advance(50);const unfocused=ex.playback.view().phase;
q('.jvx-stage').focus();
hook('studio-explorer-preview',' ');await env.advance(50);const played=ex.playback.view().phase;
hook('studio-explorer-preview',' ');await env.advance(50);const paused=ex.playback.view().phase;
hook('studio-explorer-preview','ArrowRight');await env.advance(50);const next=ex.playback.view().scene_index;
hook('another-object','ArrowRight');await env.advance(50);const other=ex.playback.view().scene_index;
hook('studio-explorer-preview','m');const sound=ex.playback.sound().on;
q('.jvx-more,[aria-label="Plus de lecture"]').click();await env.advance(10);
const menuOpen=ex.state().menu;q('.jvx-stage').focus();hook('studio-explorer-preview','ArrowRight');await env.advance(50);
return {unfocused,played,paused,next,other,sound,menuOpen,withMenu:ex.playback.view().scene_index};
""")
    assert out["unfocused"] == "paused", "the focus is elsewhere: a key from the scene does nothing"
    assert out["played"] == "playing" and out["paused"] == "paused", "once each"
    assert out["next"] == 1 and out["other"] == 1 and out["sound"] is True
    assert out["menuOpen"] is True and out["withMenu"] == 1, "never while a menu is open"
