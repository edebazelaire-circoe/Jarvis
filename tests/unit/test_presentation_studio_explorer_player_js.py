"""La lecture automatique du Studio : icône lecture / pause, flèches, double flèche gauche, Espace, F, +/- 5 s, plein écran (retour du 2026-10-11).

Même banc que `test_presentation_studio_explorer_view_js.py` (vrai module, faux DOM, Core minuscule). Ce que l'utilisateur doit constater :
la présentation défile d'elle-même dans le grand Studio (liste des variantes à gauche), un seul bouton lecture dont l'icône dit l'état, la flèche
droite passe à la slide suivante, la flèche gauche revient au début de la slide, deux flèches gauches à la suite à la slide d'avant.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_node, run_ui



def test_the_pure_clock_and_key_rules(tmp_path):
    out = run_node(tmp_path, """
const C=require(process.env.JARVIS_EXPLORER_CORE);
return {
  stay:C.autoStep({elapsedMs:3000,dwellMs:8000,index:0,count:3,loop:false}),
  next:C.autoStep({elapsedMs:8000,dwellMs:8000,index:0,count:3,loop:false}),
  end:C.autoStep({elapsedMs:9000,dwellMs:8000,index:2,count:3,loop:false}),
  wrap:C.autoStep({elapsedMs:9000,dwellMs:8000,index:2,count:3,loop:true}),
  single:C.autoStep({elapsedMs:9000,dwellMs:8000,index:0,count:1,loop:true}),
  once:C.leftKeyAction(0,1000),quick:C.leftKeyAction(1000,1400),slow:C.leftKeyAction(1000,2000),
  dwell:[4000,8000,15000,30000].map(C.nextDwell),
};
""")
    assert out["stay"]["action"] == "stay" and out["next"]["action"] == "next" and out["end"]["action"] == "end"
    assert out["wrap"]["action"] == "wrap" and out["single"]["action"] == "end"
    assert (out["once"], out["quick"], out["slow"]) == ("restart", "previous", "restart")
    assert out["dwell"] == [8000, 15000, 30000, 4000]


def test_one_play_button_whose_icon_is_the_state_and_the_slides_advance_by_themselves(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
const title=()=>q('.jvx-scene-title').textContent;
const play=q('.jvx-t-play');
const glyph=()=>play.querySelector('path').getAttribute('d');
const word=play.children[1];
const idle={label:play.getAttribute('aria-label'),pressed:play.getAttribute('aria-pressed'),glyph:glyph(),wordDrawn:!/jvx-sr/.test(word.className),count:qa('.jvx-t-play').length};
const first=title();
play.click();await env.advance(300);
const running={label:play.getAttribute('aria-label'),pressed:play.getAttribute('aria-pressed'),glyph:glyph(),on:ex.state().auto.on};
await env.advance(8500);
const second=title();
await env.advance(8500);
const third=title();
play.click();await env.advance(300);
const paused=ex.state().auto.on;
await env.advance(20000);
return {idle,running,first,second,third,paused,still:title(),buttons:qa('.jvx-transport button').map(b=>b.getAttribute('aria-label')||b.textContent)};
""")
    assert out["idle"] == {"label": "Lire", "pressed": "false", "glyph": "M8 5l11 7-11 7z", "wordDrawn": False, "count": 1}, "a glyph button: the word is read, never drawn"
    assert out["running"] == {"label": "Pause", "pressed": "true", "glyph": "M8 5v14", "on": True}, "playing: the icon is the pause bars"
    assert out["first"] != out["second"] != out["third"], "the slides move on their own, one dwell time each"
    assert out["paused"] is False and out["still"] == out["third"], "paused means paused: it never moves again by itself"
    for wanted in ("Début de la slide", "Reculer de 5 secondes", "Avancer de 5 secondes", "Scène suivante"):
        assert wanted in out["buttons"]
    assert "Quitter le plein écran" in out["buttons"], "the bench opens in fullscreen: the bar button says how to leave it"


def test_keys_right_left_double_left_space_and_f(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
const count=()=>q('.jvx-stage-note > span').textContent;
const stage=q('.jvx-stage');
const log=[count()];
env.key(stage,'ArrowRight');log.push(count());
env.key(stage,'ArrowRight');log.push(count());
const before=ex.state().auto.elapsed_ms;
await env.advance(2000);
env.key(stage,'ArrowLeft');                       /* a single left: the start of THIS slide */
log.push(count());
const afterOne=ex.state().auto.elapsed_ms;
await env.advance(2000);
env.key(stage,'ArrowLeft');env.key(stage,'ArrowLeft');   /* two in a row: the slide before */
log.push(count());
env.key(stage,' ');await env.advance(100);
const spaceOn=ex.state().auto.on;
env.key(stage,' ');await env.advance(100);
const spaceOff=ex.state().auto.on;
const fsBefore=!!doc.fullscreenElement;
env.key(stage,'f');await env.advance(100);
return {log,afterOne,spaceOn,spaceOff,fsBefore,fsAfter:!!doc.fullscreenElement};
""")
    assert out["log"][0].startswith("Scène 1") and out["log"][1].startswith("Scène 2") and out["log"][2].startswith("Scène 3")
    assert out["log"][3].startswith("Scène 3"), "one left stays on the slide (start of the slide)"
    assert out["afterOne"] == 0
    assert out["log"][4].startswith("Scène 2"), "two quick lefts go to the slide before"
    assert out["spaceOn"] is True and out["spaceOff"] is False
    assert out["fsBefore"] is True and out["fsAfter"] is False, "F toggles fullscreen (the bench opened in fullscreen: F leaves it)"


def test_skip_five_seconds_moves_the_clock_and_carries_over_to_the_next_slide(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
const count=()=>q('.jvx-stage-note > span').textContent;
q('.jvx-t-play').click();await env.advance(300);
const forward=q('[aria-label="Avancer de 5 secondes"]'),back=q('[aria-label="Reculer de 5 secondes"]');
env.click(forward);
const a=ex.state().auto.elapsed_ms;
env.click(back);
const b=ex.state().auto.elapsed_ms;
env.click(forward);env.click(forward);   /* 5 + 5 + the clock already running: the dwell time (8 s) is over */
await env.advance(300);
return {a,b,count:count(),elapsed:ex.state().auto.elapsed_ms};
""")
    assert out["a"] >= 5000 and out["b"] < out["a"]
    assert out["count"].startswith("Scène 2") and out["elapsed"] < 2000


def test_the_run_ends_on_the_last_slide_and_can_loop(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
const count=()=>q('.jvx-stage-note > span').textContent;
q('.jvx-t-play').click();
await env.advance(60000);
const ended={on:ex.state().auto.on,count:count()};
q('[aria-label="Plus de lecture"]').click();
qa('button').find(b=>/Recommencer à la fin/.test(b.textContent)).click();
q('.jvx-t-play').click();
await env.advance(30000);
return {ended,looping:ex.state().auto.on,loop:ex.state().auto.loop};
""")
    assert out["ended"]["on"] is False and out["ended"]["count"].startswith("Scène 3") or out["ended"]["on"] is False
    assert out["looping"] is True and out["loop"] is True


def test_open_with_autoplay_starts_the_clock_inside_the_big_studio(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex,result}=await opened({autoplay:true});
await env.advance(500);
return {on:ex.state().auto.on,open:ex.state().open,mode:ex.state().mode,players:world.calls.filter(c=>/playback\\/(start|next)/.test(c.url)).length};
""")
    assert out["open"] is True and out["on"] is True
    assert out["players"] == 0, "no Core run and no small stage window: the Studio plays by itself"
