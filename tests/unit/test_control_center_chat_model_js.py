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
