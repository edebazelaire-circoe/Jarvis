"""`GET /v1/conversation-events...` over the real loopback protocol (Slice 04).

Chain: `LocalCoreClient` typed reads -> HTTP -> `LocalProtocolServer` ->
`ConversationEventQueryService` -> SQLite store. Contract:
`docs/conversation-events.md`, "Query and live API".
"""

from __future__ import annotations

import asyncio
import socket
import time

import aiohttp
import pytest

from jarvis.core.conversation_event_query import QUERY_FAILED_KIND, QUERY_RECOVERED_KIND
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_event_query import decode_event_page
from jarvis.domain.conversation_event_store import ConversationEventStoreError
from jarvis.domain.conversation_events import ConversationEventType as T, ConversationVisibility
from jarvis.domain.v2 import PROTOCOL_VERSION
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.conversation_events import RecordingDiagnostics, make_event

TOKEN = "q" * 48
VOICE = "voice.speech_scheduler"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def core_stack(tmp_path):
    port = free_port()
    diagnostics = RecordingDiagnostics()
    core = JarvisCoreApplication(data_root=tmp_path / "data", diagnostics=diagnostics)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, server, client, port, diagnostics
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def raw_get(port: int, path: str, params: dict | None = None, *, token: str = TOKEN) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}{path}", params=params, headers=headers) as response:
            return response.status, await response.json()


def mouth(index: int, conversation_id: str = "conv-a", **fields):
    return make_event(T.MOUTH_SPEECH_QUEUED, f"s{index}", producer=VOICE, conversation_id=conversation_id,
                      ms=index, **fields)


async def append(core, events) -> None:
    events = list(events)
    for start in range(0, len(events), 32):
        await core.conversation_events.append_many(events[start:start + 32])


async def walk(client, conversation_id: str, *, limit: int, after: int = 0, **query):
    """Page to the end; return (event ids in order, final cursor, pages)."""
    ids, pages = [], 0
    while True:
        page = await client.list_conversation_events(conversation_id, after_sequence=after, limit=limit, **query)
        pages += 1
        ids.extend(item.event.event_id for item in page.events)
        after = page.next_cursor
        if not page.has_more:
            return ids, after, pages


# ----------------------------------------------------------------- basics

async def test_every_read_route_requires_the_session_token(core_stack):
    _, _, _, port, _ = core_stack
    for path in ("/v1/conversation-events?conversation_id=conv-a", "/v1/conversation-events/conversations",
                 "/v1/conversation-events/sessions?conversation_id=conv-a",
                 "/v1/conversation-events/lookup?field=speech_id&value=x",
                 "/v1/conversation-events/events/cev-" + "0" * 64):
        status, body = await raw_get(port, path, token="x" * 48)
        assert (status, body["error"]["code"]) == (401, "unauthorized"), path


async def test_pages_carry_the_stored_events_exactly_with_sequence_and_recorded_at(core_stack):
    core, _, client, port, _ = core_stack
    events = [mouth(i) for i in range(5)] + [mouth(99, conversation_id="conv-b")]
    await append(core, events)
    page = await client.list_conversation_events("conv-a", limit=3)
    stored = await core.conversation_events.list_conversation_events("conv-a", limit=3)
    assert page == stored
    assert page.has_more is True and page.next_cursor == stored.events[-1].sequence
    status, body = await raw_get(port, "/v1/conversation-events", {"conversation_id": "conv-a", "limit": "3"})
    assert status == 200 and set(body) == {"schema_version", "events", "next_cursor", "has_more", "skipped_rows"}
    assert set(body["events"][0]) == {"sequence", "recorded_at", "event"}
    assert decode_event_page(body) == stored


async def test_an_unknown_conversation_is_an_empty_page_not_a_404(core_stack):
    _, _, client, _, _ = core_stack
    page = await client.list_conversation_events("conv-never-seen", after_sequence=7)
    assert (page.events, page.next_cursor, page.has_more, page.skipped_rows) == ((), 7, False, 0)


async def test_has_more_is_false_exactly_when_the_last_page_is_full(core_stack):
    core, _, client, _, _ = core_stack
    await append(core, [mouth(i) for i in range(4)])
    first = await client.list_conversation_events("conv-a", limit=2)
    second = await client.list_conversation_events("conv-a", after_sequence=first.next_cursor, limit=2)
    assert (len(first.events), first.has_more, len(second.events), second.has_more) == (2, True, 2, False)
    empty = await client.list_conversation_events("conv-a", after_sequence=second.next_cursor, limit=2)
    assert (empty.events, empty.next_cursor, empty.has_more) == ((), second.next_cursor, False)
    all_four = await client.list_conversation_events("conv-a", limit=4)
    assert (len(all_four.events), all_four.has_more) == (4, False)


async def test_limits_are_the_store_maxima(core_stack):
    core, _, client, port, _ = core_stack
    await append(core, [mouth(i) for i in range(3)])
    assert len((await client.list_conversation_events("conv-a", limit=500)).events) == 3
    for path, params in (("/v1/conversation-events", {"conversation_id": "conv-a", "limit": "501"}),
                         ("/v1/conversation-events", {"conversation_id": "conv-a", "limit": "0"}),
                         ("/v1/conversation-events/conversations", {"limit": "101"}),
                         ("/v1/conversation-events/sessions", {"conversation_id": "conv-a", "limit": "101"}),
                         ("/v1/conversation-events/lookup", {"field": "speech_id", "value": "x", "limit": "501"}),
                         ("/v1/conversation-events", {"conversation_id": "conv-a", "wait_ms": "25001"})):
        status, body = await raw_get(port, path, params)
        assert (status, body["error"]["code"]) == (400, "invalid_request"), (path, params)


@pytest.mark.parametrize(("path", "params", "fragment"), [
    ("/v1/conversation-events", {"conversation_id": "conv-a", "after_sequence": "-1SECRET"}, "after_sequence"),
    ("/v1/conversation-events", {"conversation_id": "conv-a", "limit": "SECRET"}, "limit"),
    ("/v1/conversation-events", {"conversation_id": "conv-a", "limit": "１２"}, "limit"),
    ("/v1/conversation-events", {"conversation_id": " SECRET "}, "conversation_id"),
    ("/v1/conversation-events", {}, "conversation_id is required"),
    ("/v1/conversation-events", {"conversation_id": "conv-a", "SECRET_PARAM": "1"}, "unexpected query parameter"),
    ("/v1/conversation-events", {"conversation_id": "conv-a", "visibility": "SECRET"}, "visibility"),
    ("/v1/conversation-events/lookup", {"field": "SECRET_FIELD", "value": "x"}, "field must be one of"),
    ("/v1/conversation-events/lookup", {"field": "task_id"}, "value is required"),
    ("/v1/conversation-events/conversations", {"before_sequence": "1e3SECRET"}, "before_sequence"),
    ("/v1/conversation-events/events/cev-SECRET", {}, "event_id must match"),
])
async def test_invalid_parameters_are_400_without_echoing_values(core_stack, path, params, fragment):
    _, _, _, port, _ = core_stack
    status, body = await raw_get(port, path, params)
    assert (status, body["error"]["code"]) == (400, "invalid_request")
    assert fragment in body["error"]["message"] and "SECRET" not in body["error"]["message"]


async def test_a_repeated_parameter_is_refused(core_stack):
    _, _, _, port, _ = core_stack
    status, body = await raw_get(port, "/v1/conversation-events?conversation_id=a&limit=1&limit=2")
    assert status == 400 and "limit must not be repeated" in body["error"]["message"]


# -------------------------------------------------- cursor, reload and live

async def test_paging_while_producers_append_neither_loses_nor_repeats_and_equals_a_reload(core_stack):
    core, _, client, _, _ = core_stack
    total = 400
    events = [mouth(i) for i in range(total)] + [mouth(i, conversation_id="conv-noise") for i in range(total)]

    async def producer():
        for start in range(0, total, 16):
            # interleave two conversations so conv-a sequences have gaps
            await core.conversation_events.append_many(events[start:start + 16])
            await core.conversation_events.append_many(events[total + start:total + start + 16])
            await asyncio.sleep(0)

    live_ids, after = [], 0
    task = asyncio.create_task(producer())
    while True:
        page = await client.list_conversation_events("conv-a", after_sequence=after, limit=7)
        live_ids.extend(item.event.event_id for item in page.events)
        after = page.next_cursor
        if task.done() and not page.has_more:
            break
    await task
    # one more poll after the producer finished: nothing is left behind the cursor
    tail = await client.list_conversation_events("conv-a", after_sequence=after, limit=500)
    live_ids.extend(item.event.event_id for item in tail.events)
    reload_ids, _, _ = await walk(client, "conv-a", limit=500)
    expected = [event.event_id for event in events[:total]]
    assert len(live_ids) == len(set(live_ids)) == total
    assert live_ids == reload_ids == expected


async def test_a_reconnect_resumes_from_the_last_cursor_without_duplicates(core_stack):
    core, server, client, port, _ = core_stack
    await append(core, [mouth(i) for i in range(10)])
    first = await client.list_conversation_events("conv-a", limit=4)
    seen = [item.event.event_id for item in first.events]
    # the consumer "disconnects": its client goes away, events keep arriving
    await client.close()
    await append(core, [mouth(i) for i in range(10, 15)])
    fresh = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        ids, _, _ = await walk(fresh, "conv-a", limit=3, after=first.next_cursor)
    finally:
        await fresh.close()
    assert seen + ids == [mouth(i).event_id for i in range(15)]


async def test_public_visibility_filter_keeps_the_cursor_of_the_scan(core_stack):
    core, _, client, _, _ = core_stack
    queued = [mouth(i) for i in range(3)]  # diagnostic
    started = [make_event(T.MOUTH_SPEECH_STARTED, f"p{i}", producer=VOICE, ms=10 + i) for i in range(2)]  # public
    await append(core, [queued[0], started[0], queued[1], queued[2], started[1]])
    page = await client.list_conversation_events("conv-a", limit=2, visibility=ConversationVisibility.PUBLIC)
    assert [item.event.event_id for item in page.events] == [started[0].event_id]
    assert page.has_more is True
    only_diagnostic = await client.list_conversation_events("conv-a", after_sequence=page.next_cursor, limit=2,
                                                            visibility=ConversationVisibility.PUBLIC)
    assert only_diagnostic.events == () and only_diagnostic.next_cursor > page.next_cursor
    ids, _, _ = await walk(client, "conv-a", limit=2, visibility=ConversationVisibility.PUBLIC)
    assert ids == [event.event_id for event in started]


# --------------------------------------------------------------- long-poll

async def test_a_long_poll_returns_as_soon_as_an_event_is_appended(core_stack):
    core, _, client, _, _ = core_stack
    await append(core, [mouth(0)])
    cursor = (await client.list_conversation_events("conv-a")).next_cursor
    started = time.monotonic()
    poll = asyncio.create_task(client.list_conversation_events("conv-a", after_sequence=cursor, wait_ms=20_000))
    await asyncio.sleep(0.3)
    assert not poll.done()
    await append(core, [mouth(1, conversation_id="conv-other")])  # another conversation: keeps waiting
    await asyncio.sleep(0.2)
    assert not poll.done()
    await append(core, [mouth(1)])
    page = await asyncio.wait_for(poll, 5)
    elapsed = time.monotonic() - started
    assert [item.event.event_id for item in page.events] == [mouth(1).event_id]
    assert 0.4 < elapsed < 3.0


async def test_a_long_poll_without_append_times_out_bounded_with_an_empty_page(core_stack):
    _, _, client, _, _ = core_stack
    started = time.monotonic()
    page = await client.list_conversation_events("conv-a", after_sequence=0, wait_ms=600)
    elapsed = time.monotonic() - started
    assert (page.events, page.next_cursor, page.has_more) == ((), 0, False)
    assert 0.55 < elapsed < 3.0


async def test_an_event_appended_between_the_query_and_the_wait_is_not_missed(core_stack, monkeypatch):
    core, _, client, _, _ = core_stack
    store = core.conversation_events
    original = store.list_conversation_events
    calls = 0

    async def query_then_append(*args, **kwargs):
        nonlocal calls
        calls += 1
        page = await original(*args, **kwargs)
        if calls == 1:
            await store.append(mouth(5))  # lands after the empty read, before the wait
        return page

    monkeypatch.setattr(store, "list_conversation_events", query_then_append)
    started = time.monotonic()
    page = await client.list_conversation_events("conv-a", wait_ms=20_000)
    assert [item.event.event_id for item in page.events] == [mouth(5).event_id]
    assert time.monotonic() - started < 3.0


async def test_server_stop_releases_a_pending_long_poll(core_stack):
    core, server, client, _, _ = core_stack
    poll = asyncio.create_task(client.list_conversation_events("conv-a", wait_ms=25_000))
    await asyncio.sleep(0.3)
    started = time.monotonic()
    await server.stop()
    page = await asyncio.wait_for(poll, 5)
    assert page.events == ()
    assert time.monotonic() - started < 5.0


# ------------------------------------------------------ failures and damage

async def test_store_failure_is_a_503_diagnosed_once_per_episode(core_stack, monkeypatch):
    core, _, client, port, diagnostics = core_stack

    async def broken(*args, **kwargs):
        raise ConversationEventStoreError("conversation event query failed: OperationalError: disk I/O error")

    monkeypatch.setattr(core.conversation_events, "list_conversation_events", broken)
    monkeypatch.setattr(core.conversation_events, "list_conversations", broken)
    for _ in range(3):
        with pytest.raises(CoreProtocolError) as caught:
            await client.list_conversation_events("conv-a")
        assert (caught.value.status, caught.value.code) == (503, "conversation_events_unavailable")
    status, body = await raw_get(port, "/v1/conversation-events/conversations")
    assert status == 503 and "disk" not in body["error"]["message"]
    failed = [entry for entry in diagnostics.entries if entry[0] == QUERY_FAILED_KIND]
    assert len(failed) == 1 and failed[0][3]["error_class"] == "ConversationEventStoreError"
    monkeypatch.undo()
    await client.list_conversation_events("conv-a")
    assert diagnostics.kinds().count(QUERY_RECOVERED_KIND) == 1


async def test_a_closed_repository_answers_503(core_stack):
    core, _, client, _, _ = core_stack
    await core.state.close()
    with pytest.raises(CoreProtocolError) as caught:
        await client.list_event_conversations()
    assert caught.value.status == 503


async def test_unreadable_rows_are_skipped_counted_and_a_lookup_of_one_is_404(core_stack):
    core, _, client, _, diagnostics = core_stack
    await append(core, [mouth(i) for i in range(4)])
    await core.state.run_serialized(lambda conn: conn.execute(
        "UPDATE conversation_events SET data='{\"broken' WHERE event_id=?", (mouth(1).event_id,)))
    page = await client.list_conversation_events("conv-a", limit=500)
    assert page.skipped_rows == 1 and len(page.events) == 3
    assert await client.get_conversation_event(mouth(1).event_id) is None
    assert (await client.get_conversation_event(mouth(2).event_id)).event == mouth(2)
    assert await client.get_conversation_event("cev-" + "f" * 64) is None
    assert "core.conversation_events.row_unreadable" in diagnostics.kinds()


# ------------------------------------------------------- listings and lookup

async def test_conversation_listing_sessions_and_lookup(core_stack):
    core, _, client, _, _ = core_stack
    await append(core, [mouth(0, conversation_id="conv-old"),
                        mouth(1, session_id="sess-1"), mouth(2, session_id="sess-2"), mouth(3, session_id="sess-1"),
                        mouth(4, conversation_id="conv-new")])
    first = await client.list_event_conversations(limit=2)
    assert [s.conversation_id for s in first.summaries] == ["conv-new", "conv-a"] and first.has_more
    rest = await client.list_event_conversations(before_sequence=first.next_cursor, limit=2)
    assert [s.conversation_id for s in rest.summaries] == ["conv-old"] and not rest.has_more
    sessions = await client.list_event_sessions("conv-a")
    assert [(s.session_id, s.event_count) for s in sessions.summaries] == [("sess-1", 2), ("sess-2", 1)]
    lookup = await client.lookup_conversation_events("speech_id", mouth(2).speech_id)
    assert [item.event.event_id for item in lookup.events] == [mouth(2).event_id]
    scoped = await client.lookup_conversation_events("correlation_id", mouth(4).correlation_id,
                                                     conversation_id="conv-a")
    assert scoped.events == ()


async def test_health_exposes_conversation_event_loss_counters(core_stack):
    core, _, client, _, _ = core_stack
    health = await client.health()
    block = health["conversation_events"]
    assert set(block) == {"emitter", "store", "query_failures"}
    assert {"enqueued", "dropped_queue_full", "dropped_store_error", "ingest_failures"} <= set(block["emitter"])
    assert block["store"] == {"unreadable_rows": 0, "diagnostic_failures": 0}


# ---------------------------------------------------------------- long session

async def test_a_long_session_of_5000_events_pages_quickly(core_stack):
    core, _, client, _, _ = core_stack
    events = [mouth(i) for i in range(5000)]
    await append(core, events)
    started = time.perf_counter()
    ids, _, pages = await walk(client, "conv-a", limit=500)
    by_500 = time.perf_counter() - started
    started = time.perf_counter()
    ids_100, _, pages_100 = await walk(client, "conv-a", limit=100)
    by_100 = time.perf_counter() - started
    print(f"5000 events: limit 500 -> {pages} pages in {by_500:.2f} s; limit 100 -> {pages_100} pages in {by_100:.2f} s")
    assert ids == ids_100 == [event.event_id for event in events]
    assert (pages, pages_100) == (10, 50)
    # sanity bound, generous for a loaded CI host
    assert by_500 < 20 and by_100 < 30


# ------------------------------------------------------ rework (QA S3, S4, nits)

async def test_append_watches_are_per_conversation_and_cleaned_up(core_stack):
    core, _, _, _, _ = core_stack
    store = core.conversation_events
    with store.watch_appends("conv-a") as watched_a, store.watch_appends("conv-a") as shared:
        assert shared is watched_a and store.watched_conversations == 1
        await store.append(mouth(1, conversation_id="conv-b"))
        assert not watched_a.is_set()
        await store.append(mouth(2))
        assert watched_a.is_set()
        with store.watch_appends("conv-a") as fresh:
            assert fresh is not watched_a and not fresh.is_set()
    assert store.watched_conversations == 0


async def test_appends_to_other_conversations_never_requery_waiting_long_polls(core_stack, monkeypatch):
    core, _, client, _, _ = core_stack
    store = core.conversation_events
    original = store.list_conversation_events
    queries: list[str] = []

    async def counted(conversation_id, **kwargs):
        queries.append(conversation_id)
        return await original(conversation_id, **kwargs)

    monkeypatch.setattr(store, "list_conversation_events", counted)
    polls = [asyncio.create_task(client.list_conversation_events("conv-quiet", wait_ms=20_000)) for _ in range(20)]
    await wait_for(lambda: len(queries) == 20 and store.watched_conversations == 1)
    started = time.perf_counter()
    for index in range(30):
        await store.append(mouth(index, conversation_id="conv-busy"))
    append_s = time.perf_counter() - started
    await asyncio.sleep(0.2)
    assert queries.count("conv-quiet") == 20  # no waiter was woken by conv-busy appends
    await store.append(mouth(99, conversation_id="conv-quiet"))
    pages = await asyncio.wait_for(asyncio.gather(*polls), 5)
    assert all([item.event.event_id for item in page.events] == [mouth(99, "conv-quiet").event_id] for page in pages)
    print(f"30 appends with 20 waiters on another conversation: {append_s * 1000:.0f} ms")


async def test_a_filtered_long_poll_waits_past_hidden_events_and_returns_the_advanced_cursor(core_stack):
    core, _, client, _, _ = core_stack
    poll = asyncio.create_task(client.list_conversation_events("conv-a", visibility=ConversationVisibility.PUBLIC,
                                                               wait_ms=20_000))
    await asyncio.sleep(0.3)
    await core.conversation_events.append_many([mouth(i) for i in range(3)])  # diagnostic only
    await asyncio.sleep(0.4)
    assert not poll.done()
    public = make_event(T.MOUTH_SPEECH_STARTED, "p1", producer=VOICE, ms=50)
    stored = await core.conversation_events.append(public)
    page = await asyncio.wait_for(poll, 5)
    assert [item.event.event_id for item in page.events] == [public.event_id]
    assert page.next_cursor == stored.sequence

    hidden = await core.conversation_events.append(mouth(10))
    timed_out = await client.list_conversation_events("conv-a", after_sequence=page.next_cursor, wait_ms=500,
                                                      visibility=ConversationVisibility.PUBLIC)
    assert timed_out.events == () and timed_out.next_cursor == hidden.sequence


async def test_a_client_that_disconnects_releases_the_core_wait(core_stack):
    core, _, _, port, _ = core_stack
    store = core.conversation_events
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    session = aiohttp.ClientSession()
    request = asyncio.create_task(session.get(f"http://127.0.0.1:{port}/v1/conversation-events",
                                              params={"conversation_id": "conv-a", "wait_ms": "25000"},
                                              headers=headers))
    await wait_for(lambda: store.watched_conversations == 1)
    request.cancel()
    await asyncio.gather(request, return_exceptions=True)
    await session.close()
    started = time.monotonic()
    await wait_for(lambda: store.watched_conversations == 0, timeout_s=5)
    assert time.monotonic() - started < 3.0


async def wait_for(predicate, *, timeout_s: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.02)
