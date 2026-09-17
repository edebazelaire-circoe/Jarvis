"""Logique pure de la chronologie de conversation (Slice 05), exécutée par node.

Le module servi à la page (`jarvis/runtime/control_center_timeline.js`) est
exécuté tel quel : appariement des spans comparé au domaine Python
(`reconstruct_conversation`) sur le fixture doré et sur les cas d'anomalie,
lanes, fusion des messages dupliqués, géométrie et empilement, fenêtre
virtualisée sur 5 000 événements, machine d'état hydratation + long-poll avec
un `fetch` simulé, erreurs, modèles de statut / détail / trace et rendu
accessible d'une entrée. Contrat : `docs/conversation-events.md`.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import random
import shutil
import subprocess

import pytest

from jarvis.domain.conversation_events import (
    SPAN_OPENER, ConversationEventType as T, decode_conversation_event, encode_conversation_event, event_actor,
    event_shape, event_visibility, reconstruct_conversation,
)
from tests.fakes.conversation_events import BASE, make_event

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_timeline.js"
FIXTURE = ROOT / "tests" / "fixtures" / "conversation_events" / "overlapping_conversation.json"


def run_node(tmp_path: Path, source: str, data: object = None, *, tz: str = "UTC") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_file = tmp_path / "timeline-data.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "timeline-test.cjs"
    script.write_text(
        f"const TL=require({json.dumps(str(MODULE))});\n"
        f"const DATA=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const tick=()=>new Promise(r=>setImmediate(r));\n"
        "const until=async(test,limit=2000)=>{for(let i=0;i<limit;i++){if(test())return;await tick()}throw new Error('until: condition never met')};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
        env={**os.environ, "TZ": tz},
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fixture_payloads() -> list[dict]:
    return [row["event"] for row in fixture()["events"]]


def python_rows(events, include_diagnostic: bool = True) -> list[dict]:
    fmt = lambda v: None if v is None else v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.microsecond // 1000:03d}Z"
    return [{"item_id": i.item_id, "actor": i.actor.value, "event_type": i.event_type.value, "status": i.status,
             "visibility": i.visibility.value, "started_at": fmt(i.started_at), "ended_at": fmt(i.ended_at),
             "text": i.text, "span_id": i.span_id, "event_ids": list(i.event_ids), "anomalies": list(i.anomalies)}
            for i in reconstruct_conversation(events, include_diagnostic=include_diagnostic)]


JS_ROWS = """
const rows=items=>items.map(i=>({item_id:i.item_id,actor:i.actor,event_type:i.event_type,status:i.status,visibility:i.visibility,
  started_at:i.started_at===null?null:new Date(i.started_at).toISOString(),ended_at:i.ended_at===null?null:new Date(i.ended_at).toISOString(),
  text:i.text,span_id:i.span_id,event_ids:i.event_ids,anomalies:i.anomalies}));
"""


# ------------------------------------------------------------------ contract

def test_the_event_table_mirrors_the_python_contract(tmp_path):
    result = run_node(tmp_path, "out({specs:TL.SPECS,opener:TL.SPAN_OPENER})")
    shapes = {"instant": "instant", "span_open": "open", "span_close": "close"}
    expected = {t.value: [event_actor(t).value, shapes[event_shape(t).value], event_visibility(t).value] for t in T}
    assert result["specs"] == expected
    assert result["opener"] == {close.value: opener.value for close, opener in SPAN_OPENER.items()}


def test_reconstruction_matches_python_on_the_shuffled_golden_fixture(tmp_path):
    payloads = fixture_payloads()
    shuffled = payloads + payloads[:6]
    random.Random(11).shuffle(shuffled)
    result = run_node(tmp_path, JS_ROWS + """
      const items=TL.reconstruct(DATA.events);
      out({all:rows(items),pub:rows(TL.filterItems(items,'public')),asRows:items.map(TL.toRow)});
    """, {"events": shuffled})
    events = [decode_conversation_event(p) for p in payloads]
    assert result["all"] == python_rows(events)
    assert result["pub"] == python_rows(events, include_diagnostic=False)
    document = fixture()
    assert result["asRows"] == document["expected_timeline"]
    assert [r for r, i in zip(result["asRows"], result["all"]) if i["visibility"] == "public"] == document["expected_public_transcript"]


def anomaly_cases():
    ids = dict(span_id="s-1", speech_id="s-1", correlation_id="c-1")
    voice = "voice.speech_scheduler"
    opened = make_event(T.MOUTH_SPEECH_STARTED, "open-a", producer=voice, ms=10, **ids)
    later_open = make_event(T.MOUTH_SPEECH_STARTED, "open-b", producer=voice, ms=20, **ids)
    completed = make_event(T.MOUTH_SPEECH_COMPLETED, "close-a", producer=voice, ms=500, **ids)
    interrupted = make_event(T.MOUTH_SPEECH_INTERRUPTED, "close-b", producer=voice, ms=600, attributes={"played_ms": 300}, **ids)
    early_close = make_event(T.MOUTH_SPEECH_COMPLETED, "close-early", producer=voice, ms=5, **ids)
    failed = make_event(T.MOUTH_SPEECH_FAILED, "failed", producer=voice, ms=40, attributes={"code": "speech_speak_failed"}, **ids)
    lone_expired = make_event(T.MOUTH_SPEECH_EXPIRED, "expired", producer=voice, ms=900,
                              span_id="s-9", speech_id="s-9", correlation_id="c-9")
    lone_subagent = make_event(T.SUBAGENT_FAILED, "t-1", producer="control_center.agent_tasks", ms=900,
                               started_at=BASE, span_id="t-1", task_id="t-1", correlation_id=None)
    open_only = make_event(T.SUBAGENT_STARTED, "t-2", producer="control_center.agent_tasks", ms=50,
                           span_id="t-2", task_id="t-2", correlation_id=None)
    return {
        "duplicate_closes": [interrupted, opened, completed],
        "duplicate_opens": [later_open, opened],
        "close_before_open": [opened, early_close],
        "conflict_on_extra": [opened, later_open, replace(later_open, content="Autre.")],
        "conflict_on_instant": [make_event(T.SYSTEM_FAILURE, "f"), replace(make_event(T.SYSTEM_FAILURE, "f"), attributes={"code": "x"})],
        "failed_close": [opened, failed],
        "lone_closes": [lone_expired, lone_subagent, open_only, failed],
    }


@pytest.mark.parametrize("case", sorted(anomaly_cases()))
def test_reconstruction_anomalies_match_python(tmp_path, case):
    events = anomaly_cases()[case]
    result = run_node(tmp_path, JS_ROWS + """
      const items=TL.reconstruct(DATA.events);
      out({all:rows(items),pub:rows(TL.filterItems(items,'public'))});
    """, {"events": [encode_conversation_event(e) for e in events]})
    assert result["all"] == python_rows(events)
    assert result["pub"] == python_rows(events, include_diagnostic=False)


def test_reconstruction_refuses_mixed_conversations_like_python(tmp_path):
    result = run_node(tmp_path, """
      const errors=[];
      try{TL.reconstruct(DATA.events)}catch(e){errors.push(e.message)}
      try{TL.reconstruct([{nope:true}])}catch(e){errors.push(e.message)}
      out({errors,empty:TL.reconstruct([])});
    """, {"events": [encode_conversation_event(make_event(T.SYSTEM_FAILURE, "a")),
                     encode_conversation_event(make_event(T.SYSTEM_FAILURE, "b", conversation_id="conv-b"))]})
    assert "several conversations" in result["errors"][0]
    assert "canonical event objects only" in result["errors"][1]
    assert result["empty"] == []


# ----------------------------------------------------------- lanes, collapse

def test_lanes_follow_the_actor_and_tools_follow_their_producer(tmp_path):
    events = [
        make_event(T.TOOL_CALL_STARTED, "voice-tool", producer="voice.realtime_audio", correlation_id=None,
                   attributes={"tool_name": "get_time", "arguments_redacted": True}),
        make_event(T.TOOL_CALL_STARTED, "core-tool", producer="core.tools", correlation_id=None, ms=1),
        make_event(T.SYSTEM_FAILURE, "voice-fail", producer="voice.realtime_audio", ms=2),
        make_event(T.SYSTEM_FAILURE, "core-fail", producer="core.brain_service", ms=3),
    ]
    result = run_node(tmp_path, """
      const fx=TL.reconstruct(DATA.fixture),extra=TL.reconstruct(DATA.extra);
      out({fixture:fx.map(i=>[i.event_type,TL.laneOf(i),TL.entryKind(i)]),extra:extra.map(i=>[i.producer,TL.laneOf(i),TL.displayText(i)]),
        lanes:TL.LANES.map(l=>l.id)});
    """, {"fixture": fixture_payloads(), "extra": [encode_conversation_event(e) for e in events]})
    assert result["lanes"] == ["user", "mouth", "brain", "subagent"]
    lanes = {(t, lane, kind) for t, lane, kind in result["fixture"]}
    assert ("user.transcript.accepted", "user", "card") in lanes
    assert ("mouth.speech.started", "mouth", "card") in lanes
    assert ("brain.work.started", "brain", "bar") in lanes
    assert ("brain.message.published", "brain", "card") in lanes
    assert ("subagent.started", "subagent", "block") in lanes
    assert ("tool.call.started", "mouth", "bar") in lanes  # voice.realtime_audio tool
    assert ("brain.turn.accepted", "brain", "dot") in lanes
    assert ("mouth.speech.queued", "mouth", "dot") in lanes
    assert ("system.failure", "brain", "failure") not in lanes  # fixture has none; see extra
    assert result["extra"] == [["voice.realtime_audio", "mouth", "Outil get_time"], ["core.tools", "brain", "Outil inconnu"],
                               ["voice.realtime_audio", "mouth", "Échec système"], ["core.brain_service", "brain", "Échec système"]]


def test_identical_consecutive_brain_messages_collapse_per_correlation(tmp_path):
    def message(source, ms, text, correlation="corr-1"):
        return make_event(T.BRAIN_MESSAGE_PUBLISHED, source, producer="core.brain_outcomes", ms=ms, content=text,
                          correlation_id=correlation)
    events = [
        message("speech-result", 0, "Les tests passent."),
        message("turn-result", 10, "Les tests passent."),  # collapsed into the first
        message("other-text", 20, "Autre chose."),
        message("again", 30, "Les tests passent."),  # previous message of corr-1 differs: kept
        message("other-corr", 40, "Autre chose.", correlation="corr-2"),  # other correlation: kept
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "user", producer="core.voice_admission", ms=5, correlation_id="corr-1"),
    ]
    result = run_node(tmp_path, """
      const items=TL.collapseMessages(TL.reconstruct(DATA.events));
      out(items.map(i=>({type:i.event_type,text:i.text,collapsed:i.collapsed.map(c=>c.item_id),events:i.events.map(e=>e.event_id)})));
    """, {"events": [encode_conversation_event(e) for e in events]})
    messages = [r for r in result if r["type"] == "brain.message.published"]
    assert [m["text"] for m in messages] == ["Les tests passent.", "Autre chose.", "Les tests passent.", "Autre chose."]
    assert messages[0]["collapsed"] == [events[1].event_id]
    assert messages[0]["events"] == [events[0].event_id, events[1].event_id]
    assert all(m["collapsed"] == [] for m in messages[1:])
    assert len(result) == 5


# ------------------------------------------------------------------ geometry

def test_layout_keeps_overlaps_visible_across_lanes_and_packs_them_within_a_lane(tmp_path):
    parallel = [
        make_event(T.SUBAGENT_STARTED, "p1", producer="control_center.agent_tasks", ms=0, span_id="p1", task_id="p1"),
        make_event(T.SUBAGENT_STARTED, "p2", producer="control_center.agent_tasks", ms=500, span_id="p2", task_id="p2"),
        make_event(T.SUBAGENT_FINISHED, "p1-end", producer="control_center.agent_tasks", ms=4000, span_id="p1", task_id="p1"),
        make_event(T.SUBAGENT_FINISHED, "p2-end", producer="control_center.agent_tasks", ms=3000, span_id="p2", task_id="p2"),
        make_event(T.SUBAGENT_STARTED, "p3", producer="control_center.agent_tasks", ms=5000, span_id="p3", task_id="p3"),
        make_event(T.SUBAGENT_FINISHED, "p3-end", producer="control_center.agent_tasks", ms=5500, span_id="p3", task_id="p3"),
        # ten minutes of silence, then one user turn
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "late", producer="core.voice_admission", ms=605_500),
    ]
    result = run_node(tmp_path, """
      const byKey=(model)=>Object.fromEntries(model.entries.map(e=>[e.item.span_id||e.item.event_type,e]));
      const fx=TL.layout(TL.reconstruct(DATA.fixture),{width:1200,pxPerSecond:40});
      const f=byKey(fx),lane=id=>fx.lanes.find(l=>l.id===id);
      const barge=fx.entries.find(e=>e.item.text&&e.item.text.startsWith('Attends'));
      const p=TL.layout(TL.reconstruct(DATA.parallel),{width:1200,pxPerSecond:40});
      const pk=byKey(p);
      const ys=[0,1000,4000,5500,300000,605500].map(ms=>p.toY(Date.parse(DATA.base)+ms));
      const work=f['work-tests'],tool=f['call-1'],dot=fx.entries.find(e=>e.item.event_type==='brain.turn.accepted'),brain=lane('brain'),mouth=lane('mouth');
      out({
        ack:[f['speech-ack-1'].lane,f['speech-ack-1'].kind,f['speech-ack-1'].ty,f['speech-ack-1'].yEnd,f['speech-ack-1'].item.status],
        barge:[barge.lane,barge.ty],
        sub:[f['task-7'].lane,f['task-7'].kind,f['task-7'].ty,f['task-7'].yEnd],work:[work.lane,work.kind,work.ty,work.yEnd],
        second:[f['speech-2'].ty,f['speech-2'].yEnd],open:[f['speech-3'].open,f['speech-3'].yEnd===f['speech-3'].ty],
        rails:{workRight:work.x+work.w<=brain.x+brain.width&&work.x>=brain.textRight,workW:work.w,
          toolRight:tool.x>=mouth.textRight&&tool.x+tool.w<=mouth.x+mouth.width,toolKind:tool.kind,
          dotLeft:dot.x>=brain.x&&dot.x+dot.w<=brain.x+brain.textLeft,dotKind:dot.kind},
        pps:(f['speech-2'].yEnd-f['speech-2'].ty),
        cols:[[pk.p1.col,pk.p1.cols],[pk.p2.col,pk.p2.cols],[pk.p3.col,pk.p3.cols]],
        breaks:p.breaks.map(b=>[b.durationMs,b.y1-b.y0]),ys,height:p.height,
        live:TL.layout(TL.reconstruct(DATA.fixture),{width:1200,pxPerSecond:40,now:Date.parse('2026-09-16T10:00:12.000Z')}).entries.find(e=>e.item.span_id==='speech-3').yEnd,
        lastPoint:fx.toY(Date.parse('2026-09-16T10:00:09.500Z')),
      });
    """, {"fixture": fixture_payloads(), "parallel": [encode_conversation_event(e) for e in parallel],
          "base": BASE.strftime("%Y-%m-%dT%H:%M:%S.000Z")})
    ack_lane, ack_kind, ack_y0, ack_end, ack_status = result["ack"]
    assert (ack_lane, ack_kind, ack_status) == ("mouth", "card", "interrupted")
    barge_lane, barge_y = result["barge"]
    assert barge_lane == "user" and ack_y0 < barge_y < ack_end  # the barge-in lands inside the speech it interrupts
    sub_lane, sub_kind, sub_y0, sub_end = result["sub"]
    work_lane, work_kind, work_y0, work_end = result["work"]
    assert (sub_lane, sub_kind, work_lane, work_kind) == ("subagent", "block", "brain", "bar")
    assert work_y0 <= sub_y0 and sub_end <= work_end
    assert sub_y0 < ack_end  # the interrupted speech overlaps the sub-agent start
    assert sub_y0 < result["second"][0] < result["second"][1] < sub_end
    assert result["open"] == [True, True]
    assert result["live"] > result["lastPoint"]  # an open span grows to "now"
    rails = result["rails"]
    assert rails == {"workRight": True, "workW": 14, "toolRight": True, "toolKind": "bar", "dotLeft": True, "dotKind": "dot"}
    assert result["pps"] == pytest.approx(44.0)  # 1.1 s at 40 px/s, proportional
    assert result["cols"] == [[0, 2], [1, 2], [0, 1]]
    assert result["breaks"] == [[600_000, 44]]
    assert result["ys"] == sorted(result["ys"]) and result["height"] < 800


def test_public_text_is_never_clamped_and_every_card_fits_its_final_column(tmp_path):
    long_text = ("Jarvis, relis les journaux du Control Center depuis ce matin, compare-les avec ceux d'hier "
                 "et dis-moi quelles erreurs sont nouvelles, en commençant par les plus fréquentes. ") * 2
    events = [make_event(T.USER_TRANSCRIPT_ACCEPTED, f"u{i}", producer="core.voice_admission", ms=i * 300,
                         content=long_text[: 60 + i * 70], correlation_id=f"c{i}") for i in range(4)]
    events += [
        make_event(T.MOUTH_SPEECH_STARTED, "s1", producer="voice.speech_scheduler", ms=100, content=long_text,
                   span_id="s1", speech_id="s1", correlation_id="c0"),
        make_event(T.MOUTH_SPEECH_INTERRUPTED, "s1-end", producer="voice.speech_scheduler", ms=900,
                   span_id="s1", speech_id="s1", correlation_id="c0", attributes={"played_ms": 700}),
        make_event(T.MOUTH_SPEECH_STARTED, "s2", producer="voice.speech_scheduler", ms=400, content="Oui.",
                   span_id="s2", speech_id="s2", correlation_id="c1"),
        make_event(T.BRAIN_MESSAGE_PUBLISHED, "m", producer="core.brain_outcomes", ms=200, content=long_text, correlation_id="c0"),
        make_event(T.BRAIN_TURN_ACCEPTED, "c0", producer="core.brain_service", ms=210, correlation_id="c0"),
        make_event(T.BRAIN_SPEECH_REQUESTED, "req", producer="core.brain_service", ms=220, correlation_id="c0", content="Oui."),
        make_event(T.SYSTEM_FAILURE, "fail", producer="core.brain_service", ms=230, correlation_id="c0",
                   attributes={"code": "brain_turn_settlement_failed"}),
    ]
    result = run_node(tmp_path, """
      const out2=[];
      for(const width of [1364,332]){
        const m=TL.layout(TL.reconstruct(DATA.events),{width,pxPerSecond:60,now:Date.parse(DATA.now)});
        const cards=m.entries.filter(e=>e.kind==='card'||e.kind==='failure');
        const tooShort=cards.filter(e=>e.h<TL.cardHeight(e.item,e.w,TL.GEOMETRY,Date.parse(DATA.now))).length;
        const clamped=cards.filter(e=>/line-clamp/.test(TL.entryHtml(e))).length;
        let overlaps=0;
        for(const a of cards)for(const b of cards){
          if(a===b||a.lane!==b.lane)continue;
          const yo=a.y0<b.y0+b.h&&b.y0<a.y0+a.h,xo=a.x<b.x+b.w&&b.x<a.x+a.w;
          if(yo&&xo)overlaps++;
        }
        const outside=m.entries.filter(e=>{const l=m.lanes.find(g=>g.id===e.lane);return e.x<l.x-0.5||e.x+e.w>l.x+l.width+0.5}).length;
        const narrowest=Math.min(...cards.map(e=>e.w));
        out2.push({width,total:m.width,cards:cards.length,tooShort,clamped,overlaps,outside,narrowest,
          lanes:m.lanes.map(l=>[l.id,l.width]),minChars:(narrowest-TL.GEOMETRY.cardPadXPx)/TL.GEOMETRY.charPx,
          cardHtml:TL.entryHtml(cards.find(e=>e.item.actor==='mouth'))});
      }
      out(out2);
    """, {"events": [encode_conversation_event(e) for e in events], "now": "2026-09-16T10:00:05.000Z"})
    desktop, narrow = result
    for run in result:
        assert run["cards"] == 8  # 4 user + 2 speech + 1 brain message + 1 failure
        assert run["tooShort"] == 0 and run["clamped"] == 0 and run["overlaps"] == 0 and run["outside"] == 0
    assert desktop["total"] >= 1364  # lanes fill the width, or keep their need and scroll
    assert narrow["total"] > 332  # too narrow: lanes keep their need and scroll horizontally
    assert narrow["minChars"] >= 27.5  # never less than ~28 characters per text column on a phone
    assert "tl-durbar" in desktop["cardHtml"] and "min-height:" in desktop["cardHtml"]


def test_lane_widths_follow_need(tmp_path):
    events = [make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", producer="core.voice_admission", ms=0, content="Bonjour.")]
    events += [make_event(T.MOUTH_SPEECH_STARTED, f"s{i}", producer="voice.speech_scheduler", ms=i * 100,
                          content="Une réponse assez longue pour occuper plusieurs lignes dans sa colonne de texte.",
                          span_id=f"s{i}", speech_id=f"s{i}") for i in range(3)]
    result = run_node(tmp_path, """
      const m=TL.layout(TL.reconstruct(DATA.events),{width:1364,pxPerSecond:60});
      out({lanes:Object.fromEntries(m.lanes.map(l=>[l.id,l.width])),mouthCols:Math.max(...m.entries.filter(e=>e.lane==='mouth').map(e=>e.cols))});
    """, {"events": [encode_conversation_event(e) for e in events]})
    lanes = result["lanes"]
    assert result["mouthCols"] == 3
    assert lanes["mouth"] > 2 * lanes["user"]  # three simultaneous speeches get room; the single-column user lane stays narrow
    assert lanes["subagent"] < lanes["user"] and lanes["brain"] < lanes["user"]  # empty lanes keep a readable minimum only
    assert sum(lanes.values()) == pytest.approx(1364, abs=4)


def test_wrap_lines_counts_like_pre_wrap_and_readable_events_skip_bad_times(tmp_path):
    result = run_node(tmp_path, """
      out({a:TL.wrapLines('un deux trois',5),b:TL.wrapLines('abcdefghijkl',5),c:TL.wrapLines('ab\\ncd',10),d:TL.wrapLines('',10),
        e:TL.wrapLines('un deux',7),
        readable:TL.readableEvents([{event_id:'a',occurred_at:'2026-09-16T10:00:00.000Z'},{event_id:'b',occurred_at:'nope'},{event_id:'c',occurred_at:null}]),
        items:TL.reconstruct([{...DATA.ok},{...DATA.ok,event_id:'cev-bad',occurred_at:'nope'}]).map(i=>[i.item_id,i.started_at])});
    """, {"ok": encode_conversation_event(make_event(T.SYSTEM_FAILURE, "ok"))})
    assert (result["a"], result["b"], result["c"], result["d"], result["e"]) == (3, 3, 2, 1, 1)
    assert [e["event_id"] for e in result["readable"]["events"]] == ["a"] and result["readable"]["unreadable"] == ["b", "c"]
    assert len(result["items"]) == 1 and result["items"][0][1] > 0  # never epoch 0


def test_the_visible_window_on_a_5000_event_session_is_exact_and_fast(tmp_path):
    result = run_node(tmp_path, """
      const base=Date.parse('2026-09-16T10:00:00.000Z'),events=[];
      const iso=ms=>new Date(base+ms).toISOString();
      const ev=(i,type,extra)=>({schema_version:1,event_id:'cev-'+String(i).padStart(64,'0'),event_type:type,actor:type.split('.')[0],
        conversation_id:'conv-long',producer:type.startsWith('mouth')?'voice.speech_scheduler':'core.x',visibility:TL.SPECS[type][2],
        occurred_at:iso(extra.ms),started_at:null,ended_at:null,span_id:null,session_id:null,turn_id:null,correlation_id:'c'+i,
        parent_event_id:null,task_id:null,work_id:null,speech_id:null,outcome_id:null,trace_ref:null,content:extra.content||null,attributes:{},...extra.f});
      let n=0;
      events.push(ev(n++,'subagent.started',{ms:0,f:{span_id:'long',task_id:'long',started_at:iso(0)}}));
      for(let k=0;k<1666;k++){
        const t=k*2500;
        events.push(ev(n++,'user.transcript.accepted',{ms:t,content:'Question numéro '+k}));
        events.push(ev(n++,'mouth.speech.started',{ms:t+400,content:'Réponse '+k,f:{span_id:'s'+k,speech_id:'s'+k,started_at:iso(t+400)}}));
        events.push(ev(n++,'mouth.speech.completed',{ms:t+1900,f:{span_id:'s'+k,speech_id:'s'+k,ended_at:iso(t+1900)}}));
      }
      events.push(ev(n++,'subagent.finished',{ms:4200000,f:{span_id:'long',task_id:'long',ended_at:iso(4200000)}}));
      const t0=Date.now();
      const items=TL.collapseMessages(TL.reconstruct(events));
      const model=TL.layout(items,{width:1300,pxPerSecond:40});
      const built=Date.now()-t0;
      const checks=[];let worst=0;
      for(const top of [0,52000,99000,model.height/2,model.height-900]){
        const s=Date.now();const win=TL.visibleRange(model,top,top+900);worst=Math.max(worst,Date.now()-s);
        const brute=model.entries.filter(e=>e.bottom>=top&&e.y0<=top+900).map(e=>e.item.item_id).sort();
        checks.push([win.map(e=>e.item.item_id).sort().join()==brute.join(),win.length,win.some(e=>e.item.span_id==='long')]);
      }
      out({events:events.length,items:items.length,built,worst,checks,height:model.height});
    """)
    assert result["events"] == 5000
    assert result["items"] == 1666 * 2 + 1
    assert all(same for same, _, _ in result["checks"])
    assert all(count < 80 for _, count, _ in result["checks"])  # a window renders tens of nodes, not thousands
    assert all(long_span for _, _, long_span in result["checks"])  # the session-long span stays visible everywhere
    assert result["built"] < 3000 and result["worst"] < 50


def test_ticks_and_keyboard_neighbors(tmp_path):
    result = run_node(tmp_path, """
      const model=TL.layout(TL.reconstruct(DATA.fixture),{width:1200,pxPerSecond:40});
      const ticks=TL.ticks(model,0,model.height);
      const first=TL.neighbor(model,null,'first'),last=TL.neighbor(model,null,'last');
      const userItem=model.entries.find(e=>e.lane==='user');
      const right=TL.neighbor(model,userItem.item.item_id,'right');
      const left=TL.neighbor(model,userItem.item.item_id,'left');
      const next=TL.neighbor(model,first.item.item_id,'next');
      out({step:TL.tickStep(40),ticks,labels:ticks.map(t=>TL.fmtClock(t.t,{millis:false})),mono:ticks.every((t,i)=>!i||t.y>=ticks[i-1].y),
        first:first.item.event_type,last:last.item.event_type,right:right.lane,left,next:next.item.item_id!==first.item.item_id,
        prevOfFirst:TL.neighbor(model,first.item.item_id,'prev')});
    """, {"fixture": fixture_payloads()})
    assert result["step"] == 2000
    assert result["labels"][0] == "10:00:00" and "10:00:08" in result["labels"] and result["mono"]
    assert all(b["y"] - a["y"] >= 26 for a, b in zip(result["ticks"], result["ticks"][1:]))  # labels never overlap
    assert result["first"] == "user.transcript.accepted" and result["last"] == "mouth.speech.started"
    assert result["right"] == "mouth" and result["left"] is None and result["next"] and result["prevOfFirst"] is None


# ---------------------------------------------------------------- live feed

FEED_HARNESS = """
const calls=[],script=[],delays=[];
const page=(ids,next,more,skipped=0)=>({schema_version:1,events:ids.map(i=>({sequence:i,recorded_at:'x',event:{event_id:'cev-'+i,conversation_id:'conv-a'}})),next_cursor:next,has_more:more,skipped_rows:skipped});
const fail=(status,code,message)=>Object.assign(new Error(message||code),{status,code});
function request(url,{signal,timeoutMs}){
  return new Promise((resolve,reject)=>{
    const call={url,timeoutMs,resolve,reject};calls.push(call);
    if(signal)signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})));
    const next=script.shift();
    if(next===undefined)return;               // stays pending: a held long-poll
    setImmediate(()=>next instanceof Error?reject(next):resolve(next));
  });
}
const schedule=(fn,ms)=>{delays.push(ms);setImmediate(fn);return ()=>{}};
const phases=[];
const feed=TL.createFeed({request,schedule,now:()=>1000,onChange:(s,reason)=>phases.push(`${s.phase}:${reason}`)});
const q=u=>Object.fromEntries(new URL('http://x'+u).searchParams);
"""


def test_the_feed_hydrates_then_long_polls_and_resumes_from_the_last_cursor(tmp_path):
    result = run_node(tmp_path, FEED_HARNESS + """
      script.push(page([1,2],5,true), page([],9,true,2), page([3],10,false));
      feed.start('conv-a');
      await until(()=>calls.length===4);
      const hydrated={phase:feed.state.phase,rows:feed.state.rows.size,skipped:feed.state.skippedRows,urls:calls.map(c=>q(c.url)),poll:calls[3].timeoutMs};
      // A replayed page (same row) is not a new event: no new version, same rows.
      const v0=feed.state.version;
      calls[3].resolve(page([3],10,false));
      await until(()=>calls.length===5);
      const replay={versionDelta:feed.state.version-v0,rows:feed.state.rows.size,reason:phases[phases.length-1]};
      // Core goes down under the held long-poll, then comes back: resume at cursor 10, replayed row ignored.
      script.push(page([3,4],12,false));
      calls[4].reject(fail(503,'core_unreachable','Core injoignable'));
      await until(()=>feed.state.rows.size===4&&calls.length===7);
      const resumed={urls:calls.slice(5).map(c=>q(c.url)),delays:[...delays],rows:[...feed.state.rows.keys()],phase:feed.state.phase,attempt:feed.state.attempt,error:feed.state.error};
      // Blocking refusal: no automatic retry until retryNow().
      calls[6].reject(fail(400,'invalid_request','limit: must be 1..500'));
      await until(()=>feed.state.phase==='blocked');
      await tick();await tick();
      const blocked={phase:feed.state.phase,calls:calls.length,error:feed.state.error.code,retryable:feed.state.error.retryable};
      feed.retryNow();
      await until(()=>calls.length===8);
      const retried=q(calls[7].url);
      feed.stop();
      await tick();
      out({hydrated,replay,resumed,blocked,retried,phases,final:feed.state.phase,callsAfterStop:calls.length});
    """)
    h = result["hydrated"]
    assert h["phase"] == "live" and h["rows"] == 3 and h["skipped"] == 2
    assert [u["after_sequence"] for u in h["urls"]] == ["0", "5", "9", "10"]
    assert [u.get("wait_ms") for u in h["urls"]] == [None, None, None, "25000"]
    assert all(u["limit"] == "500" and u["conversation_id"] == "conv-a" for u in h["urls"])
    assert h["poll"] == 35000  # held poll deadline = wait + grace: it can never hang forever
    r = result["resumed"]
    assert r["delays"] == [1000]
    assert [(u["after_sequence"], u.get("wait_ms")) for u in r["urls"]] == [("10", None), ("12", "25000")]
    assert r["rows"] == ["cev-1", "cev-2", "cev-3", "cev-4"] and r["phase"] == "live" and r["attempt"] == 0 and r["error"] is None
    assert result["replay"] == {"versionDelta": 0, "rows": 3, "reason": "live:page"}
    assert result["blocked"] == {"phase": "blocked", "calls": 7, "error": "invalid_request", "retryable": False}
    assert result["retried"]["after_sequence"] == "12" and "wait_ms" not in result["retried"]
    assert "reconnecting:error" in result["phases"] and "blocked:blocked" in result["phases"]
    assert result["final"] == "stopped" and result["callsAfterStop"] == 8


def test_the_feed_backs_off_exponentially_and_restarts_cleanly_on_a_new_conversation(tmp_path):
    result = run_node(tmp_path, FEED_HARNESS + """
      for(const code of ['core_unreachable','conversation_events_unavailable','control_center_stopping','core_unauthorized'])script.push(fail(503,code));
      script.push(Object.assign(new TypeError('Failed to fetch')));
      script.push(page([1],1,false));
      feed.start('conv-a');
      await until(()=>feed.state.rows.size===1);
      const first={delays:[...delays],attempt:feed.state.attempt,phase:feed.state.phase,disconnected:feed.state.disconnectedAt};
      // Switch while a long-poll is held: it is aborted, the new conversation hydrates from cursor 0.
      await until(()=>calls.length===7);
      script.push(page([],0,false));
      const switching=feed.start('conv-b');
      await until(()=>feed.state.phase==='live'&&feed.state.conversationId==='conv-b');
      out({first,urls:calls.map(c=>q(c.url)),rows:feed.state.rows.size,backoff:[1,2,3,4,5,6,7].map(a=>TL.backoffMs(a))});
    """)
    assert result["first"]["delays"] == [1000, 2000, 4000, 8000, 16000]
    assert result["first"]["attempt"] == 0 and result["first"]["phase"] == "live" and result["first"]["disconnected"] is None
    assert [u["conversation_id"] for u in result["urls"]][-1] == "conv-b"
    assert result["urls"][-1]["after_sequence"] == "0" and result["rows"] == 0
    assert result["backoff"] == [1000, 2000, 4000, 8000, 16000, 30000, 30000]


def test_errors_are_classified_with_their_real_cause(tmp_path):
    result = run_node(tmp_path, """
      const c=(e)=>{const x=TL.classifyError(e);return x.aborted?'aborted':[x.code,x.retryable,x.title,x.message]};
      out({
        unreachable:c({status:503,code:'core_unreachable',message:'Core down: ConnectionRefused'}),
        unavailable:c({status:503,code:'conversation_events_unavailable'}),
        stopping:c({status:503,code:'control_center_stopping'}),
        notConfigured:c({status:503,code:'not_configured'}),
        origin:c({status:403,code:'forbidden_origin'}),
        invalid:c({status:400,code:'invalid_request',message:'limit: must be 1..500'}),
        missing:c({status:404}),
        network:c(new TypeError('Failed to fetch')),
        timeout:c({name:'TimeoutError',timeout:true}),
        busy:c({status:503,code:'trace_busy'}),
        unknown5xx:c({status:502,code:'brand_new_code'}),
        abort:c({name:'AbortError'}),
      });
    """)
    assert result["unreachable"] == ["core_unreachable", True, "Core injoignable", "Core down: ConnectionRefused"]
    assert result["unavailable"][:2] == ["conversation_events_unavailable", True]
    assert result["stopping"][:2] == ["control_center_stopping", True]
    assert result["notConfigured"][:2] == ["not_configured", False]
    assert result["origin"][:2] == ["forbidden_origin", False]
    assert result["invalid"] == ["invalid_request", False, "Requête refusée", "limit: must be 1..500"]
    assert result["missing"][:2] == ["missing_route", False]
    assert result["network"][:3] == ["network", True, "Control Center injoignable"]
    assert result["timeout"][:2] == ["timeout", True]
    assert result["busy"][:2] == ["trace_busy", True]
    assert result["unknown5xx"][:2] == ["brand_new_code", True]
    assert result["abort"] == "aborted"


def test_fetch_json_never_turns_an_error_answer_into_data(tmp_path):
    result = run_node(tmp_path, """
      const answer=(status,text)=>async()=>({ok:status<400,status,text:async()=>text});
      const grab=async p=>{try{return ['ok',await p]}catch(e){return ['err',e.status??null,e.code,e.message,e.name]}};
      const hang=(path,{signal})=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));
      out({
        refused:await grab(TL.createFetchJson(answer(503,'{"ok":false,"code":"core_unreachable","error":"Core injoignable (ConnectionRefusedError)","core_status":null}'))('/api/conversations')),
        plain:await grab(TL.createFetchJson(answer(413,'Payload Too Large'))('/x')),
        garbled:await grab(TL.createFetchJson(answer(200,'<html>'))('/x')),
        good:await grab(TL.createFetchJson(answer(200,'{"summaries":[]}'))('/x')),
        timeout:await grab(TL.createFetchJson(hang)('/x',{timeoutMs:30})),
      });
    """)
    assert result["refused"] == ["err", 503, "core_unreachable", "Core injoignable (ConnectionRefusedError)", "Error"]
    assert result["plain"][:3] == ["err", 413, ""] and result["plain"][3] == "Payload Too Large"
    assert result["garbled"][:3] == ["err", 200, "invalid_page"]
    assert result["good"] == ["ok", {"summaries": []}]
    assert result["timeout"][2] == "timeout" and result["timeout"][4] == "TimeoutError"


# ------------------------------------------------------ status, empty, detail

def test_status_and_empty_views_always_say_what_happens_and_how_to_get_out(tmp_path):
    result = run_node(tmp_path, """
      const rows=n=>new Map(Array.from({length:n},(_,i)=>['e'+i,{}]));
      const base={conversationId:'conv-a',rows:rows(3),startedAt:0,lastEventAt:null,hydrated:true,error:null,attempt:0,retryAt:null,disconnectedAt:null};
      const now=60000;
      out({
        loadingList:TL.statusView({conversationId:null,rows:new Map()},{loading:true,startedAt:57000},now),
        listError:TL.statusView({conversationId:null,rows:new Map()},{error:TL.classifyError({status:503,code:'core_unreachable',message:'refusé'})},now),
        hydrating:TL.statusView({...base,phase:'hydrating',rows:rows(1500),startedAt:58000},{},now),
        live:TL.statusView({...base,phase:'live',lastEventAt:48000},{},now),
        reconnecting:TL.statusView({...base,phase:'reconnecting',attempt:3,retryAt:63500,disconnectedAt:18000,error:TL.classifyError({status:503,code:'core_unreachable',message:'Core injoignable'})},{},now),
        retrying:TL.statusView({...base,phase:'reconnecting',attempt:2,retryAt:null,disconnectedAt:30000,error:TL.classifyError({status:503,code:'core_unreachable'})},{},now),
        blocked:TL.statusView({...base,phase:'blocked',error:TL.classifyError({status:403,code:'forbidden_origin',message:'Origine refusée'})},{},now),
        noConversation:TL.emptyView({feed:{conversationId:null},conversations:{loadedAt:1},total:0,visible:0,mode:'all'}),
        emptyConversation:TL.emptyView({feed:{...base,hydrated:true,phase:'live'},conversations:{},total:0,visible:0,mode:'all'}),
        loadingConversation:TL.emptyView({feed:{...base,hydrated:false,phase:'hydrating'},conversations:{},total:0,visible:0,mode:'all'}),
        downBeforeData:TL.emptyView({feed:{...base,hydrated:false,phase:'reconnecting',error:TL.classifyError({status:503,code:'core_unreachable'})},conversations:{},total:0,visible:0,mode:'all'}),
        filtered:TL.emptyView({feed:base,conversations:{},total:7,visible:0,mode:'public'}),
        shown:TL.emptyView({feed:base,conversations:{},total:7,visible:7,mode:'public'}),
      });
    """)
    assert result["loadingList"]["tone"] == "busy" and result["loadingList"]["detail"] == "3 s"
    assert result["listError"]["tone"] == "bad" and result["listError"]["retry"] and "refusé" in result["listError"]["detail"]
    assert result["hydrating"]["label"] == "Chargement" and "événements · 2 s" in result["hydrating"]["detail"]
    assert result["live"]["tone"] == "live" and result["live"]["detail"].endswith("dernier reçu il y a 12 s")
    rec = result["reconnecting"]
    assert rec["tone"] == "warn" and rec["label"] == "Core injoignable" and rec["retry"]
    assert "nouvelle tentative dans 4 s (essai 3)" in rec["detail"] and "coupé depuis 42 s" in rec["detail"]
    assert "nouvelle tentative en cours (essai 3)" in result["retrying"]["detail"]  # never "dans 0 s" while a retry is in flight
    assert result["blocked"]["tone"] == "bad" and result["blocked"]["retry"] and "127.0.0.1" in result["blocked"]["detail"]
    assert result["noConversation"]["title"] == "Aucune conversation enregistrée"
    assert result["emptyConversation"]["title"] == "Cette conversation n’a encore aucun événement"
    assert result["loadingConversation"]["tone"] == "busy"
    assert result["downBeforeData"]["tone"] == "warn" and result["downBeforeData"]["title"] == "Core injoignable"
    assert result["filtered"]["action"] == "all" and result["shown"] is None


def test_detail_model_exposes_ids_status_timing_reason_and_trace_navigation(tmp_path):
    result = run_node(tmp_path, """
      const items=TL.collapseMessages(TL.reconstruct(DATA.fixture)),ctx=TL.indexItems(items);
      const find=span=>items.find(i=>i.span_id===span);
      const seq=new Map(DATA.fixture.map((e,i)=>[e.event_id,i+1]));
      const now=Date.parse('2026-09-16T10:00:11.000Z');
      out({ack:TL.detailModel(find('speech-ack-1'),ctx,{now,sequences:seq}),sub:TL.detailModel(find('task-7'),ctx,{now}),
        work:TL.detailModel(find('work-tests'),ctx,{now}),open:TL.detailModel(find('speech-3'),ctx,{now})});
    """, {"fixture": fixture_payloads()})
    ack = result["ack"]
    assert ack["status"] == {"raw": "interrupted", "label": "interrompu", "tone": "warn"}
    assert ack["note"] == "Texte envoyé à la lecture · coupé après 1,20 s entendues"
    timing = dict(ack["timing"])
    assert timing["Durée"] == "1,35 s" and timing["Depuis la parole utilisateur"] == "+1,10 s"
    assert dict(ack["outcome"]) == {"Statut fournisseur": "cancelled", "Entendu": "1,20 s", "Sortie audio": "output-1"}
    assert [e["role"] for e in ack["events"]] == ["ouverture", "clôture"]
    assert ack["events"][1]["sequence"] == 9 and ack["events"][1]["trace_ref"]["source"] == "runtime_journal"
    assert ["speech_id", "speech-ack-1"] in ack["events"][0]["ids"]
    sub = result["sub"]
    assert sub["title"] == "Lancer la suite de tests" and sub["agent_task"] == "task-7" and sub["lane"] == "subagent"
    assert sub["parent"]["label"] == "Brain · Travail du Brain" and sub["parent"]["item_id"]
    assert dict(sub["outcome"])["Jetons"] == "1234"
    assert [c["label"].split(" · ")[:2] for c in result["work"]["children"]] == [["Sous-agents", "Sous-agent"]]
    assert dict(result["open"]["timing"])["Fin"] == "en cours"


def test_trace_model_renders_every_drill_down_outcome(tmp_path):
    found = {"ok": True, "status": "found", "event_id": "cev-1", "trace_ref": {"source": "runtime_journal", "journal_kind": "voice.speech.interrupted", "join_keys": []},
             "agent_task": None, "scan": {"entries": [{"ts": "2026-09-16T10:00:02.450+00:00", "kind": "voice.speech.interrupted", "level": "info", "message": None,
                                                      "message_redacted": True, "data": {"speech_id": "speech-ack-1", "played_ms": 1200}, "redacted_keys": ["text"], "redacted_key_count": 1}],
                                         "match_count": 1, "scanned_lines": 1200, "scanned_bytes": 90000, "corrupt_lines": 1, "oversized_lines": 0, "truncated": False, "stopped_by": "window_start"}}
    result = run_node(tmp_path, """
      out({
        found:TL.traceModel(DATA.found),
        notFound:TL.traceModel({...DATA.found,status:'not_found',scan:{...DATA.found.scan,entries:[],truncated:true,stopped_by:'max_bytes'}}),
        none:TL.traceModel({ok:true,status:'no_trace_ref',trace_ref:null,agent_task:null,scan:null}),
        agent:TL.traceModel({ok:true,status:'agent_task',trace_ref:{source:'agent_task',journal_kind:null,join_keys:['task_id']},agent_task:{task_id:'task-7',trace_url:'/api/agent/tasks/task-7/trace'},scan:null}),
        busy:TL.traceModel(null,TL.classifyError({status:503,code:'trace_busy',message:'2 lectures de trace déjà en cours'})),
        unreadable:TL.traceModel(null,{status:503,code:'trace_unreadable',message:'Lecture de la trace impossible : PermissionError.'}),
        user:TL.traceModel(null,{status:404,code:'trace_not_applicable'}),
      });
    """, {"found": found})
    f = result["found"]
    assert f["state"] == "found" and f["title"] == "1 ligne de trace jointe" and f["journal_kind"] == "voice.speech.interrupted"
    assert f["entries"][0]["data"] == [["speech_id", "speech-ack-1"], ["played_ms", 1200]]
    assert f["entries"][0]["message_redacted"] is True and f["entries"][0]["redacted"] == 1
    assert "fenêtre de ±15 min" in f["stats"] and "1 illisible(s)" in f["stats"]
    assert result["notFound"]["state"] == "empty" and result["notFound"]["truncated"] and "tronquée" in result["notFound"]["stats"]
    assert result["none"]["state"] == "none"
    assert result["agent"]["state"] == "agent_task" and result["agent"]["agent_task"]["task_id"] == "task-7"
    assert result["busy"]["state"] == "error" and result["busy"]["retry"] and "2 lectures" in result["busy"]["detail"]
    assert result["unreadable"]["title"] == "Trace illisible" and "PermissionError" in result["unreadable"]["detail"]
    assert result["user"]["state"] == "none"


def test_entries_are_accessible_escaped_and_never_color_only(tmp_path):
    hostile = make_event(T.USER_TRANSCRIPT_ACCEPTED, "xss", producer="core.voice_admission", ms=20_000,
                         content='<img src=x onerror="alert(1)">', correlation_id="voice-source-9",
                         conversation_id="conv-demo")
    result = run_node(tmp_path, """
      const events=[...DATA.fixture,DATA.hostile],now=Date.parse('2026-09-16T10:00:12.000Z');
      const model=TL.layout(TL.collapseMessages(TL.reconstruct(events)),{width:1200,pxPerSecond:40,now});
      const find=pred=>model.entries.find(pred);
      const html=span=>TL.entryHtml(find(e=>e.item.span_id===span),{now});
      out({ack:html('speech-ack-1'),sub:html('task-7'),open:html('speech-3'),work:html('work-tests'),tool:html('call-1'),
        dot:TL.entryHtml(find(e=>e.item.event_type==='brain.speech.requested')),
        user:TL.entryHtml(find(e=>e.item.actor==='user')),hostile:TL.entryHtml(find(e=>e.item.text&&e.item.text.includes('<img')))});
    """, {"fixture": fixture_payloads(), "hostile": encode_conversation_event(hostile)})
    ack = result["ack"]
    assert ack.startswith("<button ") and 'aria-controls="tlDrawer"' in ack and 'aria-expanded="false"' in ack
    assert "tl-card" in ack and "tl-durbar" in ack and "is-unheard" in ack and "st-interrupted" in ack
    assert 'aria-label="Jarvis · voix, Parole de Jarvis, interrompu, à 10:00:01.100, durée 1,35 s, Texte envoyé à la lecture' in ack
    assert ">interrompu<" in ack and "line-clamp" not in ack  # status written as text; public text never clamped
    sub = result["sub"]
    assert "tl-block" in sub and "Lancer la suite de tests" in sub and "· 7,40 s " in sub and ">terminé<" in sub
    assert "st-open" in result["open"] and ">en cours<" in result["open"] and ">2,50 s<" in result["open"]
    work = result["work"]
    assert "tl-railbar" in work and 'class="tl-vl"' in work and "Tests unitaires · 7,80 s" in work  # tall bar: vertical label
    assert "tl-railbar" in result["tool"] and "tl-tool" in result["tool"] and "tl-vl" not in result["tool"]  # short bar: drawer only
    dot = result["dot"]
    assert "tl-dot" in dot and "dot-diamond" in dot and 'class="tl-tip"' in dot and "Parole demandée : Je lance les tests." in dot
    assert 'aria-label="Brain, Parole demandée, à 10:00:00.900' in dot
    user = result["user"]
    assert user.startswith('<div role="article"') and "aria-controls" not in user and "Entrée pour le détail" not in user
    assert "<img" not in result["hostile"] and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in result["hostile"]


def test_sub_agent_block_text_lines_follow_the_block_height(tmp_path):
    events = [
        make_event(T.SUBAGENT_STARTED, "tall", producer="control_center.agent_tasks", ms=0, span_id="tall", task_id="tall",
                   content="Relire tous les journaux et comparer les erreurs avec la semaine précédente",
                   attributes={"subagent_type": "log-reader"}),
        make_event(T.SUBAGENT_FINISHED, "tall-end", producer="control_center.agent_tasks", ms=5000, span_id="tall", task_id="tall"),
        make_event(T.SUBAGENT_STARTED, "short", producer="control_center.agent_tasks", ms=20000, span_id="short", task_id="short",
                   content="Vérifier", attributes={"subagent_type": "Explore"}),
        make_event(T.SUBAGENT_FAILED, "short-end", producer="control_center.agent_tasks", ms=20200, span_id="short", task_id="short"),
    ]
    result = run_node(tmp_path, """
      const m=TL.layout(TL.reconstruct(DATA.events),{width:1200,pxPerSecond:60});
      const get=s=>m.entries.find(e=>e.item.span_id===s);
      out({tall:[get('tall').h,TL.entryHtml(get('tall'))],short:[get('short').h,TL.entryHtml(get('short'))]});
    """, {"events": [encode_conversation_event(e) for e in events]})
    tall_h, tall = result["tall"]
    short_h, short = result["short"]
    assert tall_h == pytest.approx(300) and "Log Reader" in tall and 'class="tl-bd"' in tall and "Relire tous les journaux" in tall
    assert 'class="tl-bm"' in tall and "is-short" not in tall
    assert short_h == 46 and "is-short" in short and ">échec<" in short  # 0,2 s: minimum block, dashed beyond the exact fill
    assert 'class="tl-fill" style="height:12px"' in short


def test_the_timeline_reads_only_canonical_conversation_routes():
    """Never `/api/trace` nor a raw trace line: only the Slice 04 routes (comments aside)."""
    import re

    source = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    routes = set(re.findall(r"/api/[A-Za-z0-9_/.-]*", code))
    assert routes == {"/api/conversations", "/api/conversations/events", "/api/conversations/events/",
                      "/api/conversations/sessions", "/api/conversations/transcript", "/api/conversations/export",
                      "/api/conversations/search"}, routes
    assert "/api/trace" not in code and "agent.event" not in code and "thinking" not in code.lower()
    assert "fetch(" not in code.replace("fetchImpl(", "")  # every read goes through the checked fetchJson


def test_a_public_reflex_is_transcript_text_and_only_diagnostic_instants_are_dots(tmp_path):
    reflex = "Mmh, d'accord, je regarde ça tout de suite et je te réponds dès que j'ai quelque chose de solide. " * 3
    events = [
        make_event(T.MOUTH_REFLEX_STARTED, "short", producer="voice.speech_scheduler", ms=0, correlation_id="c1", content="Mmh."),
        make_event(T.MOUTH_REFLEX_STARTED, "long", producer="voice.speech_scheduler", ms=5000, correlation_id="c2", content=reflex),
        make_event(T.MOUTH_SPEECH_QUEUED, "q", producer="voice.speech_scheduler", ms=100, correlation_id="c1", speech_id="q"),
    ]
    result = run_node(tmp_path, """
      const items=TL.reconstruct(DATA.events);
      const out2={};
      for(const mode of ['all','public']){
        const m=TL.layout(TL.filterItems(items,mode),{width:1200,pxPerSecond:60});
        out2[mode]=m.entries.map(e=>({type:e.item.event_type,kind:e.kind,lane:e.lane,h:e.h,fits:e.h>=TL.cardHeight(e.item,e.w),
          html:TL.entryHtml(e)}));
      }
      out(out2);
    """, {"events": [encode_conversation_event(e) for e in events]})
    for mode in ("all", "public"):
        reflexes = [e for e in result[mode] if e["type"] == "mouth.reflex.started"]
        assert [(e["kind"], e["lane"]) for e in reflexes] == [("card", "mouth"), ("card", "mouth")]
        short, long = reflexes
        assert short["h"] == 45 and long["h"] > 45 and long["fits"]  # one line when short, grows when long
        assert all("line-clamp" not in e["html"] and ">réflexe<" in e["html"] for e in reflexes)
        assert "Mmh." in short["html"] and "tl-tip" not in short["html"]
    assert [e["kind"] for e in result["all"] if e["type"] == "mouth.speech.queued"] == ["dot"]
    assert not [e for e in result["public"] if e["type"] == "mouth.speech.queued"]


def test_a_long_dot_label_is_shortened_in_its_tooltip_but_complete_for_screen_readers(tmp_path):
    event = make_event(T.BRAIN_SPEECH_REQUESTED, "long", producer="core.brain_service", ms=0, correlation_id="c", content="L" * 3000)
    result = run_node(tmp_path, """
      const m=TL.layout(TL.reconstruct(DATA.events),{width:1200});
      const html=TL.entryHtml(m.entries[0]);
      out({tip:html.match(/<span class="tl-tip"[^>]*>([^<]*)<[/]span>/)[1],aria:html.match(/aria-label="([^"]*)"/)[1]});
    """, {"events": [encode_conversation_event(event)]})
    assert result["tip"].startswith("Parole demandée : LLL") and "…" in result["tip"] and len(result["tip"]) < 300
    assert "L" * 3000 in result["aria"]


# ------------------------------------------- Slice 06: transcript, export, search

def test_projection_urls_encode_ids_and_never_render_text_themselves(tmp_path):
    result = run_node(tmp_path, """
      out({
        plain:TL.transcriptUrl('conv/é 1','plain'),detailed:TL.transcriptUrl('c','detailed'),odd:TL.transcriptUrl('c','<x>'),
        export:TL.exportUrl('a&b'),
        search:TL.searchUrl({q:'réunion & co',conversationId:'c 1',beforeSequence:42}),
        searchAll:TL.searchUrl({q:'x'}),
        names:[TL.transcriptFilename('c/1','plain'),TL.transcriptFilename('c','detailed'),TL.exportFilename('')],
        bytes:[0,1023,1024,1536,1048576*3.25].map(TL.fmtBytes),
      });
    """)
    assert result["plain"] == ("/api/conversations/transcript?conversation_id=conv%2F%C3%A9%201&mode=plain"
                               "&utc_offset_minutes=0")
    assert result["detailed"].endswith("&mode=detailed&utc_offset_minutes=0")
    assert result["odd"].endswith("&mode=plain&utc_offset_minutes=0")
    assert result["export"] == "/api/conversations/export?conversation_id=a%26b"
    assert result["search"] == "/api/conversations/search?q=r%C3%A9union%20%26%20co&limit=20&conversation_id=c%201&before_sequence=42"
    assert result["searchAll"] == "/api/conversations/search?q=x&limit=20"
    from jarvis.domain.conversation_event_export import file_stem
    assert result["names"] == [f"{file_stem('c/1')}.transcription.txt", "conversation-c.transcription-detaillee.txt",
                               "conversation-sans-id.events.jsonl"]
    assert result["names"][0].startswith("conversation-c_1-")  # a replaced character adds the id hash
    assert result["bytes"] == ["0 o", "1023 o", "1,0 Ko", "1,5 Ko", "3,3 Mo"]
    source = MODULE.read_text(encoding="utf-8")
    assert "Transcription de conversation" not in source  # the text is Core's rendering, never rebuilt here


def test_an_export_is_complete_only_with_its_final_control_line(tmp_path):
    trailer = json.dumps({"format": "jarvis.conversation-events.export", "complete": True,
                          "counts": {"events": 12, "skipped_rows": 1}})
    incomplete = json.dumps({"format": "jarvis.conversation-events.export", "complete": False,
                             "counts": {"events": 1, "skipped_rows": 0}})
    samples = ['{"sequence":1}\n' + trailer + "\n", trailer, '{"sequence":1}\n{"sequence":2}\n',
               '{"format":"jarvis.conversation-events.export"', incomplete, ""]
    result = run_node(tmp_path, "out(DATA.map(TL.exportSummary));", samples)
    assert result[0] == {"complete": True, "events": 12, "skippedRows": 1} and result[1]["complete"] is True
    assert all(r == {"complete": False, "events": None, "skippedRows": None} for r in result[2:])


def test_search_hits_are_escaped_highlighted_by_code_point_and_labelled(tmp_path):
    hit = {"conversation_id": "conv-b", "event_id": "cev-" + "1" * 64, "sequence": 9,
           "occurred_at": "2026-09-16T10:00:04.000Z", "event_type": "mouth.speech.interrupted", "actor": "mouth",
           "visibility": "public", "matched": ["content", "attributes.code"],
           "snippet": "\U0001F600 <b>Réunion</b> & co", "marks": [[5, 12], [99, 120], [3, 2]]}
    result = run_node(tmp_path, """
      out({view:TL.hitView(DATA,{currentConversationId:'conv-a'}),same:TL.hitView(DATA,{currentConversationId:'conv-b'}).elsewhere,
        problems:['',' ','x'.repeat(201),'é'.repeat(200),'ok'].map(TL.searchQueryProblem)});
    """, hit)
    view = result["view"]
    assert view["snippet"] == "\U0001F600 &lt;b&gt;<mark>Réunion</mark>&lt;/b&gt; &amp; co"
    assert (view["who"], view["what"], view["when"], view["day"]) == ("Jarvis · voix", "Parole de Jarvis", "10:00:04",
                                                                      "2026-09-16")
    assert view["elsewhere"] is True and result["same"] is False and view["matched"] == "texte, code"
    assert result["problems"][0] and result["problems"][1] and result["problems"][2]
    assert result["problems"][3] is None and result["problems"][4] is None


def test_search_and_job_states_say_what_happens_for_how_long_and_how_to_get_out(tmp_path):
    result = run_node(tmp_path, """
      const now=100000;
      const err=TL.classifyError({status:413,code:'transcript_too_large',message:'Conversation trop longue'});
      out({
        idle:TL.searchStateView({},now),
        searching:TL.searchStateView({loading:true,startedAt:97500},now),
        failed:TL.searchStateView({error:TL.classifyError({status:503,code:'core_unreachable',message:'Core injoignable'})},now),
        none:TL.searchStateView({done:true,hits:[]},now),
        partial:TL.searchStateView({done:true,hits:[{},{}],hasMore:true,scanLimited:true,scanned:50000,skippedRows:1},now),
        exporting:TL.jobStateView('export',{loading:true,startedAt:95000,received:1536000},now),
        exported:TL.jobStateView('export',{done:true,events:1234,skippedRows:2,received:2048,filename:'conversation-c.events.jsonl'},now),
        rendering:TL.jobStateView('transcript',{loading:true,startedAt:99000},now),
        rendered:TL.jobStateView('transcript',{done:true,text:'a\\nb\\n\\nc\\n',bytes:9,elapsedMs:420},now),
        tooLarge:TL.jobStateView('transcript',{error:err},now),
        errRetryable:err.retryable,
      });
    """)
    nnbsp = " "
    assert result["idle"]["tone"] == "muted" and "Jamais la trace" in result["idle"]["text"]
    assert result["searching"] == {"tone": "busy", "text": "Recherche en cours · 2 s", "cancel": True}
    assert result["failed"]["tone"] == "bad" and result["failed"]["retry"] and "Core injoignable" in result["failed"]["text"]
    assert result["none"]["text"] == "Aucun résultat"
    assert result["partial"]["text"] == (f"2 résultats · recherche arrêtée après 50{nnbsp}000 événements parcourus · "
                                         "1 ligne illisible ignorée")
    assert result["partial"]["more"] is True
    assert result["exporting"] == {"tone": "busy", "text": "Export en cours · 1,5 Mo reçus · 5 s", "cancel": True}
    assert f"1{nnbsp}234 événements" in result["exported"]["text"]
    assert "2 lignes illisibles ignorées par Core" in result["exported"]["text"]
    assert result["rendering"]["cancel"] and result["rendered"]["text"] == "3 lignes · 9 o · rendue en 420 ms"
    assert result["tooLarge"]["tone"] == "bad" and "Exporter JSONL" in result["tooLarge"]["detail"]
    assert result["errRetryable"] is False


def test_fetch_text_and_open_stream_surface_the_server_error(tmp_path):
    result = run_node(tmp_path, """
      const answer=(status,text)=>async()=>({ok:status<400,status,text:async()=>text});
      const grab=async p=>{try{const v=await p;return ['ok',typeof v==='string'?v:v.status]}catch(e){return ['err',e.status??null,e.code,e.message,e.name]}};
      const hang=(path,{signal})=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));
      out({
        text:await grab(TL.createFetchText(answer(200,'Transcription\\n'))('/t')),
        tooLarge:await grab(TL.createFetchText(answer(413,'{"ok":false,"code":"transcript_too_large","error":"Trop longue"}'))('/t')),
        plain:await grab(TL.createFetchText(answer(502,'Bad Gateway'))('/t')),
        timeout:await grab(TL.createFetchText(hang)('/t',{timeoutMs:20})),
        stream:await grab(TL.createOpenStream(answer(200,''))('/e')),
        refused:await grab(TL.createOpenStream(answer(403,'{"ok":false,"code":"forbidden_origin","error":"forbidden host"}'))('/e')),
      });
    """)
    assert result["text"] == ["ok", "Transcription\n"]
    assert result["tooLarge"][:4] == ["err", 413, "transcript_too_large", "Trop longue"]
    assert result["plain"][:4] == ["err", 502, "", "Bad Gateway"]
    assert result["timeout"][2] == "timeout" and result["timeout"][4] == "TimeoutError"
    assert result["stream"] == ["ok", 200] and result["refused"][:3] == ["err", 403, "forbidden_origin"]


def test_a_search_jump_resolves_merged_publications_and_marks_the_entry(tmp_path):
    from tests.fakes.conversation_events import transcript_scenario

    events = transcript_scenario()
    merged = next(e for e in events if e.outcome_id == "o2")
    kept = next(e for e in events if e.outcome_id == "o1")
    result = run_node(tmp_path, """
      const items=TL.collapseMessages(TL.reconstruct(DATA.events)),ctx=TL.indexItems(items);
      const model=TL.layout(items,{width:1200});
      const entry=model.entries[model.index.get(TL.itemForEvent(ctx,DATA.merged).item_id)];
      out({item:TL.itemForEvent(ctx,DATA.merged).item_id,missing:TL.itemForEvent(ctx,'cev-'+'0'.repeat(64)),noctx:TL.itemForEvent(null,'x'),
        found:TL.entryHtml(entry,{found:true}).includes('is-found'),plain:TL.entryHtml(entry).includes('is-found')});
    """, {"events": [encode_conversation_event(e) for e in events], "merged": merged.event_id})
    assert result["item"] == kept.event_id and result["missing"] is None and result["noctx"] is None
    assert result["found"] is True and result["plain"] is False


# ------------------------------------------------------- Slice 06 rework (QA findings)

def test_search_hit_day_and_time_are_both_local(tmp_path):
    hit = {"conversation_id": "c", "event_id": "cev-" + "2" * 64, "sequence": 1, "occurred_at": "2026-09-16T22:47:02.170Z",
           "event_type": "user.transcript.accepted", "actor": "user", "visibility": "public", "matched": ["content"],
           "snippet": "x", "marks": []}
    paris = run_node(tmp_path, "out(TL.hitView(DATA))", hit, tz="Europe/Paris")
    utc = run_node(tmp_path, "out(TL.hitView(DATA))", hit, tz="UTC")
    assert (paris["day"], paris["when"]) == ("2026-09-17", "00:47:02")  # was 2026-09-16 00:47 before the fix
    assert (utc["day"], utc["when"]) == ("2026-09-16", "22:47:02")


def test_the_transcript_request_carries_the_browser_offset_and_labels_it(tmp_path):
    result = run_node(tmp_path, """
      out({offset:TL.localOffsetMinutes(new Date('2026-09-16T12:00:00Z')),winter:TL.localOffsetMinutes(new Date('2026-01-16T12:00:00Z')),
        labels:[0,120,-330,60].map(TL.offsetLabel),url:TL.transcriptUrl('c','plain',120),bad:TL.transcriptUrl('c','plain',1.5)});
    """, tz="Europe/Paris")
    assert (result["offset"], result["winter"]) == (120, 60)
    assert result["labels"] == ["UTC", "UTC+02:00", "UTC-05:30", "UTC+01:00"]
    assert result["url"].endswith("&utc_offset_minutes=120") and result["bad"].endswith("&utc_offset_minutes=0")


def test_a_broken_export_stream_is_an_incomplete_export_never_a_reconnection(tmp_path):
    result = run_node(tmp_path, """
      const net=Object.assign(new TypeError('network error'),{});
      out({
        afterBytes:TL.exportFailure(net,{received:1536000}),
        idleAfterBytes:TL.exportFailure(null,{received:10,timedOut:true}),
        noTrailer:TL.exportFailure(Object.assign(new Error('Ligne finale de contrôle absente.'),{code:'export_incomplete'}),{received:99}),
        beforeBytes:TL.exportFailure(Object.assign(new Error('Core injoignable'),{status:503,code:'core_unreachable'}),{received:0}),
        cancelled:TL.exportFailure(Object.assign(new Error('x'),{name:'AbortError'}),{received:500}),
        busy:TL.classifyError({status:429,code:'projection_busy',message:'occupé'}),
      });
    """)
    after = result["afterBytes"]
    assert after["code"] == "export_incomplete" and after["title"] == "Export incomplet"
    assert "1,5 Mo reçus" in after["message"] and "Aucun fichier enregistré" in after["message"]
    assert "automatique" not in (after["hint"] + after["message"])  # never promises a retry that will not happen
    assert result["idleAfterBytes"]["code"] == "export_incomplete" and "30 s" in result["idleAfterBytes"]["message"]
    assert result["noTrailer"]["code"] == "export_incomplete" and result["noTrailer"]["message"] == "Ligne finale de contrôle absente."
    assert result["beforeBytes"]["code"] == "core_unreachable"
    assert result["cancelled"] == {"aborted": True, "title": "Export annulé", "message": "", "hint": ""}
    assert result["busy"]["title"] == "Core est occupé" and result["busy"]["retryable"] is False


def test_an_empty_export_says_there_is_nothing_to_save(tmp_path):
    result = run_node(tmp_path, "out(TL.jobStateView('export',{done:true,events:0,received:220,filename:'f'},1000))")
    assert result["text"].startswith("Aucun événement dans cette conversation") and result["tone"] == "muted"
    source = MODULE.read_text(encoding="utf-8")
    assert "if(summary.events>0){saveBlob(blob,filename)" in source


def test_new_entries_are_counted_only_after_a_hydration_already_seen(tmp_path):
    result = run_node(tmp_path, """
      let memo={pending:0,liveConversation:null};const steps=[];
      const step=(args)=>{memo=TL.trackNewEntries(memo,args);steps.push({...memo})};
      step({conversationId:'a',hydrated:false,follow:false,visibleCount:500,previousCount:0});   // hydrating
      step({conversationId:'a',hydrated:true,follow:false,visibleCount:900,previousCount:500});  // last hydration page
      step({conversationId:'a',hydrated:true,follow:false,visibleCount:903,previousCount:900});  // live: 3 new
      step({conversationId:'b',hydrated:true,follow:false,visibleCount:40,previousCount:903});   // switch / jump
      step({conversationId:'b',hydrated:true,follow:false,visibleCount:41,previousCount:40});    // live in b
      step({conversationId:'b',hydrated:true,follow:true,visibleCount:42,previousCount:41});     // at the bottom
      out(steps);
    """)
    assert [s["pending"] for s in result] == [0, 0, 3, 3, 4, 0]
    assert [s["liveConversation"] for s in result] == [None, "a", "a", "b", "b", "b"]


def test_download_hash_is_the_same_in_the_page_and_in_python(tmp_path):
    from jarvis.domain.conversation_event_export import _fnv1a, export_filename

    ids = ["é", "è", "conv 1", "conv_1", "\U0001F642", ""]
    result = run_node(tmp_path, "out({hash:DATA.map(TL.fnv1a),names:DATA.map(TL.exportFilename)})", ids)
    assert result["hash"] == [_fnv1a(value) for value in ids]
    assert result["names"] == [export_filename(value) for value in ids]
    assert len(set(result["names"][:2])) == 2 and result["names"][2] != result["names"][3]


def test_panels_never_promise_an_automatic_retry(tmp_path):
    result = run_node(tmp_path, """
      const down=TL.classifyError({status:503,code:'core_unreachable',message:'Core injoignable'});
      out({transcript:TL.jobStateView('transcript',{error:down},0),search:TL.searchStateView({error:down},0),
        busy:TL.jobStateView('export',{error:TL.classifyError({status:429,code:'projection_busy'})},0),
        live:TL.statusView({conversationId:'c',rows:new Map(),phase:'reconnecting',attempt:1,retryAt:5000,error:down},{},0)});
    """)
    for view in (result["transcript"], result["search"]):
        assert "automatique" not in view["detail"] and "Réessayer" in view["detail"] and view["retry"]
    assert "Réessayez dans un instant" in result["busy"]["detail"]
    assert "automatique" in (result["live"]["hint"] + result["live"]["detail"])  # the live feed really does retry


# --------------------------------------------------------------------------
# Un seul long-poll par profil (Issue 04) : meneur élu par Web Locks, relais
# par BroadcastChannel. Le banc simule plusieurs onglets d'un même profil dans
# un seul processus node : un registre de verrous partagé, un bus de messages,
# une horloge que le test fait avancer, et un `fetch` scripté par onglet.

SHARED_HARNESS = """
const registry={},bus={tabs:[],post(from,message){for(const t of bus.tabs)if(t!==from)t.deliver(message)}};
let clock=1000;const timers=[];
const delays=[];
const schedule=(fn,ms)=>{delays.push(ms);const task={at:clock+ms,fn,dead:false};timers.push(task);return()=>{task.dead=true}};
const now=()=>clock;
const advance=async ms=>{
  const target=clock+ms;
  for(;;){
    const due=timers.filter(t=>!t.dead&&t.at<=target).sort((a,b)=>a.at-b.at)[0];
    if(!due)break;
    clock=due.at;due.dead=true;due.fn();await tick();await tick();
  }
  clock=target;await tick();
};
function grantNext(slot){
  slot.held=false;
  const entry=slot.queue.shift();
  if(!entry)return;
  if(entry.aborted)return grantNext(slot);
  slot.held=true;
  Promise.resolve().then(()=>entry.fn({})).then(v=>{entry.resolve(v);grantNext(slot)},e=>{entry.reject(e);grantNext(slot)});
}
const locks={request(name,options,fn){
  const slot=registry[name]||(registry[name]={held:false,queue:[]});
  if(options&&options.ifAvailable){
    if(slot.held)return Promise.resolve().then(()=>fn(null));
    slot.held=true;
    return Promise.resolve().then(()=>fn({name})).then(()=>grantNext(slot),e=>{grantNext(slot);throw e});
  }
  return new Promise((resolve,reject)=>{
    const entry={fn,resolve,reject,aborted:false};
    const signal=options&&options.signal;
    if(signal){
      if(signal.aborted){const e=new Error('aborted');e.name='AbortError';reject(e);return}
      signal.addEventListener('abort',()=>{
        entry.aborted=true;
        const i=slot.queue.indexOf(entry);if(i>=0)slot.queue.splice(i,1);
        const e=new Error('aborted');e.name='AbortError';reject(e);
      });
    }
    slot.queue.push(entry);
    if(!slot.held)grantNext(slot);
  });
}};
const page=(ids,next,more,conv='conv-a')=>({schema_version:1,
  events:ids.map(i=>({sequence:i,recorded_at:'x',event:{event_id:'cev-'+i,conversation_id:conv}})),
  next_cursor:next,has_more:more,skipped_rows:0});
const q=u=>Object.fromEntries(new URL('http://x'+u).searchParams);
function makeTab(name,{shared=true}={}){
  const calls=[],script=[];
  const request=(url,{signal,timeoutMs})=>new Promise((resolve,reject)=>{
    const call={tab:name,url,timeoutMs,resolve,reject,q:q(url)};calls.push(call);
    if(signal)signal.addEventListener('abort',()=>{
      call.aborted=true;reject(Object.assign(new Error('aborted'),{name:'AbortError'}));
    });
    const next=script.shift();
    if(next===undefined)return;                 // reste en vol : un long-poll tenu
    setImmediate(()=>next instanceof Error?reject(next):resolve(next));
  });
  let ref=null;
  const feed=TL.createFeed({request,schedule,now,onChange:(s,r,d)=>{if(ref)ref.observe(s,r,d)}});
  const tab={name,calls,script,feed,deliver:m=>tab.shared.handleMessage(m)};
  tab.shared=TL.createSharedFeed({feed,locks:shared?locks:null,
    // `muted` : un onglet dont les diffusions se perdent (meneur figé, canal muet).
    channel:shared?{postMessage:m=>{if(!tab.muted)bus.post(tab,m)}}:null,
    createAbort:()=>new AbortController(),now,schedule});
  ref=tab.shared;
  bus.tabs.push(tab);
  return tab;
}
"""


def test_one_leader_holds_the_only_long_poll_and_the_others_follow(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a'),b=makeTab('b'),c=makeTab('c');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      for(const t of [b,c]){t.script.push(page([1],1,false));await t.shared.watch('conv-a')}
      await until(()=>b.feed.state.phase==='following'&&c.feed.state.phase==='following');
      const settled={roles:[a,b,c].map(t=>t.shared.view().role),
        waits:[a,b,c].map(t=>t.calls.filter(x=>x.q.wait_ms).length),
        reads:[a,b,c].map(t=>t.calls.length)};
      // Un événement arrive : le meneur le relaie, les suiveurs ne demandent rien.
      const before=[b,c].map(t=>t.calls.length);
      a.calls[a.calls.length-1].resolve(page([2],2,false));
      await until(()=>b.feed.state.rows.size===2&&c.feed.state.rows.size===2);
      out({settled,rows:[a,b,c].map(t=>t.feed.state.rows.size),
        cursors:[a,b,c].map(t=>t.feed.state.cursor),
        followerReadsAfter:[b,c].map((t,i)=>t.calls.length-before[i]),
        modes:[a,b,c].map(t=>t.shared.view().mode)});
    """)
    assert result["settled"]["roles"] == ["leader", "follower", "follower"]
    # Un seul onglet demande une attente longue ; les suiveurs ne lisent qu'une fois.
    assert result["settled"]["waits"] == [1, 0, 0]
    assert result["settled"]["reads"] == [2, 1, 1]
    assert result["rows"] == [2, 2, 2] and result["cursors"] == [2, 2, 2]
    assert result["followerReadsAfter"] == [0, 0]
    assert result["modes"] == ["shared", "shared", "shared"]


def test_a_gap_in_the_relay_costs_one_short_read_and_never_a_long_poll(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a'),b=makeTab('b');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      b.script.push(page([1],1,false));
      await b.shared.watch('conv-a');
      await until(()=>b.feed.state.phase==='following');
      const reads=b.calls.length;
      // Une diffusion perdue : la page relayée commence après notre curseur.
      b.script.push(page([2,3],3,false));
      b.deliver({v:TL.SHARED_MESSAGE_VERSION,type:'page',conversation_id:'conv-a',from:2,cursor:3,
        events:page([3],3,false).events,has_more:false});
      await until(()=>b.feed.state.rows.size===3);
      out({extraReads:b.calls.length-reads,waited:b.calls.some(c=>c.q.wait_ms),
        url:b.calls[b.calls.length-1].q,rows:[...b.feed.state.rows.keys()],
        gaps:b.shared.view().stats.gaps,phase:b.feed.state.phase});
    """)
    assert result["extraReads"] == 1 and result["waited"] is False
    assert result["url"]["after_sequence"] == "1" and "wait_ms" not in result["url"]
    assert result["rows"] == ["cev-1", "cev-2", "cev-3"]
    assert result["gaps"] == 1 and result["phase"] == "following"


def test_a_hidden_leader_hands_over_and_the_new_leader_resumes_at_its_own_cursor(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a'),b=makeTab('b');
      a.script.push(page([1,2],2,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      b.script.push(page([1,2],2,false));
      await b.shared.watch('conv-a');
      await until(()=>b.feed.state.phase==='following');
      const readsBefore=b.calls.length;
      b.script.push(page([],2,false));            // ce que lira le nouveau meneur
      // Le meneur est caché en plein vol : il rend le verrou et n'écoute plus.
      await a.shared.setVisible(false);
      await until(()=>b.shared.view().role==='leader');
      await until(()=>b.calls.length>readsBefore);
      const promoted=b.calls[b.calls.length-1].q;
      await until(()=>b.feed.state.phase==='live');
      out({roles:[a,b].map(t=>t.shared.view().role),oldPhase:a.feed.state.phase,
        promoted,longPoll:b.calls.filter(c=>c.q.wait_ms).length,
        rows:b.feed.state.rows.size});
    """)
    assert result["roles"][1] == "leader"
    assert result["oldPhase"] == "paused"
    # Reprise au curseur tenu : ni relecture depuis zéro, ni trou.
    assert result["promoted"]["after_sequence"] == "2"
    assert result["longPoll"] == 1 and result["rows"] == 2


def test_a_hidden_follower_asks_nothing_and_catches_up_when_it_comes_back(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a'),b=makeTab('b');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      b.script.push(page([1],1,false));
      await b.shared.watch('conv-a');
      await until(()=>b.feed.state.phase==='following');
      await b.shared.setVisible(false);
      const paused={phase:b.feed.state.phase,calls:b.calls.length};
      await advance(120000);                       // deux minutes cachees
      const slept=b.calls.length;
      b.script.push(page([2],2,false));
      await b.shared.setVisible(true);
      await until(()=>b.feed.state.rows.size===2);
      out({paused,sleptReads:slept-paused.calls,back:b.calls[b.calls.length-1].q,
        phase:b.feed.state.phase,role:b.shared.view().role});
    """)
    assert result["paused"]["phase"] == "paused"
    assert result["sleptReads"] == 0            # un onglet caché ne demande rien
    assert result["back"]["after_sequence"] == "1" and "wait_ms" not in result["back"]
    assert result["phase"] == "following" and result["role"] == "follower"


def test_a_silent_leader_costs_one_bounded_read_per_silence_window(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a'),b=makeTab('b');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      b.script.push(page([1],1,false));
      await b.shared.watch('conv-a');
      await until(()=>b.feed.state.phase==='following');
      const base=b.calls.length;
      a.muted=true;                               // le meneur se tait : plus un battement
      await advance(30000);
      const quiet=b.calls.length-base;            // sous le seuil : rien
      b.script.push(page([],1,false));
      await advance(12000);                       // 42 s de silence : une lecture
      const first=b.calls.length-base;
      b.script.push(page([],1,false));
      await advance(40000);
      const second=b.calls.length-base;
      out({quiet,first,second,waited:b.calls.some(c=>c.q.wait_ms),
        watchdog:b.shared.view().stats.watchdogReads,bound:TL.FOLLOWER_SILENCE_MS+TL.FOLLOWER_CHECK_MS});
    """)
    assert result["quiet"] == 0
    assert result["first"] == 1 and result["second"] == 2
    assert result["waited"] is False and result["watchdog"] == 2
    assert result["bound"] <= 40000             # un suiveur n'est jamais muet plus de ~40 s


def test_without_web_locks_or_broadcast_channel_each_tab_reads_for_itself(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a',{shared:false}),b=makeTab('b',{shared:false});
      for(const t of [a,b]){t.script.push(page([1],1,false));await t.shared.watch('conv-a')}
      await until(()=>a.feed.state.phase==='live'&&b.feed.state.phase==='live');
      out({modes:[a,b].map(t=>t.shared.view().mode),roles:[a,b].map(t=>t.shared.view().role),
        waits:[a,b].map(t=>t.calls.filter(c=>c.q.wait_ms).length),rows:[a,b].map(t=>t.feed.state.rows.size)});
    """)
    assert result["modes"] == ["solo", "solo"] and result["roles"] == ["solo", "solo"]
    # Repli documenté : le comportement d'avant, un long-poll par onglet.
    assert result["waits"] == [1, 1] and result["rows"] == [1, 1]


def test_a_follower_never_shows_a_false_live_while_the_leader_is_in_trouble(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const down=TL.classifyError({status:503,code:'core_unreachable',message:'Core injoignable'});
      const base={conversationId:'c',rows:new Map([['a',1]]),cursor:3,lastEventAt:null,phase:'following'};
      out({
        following:TL.statusView({...base,sharedRole:'follower'},{},1000),
        reconnecting:TL.statusView({...base,sharedRole:'follower',leaderPhase:'reconnecting',leaderError:down},{},1000),
        blocked:TL.statusView({...base,sharedRole:'follower',leaderPhase:'blocked',
          leaderError:TL.classifyError({status:400,code:'invalid_request',message:'limit: must be 1..500'})},{},1000),
        paused:TL.statusView({...base,sharedRole:'follower',phase:'paused'},{},1000),
        leader:TL.statusView({...base,sharedRole:'leader',phase:'live'},{},1000),
      });
    """)
    assert result["following"]["tone"] == "live" and "autre onglet" in result["following"]["detail"]
    assert result["reconnecting"]["tone"] == "warn" and result["reconnecting"]["retry"] is True
    assert "Core injoignable" in result["reconnecting"]["detail"]
    assert result["blocked"]["tone"] == "bad" and result["blocked"]["retry"] is True
    assert result["paused"]["tone"] == "muted" and "arrière-plan" in result["paused"]["detail"]
    assert result["leader"]["tone"] == "live" and "autre onglet" not in result["leader"]["detail"]


def test_closing_the_leader_tab_hands_the_long_poll_over_without_a_hole(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a'),b=makeTab('b');
      a.script.push(page([1,2],2,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      b.script.push(page([1,2],2,false));
      await b.shared.watch('conv-a');
      await until(()=>b.feed.state.phase==='following');
      b.script.push(page([3],3,false));
      // L'onglet meneur est ferme : le verrou est rendu, un autre le recoit.
      a.shared.stop();
      await until(()=>b.shared.view().role==='leader');
      await until(()=>b.feed.state.phase==='live');
      out({closed:a.feed.state.phase,role:b.shared.view().role,
        rows:[...b.feed.state.rows.keys()],cursor:b.feed.state.cursor,
        resumed:b.calls.map(c=>c.q.after_sequence),
        longPolls:b.calls.filter(c=>c.q.wait_ms).length});
    """)
    assert result["closed"] == "stopped" and result["role"] == "leader"
    # Reprise au curseur tenu : l'evenement publie pendant la passation arrive.
    # Une lecture courte au curseur tenu, puis le long-poll : pas une de plus.
    assert result["resumed"] == ["0", "2", "3"] and result["cursor"] == 3
    assert result["rows"] == ["cev-1", "cev-2", "cev-3"]
    assert result["longPolls"] == 1


# -- Changer de conversation, en mode partagé -------------------------------
# Le geste le plus ordinaire de l'écran, et celui que le partage avait cassé :
# un onglet déjà meneur restait meneur, donc ne relançait rien, et le flux
# gardait l'ancienne conversation pendant que le sélecteur annonçait la
# nouvelle. Ces tests tiennent le geste sous toutes ses formes.


def test_a_leader_that_switches_conversation_really_restarts_on_the_new_one(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a');
      a.script.push(page([1,2],2,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      const holding=a.calls[a.calls.length-1];          // long-poll en vol sur A
      a.script.push(page([7],7,false,'conv-b'));
      await a.shared.watch('conv-b');
      await until(()=>a.feed.state.conversationId==='conv-b'&&a.feed.state.phase==='live');
      out({aborted:holding.aborted===true,role:a.shared.view().role,
        url:a.calls.map(c=>[c.q.conversation_id,c.q.after_sequence]),
        rows:[...a.feed.state.rows.keys()],cursor:a.feed.state.cursor,
        waits:a.calls.filter(c=>c.q.wait_ms&&!c.aborted).length});
    """)
    assert result["aborted"] is True           # la lecture de A est bien abandonnée
    assert result["role"] == "leader"
    assert result["url"][-2:] == [["conv-b", "0"], ["conv-b", "7"]]
    assert result["rows"] == ["cev-7"] and result["cursor"] == 7
    assert result["waits"] == 1


def test_a_follower_that_switches_conversation_follows_the_other_leader(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a'),b=makeTab('b'),c=makeTab('c');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      c.script.push(page([7],7,false,'conv-b'));
      await c.shared.watch('conv-b');
      await until(()=>c.feed.state.phase==='live');
      b.script.push(page([1],1,false));
      await b.shared.watch('conv-a');
      await until(()=>b.feed.state.phase==='following');
      // Le suiveur de A passe sur B, déjà menée par un autre onglet.
      b.script.push(page([7],7,false,'conv-b'));
      await b.shared.watch('conv-b');
      await until(()=>b.feed.state.conversationId==='conv-b'&&b.feed.state.phase==='following');
      const reads=b.calls.length;
      // Un événement de B : il arrive par le relais, sans nouvelle requête.
      c.calls[c.calls.length-1].resolve(page([8],8,false,'conv-b'));
      await until(()=>b.feed.state.rows.size===2);
      out({role:b.shared.view().role,rows:[...b.feed.state.rows.keys()],
        waits:b.calls.filter(x=>x.q.wait_ms).length,extraReads:b.calls.length-reads,
        urls:b.calls.map(x=>x.q.conversation_id),
        leaders:[a,c].map(t=>t.shared.view().role)});
    """)
    assert result["role"] == "follower"
    assert result["rows"] == ["cev-7", "cev-8"]
    # Aucun long-poll de ce côté, et rien de plus à demander : le relais suffit.
    assert result["waits"] == 0 and result["extraReads"] == 0
    assert result["urls"] == ["conv-a", "conv-b"]
    # Deux conversations réellement regardées : deux meneurs, c'est irréductible.
    assert result["leaders"] == ["leader", "leader"]


def test_switching_back_and_forth_leaves_exactly_one_read_on_the_shown_conversation(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      a.script.push(page([7],7,false,'conv-b'));
      await a.shared.watch('conv-b');
      await until(()=>a.feed.state.conversationId==='conv-b'&&a.feed.state.phase==='live');
      a.script.push(page([1,2],2,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.conversationId==='conv-a'&&a.feed.state.phase==='live');
      out({rows:[...a.feed.state.rows.keys()],cursor:a.feed.state.cursor,
        live:a.calls.filter(c=>c.q.wait_ms&&!c.aborted).length,
        conversations:a.calls.map(c=>c.q.conversation_id)});
    """)
    # Retour sur A : tout est relu depuis zéro, et rien de B ne subsiste.
    assert result["rows"] == ["cev-1", "cev-2"] and result["cursor"] == 2
    assert result["live"] == 1
    assert result["conversations"] == ["conv-a", "conv-a", "conv-b", "conv-b", "conv-a", "conv-a"]


def test_a_page_of_the_old_conversation_can_never_land_in_the_new_one(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      const stale=a.calls[a.calls.length-1];
      a.script.push(page([7],7,false,'conv-b'));
      await a.shared.watch('conv-b');
      await until(()=>a.feed.state.conversationId==='conv-b'&&a.feed.state.phase==='live');
      // La rafale de A arrive après coup : elle ne doit rien ajouter à B.
      stale.resolve(page([2,3,4],4,false));
      for(let i=0;i<30;i++)await tick();
      // Et une diffusion de A non plus.
      const verdict=a.shared.handleMessage({v:TL.SHARED_MESSAGE_VERSION,type:'page',
        conversation_id:'conv-a',from:1,cursor:4,events:page([2],2,false).events,has_more:false});
      out({rows:[...a.feed.state.rows.keys()],cursor:a.feed.state.cursor,verdict,
        conversation:a.feed.state.conversationId});
    """)
    assert result["rows"] == ["cev-7"] and result["cursor"] == 7
    assert result["verdict"] == "other" and result["conversation"] == "conv-b"


def test_the_retry_control_restarts_a_leader_that_has_nothing_to_wake(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      const before=a.calls.length,holding=a.calls[a.calls.length-1];
      a.script.push(page([1,2],2,false));
      await a.shared.restart();
      await until(()=>a.feed.state.rows.size===2);
      out({aborted:holding.aborted===true,extra:a.calls.length-before,
        role:a.shared.view().role,rows:a.feed.state.rows.size,
        url:a.calls[before].q});
    """)
    # Le long-poll en cours est abandonné et la lecture repart vraiment.
    assert result["aborted"] is True and result["role"] == "leader"
    # Même conversation : on reprend au curseur tenu, on ne retélécharge rien.
    assert result["url"]["conversation_id"] == "conv-a" and result["url"]["after_sequence"] == "1"
    assert result["rows"] == 2 and result["extra"] == 2


def test_a_follower_says_it_has_lost_the_relay_long_before_the_watchdog(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const base={conversationId:'c',rows:new Map([['a',1]]),cursor:3,phase:'following',
        sharedRole:'follower',hydratedAt:1000,startedAt:1000,lastEventAt:1000};
      out({fresh:TL.statusView({...base,leaderAt:60000},{},61000),
        late:TL.statusView({...base,leaderAt:10000},{},60000),
        never:TL.statusView({...base,leaderAt:null},{},60000),
        threshold:TL.LEADER_LATE_MS,watchdog:TL.FOLLOWER_SILENCE_MS});
    """)
    assert result["fresh"]["tone"] == "live"
    # Le silence est dit bien avant que le chien de garde ne lise.
    assert result["late"]["tone"] == "warn" and result["late"]["retry"] is True
    assert "aucune nouvelle" in result["late"]["detail"]
    assert result["never"]["tone"] == "warn"
    assert result["threshold"] < result["watchdog"]


def test_a_tab_that_cannot_queue_for_the_lock_tries_again(tmp_path):
    result = run_node(tmp_path, SHARED_HARNESS + """
      const a=makeTab('a');
      a.script.push(page([1],1,false));
      await a.shared.watch('conv-a');
      await until(()=>a.feed.state.phase==='live');
      // Un onglet dont la mise en file échoue : sans reprise, il ne serait
      // jamais meneur, même une fois le verrou libre.
      let failures=0;
      const broken={request(name,options,fn){
        if(options&&options.ifAvailable)return Promise.resolve().then(()=>fn(null));
        failures++;return Promise.reject(new Error('lock manager down'));
      }};
      const feed=TL.createFeed({request:()=>new Promise(()=>{}),schedule,now});
      const solo=TL.createSharedFeed({feed,locks:broken,channel:{postMessage:()=>{}},
        createAbort:()=>new AbortController(),now,schedule});
      await solo.watch('conv-a');
      const first=failures;
      await advance(1000);
      await advance(2000);
      out({first,after:failures,delays:delays.filter(d=>d===1000||d===2000).length});
    """)
    assert result["first"] == 1
    # Remise en file avec un délai qui s'allonge, au lieu d'abandonner.
    assert result["after"] >= 3
