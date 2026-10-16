"""`projection=chat` over a real Core and the Control Center relay (handoff jarvis-unified-chat-and-board-drop, Slice 05).

Chain: browser -> `ControlCenter` (origin guard) -> `ConversationEventView` ->
`CoreConversationEventReader` -> `LocalProtocolServer` -> store, Core in
`tmp_path`. Contract: `docs/chat.md`, "Reading". No new route: the Chat reads
`GET /api/conversations/events` with `projection=chat`.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.chat_projection import is_chat_event, project_chat
from jarvis.domain.conversation_event_query import decode_event_page, encode_event_page
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol.client import LocalCoreClient
from tests.fakes.conversation_events import make_event
from tests.integration.test_conversation_event_query_protocol import free_port, raw_get
from tests.integration.test_control_center_conversation_events import (
    TOKEN, control_center, core_running, get, mouth,
)

EVENTS = "/api/conversations/events"


def user(source: str, addressing: str = "addressed"):
    return make_event(T.USER_TRANSCRIPT_ACCEPTED, source, attributes={"source": "text", "addressing": addressing})


def reply(source: str, attempt: int = 1):
    """Publication of `corr-<source>`; a second attempt repeats the text (folded by the Chat)."""
    return make_event(T.BRAIN_MESSAGE_PUBLISHED, f"reply-{source}-{attempt}", correlation_id=f"corr-{source}",
                      content=f"reply {source}", attributes={"kind": "turn_result", "status": "completed"})


def failed(source: str):
    return make_event(T.BRAIN_TURN_FAILED, f"failed-{source}", correlation_id=f"corr-{source}",
                      attributes={"code": "brain_backend_exception"})


def conversation():
    """A Chat-shaped log: hidden voice/diagnostic rows around every chat event."""
    return [user("a"), make_event(T.BRAIN_TURN_ACCEPTED, "a"), mouth(1), reply("a"), mouth(2),
            user("u", "uncertain"), make_event(T.BRAIN_SPEECH_REQUESTED, "sp"), reply("u"), reply("u", 2),
            user("f"), failed("f"), user("x", "ambient_other"), mouth(3)]


async def hydrate(client, *, limit: int) -> tuple[list[dict], int]:
    rows, after = [], 0
    while True:
        status, page = await get(client, EVENTS, params={"conversation_id": "conv-a", "projection": "chat",
                                                         "limit": str(limit), "after_sequence": str(after)})
        assert status == 200
        rows += page["events"]
        after = page["next_cursor"]
        if not page["has_more"]:
            return rows, after


async def test_hydration_then_long_poll_equals_the_projection_of_the_store(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        log = conversation()
        await core.conversation_events.append_many(log)
        rows, cursor = await hydrate(client, limit=2)
        # Live: the long-poll waits past hidden rows, wakes on the Chat's next event only.
        poll = asyncio.create_task(get(client, EVENTS, params={
            "conversation_id": "conv-a", "projection": "chat", "after_sequence": str(cursor), "wait_ms": "20000"}))
        await asyncio.sleep(0.3)
        await core.conversation_events.append_many([mouth(4), make_event(T.BRAIN_SPEECH_REQUESTED, "sp2")])
        await asyncio.sleep(0.4)
        assert not poll.done()
        late = [user("b"), reply("b")]
        await core.conversation_events.append_many(late)
        status, page = await asyncio.wait_for(poll, 5)
        assert status == 200
        rows += page["events"]

        live = decode_event_page({**page, "events": rows}).events
        types = {item.event.event_type for item in live}
        assert types == {T.USER_TRANSCRIPT_ACCEPTED, T.BRAIN_MESSAGE_PUBLISHED, T.BRAIN_TURN_FAILED}
        assert all(is_chat_event(item.event) for item in live)
        everything = (await core.conversation_event_queries.events(
            "conv-a", after_sequence=0, limit=500, visibility=None)).events
        assert len(everything) == len(log) + 2 + len(late)
        assert project_chat(live, conversation_id="conv-a") == project_chat(everything, conversation_id="conv-a")
        failure = [item for item in project_chat(live, conversation_id="conv-a") if item.failure_code]
        assert [item.event_id for item in failure] == [user("f").event_id]


async def test_the_route_without_projection_is_unchanged(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        await core.conversation_events.append_many(conversation())
        direct = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        try:
            status, body = await get(client, EVENTS, params={"conversation_id": "conv-a", "limit": "5"})
            assert status == 200 and len(body["events"]) == 5
            assert body == encode_event_page(await direct.list_conversation_events("conv-a", limit=5))
            chat = await direct.list_conversation_events("conv-a", limit=5, projection="chat")
            status, body = await get(client, EVENTS, params={"conversation_id": "conv-a", "limit": "5",
                                                             "projection": "chat"})
            assert status == 200 and body == encode_event_page(chat) and chat.next_cursor == 5
        finally:
            await direct.close()


@pytest.mark.parametrize("params, fragment", [
    ({"projection": "chat", "visibility": "public"}, "projection and visibility must not be combined"),
    ({"projection": "timeline"}, "projection must be chat"),
])
async def test_invalid_projection_is_400_on_core_and_control_center(tmp_path, params, fragment):
    port = free_port()
    async with core_running(tmp_path, port), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        query = {"conversation_id": "conv-a", **params}
        status, body = await get(client, EVENTS, params=query)
        assert (status, body["code"]) == (400, "invalid_request") and fragment in body["error"]
        status, body = await raw_get(port, "/v1/conversation-events", query, token=TOKEN)
        assert (status, body["error"]["code"]) == (400, "invalid_request") and fragment in body["error"]["message"]


async def test_the_origin_guard_holds_for_the_chat_projection(tmp_path):
    async with control_center(tmp_path, free_port(), view=False) as (_, client, _):
        status, body = await get(client, EVENTS + "?conversation_id=a&projection=chat",
                                 headers={"Origin": "http://evil.example"})
        assert (status, body["code"]) == (403, "forbidden_origin")


async def test_chat_and_timeline_share_the_long_poll_cap(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client,
                                                                                           token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        view = control.conversation_event_view
        view.max_long_polls = 1
        timeline = asyncio.create_task(get(client, EVENTS, params={"conversation_id": "conv-a", "wait_ms": "20000"}))
        for _ in range(50):
            if view.long_polls == 1:
                break
            await asyncio.sleep(0.05)
        assert view.long_polls == 1
        # The Chat's long-poll counts against the same cap: sent as a plain poll, answered at once.
        status, page = await asyncio.wait_for(get(client, EVENTS, params={
            "conversation_id": "conv-a", "projection": "chat", "wait_ms": "20000"}), 5)
        assert status == 200 and page["events"] == [] and view.long_polls_downgraded == 1
        await core.conversation_events.append(user("a"))
        status, body = await asyncio.wait_for(timeline, 5)
        assert status == 200 and [e["event"]["event_id"] for e in body["events"]] == [user("a").event_id]
