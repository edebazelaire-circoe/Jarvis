"""Chat projection, Python reference (`jarvis/domain/chat_projection.py`, Slice 02).

Contract: `docs/chat.md`, section "Projection". The shared fixture
`tests/fixtures/chat_projection/cases.json` is also played by node against
`control_center_chat_model.js` (`test_control_center_chat_model_js.py`).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import random

import pytest

from jarvis.domain.chat_projection import (
    CHAT_EVENT_TYPES, UNKNOWN_FAILURE_CODE, ChatItem, is_chat_event, project_chat,
)
from jarvis.domain.conversation_event_query import decode_stored_event
from jarvis.domain.conversation_event_store import StoredConversationEvent
from jarvis.domain.conversation_events import ConversationEventType as T
from tests.fakes.conversation_events import BASE, make_event

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "chat_projection" / "cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
CONV = "conv-a"


def rows(case: dict) -> list[StoredConversationEvent]:
    return [decode_stored_event(row) for row in case["events"]]


def as_dicts(items: tuple[ChatItem, ...]) -> list[dict]:
    return [{**asdict(item), "collapsed_event_ids": list(item.collapsed_event_ids)} for item in items]


def stored(*events) -> list[StoredConversationEvent]:
    """Each event stored at its position (sequence 1, 2, ...)."""
    return [StoredConversationEvent(i, BASE + timedelta(seconds=i), e) for i, e in enumerate(events, 1)]


def user(source: str, addressing: str | None = "addressed", **fields):
    attributes = {"source": "realtime"} if addressing is None else {"source": "realtime", "addressing": addressing}
    return make_event(T.USER_TRANSCRIPT_ACCEPTED, source, attributes=attributes, **fields)


def reply(source: str, **fields):
    return make_event(T.BRAIN_MESSAGE_PUBLISHED, f"reply-{source}", correlation_id=f"corr-{source}",
                      attributes={"kind": "turn_result", "status": "completed"}, **fields)


def failed(source: str, code: str | None = "brain_backend_failed", attempt: int = 1):
    return make_event(T.BRAIN_TURN_FAILED, f"failed-{source}-{attempt}", correlation_id=f"corr-{source}",
                      attributes={} if code is None else {"code": code})


def roles(items) -> list[tuple[str, int]]:
    return [(item.role, item.sequence) for item in items]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fixture_cases_python(case):
    assert as_dicts(project_chat(rows(case), conversation_id=case["conversation_id"])) == case["expected"]


def test_fixture_item_shape_is_the_contract():
    fields = json.loads(FIXTURE.read_text(encoding="utf-8"))["item_fields"]
    assert [f for f in ChatItem.__dataclass_fields__] == fields
    assert all(list(item) == fields for case in CASES for item in case["expected"])


def test_fixture_cases_any_page_order():
    for case in CASES:
        shuffled = rows(case)
        random.Random(case["name"]).shuffle(shuffled)
        assert as_dicts(project_chat(shuffled, conversation_id=case["conversation_id"])) == case["expected"]


def test_is_chat_event_allowlist_exhaustive():
    passing = set()
    for event_type in T:
        if event_type is T.USER_TRANSCRIPT_ACCEPTED:
            event = user("x")
        else:
            event = make_event(event_type, "x")
        if is_chat_event(event):
            passing.add(event_type)
    assert passing == set(CHAT_EVENT_TYPES) == {
        T.USER_TRANSCRIPT_ACCEPTED, T.BRAIN_MESSAGE_PUBLISHED, T.BRAIN_TURN_FAILED}


@pytest.mark.parametrize("addressing,shown", [
    (None, True), ("addressed", True), ("uncertain", True), ("ambient", False), ("ADDRESSED", False), ("", False),
])
def test_is_chat_event_addressing(addressing, shown):
    assert is_chat_event(user("x", addressing)) is shown


def test_uncertain_hidden_until_promoted():
    turn = user("u", "uncertain")
    accepted = make_event(T.BRAIN_TURN_ACCEPTED, "u")
    assert project_chat(stored(turn, accepted), conversation_id=CONV) == ()
    items = project_chat(stored(turn, accepted, reply("u")), conversation_id=CONV)
    # Shown at its own sequence, before the reply that promoted it.
    assert roles(items) == [("user", 1), ("brain", 3)]
    assert items[0].event_id == turn.event_id


def test_refused_uncertain_never_shown():
    # Declined by `[pas-pour-moi]`: no publication of its correlation, whatever else happens.
    events = stored(user("u", "uncertain"), make_event(T.BRAIN_TURN_ACCEPTED, "u"), user("a"), reply("a"),
                    user("v", "ambient"), reply("v"), failed("u"))
    items = project_chat(events, conversation_id=CONV)
    assert roles(items) == [("user", 3), ("brain", 4), ("brain", 6)]
    assert all(item.correlation_id != "corr-u" for item in items)


def test_page_replay_idempotent():
    events = stored(user("a"), reply("a"), user("b"), reply("b"))
    once = project_chat(events, conversation_id=CONV)
    assert project_chat(events + events[1:3] + events, conversation_id=CONV) == once
    assert project_chat(list(reversed(events)), conversation_id=CONV) == once


def test_cursor_split_promotion():
    # The uncertain turn ends page 1, the Brain message opens page 2.
    page_1 = stored(user("u", "uncertain"), make_event(T.BRAIN_TURN_ACCEPTED, "u"))
    page_2 = [StoredConversationEvent(3, BASE, reply("u"))]
    assert project_chat(page_1, conversation_id=CONV) == ()
    assert roles(project_chat(page_1 + page_2, conversation_id=CONV)) == [("user", 1), ("brain", 3)]
    assert roles(project_chat(page_2 + page_1, conversation_id=CONV)) == [("user", 1), ("brain", 3)]


def test_failed_on_system_turn_ignored():
    items = project_chat(stored(failed("system"), user("a"), reply("a")), conversation_id=CONV)
    assert roles(items) == [("user", 2), ("brain", 3)]
    assert all(item.failure_code is None for item in items)


def test_failed_status_on_user_bubble():
    items = project_chat(stored(user("a"), failed("a", "first"), failed("a", "second", 2)), conversation_id=CONV)
    # Never a bubble; the latest failure of the correlation is the status.
    assert roles(items) == [("user", 1)]
    assert items[0].failure_code == "second"
    without_code = project_chat(stored(user("a"), failed("a", None)), conversation_id=CONV)
    assert without_code[0].failure_code == UNKNOWN_FAILURE_CODE


def test_failed_on_unpromoted_uncertain_ignored():
    assert project_chat(stored(user("u", "uncertain"), failed("u")), conversation_id=CONV) == ()


def test_other_conversation_never_counts():
    other = "conv-b"
    events = stored(user("a"), reply("a"), reply("a", conversation_id=other), failed("a"))
    events[3] = StoredConversationEvent(4, BASE, make_event(T.BRAIN_TURN_FAILED, "failed-a-1", conversation_id=other,
                                                            correlation_id="corr-a", attributes={"code": "x"}))
    items = project_chat(events, conversation_id=CONV)
    assert roles(items) == [("user", 1), ("brain", 2)]
    assert items[0].failure_code is None and items[1].collapsed_event_ids == ()
    assert project_chat(events, conversation_id="conv-unknown") == ()
