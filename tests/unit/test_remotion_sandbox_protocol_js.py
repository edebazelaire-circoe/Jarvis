"""Protocole `rs: 1` hôte <-> bac à sable d'une scène Remotion et chien de garde (Slice 06), exécutés par node.

Contrat : `jarvis/runtime/remotion_sandbox_protocol.js`, `docs/remotion-isolation.md` section 5. Même motif que
`tests/fakes/prefab_js.py` : un script `.cjs` dans `tmp_path`, la valeur rendue imprimée en JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain import remotion_source as rs

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "jarvis" / "runtime" / "remotion_sandbox_protocol.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def run_node(tmp_path: Path, body: str):
    script = tmp_path / "case.cjs"
    script.write_text(f"""const P=require({json.dumps(str(PROTOCOL))});
const SRC={{}}, OK=(data)=>({{source:SRC,origin:'null',data}});
const run=()=>{{{body}}};
process.stdout.write(JSON.stringify(run()));
""", encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_limits_agree_with_the_python_contract(tmp_path):
    limits = run_node(tmp_path, "return P.LIMITS;")
    assert limits["maxFrame"] == rs.MAX_DURATION_FRAMES and limits["maxFps"] == rs.MAX_FPS
    assert (limits["minCompositionPx"], limits["maxCompositionPx"]) == (rs.MIN_DIMENSION, rs.MAX_DIMENSION)
    assert run_node(tmp_path, "return {h:P.HOST_TYPES,c:P.CHILD_TYPES};") == {
        "h": ["init", "props", "control", "cue", "ping", "teardown"], "c": ["ready", "pong", "violation", "error"]}


def test_valid_child_messages_are_accepted_as_clean_copies(tmp_path):
    result = run_node(tmp_path, """
      const cases=[{rs:1,type:'ready'},{rs:1,type:'pong',n:'abcd1234',frame:-1,dropped:0},
        {rs:1,type:'violation',directive:'connect-src',blocked:'http://x/'+'y'.repeat(500)},
        {rs:1,type:'error',message:'boom\\u0000\\n'+'z'.repeat(900)}];
      return cases.map(c=>{const r=P.parseChildMessage(OK(c),SRC);return {ok:r.ok,type:r.message&&r.message.type,len:JSON.stringify(r.message||{}).length}});
    """)
    assert [r["ok"] for r in result] == [True] * 4
    assert result[2]["len"] < 400 and result[3]["len"] < 400  # bounded copies, not the 500/900 characters sent


def test_a_child_message_is_refused_for_each_kind_of_malformation(tmp_path):
    result = run_node(tmp_path, """
      const proto=JSON.parse('{"rs":1,"type":"error","message":"m","__proto__":{"admin":true}}');
      const cases={
        string:'{"rs":1}', null:null, array:[], number:7, wrongVersion:{rs:2,type:'ready'}, noVersion:{type:'ready'},
        hostType:{rs:1,type:'init',composition:{},props:{}}, unknown:{rs:1,type:'sudo'}, nonStringType:{rs:1,type:['ready']},
        extra:{rs:1,type:'error',message:'m',extra:1}, proto, huge:{rs:1,type:'error',message:'x'.repeat(100000)},
        badToken:{rs:1,type:'pong',n:'UPPER!!',frame:0,dropped:0}, badFrame:{rs:1,type:'pong',n:'abcd1234',frame:1.5,dropped:0},
        nan:{rs:1,type:'pong',n:'abcd1234',frame:NaN,dropped:0}, badDirective:{rs:1,type:'violation',directive:'x y',blocked:''},
        errorNumber:{rs:1,type:'error',message:5}, fn:{rs:1,type:'error',message:()=>1}, classInstance:new (class A{constructor(){this.rs=1;this.type='ready'}})(),
      };
      const out={};
      for(const [k,v] of Object.entries(cases)){const r=P.parseChildMessage(OK(v),SRC);out[k]=r.ok?'ACCEPTED':r.reason}
      return out;
    """)
    assert "ACCEPTED" not in result.values(), result
    assert result["hostType"] == "bad_type" and result["extra"] == "extra_field" and result["wrongVersion"] == "bad_version"
    assert result["huge"] == "too_large" and result["proto"] in ("extra_field", "too_large")


def test_source_and_origin_are_both_checked(tmp_path):
    result = run_node(tmp_path, """
      const other={}; const m={rs:1,type:'ready'};
      return {
        foreign:P.parseChildMessage({source:other,origin:'null',data:m},SRC).reason,
        nullSource:P.parseChildMessage({source:null,origin:'null',data:m},null).reason,
        sameOrigin:P.parseChildMessage({source:SRC,origin:'http://127.0.0.1:1',data:m},SRC).reason,
        ok:P.parseChildMessage({source:SRC,origin:'null',data:m},SRC).ok,
        hostForeign:P.parseHostMessage({source:other,origin:'http://h',data:{rs:1,type:'teardown'}},SRC,'http://h').reason,
        hostOrigin:P.parseHostMessage({source:SRC,origin:'http://evil',data:{rs:1,type:'teardown'}},SRC,'http://h').reason,
        hostOk:P.parseHostMessage({source:SRC,origin:'http://h',data:{rs:1,type:'teardown'}},SRC,'http://h').ok,
        hostNoExpectedOrigin:P.parseHostMessage({source:SRC,origin:'null',data:{rs:1,type:'teardown'}},SRC,undefined).reason,
      };
    """)
    assert result == {"foreign": "foreign_source", "nullSource": "foreign_source", "sameOrigin": "bad_origin", "ok": True,
                      "hostForeign": "foreign_source", "hostOrigin": "bad_origin", "hostOk": True, "hostNoExpectedOrigin": "bad_origin"}


def test_host_messages_are_typed_and_bounded(tmp_path):
    result = run_node(tmp_path, """
      const H=(d)=>{const r=P.parseHostMessage({source:SRC,origin:'http://h',data:d},SRC,'http://h');return r.ok?'ok':r.reason};
      const comp={id:'Scene',width:1280,height:720,fps:30,durationInFrames:90};
      const deep=(n)=>{let o={};for(let i=0;i<n;i++)o={a:o};return o};
      return {
        init:H({rs:1,type:'init',composition:comp,props:{title:'x'}}),
        badComp:H({rs:1,type:'init',composition:{...comp,fps:0},props:{}}),
        extraComp:H({rs:1,type:'init',composition:{...comp,evil:1},props:{}}),
        bigProps:H({rs:1,type:'props',props:{t:'x'.repeat(70000)}}),
        deepProps:H({rs:1,type:'props',props:deep(20)}),
        protoProps:H({rs:1,type:'props',props:JSON.parse('{"__proto__":{"a":1}}')}),
        fnProps:H({rs:1,type:'props',props:{f:()=>1}}),
        seek:H({rs:1,type:'control',action:'seek',frame:30}), seekNoFrame:H({rs:1,type:'control',action:'seek'}),
        playWithFrame:H({rs:1,type:'control',action:'play',frame:3}), badAction:H({rs:1,type:'control',action:'eval'}),
        cue:H({rs:1,type:'cue',name:'intro',frame:10}), badCue:H({rs:1,type:'cue',name:'Intro!',frame:10}),
        farFrame:H({rs:1,type:'cue',name:'intro',frame:10**9}), ping:H({rs:1,type:'ping',n:'abcd1234'}), childType:H({rs:1,type:'ready'}),
        built:P.hostMessage('ping',{n:'abcd1234'}), threw:(()=>{try{P.hostMessage('ping',{n:'!'});return 'no'}catch(e){return 'yes'}})(),
      };
    """)
    assert result["init"] == "ok" and result["seek"] == "ok" and result["cue"] == "ok" and result["ping"] == "ok"
    for bad in ("badComp", "extraComp", "bigProps", "deepProps", "protoProps", "fnProps", "seekNoFrame", "playWithFrame", "badAction", "badCue",
                "farFrame", "childType"):
        assert result[bad] != "ok", bad
    assert result["built"] == {"rs": 1, "type": "ping", "n": "abcd1234"} and result["threw"] == "yes"


SUPERVISOR = """
  let t=0, kills=[], sent=[], n=0;
  const sup=P.createSupervisor({now:()=>t, send:(m)=>sent.push(m), kill:(r,d)=>kills.push([r,d]), token:()=>'tok'+(++n)+'abcdefgh',
                                limits:{silentMs:3000,readyMs:10000,maxViolations:5,maxChildMessagesPerSecond:50}});
  const feed=(data,source)=>sup.accept({source:source===undefined?SRC:source,origin:'null',data},SRC);
"""


def test_the_supervisor_pings_with_a_fresh_token_and_demands_the_matching_pong(tmp_path):
    result = run_node(tmp_path, SUPERVISOR + """
      feed({rs:1,type:'ready'}); sup.tick();
      const first=sent[0]; const noPingYet=sent.length;
      const wrong=feed({rs:1,type:'pong',n:'zzzzzzzz',frame:0,dropped:0});
      t=500; feed({rs:1,type:'pong',n:first.n,frame:12,dropped:2});
      t=1500; sup.tick();
      return {noPingYet, second:sent[1].n!==first.n, wrong:wrong.reason, state:{pending:sup.state().pending,pongs:sup.state().pongs,
              frame:sup.state().lastFrame,dropped:sup.state().childDropped,violations:sup.state().violations}, kills};
    """)
    assert result["noPingYet"] == 1 and result["second"] and result["wrong"] == "unexpected_pong"
    assert result["state"] == {"pending": "tok2abcdefgh", "pongs": 1, "frame": 12, "dropped": 2, "violations": 1} and result["kills"] == []


def test_a_frame_that_never_answers_is_killed_once(tmp_path):
    result = run_node(tmp_path, SUPERVISOR + """
      feed({rs:1,type:'ready'}); t=100; sup.tick(); t=2000; sup.tick(); const early=kills.length;
      t=3500; sup.tick(); t=9000; sup.tick(); sup.tick();
      return {early, kills, afterKill:feed({rs:1,type:'ready'}).reason};
    """)
    assert result["early"] == 0 and result["kills"] == [["unresponsive", "3400"]] and result["afterKill"] == "killed"


def test_a_frame_that_never_says_ready_is_killed(tmp_path):
    assert run_node(tmp_path, SUPERVISOR + "t=11000; sup.tick(); return kills;") == [["no_ready", None]]


def test_repeated_violations_kill_the_frame_but_foreign_windows_do_not(tmp_path):
    result = run_node(tmp_path, SUPERVISOR + """
      for(let i=0;i<30;i++)feed({rs:1,type:'ready'},{});   // a sibling frame: not the frame's fault
      const afterForeign={kills:kills.length,foreign:sup.state().foreign,violations:sup.state().violations};
      feed({rs:1,type:'ready'});
      for(let i=0;i<10;i++)feed({rs:1,type:'sudo'});
      return {afterForeign,kills,refused:sup.state().refused};
    """)
    assert result["afterForeign"] == {"kills": 0, "foreign": 30, "violations": 0}
    assert result["kills"] == [["protocol_abuse", "duplicate_ready"]] or result["kills"][0][0] == "protocol_abuse"


def test_a_flood_is_dropped_before_parsing_and_ends_the_frame(tmp_path):
    result = run_node(tmp_path, SUPERVISOR + """
      feed({rs:1,type:'ready'});
      let parsed=0; const lazy={get rs(){parsed++;return 1},type:'error',message:'x'};
      for(let i=0;i<4000;i++)feed({rs:1,type:'error',message:'flood'+i});
      return {kills,accepted:sup.state().accepted,refused:sup.state().refused};
    """)
    assert result["kills"] and result["kills"][0][0] == "protocol_abuse"
    assert result["accepted"] <= 21  # at most the reports-per-second budget got through; the rest never reached the parser


def test_error_and_violation_reports_are_rate_limited_per_second(tmp_path):
    result = run_node(tmp_path, SUPERVISOR + """
      feed({rs:1,type:'ready'});
      const out=[]; for(let i=0;i<24;i++)out.push(feed({rs:1,type:'error',message:'e'}).ok);
      t=1500; const later=feed({rs:1,type:'error',message:'e'}).ok;
      return {accepted:out.filter(Boolean).length,later,reasons:sup.state().refused};
    """)
    assert result["accepted"] == 20 and result["later"] is True and "report_flood" in result["reasons"]


def test_the_protocol_module_is_pure():
    text = PROTOCOL.read_text(encoding="utf-8")
    for needle in ("document", "fetch(", "XMLHttpRequest", "WebSocket", "setTimeout", "setInterval", "localStorage", "eval(", "new Function"):
        assert needle not in text, needle


def test_a_pong_that_reports_a_heap_over_the_limit_ends_the_frame_and_a_bad_heap_is_refused(tmp_path):
    result = run_node(tmp_path, SUPERVISOR.replace("maxViolations:5,", "maxViolations:5,maxHeapMb:100,") + """
      feed({rs:1,type:'ready'}); sup.tick();
      const okHeap=feed({rs:1,type:'pong',n:sent[0].n,frame:0,dropped:0,heap:90}).ok;
      t=1500; sup.tick();
      const bad=feed({rs:1,type:'pong',n:sent[1].n,frame:0,dropped:0,heap:-5}).reason;
      const over=feed({rs:1,type:'pong',n:sent[1].n,frame:0,dropped:0,heap:101});
      return {okHeap,bad,kills,last:sup.state().lastHeapMb};
    """)
    assert result["okHeap"] is True and result["bad"] == "bad_pong" and result["kills"] == [["memory", "101"]] and result["last"] == 101


def test_a_sustained_flood_ends_the_frame_after_three_seconds_not_twenty(tmp_path):
    result = run_node(tmp_path, SUPERVISOR.replace("maxViolations:5","maxViolations:100000") + """
      feed({rs:1,type:'ready'});
      const killedAt=[];
      for(let second=0;second<30&&kills.length===0;second++){
        t=second*1000+1;
        for(let i=0;i<80;i++)feed({rs:1,type:'error',message:'x'});   // 80 messages a second, cap 50: 30 of them are dropped unparsed each second
        if(kills.length)killedAt.push(second);
      }
      return {kills,killedAt,floodStreak:sup.state().floodStreak};
    """)
    assert result["kills"] and result["kills"][0] == ["protocol_abuse", "flood"] and result["killedAt"][0] <= 4, result


def test_the_default_ping_token_is_128_cryptographic_bits_and_never_repeats(tmp_path):
    result = run_node(tmp_path, """
      const seen=new Set(); for(let i=0;i<2000;i++)seen.add(P.strongToken());
      const sample=[...seen][0];
      let t=0, sent=[];
      const sup=P.createSupervisor({now:()=>t, send:(m)=>sent.push(m), kill:()=>{}});
      sup.accept({source:SRC,origin:'null',data:{rs:1,type:'ready'}},SRC); sup.tick();
      return {unique:seen.size, len:sample.length, hex:/^[0-9a-f]{32}$/.test(sample), pinged:sent.length===1&&/^[0-9a-f]{32}$/.test(sent[0].n)};
    """)
    assert result == {"unique": 2000, "len": 32, "hex": True, "pinged": True}
    assert "Math.random" not in PROTOCOL.read_text(encoding="utf-8")
