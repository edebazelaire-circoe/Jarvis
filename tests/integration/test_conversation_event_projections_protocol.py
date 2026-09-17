"""Transcript, JSONL export and search over the real Core protocol (Slice 06).

Chain: `LocalCoreClient` -> HTTP -> `LocalProtocolServer` ->
`ConversationEventQueryService` -> SQLite store. Contract:
`docs/conversation-events.md`, "Readable transcript", "JSONL export", "Search".
"""

from __future__ import annotations

import asyncio
import io
import json

import aiohttp
import pytest

import jarvis.domain.conversation_transcript as transcript_module
from jarvis.core.conversation_event_query import PROJECTION_PAGE_LIMIT, QUERY_FAILED_KIND
from jarvis.domain.conversation_event_export import read_export, transcript_from_export
from jarvis.domain.conversation_event_store import ConversationEventStoreError
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.conversation_transcript import TranscriptMode, render_transcript
from jarvis.protocol.client import CoreProtocolError
from tests.fakes.conversation_events import make_event, transcript_scenario
from tests.integration.test_conversation_event_query_protocol import TOKEN, append, core_stack, raw_get  # noqa: F401

VOICE = "voice.speech_scheduler"


async def export_bytes(client, conversation_id: str) -> bytes:
    buffer = io.BytesIO()
    async for chunk in client.export_conversation_events(conversation_id):
        buffer.write(chunk)
    return buffer.getvalue()


async def raw_text(port: int, path: str, params: dict | None = None, *, token: str = TOKEN):
    headers = {"Authorization": f"Bearer {token}", "X-Jarvis-Protocol": "1"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}{path}", params=params, headers=headers) as response:
            return response.status, response.headers, await response.read()


# ----------------------------------------------------------------- guards

async def test_the_projection_routes_require_the_session_token(core_stack):
    _, _, _, port, _ = core_stack
    for path in ("/v1/conversation-events/transcript?conversation_id=conv-t",
                 "/v1/conversation-events/export?conversation_id=conv-t",
                 "/v1/conversation-events/search?q=vol"):
        status, body = await raw_get(port, path, token="x" * 48)
        assert (status, body["error"]["code"]) == (401, "unauthorized"), path


@pytest.mark.parametrize(("path", "params", "fragment"), [
    ("/v1/conversation-events/transcript", {}, "conversation_id is required"),
    ("/v1/conversation-events/transcript", {"conversation_id": "c", "mode": "PLANTED-mode"}, "mode must be one of"),
    ("/v1/conversation-events/export", {"conversation_id": "c", "extra": "PLANTED"}, "unexpected query parameter"),
    ("/v1/conversation-events/search", {"q": "PLANTED" * 40}, "q must be at most"),
    ("/v1/conversation-events/search", {"q": "   "}, "at least one non-blank term"),
    ("/v1/conversation-events/search", {"q": "vol", "before_sequence": "0"}, "before_sequence"),
    ("/v1/conversation-events/search", {"q": "vol", "limit": "PLANTED"}, "limit must be"),
])
async def test_invalid_parameters_are_400_without_echoing_values(core_stack, path, params, fragment):
    _, _, _, port, _ = core_stack
    status, body = await raw_get(port, path, params)
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert fragment in body["error"]["message"] and "PLANTED" not in json.dumps(body)


async def test_storage_failures_answer_503_and_are_diagnosed_once(core_stack, monkeypatch):
    core, _, client, port, diagnostics = core_stack

    async def broken(*args, **kwargs):
        raise ConversationEventStoreError("disk I/O error PLANTED")

    for name in ("list_conversation_events", "conversation_extent", "search_events"):
        monkeypatch.setattr(core.conversation_events, name, broken)
    for path in ("/v1/conversation-events/transcript?conversation_id=conv-t",
                 "/v1/conversation-events/export?conversation_id=conv-t", "/v1/conversation-events/search?q=vol"):
        status, body = await raw_get(port, path)
        assert (status, body["error"]["code"]) == (503, "conversation_events_unavailable"), path
        assert "PLANTED" not in json.dumps(body)
    assert diagnostics.kinds().count(QUERY_FAILED_KIND) == 1
    with pytest.raises(CoreProtocolError) as caught:
        await client.get_conversation_transcript("conv-t")
    assert caught.value.status == 503


# ------------------------------------------------------------- transcript

async def test_transcript_route_serves_the_domain_rendering_as_utf8_text(core_stack):
    core, _, client, port, _ = core_stack
    events = transcript_scenario()
    await append(core, events)
    for mode in TranscriptMode:
        text = await client.get_conversation_transcript("conv-t", mode=mode)
        assert text == render_transcript(events, conversation_id="conv-t", mode=mode)
    status, headers, body = await raw_text(port, "/v1/conversation-events/transcript", {"conversation_id": "conv-t"})
    assert status == 200 and headers["Content-Type"] == "text/plain; charset=utf-8"
    assert body.decode("utf-8").startswith("Transcription de conversation · conv-t\n")
    unknown = await client.get_conversation_transcript("conv-never")
    assert unknown.endswith("(aucun échange public enregistré)\n")


async def test_a_transcript_too_large_to_hold_is_413_pointing_to_the_export(core_stack, monkeypatch):
    core, _, client, _, _ = core_stack
    await append(core, [make_event(T.USER_TRANSCRIPT_ACCEPTED, f"u{i}", ms=i) for i in range(5)])
    monkeypatch.setattr(transcript_module, "MAX_TRANSCRIPT_EVENTS", 3)
    with pytest.raises(CoreProtocolError) as caught:
        await client.get_conversation_transcript("conv-a")
    assert (caught.value.status, caught.value.code) == (413, "transcript_too_large")
    assert "export" in str(caught.value)


# ----------------------------------------------------------------- export

async def test_export_streams_the_stored_events_and_reimports_to_the_live_transcript(core_stack):
    core, _, client, port, _ = core_stack
    events = transcript_scenario()
    await append(core, events)
    await append(core, [make_event(T.USER_TRANSCRIPT_ACCEPTED, "other", conversation_id="conv-other")])
    data = await export_bytes(client, "conv-t")
    result = read_export(data.splitlines(keepends=True))
    assert result.complete and not result.invalid_lines and len(result.events) == len(events)
    stored = await core.conversation_events.list_conversation_events("conv-t", limit=500)
    assert result.events == stored.events  # sequence, recorded_at and event, exactly as stored
    for mode in TranscriptMode:
        assert transcript_from_export(result, mode=mode) == await client.get_conversation_transcript("conv-t", mode=mode)
    status, headers, _ = await raw_text(port, "/v1/conversation-events/export", {"conversation_id": "conv-t"})
    assert status == 200 and headers["Content-Type"] == "application/x-ndjson; charset=utf-8"
    assert headers["Content-Disposition"] == 'attachment; filename="conversation-conv-t.events.jsonl"'


async def test_a_huge_conversation_is_exported_page_by_page_and_frozen_at_its_start(core_stack, monkeypatch):
    core, _, client, _, _ = core_stack
    events = [make_event(T.MOUTH_SPEECH_QUEUED, f"s{i}", producer=VOICE, ms=i) for i in range(1234)]
    await append(core, events)
    store = core.conversation_events
    original = store.list_conversation_events
    reads = []

    async def spying(conversation_id, **kwargs):
        reads.append(kwargs)
        if len(reads) == 1:  # appended while the export streams: after the frozen extent
            await store.append(make_event(T.MOUTH_SPEECH_QUEUED, "late", producer=VOICE, ms=99_999))
        return await original(conversation_id, **kwargs)

    monkeypatch.setattr(store, "list_conversation_events", spying)
    chunks = []
    async for chunk in client.export_conversation_events("conv-a"):
        chunks.append(chunk)
    result = read_export(b"".join(chunks).splitlines(keepends=True))
    assert result.complete and len(result.events) == 1234 and result.header.through_sequence == 1234
    assert [read["limit"] for read in reads] == [PROJECTION_PAGE_LIMIT] * -(-1234 // PROJECTION_PAGE_LIMIT)
    assert all(read["until_sequence"] == 1234 for read in reads)
    again = read_export((await export_bytes(client, "conv-a")).splitlines(keepends=True))
    assert len(again.events) == 1235


async def test_unreadable_rows_are_skipped_counted_and_the_reimport_still_matches(core_stack):
    core, _, client, _, _ = core_stack
    events = transcript_scenario()
    await append(core, events)

    def damage(conn):
        conn.execute("UPDATE conversation_events SET data='{\"broken\": true}' WHERE sequence=3")
        conn.commit()

    await core.state.run_serialized(damage)
    result = read_export((await export_bytes(client, "conv-t")).splitlines(keepends=True))
    assert result.complete and result.skipped_rows == 1 and len(result.events) == len(events) - 1
    for mode in TranscriptMode:
        live = await client.get_conversation_transcript("conv-t", mode=mode)
        assert transcript_from_export(result, mode=mode) == live and "1 ligne illisible ignorée par Core" in live


async def test_a_storage_failure_while_streaming_leaves_an_incomplete_file(core_stack, monkeypatch):
    core, _, client, _, _ = core_stack
    await append(core, [make_event(T.MOUTH_SPEECH_QUEUED, f"s{i}", producer=VOICE, ms=i) for i in range(700)])
    store = core.conversation_events
    original = store.list_conversation_events
    calls = 0

    async def failing_second_page(conversation_id, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConversationEventStoreError("disk full")
        return await original(conversation_id, **kwargs)

    monkeypatch.setattr(store, "list_conversation_events", failing_second_page)
    received = io.BytesIO()
    with pytest.raises(aiohttp.ClientPayloadError):
        async for chunk in client.export_conversation_events("conv-a"):
            received.write(chunk)
    result = read_export(received.getvalue().splitlines(keepends=True))
    assert not result.complete and len(result.events) == PROJECTION_PAGE_LIMIT  # the first page only


# ----------------------------------------------------------------- search

async def test_search_route_pages_hits_and_never_matches_diagnostic_content(core_stack):
    core, _, client, port, _ = core_stack
    await append(core, transcript_scenario())
    page = await client.search_conversation_events("PAUL")
    assert [hit.event_type for hit in page.hits] == ["mouth.speech.started", "brain.message.published",
                                                     "brain.message.published", "user.transcript.accepted"]
    assert all("Paul" in hit.snippet for hit in page.hits) and not page.has_more
    for private in ("Rassemble les vols", "Recherche des vols", "jamais dite", "get_time"):
        assert (await client.search_conversation_events(private)).hits == (), private
    first = await client.search_conversation_events("paul", limit=1)
    second = await client.search_conversation_events("paul", limit=1, before_sequence=first.next_cursor)
    assert first.hits[0].sequence > second.hits[0].sequence
    status, body = await raw_get(port, "/v1/conversation-events/search", {"q": "réflexe interrompu", "limit": "5"})
    assert status == 200 and body["hits"] == [] and body["schema_version"] == 1
    codes = await client.search_conversation_events("brain_backend_exception")
    assert [hit.matched for hit in codes.hits] == [("attributes.code",)]


async def test_concurrent_reads_are_served_while_a_long_export_streams(core_stack):
    core, _, client, _, _ = core_stack
    await append(core, [make_event(T.MOUTH_SPEECH_QUEUED, f"s{i}", producer=VOICE, ms=i) for i in range(1500)])
    export = asyncio.create_task(export_bytes(client, "conv-a"))
    page = await asyncio.wait_for(client.list_conversation_events("conv-a", limit=1), 5)
    assert page.events
    assert read_export((await export).splitlines(keepends=True)).complete


# ------------------------------------------------ Slice 06 rework: Core's hot path first

async def _blocking_search(core, monkeypatch):
    """Replace the store scan with one that waits; returns (started, release, outcomes)."""
    started, release, outcomes = asyncio.Event(), asyncio.Event(), []
    original = core.conversation_events.search_events

    async def slow(*args, **kwargs):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            outcomes.append("cancelled")
            raise
        outcomes.append("finished")
        return await original(*args, **kwargs)

    monkeypatch.setattr(core.conversation_events, "search_events", slow)
    return started, release, outcomes


async def test_a_second_search_is_refused_with_429_while_one_runs(core_stack, monkeypatch):
    core, _, client, port, _ = core_stack
    await append(core, transcript_scenario())
    started, release, _ = await _blocking_search(core, monkeypatch)
    first = asyncio.create_task(client.search_conversation_events("Paul"))
    await asyncio.wait_for(started.wait(), 5)
    status, body = await asyncio.wait_for(raw_get(port, "/v1/conversation-events/search", {"q": "vol"}), 5)
    assert (status, body["error"]["code"]) == (429, "search_busy")
    release.set()
    assert (await first).hits
    status, _ = await raw_get(port, "/v1/conversation-events/search", {"q": "vol"})
    assert status == 200


async def test_a_client_that_leaves_cancels_its_search_in_core(core_stack, monkeypatch):
    core, _, _, port, _ = core_stack
    started, _, outcomes = await _blocking_search(core, monkeypatch)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(raw_get(port, "/v1/conversation-events/search", {"q": "vol"}), 0.4)
    await asyncio.wait_for(started.wait(), 5)
    for _ in range(40):
        if outcomes:
            break
        await asyncio.sleep(0.1)
    assert outcomes == ["cancelled"]
    assert core.conversation_event_queries.search_slots.in_use == 0


async def test_a_client_that_leaves_cancels_its_transcript_build(core_stack, monkeypatch):
    core, _, _, port, _ = core_stack
    reading, cancelled = asyncio.Event(), []

    async def slow_page(*args, **kwargs):
        reading.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    monkeypatch.setattr(core.conversation_events, "list_conversation_events", slow_page)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(raw_text(port, "/v1/conversation-events/transcript", {"conversation_id": "conv-t"}), 0.4)
    await asyncio.wait_for(reading.wait(), 5)
    for _ in range(40):
        if cancelled:
            break
        await asyncio.sleep(0.1)
    assert cancelled and core.conversation_event_queries.projection_slots.in_use == 0


async def test_an_export_client_that_leaves_mid_stream_frees_the_build_slot(core_stack):
    core, _, _, port, _ = core_stack
    await append(core, [make_event(T.MOUTH_SPEECH_QUEUED, f"s{i}", producer=VOICE, ms=i, content="x" * 2000)
                        for i in range(3000)])
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Jarvis-Protocol": "1"}
    async with aiohttp.ClientSession() as session:
        response = await session.get(f"http://127.0.0.1:{port}/v1/conversation-events/export",
                                     params={"conversation_id": "conv-a"}, headers=headers)
        assert response.status == 200
        await response.content.read(4096)
        response.close()  # the browser tab went away
    for _ in range(50):
        if core.conversation_event_queries.projection_slots.in_use == 0:
            break
        await asyncio.sleep(0.1)
    assert core.conversation_event_queries.projection_slots.in_use == 0


async def test_three_concurrent_projection_builds_the_third_is_429(core_stack, monkeypatch):
    core, _, _, port, _ = core_stack
    service = core.conversation_event_queries
    held = [await service.open_export("conv-a"), await service.open_export("conv-a")]
    try:
        for path in ("/v1/conversation-events/transcript", "/v1/conversation-events/export"):
            status, body = await raw_get(port, path, {"conversation_id": "conv-a"})
            assert (status, body["error"]["code"]) == (429, "projection_busy"), path
    finally:
        for export in held:
            export.release()


@pytest.mark.parametrize("value", ["PLANTED", "900", "-9999", "1.5", "+60"])
async def test_an_invalid_offset_is_400_without_echo(core_stack, value):
    _, _, _, port, _ = core_stack
    status, body = await raw_get(port, "/v1/conversation-events/transcript",
                                 {"conversation_id": "conv-t", "utc_offset_minutes": value})
    assert (status, body["error"]["code"]) == (400, "invalid_request")
    assert "utc_offset_minutes must be an integer" in body["error"]["message"] and value not in body["error"]["message"]


async def test_the_offset_is_a_rendering_input_and_long_text_streams_in_chunks(core_stack):
    core, _, client, port, _ = core_stack
    events = [make_event(T.USER_TRANSCRIPT_ACCEPTED, f"long{i}", ms=i * 1000, producer="core.voice_admission",
                         content=("Une très longue phrase. " * 330)[:8000]) for i in range(20)]
    await append(core, events)
    text = await client.get_conversation_transcript("conv-a", utc_offset_minutes=120)
    assert text == render_transcript(events, conversation_id="conv-a", utc_offset_minutes=120)
    assert "heures UTC+02:00" in text and "[12:00:00.000]" in text and len(text) > 150_000
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Jarvis-Protocol": "1"}
    sizes = []
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}/v1/conversation-events/transcript",
                               params={"conversation_id": "conv-a"}, headers=headers) as response:
            assert response.headers.get("Transfer-Encoding") == "chunked"
            async for chunk in response.content.iter_any():
                sizes.append(len(chunk))
    assert sum(sizes) > 150_000
