"""`projection=chat` on the conversation-events read (handoff jarvis-unified-chat-and-board-drop, Slice 05).

Contract: `docs/chat.md`, "Reading", and `docs/conversation-events.md`,
"Cursor, reconnect and live". The filter is the stateless `is_chat_event`
applied after the scan, at the same place as `visibility`: the cursor still
advances past hidden rows and a filtered long-poll waits past them.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.conversation_event_query import ConversationEventQueryService
from jarvis.domain.chat_projection import CHAT_PROJECTION, is_chat_event, project_chat
from jarvis.domain.conversation_event_query import EVENTS_PARAMS, events_query, filter_projection, query_params
from jarvis.domain.conversation_event_store import ConversationEventPage
from jarvis.domain.conversation_events import ConversationEventType as T
from tests.fakes.conversation_events import make_event, open_store

VOICE = "voice.speech_scheduler"


def mouth(index: int, conversation_id: str = "conv-a"):
    return make_event(T.MOUTH_SPEECH_QUEUED, f"s{index}", producer=VOICE, conversation_id=conversation_id, ms=index)


def user(source: str, conversation_id: str = "conv-a", addressing: str = "addressed"):
    return make_event(T.USER_TRANSCRIPT_ACCEPTED, source, conversation_id=conversation_id,
                      attributes={"source": "text", "addressing": addressing})


def reply(source: str, conversation_id: str = "conv-a"):
    return make_event(T.BRAIN_MESSAGE_PUBLISHED, f"reply-{source}", conversation_id=conversation_id,
                      correlation_id=f"corr-{source}", attributes={"kind": "turn_result", "status": "completed"})


@pytest.fixture
async def stack(tmp_path):
    state, store = await open_store(tmp_path / "state.sqlite3")
    try:
        yield store, ConversationEventQueryService(store)
    finally:
        await state.close()


async def walk(service, conversation_id: str, *, limit: int, after: int = 0):
    """Page to the end with the Chat projection; return (stored rows, final cursor)."""
    rows = []
    while True:
        page = await service.events(conversation_id, after_sequence=after, limit=limit, visibility=None,
                                    projection=CHAT_PROJECTION)
        rows.extend(page.events)
        after = page.next_cursor
        if not page.has_more:
            return rows, after


def test_projection_param_strict():
    assert events_query({"conversation_id": "a", "projection": "chat"})["projection"] == CHAT_PROJECTION
    assert events_query({"conversation_id": "a"})["projection"] is None
    for raw in ("Chat", "timeline", "", "SECRET"):
        with pytest.raises(ValueError, match="projection must be chat") as caught:
            events_query({"conversation_id": "a", "projection": raw})
        assert "SECRET" not in str(caught.value)
    with pytest.raises(ValueError, match="projection must not be repeated"):
        query_params([("conversation_id", "a"), ("projection", "chat"), ("projection", "chat")], EVENTS_PARAMS)
    with pytest.raises(ValueError, match="projection and visibility must not be combined"):
        events_query({"conversation_id": "a", "projection": "chat", "visibility": "public"})
    page = ConversationEventPage((), 7, True, 2)
    assert filter_projection(page, None) is page
    assert filter_projection(page, CHAT_PROJECTION) == page


async def test_filtered_page_advances_cursor(stack):
    store, service = stack
    await store.append_many([mouth(i) for i in range(5)] + [user("a"), reply("a")])
    page = await service.events("conv-a", after_sequence=0, limit=3, visibility=None, projection=CHAT_PROJECTION)
    assert page.events == () and page.has_more is True and page.next_cursor == 3
    rows, cursor = await walk(service, "conv-a", limit=3)
    assert [row.event.event_id for row in rows] == [user("a").event_id, reply("a").event_id]
    assert cursor == 7
    # Without `projection` the same page is unchanged (every type, same cursor).
    plain = await service.events("conv-a", after_sequence=0, limit=3, visibility=None)
    assert len(plain.events) == 3 and plain.next_cursor == 3


async def test_long_poll_waits_past_hidden_events(stack):
    store, service = stack
    poll = asyncio.create_task(service.events("conv-a", after_sequence=0, limit=100, visibility=None,
                                              projection=CHAT_PROJECTION, wait_s=10))
    await asyncio.sleep(0.2)
    await store.append_many([mouth(i) for i in range(3)])
    await store.append(make_event(T.BRAIN_SPEECH_REQUESTED, "sp", correlation_id="corr-a"))
    await asyncio.sleep(0.3)
    assert not poll.done()
    stored = await store.append(reply("a"))
    page = await asyncio.wait_for(poll, 5)
    assert [row.event.event_id for row in page.events] == [reply("a").event_id]
    assert page.next_cursor == stored.sequence

    hidden = await store.append(mouth(10))
    timed_out = await service.events("conv-a", after_sequence=page.next_cursor, limit=100, visibility=None,
                                     projection=CHAT_PROJECTION, wait_s=0.3)
    assert timed_out.events == () and timed_out.next_cursor == hidden.sequence


async def test_union_reload_equals_live(stack):
    store, service = stack
    turns = 40

    def batch(index: int, conversation_id: str):
        source = f"{conversation_id}-{index}"
        return [user(source, conversation_id), mouth(index, conversation_id), reply(source, conversation_id),
                user(f"{source}-amb", conversation_id, addressing="ambient_other")]

    async def producer():
        for index in range(turns):
            # Two interleaved conversations: conv-a sequences have gaps, half its rows are hidden.
            await store.append_many(batch(index, "conv-a"))
            await store.append_many(batch(index, "conv-b"))
            await asyncio.sleep(0)

    live, after = [], 0
    task = asyncio.create_task(producer())
    while True:
        page = await service.events("conv-a", after_sequence=after, limit=5, visibility=None,
                                    projection=CHAT_PROJECTION)
        live.extend(page.events)
        after = page.next_cursor
        if task.done() and not page.has_more:
            break
    await task
    tail, _ = await walk(service, "conv-a", limit=500, after=after)
    live.extend(tail)
    reload, _ = await walk(service, "conv-a", limit=500)
    ids = [row.event.event_id for row in live]
    assert len(ids) == len(set(ids)) == 2 * turns
    assert ids == [row.event.event_id for row in reload]
    assert all(is_chat_event(row.event) and row.event.conversation_id == "conv-a" for row in live)
    # The projection of the filtered stream equals the projection of the whole store.
    everything = (await service.events("conv-a", after_sequence=0, limit=500, visibility=None)).events
    assert project_chat(live, conversation_id="conv-a") == project_chat(everything, conversation_id="conv-a")
    assert len(project_chat(live, conversation_id="conv-a")) == 2 * turns


async def test_unknown_conversation_empty_page(stack):
    store, service = stack
    await store.append_many([user("a"), reply("a")])
    page = await service.events("conv-unknown", after_sequence=0, limit=100, visibility=None,
                                projection=CHAT_PROJECTION)
    assert (page.events, page.next_cursor, page.has_more, page.skipped_rows) == ((), 0, False, 0)
