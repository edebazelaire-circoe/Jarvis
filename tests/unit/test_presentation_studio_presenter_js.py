"""The presenter strip of a run in Variants, by node (jarvis-interactive-presentation-studio, Slice 14; native-studio-playback-fix Slice 09).

The floating band that showed a run is retired (Slice 09): Variants shows the run, and its presenter strip is computed by the pure
`JarvisVariantsRun.presenterModel` (`control_center_presentation_studio_run.js`), drawn by the explorer (`test_variants_run_js.py`).
Pinned here, with the real module: who presents and the phase; « Scène n/N · élément i/M »; the next item and its cue phrase; the item's
time labelled as SCORE time against its soft target (never media time, § 5); the speaking indicator of a Jarvis run; the locked-sequence
progress (step, exact length); « Continuer » and the interruption note; the stated reasons of the presenter's failures; the follower
state; the page-wait sentence; that a run where Jarvis does not speak gets none of Jarvis's lines; the § 4.15 presenter column of keys;
and that neither module ever reads a script field.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
RUN_JS = RUNTIME / "control_center_presentation_studio_run.js"
PLAYER_JS = RUNTIME / "control_center_presentation_studio_player.js"

PRELUDE = r"""
const R=require(process.env.JARVIS_RUN_JS);
const base={phase:'playing',running:true,run_id:'r1',role:'user_presenter',jarvis_speaks:false,position:{index:2,of:14},
  scene:{scene_id:'pss_1',title:'Chiffres',number:2,of:12},item:{item_id:'psi_2',label:'Les marges',presenter:'user'},
  elapsed:{item_ms:12000,item_target_ms:30000},problems:[],notices:[],pending:null,presentation_id:'pst_1',variant_id:'psv_1',
  next:{item_label:'Conclusion',scene_title:'Fin',cue:{label:'Suite',armable:true,armed:true,phrases:['passons a la suite']}},
  detour:null,sequence:null,art_direction:'checked'};
const st=(extra)=>Object.assign(JSON.parse(JSON.stringify(base)),extra||{});
const JARVIS=st({role:'jarvis_presenter',jarvis_speaks:true,item:{item_id:'psi_2',label:'Demo',presenter:'jarvis'},
  presenter:{speaks:true,lines:3,interrupted:false,problem:null,line:'playing',
    sequence:{state:'running',step:2,of:3,elapsed_ms:4200,duration_ms:9000,basis:'speech_started'}},
  speaking:'jarvis',sequence:{sequence_id:'demo',step:2,of:3,duration_ms:9000},owner:'sequence'});
"""


def _node(tmp_path: Path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    index = len(list(tmp_path.glob("pr-js-*.cjs")))
    script = tmp_path / f"pr-js-{index}.cjs"
    script.write_text(PRELUDE + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),"
                      "e=>{console.error(e&&e.stack||e);process.exit(1)});\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60,
                          env={**os.environ, "JARVIS_RUN_JS": str(RUN_JS)})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_strip_says_who_presents_where_we_are_what_comes_next_and_the_score_time(tmp_path):
    out = _node(tmp_path, """
const m=R.presenterModel(st(),12000);
const over=R.presenterModel(st(),31000);
const idle=R.presenterModel({phase:'idle',running:false},0);
return {m,over:[over.over,over.clock],idle};
""")
    m = out["m"]
    assert (m["role"], m["phase"], m["where"], m["sceneTitle"]) == ("Vous présentez", "En cours", "Scène 2/12 · élément 2/14", "Chiffres")
    assert m["item"] == "Les marges · vous" and m["next"] == "Ensuite : Conclusion — dites « passons a la suite »"
    assert m["clock"] == "Partition 00:12 / 00:30" and "temps de partition" in m["clockTitle"].lower() and "jamais le temps de la vidéo" in m["clockTitle"]
    assert m["pause"] == {"label": "Pause", "command": "pause", "disabled": False} and m["skip"] is False and m["voice"] is None
    assert m["kind"] == "ok" and m["lines"] == [] and m["sceneId"] == "pss_1" and m["variantId"] == "psv_1"
    assert out["over"] == [True, "Partition 00:31 / 00:30"]
    assert out["idle"] == {"active": False}


def test_a_jarvis_run_shows_that_jarvis_speaks_and_the_sequence_progress(tmp_path):
    out = _node(tmp_path, """
const m=R.presenterModel(JARVIS,5000);
const waiting=R.presenterModel(Object.assign({},JARVIS,{speaking:null,presenter:Object.assign({},JARVIS.presenter,{line:'pending',
  sequence:{state:'waiting_start',step:0,of:3,elapsed_ms:0,duration_ms:9000}})}),0);
const paused=R.presenterModel(Object.assign({},JARVIS,{phase:'paused',speaking:null,presenter:Object.assign({},JARVIS.presenter,{interrupted:true})}),0);
return {m,waiting:[waiting.voice,waiting.sequence],paused:[paused.voice,paused.pause.label,paused.lines,paused.sequence.text]};
""")
    m = out["m"]
    assert m["role"] == "Jarvis présente" and m["voice"] == {"state": "speaking", "text": "Jarvis parle"} and m["skip"] is True
    assert m["sequence"] == {"text": "Séquence 2/3 · 4,2 s / 9,0 s", "percent": 47}
    assert any("mode réglé sur SIMPLE" in line for line in m["lines"])
    assert out["waiting"][0] == {"state": "waiting", "text": "Jarvis va parler…"}
    assert out["waiting"][1]["text"] == "Séquence verrouillée : attente du début de la parole…"
    voice, label, lines, seq = out["paused"]
    assert voice == {"state": "paused", "text": "Jarvis se tait (pause)"} and label == "Continuer" and seq.endswith("· en pause")
    assert any("attend votre « continuer »" in line for line in lines), "an interrupted run says it never restarts by itself"


def test_a_user_run_gets_no_jarvis_lines_and_keeps_reprendre(tmp_path):
    out = _node(tmp_path, """
const m=R.presenterModel(st({phase:'paused'}),0);
const pending=R.presenterModel(st({pending:'pause'}),0);
return {voice:m.voice,label:m.pause.label,command:m.pause.command,lines:m.lines,pending:[pending.phase,pending.pause.label,pending.pause.disabled,pending.lines]};
""")
    assert out["voice"] is None and out["label"] == "Reprendre" and out["command"] == "resume" and out["lines"] == []
    phase, label, disabled, lines = out["pending"]
    assert phase == "En cours · pause demandée" and label == "Pause demandée…" and disabled is True
    assert lines and "Pause demandée" in lines[0]


def test_the_presenters_failures_the_follower_and_a_silent_page_are_said_with_a_way_out(tmp_path):
    out = _node(tmp_path, """
const failures=R.presenterModel(st({problems:['speech_not_started','stage_timeout'],notices:['timeline_unresolved','some_new_code']}),0);
const absent=R.presenterModel(st({follower:'absent'}),0);
const waiting=R.presenterModel(st({follower:'waiting'}),0);
const silent=R.presenterModel(st({page_wait:{seq:3,started:true,waited_ms:16000}}),0);
const unresolved=R.presenterModel(st({page_wait:{seq:null,started:false,waited_ms:17000,reason:'timeline_unresolved'}}),0);
const lost=R.presenterModel(st(),0,{linkLostMs:9000});
return {failures:[failures.kind,failures.lines],absent:[absent.kind,absent.lines],waiting:waiting.lines,silent:silent.lines,
  unresolved:unresolved.lines,lost:[lost.kind,lost.lines]};
""")
    kind, lines = out["failures"]
    assert kind == "problem" and any("La voix n'a pas commencé la ligne à temps" in l for l in lines)
    assert any("« Reprendre » réessaie, « Arrêter » arrête" in l for l in lines), "the stuck show (Slice 09) is said with its way out"
    assert any("se joue une fois depuis sa première image" in l for l in lines) and "Problème : some_new_code" in lines
    assert out["absent"][0] == "problem" and "Suivi vocal indisponible" in out["absent"][1][0]
    assert out["waiting"] == ["Suivi vocal : connexion…"]
    assert "rien n'a été signalé depuis 16 s" in out["silent"][0] and "jamais sautée" in out["silent"][0]
    assert "la scène est tenue depuis 17 s (jamais coupée)" in out["unresolved"][0]
    assert out["lost"][0] == "problem" and "Core ne répond plus depuis 9 s" in out["lost"][1][0]


def test_the_presenter_column_of_the_key_map(tmp_path):
    out = _node(tmp_path, """
const run=st(),paused=st({phase:'paused'}),seq=Object.assign({},JARVIS);
const k=(a,v)=>R.keyCommand(a,v);
return {toggle:[k('toggle',run),k('toggle',paused)],next:k('next',run),previous:k('previous',run),home:k('home',run),end:k('end',run),
  step:k('step_back',run),skip:[k('skip',seq),k('skip',run)],fullscreen:k('fullscreen',run),sound:k('sound',run),idle:k('toggle',{phase:'idle'})};
""")
    assert out["toggle"] == [{"verb": "pause", "body": {}}, {"verb": "resume", "body": {}}]
    assert out["next"] == {"verb": "next", "body": {}} and out["previous"] == {"verb": "previous", "body": {}}
    assert out["home"] == {"verb": "goto", "body": {"position": 1}} and out["end"] == {"verb": "goto", "body": {"position": 14}}
    assert "partition mène" in out["step"]["said"]
    assert out["skip"] == [{"verb": "skip_sequence", "body": {}}, {"said": "Aucune séquence verrouillée n'est en cours."}]
    assert out["fullscreen"] is None and out["sound"] is None and out["idle"] is None, "F and M stay the Variants controls"


def test_the_strip_and_the_client_never_read_a_script_field():
    """Core sends states, counters and codes: there is no `text` / `note` of the score for the strip to read or show."""

    for module in (RUN_JS, PLAYER_JS):
        code = re.sub(r"/\*.*?\*/", "", module.read_text(encoding="utf-8"), flags=re.S)
        for forbidden in (r"(?<![\w.])item\.(text|note)", r"step\.text", r"view\.(text|note)", r"line\.text", r"innerHTML"):
            assert not re.search(forbidden, code), (module.name, forbidden)
