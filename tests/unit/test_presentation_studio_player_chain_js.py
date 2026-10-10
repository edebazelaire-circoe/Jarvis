"""La bande de lecture et la lecture continue (handoff jarvis-remotion-presentation-integration, Slice 23), exécutées par node.

Même banc que `test_presentation_studio_player_js.py` (le vrai module, seuls le DOM, l'horloge et le réseau sont des doubles). Prouvé : deux
boutons discrets jouent la slide ou tout et le bouton actif rend la main ; les faits du suiveur (segment commencé, image d'arrêt atteinte)
partent vers Core sans commande en vol ni avis, et l'état que Core rend est adopté tout de suite ; la scène qui suit est lue une fois par
annonce et donnée à la fenêtre avec la ligne de temps.
Contrat : `docs/presentation-studio.md` > *Remotion timeline bridge* > *Chained playback*.
"""

from __future__ import annotations

import json

from tests.unit.test_presentation_studio_player_js import TIMELINE, _node

CHAIN = {**TIMELINE, "auto": True, "prefab": "presentation-studio.p.s1@1"}


def test_two_discreet_buttons_play_the_slide_or_everything_and_the_active_one_hands_the_run_back(tmp_path):
    out = _node(tmp_path, """
const p=make();p.start();await env.tick();
const pressed=()=>[btn('▶ Slide').getAttribute('aria-pressed'),btn('▶▶ Tout').getAttribute('aria-pressed')];
const before=pressed();
btn('▶ Slide').click();await settle();
script.state=st({scope:'scene'});p.adopt(script.state);
const scene=pressed();
btn('▶ Slide').click();await settle();                     // the active one again: hands the run back
script.state=st({scope:'all'});p.adopt(script.state);
const all=pressed();
btn('▶▶ Tout').click();await settle();
btn('▶ Slide').click();await settle();
script.state=st({jarvis_speaks:true});p.adopt(script.state);
return {before,scene,all,posts:posts(),hiddenWhenJarvisSpeaks:[btn('▶ Slide').hidden,btn('▶▶ Tout').hidden],
  texts:[btn('▶ Slide').textContent,btn('▶▶ Tout').textContent,btn('▶ Slide').title.length>10]};
""")
    assert out["before"] == ["false", "false"] and out["scene"] == ["true", "false"] and out["all"] == ["false", "true"]
    assert out["posts"] == ['play{"scope":"scene"}', 'play{"scope":"manual"}', 'play{"scope":"manual"}', 'play{"scope":"scene"}'], out["posts"]
    assert out["hiddenWhenJarvisSpeaks"] == [True, True], "a run paced by Jarvis speech has no chained play"


def test_the_followers_segment_facts_go_to_core_without_a_command_in_flight_or_a_notice(tmp_path):
    out = _node(tmp_path, f"""
const p=make();p.start();await env.tick();
script.state=st({{scope:'all',timeline:{json.dumps(CHAIN)}}});
env.hook=rec=>{{
  if(rec.method==='GET')return answer(200,{{state:script.state}});
  return answer(200,{{status:'applied',command:'advance',state:st({{scope:'all',position:{{index:3,of:14}}}})}});
}};
p.adopt(script.state);
await p.onSegment({{detail:{{object_id:'studio-stage-r1',seq:2,event:'started',scene_id:'pss_1'}}}});
await p.onSegment({{detail:{{object_id:'studio-stage-r1',seq:2,event:'done',scene_id:'pss_1'}}}});
await settle();
p.onSegment({{detail:{{seq:'2',event:'done'}}}});                 // malformed: ignored
p.onSegment({{detail:{{seq:2,event:'ok'}}}});
p.onSegment({{}});
await settle();
return {{posts:posts(),inflight:p.state().inflight,note:textOf(bandOf()).includes('advance'),position:p.view().position,
  notice:p.state().notice,errors:consoleErrors}};
""")
    assert out["posts"] == ['advance{"seq":2,"event":"started"}', 'advance{"seq":2,"event":"done"}']
    assert out["inflight"] is None and out["note"] is False and out["notice"] is None and out["errors"] == []
    assert out["position"] == {"index": 3, "of": 14}, "the state Core answers is adopted at once: the next segment waits for no poll"


def test_a_report_core_cannot_apply_is_a_console_line_never_a_notice(tmp_path):
    out = _node(tmp_path, f"""
script.state=st({{scope:'all',timeline:{json.dumps(CHAIN)}}});
const p=make();p.start();await env.tick();
env.hook=rec=>rec.method==='GET'?answer(200,{{state:script.state}}):answer(409,{{status:'refused',reason:'not_running',state:script.state}});
await p.onSegment({{detail:{{seq:2,event:'done'}}}});
env.hook=rec=>{{if(rec.method==='GET')return answer(200,{{state:script.state}});throw new Error('down')}};
await p.onSegment({{detail:{{seq:2,event:'done'}}}});
await settle();
return {{notice:p.state().notice,failed:p.stats().failed,text:textOf(bandOf())}};
""")
    assert out["notice"] is None and "impossible" not in out["text"] and "refus" not in out["text"].lower()


def test_the_scene_to_come_is_read_once_per_scene_and_given_to_the_window_with_the_timeline(tmp_path):
    hint = {"scene_id": "pss_2", "title": "Deux", "prefab": {"id": "presentation-studio.p.s2", "version": 1, "props": {"title": "x"}, "data": {}}}
    out = _node(tmp_path, f"""
const events=[];win.dispatchEvent=e=>{{events.push({{type:e.type,detail:e.detail}});return true}};
win.CustomEvent=class{{constructor(type,init){{this.type=type;this.detail=init&&init.detail}}}};
env.hook=rec=>rec.method==='GET'&&rec.url.endsWith('/preload')?answer(200,{{preload:{json.dumps(hint)}}}):rec.method==='GET'?answer(200,{{state:script.state}}):answer(200,{{status:'applied',state:script.state}});
const ahead={{scene_id:'pss_2',prefab:'presentation-studio.p.s2@1',rev:4}};
script.state=st({{scope:'all',timeline:{json.dumps(CHAIN)},next_scene:ahead}});
const p=make();
p.adopt(script.state);await settle();
p.adopt(script.state);p.adopt(script.state);await settle();
const gets=env.posts.filter(x=>x.method==='GET'&&x.url.endsWith('/preload')).length;
script.state=st({{scope:'all',timeline:{json.dumps(CHAIN)},next_scene:Object.assign({{}},ahead,{{rev:5}})}});   // the score was edited: read again
p.adopt(script.state);await settle();
const gets2=env.posts.filter(x=>x.method==='GET'&&x.url.endsWith('/preload')).length;
const told=events.filter(e=>e.type==='jarvis:studio-timeline').map(e=>e.detail);
return {{gets,gets2,withPreload:told.filter(t=>t.preload).length,last:told[told.length-1].preload,first:told[0].preload}};
""")
    assert out["gets"] == 1 and out["gets2"] == 2, "once per announced scene, again when its revision moves"
    assert out["first"] is None and out["last"]["scene_id"] == "pss_2" and out["last"]["prefab"]["id"] == "presentation-studio.p.s2"
    assert out["withPreload"] >= 1
