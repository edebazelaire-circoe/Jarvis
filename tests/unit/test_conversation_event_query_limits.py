"""Core's hot path first: heavy conversation reads are capped and refused, never queued (Slice 06 rework).

Contract: `docs/conversation-events.md`, "Hot path". The service allows one search
and two transcript/export builds at once; over capacity it raises
`ConversationEventBusyError` (routes answer 429) and every slot comes back when
the work ends, fails, is cancelled or its export stream is closed.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.conversation_event_query import (
    PROJECTION_BUSY, SEARCH_BUSY, ConversationEventBusyError, ConversationEventQueryService,
)
import jarvis.domain.conversation_transcript as transcript_module
from jarvis.domain.conversation_event_search import SearchQuery
from jarvis.domain.conversation_events import ConversationEventType as T
from tests.fakes.conversation_events import make_event, open_store


@pytest.fixture
async def stack(tmp_path):
    state, store = await open_store(tmp_path / "state.sqlite3")
    await store.append_many([make_event(T.USER_TRANSCRIPT_ACCEPTED, f"u{i}", ms=i, content=f"Texte {i}")
                             for i in range(10)])
    try:
        yield store, ConversationEventQueryService(store)
    finally:
        await state.close()


def search(service):
    return service.search(SearchQuery.parse("texte"), conversation_id=None, before_sequence=None, limit=5,
                          visibility=None)


async def test_one_search_at_a_time_the_next_is_refused_not_queued(stack, monkeypatch):
    store, service = stack
    release = asyncio.Event()
    original = store.search_events

    async def slow(*args, **kwargs):
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(store, "search_events", slow)
    first = asyncio.create_task(search(service))
    await asyncio.sleep(0)
    with pytest.raises(ConversationEventBusyError) as caught:
        await asyncio.wait_for(search(service), 5)  # refused at once, never queued behind the first
    assert caught.value.code == SEARCH_BUSY and service.search_slots.in_use == 1
    release.set()
    assert len((await first).hits) == 5 and service.search_slots.in_use == 0
    monkeypatch.setattr(store, "search_events", original)
    assert (await search(service)).hits  # free again


async def test_a_cancelled_or_failing_search_gives_its_slot_back(stack, monkeypatch):
    store, service = stack
    started = asyncio.Event()

    async def hanging(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(store, "search_events", hanging)
    task = asyncio.create_task(search(service))
    await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert service.search_slots.in_use == 0

    async def failing(*args, **kwargs):
        raise RuntimeError("state repository is not initialized")

    monkeypatch.setattr(store, "search_events", failing)
    with pytest.raises(Exception):
        await search(service)
    assert service.search_slots.in_use == 0


async def test_two_projection_builds_at_most_and_every_exit_gives_the_slot_back(stack, monkeypatch):
    store, service = stack
    exports = [await service.open_export("conv-a"), await service.open_export("conv-a")]
    with pytest.raises(ConversationEventBusyError) as caught:
        await service.transcript("conv-a")
    assert caught.value.code == PROJECTION_BUSY
    with pytest.raises(ConversationEventBusyError):
        await service.open_export("conv-a")
    chunks = [chunk async for chunk in exports[0].chunks()]  # a finished stream releases
    assert chunks and service.projection_slots.in_use == 1
    exports[1].release()  # a stream never iterated (client gone before the first byte)
    exports[1].release()  # idempotent
    assert service.projection_slots.in_use == 0

    monkeypatch.setattr(transcript_module, "MAX_TRANSCRIPT_EVENTS", 3)
    with pytest.raises(transcript_module.TranscriptTooLargeError):
        await service.transcript("conv-a")
    assert service.projection_slots.in_use == 0

    stream = await service.open_export("conv-a")
    iterator = stream.chunks()
    await iterator.__anext__()
    await iterator.aclose()  # a client that left mid-stream
    assert service.projection_slots.in_use == 0

    async def broken(*args, **kwargs):
        raise RuntimeError("state repository is not initialized")

    monkeypatch.setattr(store, "conversation_extent", broken)
    with pytest.raises(Exception):
        await service.open_export("conv-a")
    assert service.projection_slots.in_use == 0
