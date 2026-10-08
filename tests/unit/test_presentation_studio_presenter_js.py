"""The band of a Jarvis-presented run, by node (jarvis-interactive-presentation-studio, Slice 14).

Same bench as the Slice 12 band test (the real module, a DOM double). Pinned here: the speaking indicator, the locked-sequence
progress (step, exact length, a live counter that freezes on pause), the continue button and the interruption note, the stated
reasons of the presenter's failures, and that a run where Jarvis does not speak gets none of it. Real Chrome: see
`test_presentation_studio_presenter_browser.py`.
"""

from __future__ import annotations

from tests.unit.test_presentation_studio_player_js import _node

JARVIS = """
script.state=st({role:'jarvis_presenter',jarvis_speaks:true,mode:'assistant',
  item:Object.assign({},base.item,{presenter:'jarvis',label:'Demo',timing:'locked',interruption:'at_boundary'}),
  presenter:{speaks:true,lines:3,interrupted:false,problem:null,line:'playing',
             sequence:{state:'running',step:2,of:3,elapsed_ms:4200,duration_ms:9000,basis:'speech_started'}},
  speaking:'jarvis',sequence:{sequence_id:'demo',step:2,of:3,duration_ms:9000},owner:'sequence'});
"""


def test_a_jarvis_run_shows_who_presents_that_jarvis_speaks_and_the_sequence_progress(tmp_path):
    out = _node(tmp_path, JARVIS + """
const p=make();p.start();await env.tick();
const b=bandOf();const bar=byClass(b,'jvsp-seqbar');
return {text:textOf(b),voice:byClass(b,'jvsp-voice').getAttribute('data-state'),valuenow:bar.getAttribute('aria-valuenow'),
  valuetext:bar.getAttribute('aria-valuetext'),fill:byClass(b,'jvsp-seqbar').children[0].style.width,skipHidden:btn('Sortir de la').hidden,
  seqHidden:byClass(b,'jvsp-seq').hidden,role:bar.getAttribute('role')};
""")
    for fragment in ("Jarvis présente", "Jarvis parle", "Séquence 2/3", "4,2 s / 9,0 s", "mode réglé sur SIMPLE"):
        assert fragment in out["text"], fragment
    assert out["voice"] == "speaking" and out["role"] == "progressbar" and out["valuenow"] == "47" and out["fill"] == "47%"
    assert "Séquence 2/3" in out["valuetext"] and out["seqHidden"] is False
    assert out["skipHidden"] is False, "the user's escape is on the band while a sequence owns the timeline"


def test_the_sequence_counter_runs_between_polls_and_freezes_while_paused(tmp_path):
    out = _node(tmp_path, JARVIS + """
const p=make();p.start();await env.tick();
const read=()=>byClass(bandOf(),'jvsp-seqtext').textContent;
const first=read();
await run(2000);
const later=read();
script.state=st(Object.assign(JSON.parse(JSON.stringify(script.state)),{phase:'paused',speaking:null,
  presenter:Object.assign({},script.state.presenter,{interrupted:true,sequence:Object.assign({},script.state.presenter.sequence,{elapsed_ms:6000})})}));
await p.refresh();await run(3000);
const frozenA=read();await run(3000);const frozenB=read();
return {first,later,frozenA,frozenB};
""")
    assert out["first"].startswith("Séquence 2/3 · 4,2 s") and out["later"].startswith("Séquence 2/3 · ")
    assert out["later"] != out["first"], "the live counter advances between two reads of Core"
    assert "6,0 s / 9,0 s · en pause" in out["frozenA"] and out["frozenA"] == out["frozenB"]


def test_the_first_words_of_a_sequence_are_waited_for_on_screen(tmp_path):
    out = _node(tmp_path, JARVIS + """
script.state.presenter.sequence={state:'waiting_start',step:0,of:3,elapsed_ms:0,duration_ms:9000,basis:null};
script.state.sequence.step=0;script.state.speaking=null;script.state.presenter.line='pending';
const p=make();p.start();await env.tick();
const b=bandOf();
return {text:textOf(b),voice:byClass(b,'jvsp-voice').getAttribute('data-state')};
""")
    assert "attente du début de la parole" in out["text"] and "Jarvis va parler…" in out["text"] and out["voice"] == "waiting"


def test_an_interrupted_run_says_it_waits_for_continue_and_the_button_is_continue(tmp_path):
    out = _node(tmp_path, JARVIS + """
script.state=st(Object.assign(JSON.parse(JSON.stringify(script.state)),{phase:'paused',speaking:null,sequence:null,owner:'user',
  presenter:{speaks:true,lines:1,interrupted:true,problem:null,line:'interrupted',sequence:null}}));
const p=make();p.start();await env.tick();
const b=bandOf();
const before=btn('Continuer');
await before.click();await settle();
return {text:textOf(b),voice:byClass(b,'jvsp-voice').getAttribute('data-state'),posts:posts(),label:before.textContent,seqHidden:byClass(b,'jvsp-seq').hidden};
""")
    assert "Jarvis se tait (pause)" in out["text"] and "Jarvis attend votre « continuer »" in out["text"]
    assert out["label"] == "Continuer" and out["posts"] == ["resume"] and out["seqHidden"] is True


def test_a_user_presenter_run_gets_no_speaking_indicator_and_keeps_reprendre(tmp_path):
    out = _node(tmp_path, """
script.state=st({phase:'paused'});
const p=make();p.start();await env.tick();
const b=bandOf();
return {voiceHidden:byClass(b,'jvsp-voice').hidden,seqHidden:byClass(b,'jvsp-seq').hidden,pause:btn('Reprendre')!==undefined,
  text:textOf(b)};
""")
    assert out["voiceHidden"] is True and out["seqHidden"] is True and out["pause"] is True
    assert "Jarvis parle" not in out["text"]


def test_the_presenters_failures_are_said_with_their_reason_and_a_way_out(tmp_path):
    out = _node(tmp_path, JARVIS + """
const codes=['announce_refused','announce_failed','speech_not_started','speech_stalled','speech_failed','speech_obsolete',
             'speech_unconfirmed','line_invalid','presenter_crashed'];
const seen={};
const p=make();p.start();await env.tick();
for(const code of codes){
  p.adopt(st(Object.assign(JSON.parse(JSON.stringify(script.state)),{phase:'paused',sequence:null,speaking:null,problems:[code]})));
  seen[code]={text:textOf(bandOf()),kind:bandOf().getAttribute('data-kind')};
}
return {seen,problems:P.PROBLEMS};
""")
    for code, shown in out["seen"].items():
        assert "Problème :" not in shown["text"], f"{code} must have its own words"
        assert shown["kind"] == "problem"
        assert out["problems"][code] in shown["text"]
    assert "Continuer" in out["problems"]["speech_not_started"] and "retenue par le mode" in out["problems"]["speech_not_started"]


def test_the_skip_button_and_the_s_key_send_the_users_escape_only_while_a_sequence_owns_the_timeline(tmp_path):
    out = _node(tmp_path, JARVIS + """
const p=make();p.start();await env.tick();
await btn('Sortir de la').click();await settle();
key('s');await settle();
script.state=st();await p.refresh();
key('s');await settle();
return {posts:posts()};
""")
    assert out["posts"] == ["skip_sequence", "skip_sequence"], "the third press does nothing: no sequence owns the timeline"


def test_the_band_module_never_reads_a_script_field(tmp_path):
    """Core sends states, counters and codes: there is no `text` / `note` of the score for the band to read or show."""

    from tests.unit.test_presentation_studio_player_js import MODULE  # noqa: PLC0415
    import re  # noqa: PLC0415
    code = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    for forbidden in (r"(?<![\w.])item\.(text|note)", r"step\.text", r"view\.(text|note)", r"line\.text"):
        assert not re.search(forbidden, code), forbidden
