"""Chat model of the Control Center (`jarvis/runtime/control_center_chat_model.js`, Slice 02), run by node.

The module served to the page is executed as is. Parity with the Python
reference `project_chat` (`jarvis/domain/chat_projection.py`) on the shared
fixture `tests/fixtures/chat_projection/cases.json`, then the stateful rules a
stream of pages needs: promotion across pages, idempotent replay, reset on a
Board change, pending turns. Contract: `docs/chat.md`, section "Projection".
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.chat_projection import CHAT_EVENT_TYPES, CHAT_PROJECTION, UNKNOWN_FAILURE_CODE, project_chat
from jarvis.domain.conversation_event_query import decode_stored_event
from jarvis.domain.conversation_events import ConversationEventType as T, encode_conversation_event
from tests.fakes.conversation_events import make_event

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_chat_model.js"
FIXTURE = ROOT / "tests" / "fixtures" / "chat_projection" / "cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
CONV = "conv-a"


def run_node(tmp_path: Path, source: str, data: object = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_file = tmp_path / "chat-data.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "chat-test.cjs"
    script.write_text(
        f"const CM=require({json.dumps(str(MODULE))});\n"
        f"const DATA=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(()=>{" + source + "})();",
        encoding="utf-8",
    )
    completed = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60,
                               check=False, env=dict(os.environ))
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def row(sequence: int, event) -> dict:
    """A stored row as a `GET .../conversation-events` page carries it."""
    return {"sequence": sequence, "recorded_at": "2026-10-14T09:00:00.000Z", "event": encode_conversation_event(event)}


def user(source: str, addressing: str | None = "addressed", **fields):
    attributes = {"source": "realtime"} if addressing is None else {"source": "realtime", "addressing": addressing}
    return make_event(T.USER_TRANSCRIPT_ACCEPTED, source, attributes=attributes, **fields)


def reply(source: str, **fields):
    return make_event(T.BRAIN_MESSAGE_PUBLISHED, f"reply-{source}", correlation_id=f"corr-{source}",
                      attributes={"kind": "turn_result", "status": "completed"}, **fields)


def failed(source: str, **fields):
    return make_event(T.BRAIN_TURN_FAILED, f"failed-{source}", correlation_id=f"corr-{source}",
                      attributes={"code": "brain_backend_failed"}, **fields)


def roles(items: list[dict]) -> list[list]:
    return [[item["role"], item["sequence"]] for item in items]


def test_fixture_cases_js(tmp_path):
    got = run_node(tmp_path, """
      out(DATA.map(c=>{const m=CM.createChatModel();CM.reset(m,c.conversation_id);CM.applyPage(m,{events:c.events});return CM.items(m)}));
    """, CASES)
    assert got == [case["expected"] for case in CASES]


def test_fixture_parity_with_python_reference(tmp_path):
    # Every page split of every case gives, in node, exactly what `project_chat` gives on the whole case.
    got = run_node(tmp_path, """
      out(DATA.map(c=>c.events.map((_,cut)=>{const m=CM.createChatModel(c.conversation_id);
        CM.applyPage(m,{events:c.events.slice(cut)});CM.applyPage(m,c.events.slice(0,cut));return CM.items(m)})));
    """, CASES)
    for case, splits in zip(CASES, got, strict=True):
        python = [{**asdict(i), "collapsed_event_ids": list(i.collapsed_event_ids)} for i in
                  project_chat([decode_stored_event(r) for r in case["events"]], conversation_id=case["conversation_id"])]
        assert all(split == python for split in splits), case["name"]


def test_constants_mirror_python(tmp_path):
    got = run_node(tmp_path, "out({p:CM.CHAT_PROJECTION,t:CM.CHAT_EVENT_TYPES,u:CM.UNKNOWN_FAILURE_CODE,f:CM.ITEM_FIELDS});")
    assert got["p"] == CHAT_PROJECTION
    assert set(got["t"]) == {t.value for t in CHAT_EVENT_TYPES}
    assert got["u"] == UNKNOWN_FAILURE_CODE
    assert got["f"] == json.loads(FIXTURE.read_text(encoding="utf-8"))["item_fields"]


def test_is_chat_event_allowlist_exhaustive(tmp_path):
    events = [encode_conversation_event(user("x") if t is T.USER_TRANSCRIPT_ACCEPTED else make_event(t, "x"))
              for t in T]
    events += [encode_conversation_event(user("x", a)) for a in (None, "uncertain", "ambient", "")]
    got = run_node(tmp_path, "out(DATA.map(e=>CM.isChatEvent(e)));", events)
    passing = {e["event_type"] for e, ok in zip(events[:len(T)], got) if ok}
    assert passing == {t.value for t in CHAT_EVENT_TYPES}
    assert got[len(T):] == [True, True, False, False]


def test_uncertain_hidden_until_promoted(tmp_path):
    pages = [[row(1, user("u", "uncertain")), row(2, make_event(T.BRAIN_TURN_ACCEPTED, "u"))], [row(3, reply("u"))]]
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');const seen=[];
      for(const page of DATA){CM.applyPage(m,{events:page});seen.push(CM.items(m))}
      out(seen);
    """, pages)
    assert got[0] == []
    assert roles(got[1]) == [["user", 1], ["brain", 3]]


def test_refused_uncertain_never_shown(tmp_path):
    page = [row(1, user("u", "uncertain")), row(2, make_event(T.BRAIN_TURN_ACCEPTED, "u")), row(3, user("a")),
            row(4, reply("a")), row(5, user("v", "ambient")), row(6, reply("v")), row(7, failed("u"))]
    got = run_node(tmp_path, "const m=CM.createChatModel('conv-a');CM.applyPage(m,{events:DATA});out(CM.items(m));",
                   page)
    assert roles(got) == [["user", 3], ["brain", 4], ["brain", 6]]


def test_page_replay_idempotent(tmp_path):
    page = [row(1, user("a")), row(2, reply("a")), row(3, user("b")), row(4, reply("b"))]
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');const first=CM.applyPage(m,{events:DATA});const once=CM.items(m);
      const again=CM.applyPage(m,{events:DATA})+CM.applyPage(m,DATA.slice(1,3))+CM.applyPage(m,[...DATA].reverse());
      out({first,again,same:JSON.stringify(once)===JSON.stringify(CM.items(m)),once});
    """, page)
    assert got["first"] == 4 and got["again"] == 0 and got["same"]
    assert roles(got["once"]) == [["user", 1], ["brain", 2], ["user", 3], ["brain", 4]]


def test_cursor_split_promotion(tmp_path):
    # The uncertain turn ends page 1 (cursor already past it), the Brain message opens page 2.
    pages = [[row(1, user("a")), row(2, reply("a")), row(3, user("u", "uncertain"))],
             [row(4, reply("u")), row(5, reply("u", outcome_id="outcome-again", content="text reply-u"))]]
    pages[1][1]["event"]["event_id"] = "cev-" + "f" * 64
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');const seen=[];
      for(const page of DATA){CM.applyPage(m,{events:page});seen.push(CM.items(m))}
      out(seen);
    """, pages)
    assert roles(got[0]) == [["user", 1], ["brain", 2]]
    assert roles(got[1]) == [["user", 1], ["brain", 2], ["user", 3], ["brain", 4]]
    assert got[1][3]["collapsed_event_ids"] == ["cev-" + "f" * 64]


def test_failed_on_system_turn_ignored(tmp_path):
    page = [row(1, failed("system")), row(2, user("a")), row(3, failed("a"))]
    got = run_node(tmp_path, "const m=CM.createChatModel('conv-a');CM.applyPage(m,{events:DATA});out(CM.items(m));",
                   page)
    assert roles(got) == [["user", 2]]
    assert got[0]["failure_code"] == "brain_backend_failed"


def test_reset_on_board_change_never_merges(tmp_path):
    page = [row(1, user("a")), row(2, user("b", conversation_id="conv-b")), row(3, reply("a"))]
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');CM.applyPage(m,{events:DATA});const a=CM.items(m);
      CM.reset(m,'conv-b');const emptied=CM.items(m);CM.applyPage(m,{events:DATA});const b=CM.items(m);
      const unbound=CM.createChatModel();CM.applyPage(unbound,{events:DATA});
      out({a,emptied,b,unbound:CM.items(unbound)});
    """, page)
    assert roles(got["a"]) == [["user", 1], ["brain", 3]]
    assert got["emptied"] == [] and roles(got["b"]) == [["user", 2]] and got["unbound"] == []


def test_pending_turn_cleared_by_reply_or_failure(tmp_path):
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');CM.markPending(m,'corr-a');CM.markPending(m,'corr-b');
      const before=[CM.isPending(m,'corr-a'),CM.isPending(m,'corr-b'),CM.isPending(m,'corr-c')];
      CM.applyPage(m,{events:DATA});
      const after=[CM.isPending(m,'corr-a'),CM.isPending(m,'corr-b')];
      CM.markPending(m,'corr-c');CM.reset(m,'conv-a');
      out({before,after,afterReset:CM.isPending(m,'corr-c'),items:CM.items(m)});
    """, [row(1, user("a")), row(2, user("b")), row(3, failed("b"))])
    assert got["before"] == [True, True, False]
    assert got["after"] == [True, False]
    assert got["afterReset"] is False and got["items"] == []


def test_items_are_copies(tmp_path):
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');CM.applyPage(m,{events:DATA});
      const first=CM.items(m);first[1].collapsed_event_ids.push('x');first[0].text='changed';out(CM.items(m));
    """, [row(1, user("a")), row(2, reply("a"))])
    assert got[0]["text"] == "text a" and got[1]["collapsed_event_ids"] == []


def test_malformed_rows_ignored(tmp_path):
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');
      const added=CM.applyPage(m,{events:[null,{},{sequence:'1',event:DATA[0].event},{sequence:2},DATA[0]]});
      out({added,items:CM.items(m),none:CM.applyPage(m,null)+CM.applyPage(m,{})});
    """, [row(1, user("a"))])
    assert got["added"] == 1 and roles(got["items"]) == [["user", 1]] and got["none"] == 0


# ---------- Slice 07b : état pur des pièces jointes du composer ----------

def test_attachment_count_and_stored_rows_bounded(tmp_path):
    with_files = make_event(T.USER_TRANSCRIPT_ACCEPTED, "files", attributes={"source": "text", "addressing": "addressed",
                                                                             "attachment_count": 2})
    page = [row(1, user("a")), row(2, with_files), row(3, reply("a"))]
    got = run_node(tmp_path, """
      const m=CM.createChatModel('conv-a');
      for(let i=0;i<5;i++)CM.applyPage(m,{events:DATA});
      const ids=CM.items(m).map(i=>i.event_id);
      out({counts:ids.map(id=>CM.attachmentCount(m,id)),stored:CM.storedRows(m).map(r=>r.sequence),fields:Object.keys(CM.items(m)[0])});
    """, page)
    assert got["counts"] == [0, 2, 0]
    assert got["stored"] == [1, 2, 3], "five replays of the same page: one row per event"
    assert got["fields"] == ["role", "event_id", "sequence", "correlation_id", "text", "kind", "status", "failure_code",
                             "collapsed_event_ids"], "the projection item shape (parity with Python) is unchanged"


def test_attachment_lifecycle_states_and_send_rules(tmp_path):
    got = run_node(tmp_path, """
      const L=CM.createAttachments(),snap=()=>CM.attachmentView(L,'conv-a');
      const a=CM.addAttachment(L,{name:'photo.png',size:100,mime:'image/png',cid:'conv-a',clientUploadId:'u1'});
      const b=CM.addAttachment(L,{name:'archive.zip',size:50,mime:'application/zip',cid:'conv-a',clientUploadId:'u2'});
      CM.attachmentProgress(L,a.key,40,100);const progress={loaded:a.loaded,total:a.total};
      const uploading=snap();
      CM.attachmentSent(L,a.key);const phase=a.phase;
      CM.attachmentReady(L,a.key,{artifact_id:'jart_up_a',brain_readable:true,mime_type:'image/png',size_bytes:100});
      CM.attachmentReady(L,b.key,{artifact_id:'jart_up_b',brain_readable:false});
      const ready=snap();
      const late=CM.attachmentReady(L,a.key,{artifact_id:'other'});
      const bad=CM.addAttachment(L,{name:'x',size:1,cid:'conv-a',clientUploadId:'u3'});
      CM.attachmentReady(L,bad.key,{});const malformed=snap().items[2].error.code;
      CM.removeAttachment(L,bad.key);
      const sig=CM.attachmentSignature(L,'conv-a');
      const sent=CM.takeSent(L,'conv-a',['jart_up_a','jart_up_b']);
      out({progress,phase,uploading:{blocked:uploading.blocked,n:uploading.uploading,status:uploading.items.map(i=>i.status)},
        ready:{blocked:ready.blocked,ids:ready.ids,status:ready.items.map(i=>i.status)},late,malformed,sig,
        sent:sent.map(s=>[s.name,s.readable]),after:snap().items.length});
    """)
    assert got["progress"] == {"loaded": 40, "total": 100} and got["phase"] == "checking"
    assert got["uploading"] == {"blocked": "uploading", "n": 2, "status": ["uploading", "uploading"]}
    assert got["ready"] == {"blocked": None, "ids": ["jart_up_a", "jart_up_b"], "status": ["ready", "unreadable"]}
    assert got["late"] is None, "a settled attachment ignores a late answer"
    assert got["malformed"] == "invalid_response"
    assert got["sig"] == "jart_up_a,jart_up_b"
    assert got["sent"] == [["photo.png", True], ["archive.zip", False]] and got["after"] == 0


def test_attachment_retry_identity_rules(tmp_path):
    """Issue inconnue → même id ; échec connu → nouvel id ; même id qui apprend `upload_conflict` → nouvel id auto."""

    got = run_node(tmp_path, """
      const L=CM.createAttachments(),add=(n,id)=>CM.addAttachment(L,{name:n,size:1,cid:'c',clientUploadId:id});
      const out1={};
      for(const code of ['core_timeout','client_timeout','network_error','upload_in_progress','upload_incomplete','upload_conflict','upload_storage_failed','core_unreachable']){
        const it=add(code,'id-'+code);const f=CM.attachmentFailed(L,it.key,{code,status:0});
        const r=CM.retryAttachment(L,it.key,'fresh-'+code);
        out1[code]={same:r.clientUploadId==='id-'+code,replay:r.replay,attempts:r.attempts,auto:f.autoRetry};
      }
      const z=add('z','id-z');CM.attachmentFailed(L,z.key,{code:'core_timeout'});CM.retryAttachment(L,z.key,'nope');
      const conflict=CM.attachmentFailed(L,z.key,{code:'upload_conflict',status:409});
      const big=add('big','id-big');CM.attachmentFailed(L,big.key,{code:'upload_too_large',limitBytes:67108864});
      const bigView=CM.attachmentView(L,'c').items.find(i=>i.key===big.key);
      out({codes:out1,conflict:conflict.autoRetry,bigRetry:CM.retryAttachment(L,big.key,'x'),bigError:bigView.error,
        failedBlocks:CM.attachmentView(L,'c').blocked});
    """)
    codes = got["codes"]
    for code in ("core_timeout", "client_timeout", "network_error", "upload_in_progress"):
        assert codes[code]["same"] is True and codes[code]["replay"] is True, code
    for code in ("upload_incomplete", "upload_conflict", "upload_storage_failed", "core_unreachable"):
        assert codes[code]["same"] is False and codes[code]["replay"] is False, code
    assert all(c["attempts"] == 2 and c["auto"] is False for c in codes.values())
    assert got["conflict"] is True, "a same-id replay answered upload_conflict retries at once with a new id"
    assert got["bigRetry"] is None and got["bigError"]["retryable"] is False and got["bigError"]["limitBytes"] == 67108864
    assert got["failedBlocks"] == "uploading", "uploading outranks failed: the first thing to wait for"


def test_attachment_scope_stale_rebind_restore_and_helpers(tmp_path):
    got = run_node(tmp_path, """
      const L=CM.createAttachments();
      const a=CM.addAttachment(L,{name:'a.txt',size:3,cid:'conv-a',clientUploadId:'u1'});
      CM.attachmentReady(L,a.key,{artifact_id:'jart_up_a',brain_readable:true});
      const onB=CM.attachmentView(L,'conv-b'),onA=CM.attachmentView(L,'conv-a');
      const same=CM.rebindAttachment(L,a.key,'conv-a','u9');
      const moved=CM.rebindAttachment(L,a.key,'conv-b','u2');
      const movedView=CM.attachmentView(L,'conv-b');
      const R=CM.createAttachments();
      const restored=CM.restoreAttachment(R,{name:'r.pdf',size:9,cid:'conv-a',artifactId:'jart_up_r',readable:false});
      const dup=CM.restoreAttachment(R,{name:'r.pdf',size:9,cid:'conv-a',artifactId:'jart_up_r'});
      const lost=CM.restoreAttachment(R,{name:'big.mov',size:9,cid:'conv-a',interrupted:true});
      out({onB:{ids:onB.ids,stale:onB.stale,status:onB.items[0].status,blocked:onB.blocked},onA:{ids:onA.ids,stale:onA.stale},
        same,moved:{cid:moved.cid,id:moved.clientUploadId,state:moved.state},movedBlocked:movedView.blocked,
        restored:[restored.state,restored.readable,restored.artifactId],dup,lost:[lost.state,lost.error.code,lost.error.retryable],
        bytes:[0,1023,1024,1536,10*1024*1024,64*1024*1024,3*1024*1024*1024].map(CM.formatBytes),
        limit:[CM.uploadLimitFrom('the file exceeds the 67108864-byte upload bound'),CM.uploadLimitFrom('nope')]});
    """)
    assert got["onB"] == {"ids": [], "stale": 1, "status": "stale", "blocked": None}, "never sent from another conversation"
    assert got["onA"] == {"ids": ["jart_up_a"], "stale": 0}
    assert got["same"] is None
    assert got["moved"] == {"cid": "conv-b", "id": "u2", "state": "uploading"} and got["movedBlocked"] == "uploading"
    assert got["restored"] == ["ready", False, "jart_up_r"] and got["dup"] is None
    assert got["lost"] == ["failed", "upload_interrupted_reload", False]
    assert got["bytes"] == ["0 o", "1023 o", "1 Ko", "1,5 Ko", "10 Mo", "64 Mo", "3 Go"]
    assert got["limit"] == [67108864, None]
