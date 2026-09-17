"""Wire contract of the Conversation Event query API (Slice 04, pure domain).

`jarvis/domain/conversation_event_query.py`: strict parameters (no value
echoed) and strict response decoding shared by Core, the client and the
Control Center.
"""

from __future__ import annotations

import copy

import pytest

from jarvis.domain.conversation_event_query import (
    EVENTS_PARAMS, MAX_WAIT_MS, check_event_id, decode_event_page, decode_event_response, decode_summary_page,
    encode_event_page, encode_event_response, encode_summary_page, events_query, filter_visibility, lookup_query,
    query_params,
)
from jarvis.domain.conversation_event_store import (
    ConversationEventPage, ConversationEventSummary, ConversationEventSummaryPage, StoredConversationEvent,
)
from jarvis.domain.conversation_events import ConversationEventType as T, ConversationVisibility
from tests.fakes.conversation_events import BASE, make_event


def stored(sequence: int, event_type=T.MOUTH_SPEECH_QUEUED, source: str | None = None) -> StoredConversationEvent:
    return StoredConversationEvent(sequence, BASE, make_event(event_type, source or f"s{sequence}", ms=sequence))


def page() -> ConversationEventPage:
    return ConversationEventPage((stored(3), stored(5, T.MOUTH_SPEECH_STARTED)), 6, True, 1)


def test_pages_round_trip_exactly():
    assert decode_event_page(encode_event_page(page()), after_sequence=2) == page()
    assert decode_event_response(encode_event_response(stored(4))) == stored(4)
    summaries = ConversationEventSummaryPage((ConversationEventSummary("conv-a", None, 3, 1, 9, BASE, BASE, BASE),),
                                             9, False, 2)
    assert decode_summary_page(encode_summary_page(summaries)) == summaries
    empty = ConversationEventSummaryPage((), None, False, 0)
    assert decode_summary_page(encode_summary_page(empty)) == empty


@pytest.mark.parametrize("mutate", [
    lambda body: body.update(extra=1),
    lambda body: body.update(schema_version=2),
    lambda body: body.update(has_more=1),
    lambda body: body.update(skipped_rows=True),
    lambda body: body.update(next_cursor=4),  # behind the last event
    lambda body: body["events"].reverse(),  # sequences must ascend
    lambda body: body["events"][0].update(sequence=2),  # not past the request cursor
    lambda body: body["events"][0]["event"].update(content="x" * 9000),
    lambda body: body["events"][0].update(recorded_at="yesterday"),
])
def test_an_answer_out_of_contract_is_a_value_error(mutate):
    body = copy.deepcopy(encode_event_page(page()))
    mutate(body)
    with pytest.raises(ValueError):
        decode_event_page(body, after_sequence=2)


def test_parameters_are_strict_and_never_echo_values():
    with pytest.raises(ValueError, match="unexpected query parameter") as caught:
        query_params([("conversation_id", "a"), ("SECRET", "1")], EVENTS_PARAMS)
    assert "SECRET" not in str(caught.value)
    with pytest.raises(ValueError, match="must not be repeated"):
        query_params([("limit", "1"), ("limit", "2")], EVENTS_PARAMS)
    for raw in ("-1", "+1", "1.0", " 1", "SECRET", "٣", "1" * 20):
        with pytest.raises(ValueError) as caught:
            events_query({"conversation_id": "a", "after_sequence": raw})
        assert "SECRET" not in str(caught.value) and "1.0" not in str(caught.value)
    assert events_query({"conversation_id": "a"}) == {"conversation_id": "a", "after_sequence": 0, "limit": 100,
                                                      "visibility": None, "wait_ms": 0}
    assert events_query({"conversation_id": "a", "wait_ms": str(MAX_WAIT_MS)})["wait_ms"] == MAX_WAIT_MS
    with pytest.raises(ValueError, match="opaque identifier"):
        events_query({"conversation_id": "a\udc80"})
    with pytest.raises(ValueError, match="field must be one of"):
        lookup_query({"field": "conversation_id", "value": "x"})
    with pytest.raises(ValueError, match="cev-"):
        check_event_id("cev-" + "A" * 64)


def test_visibility_filter_keeps_the_scan_cursor():
    filtered = filter_visibility(page(), ConversationVisibility.PUBLIC)
    assert [item.sequence for item in filtered.events] == [5]
    assert (filtered.next_cursor, filtered.has_more, filtered.skipped_rows) == (6, True, 1)
    assert filter_visibility(page(), None) == page()
