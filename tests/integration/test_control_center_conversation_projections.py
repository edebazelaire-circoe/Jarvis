"""Control Center `/api/conversations/{transcript,export,search}` over a real Core (Slice 06).

Chain: browser -> `ControlCenter` (origin guard) -> `ConversationEventView` ->
`CoreConversationEventReader` -> `LocalProtocolServer` -> store. The Control
Center relays Core's text and export bytes; it never renders a second time.
Contract: `docs/conversation-events.md`, "Readable transcript", "JSONL export", "Search".
"""

from __future__ import annotations

import asyncio
import json

import aiohttp
from aiohttp import web
import pytest

import jarvis.domain.conversation_transcript as transcript_module
from jarvis.domain.conversation_event_export import read_export, transcript_from_export
from jarvis.domain.conversation_event_search import encode_search_page
from jarvis.domain.conversation_event_store import ConversationEventStoreError
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.conversation_transcript import TranscriptMode
from jarvis.protocol.client import LocalCoreClient
from jarvis.runtime.conversation_event_view import UNAVAILABLE_KIND
from jarvis.runtime.journal import read_jsonl_tail
from tests.fakes.conversation_events import make_event, transcript_scenario
from tests.integration.test_control_center_conversation_events import (
    OTHER_TOKEN, TOKEN, control_center, core_running, get,
)
from tests.integration.test_conversation_event_query_protocol import append, free_port

VOICE = "voice.speech_scheduler"
ROUTES = ("/api/conversations/transcript?conversation_id=conv-t", "/api/conversations/export?conversation_id=conv-t",
          "/api/conversations/search?q=vol")


async def test_the_control_center_relays_cores_transcript_export_and_search(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        await append(core, transcript_scenario())
        direct = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        try:
            for mode in TranscriptMode:
                response = await client.get("/api/conversations/transcript",
                                            params={"conversation_id": "conv-t", "mode": mode.value})
                assert response.status == 200 and response.headers["Content-Type"] == "text/plain; charset=utf-8"
                assert await response.text() == await direct.get_conversation_transcript("conv-t", mode=mode)
            status, body = await get(client, "/api/conversations/search", params={"q": "Paul", "limit": "2"})
            assert status == 200
            assert body == encode_search_page(await direct.search_conversation_events("Paul", limit=2))
            response = await client.get("/api/conversations/export", params={"conversation_id": "conv-t"})
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/x-ndjson; charset=utf-8"
            assert response.headers["Content-Disposition"] == 'attachment; filename="conversation-conv-t.events.jsonl"'
            relayed = read_export((await response.read()).splitlines(keepends=True))
            assert relayed.complete and len(relayed.events) == 25
            assert transcript_from_export(relayed) == await direct.get_conversation_transcript("conv-t")
        finally:
            await direct.close()


@pytest.mark.parametrize("headers", [{"Origin": "http://evil.example"}, {"Host": "evil.example:17654"},
                                     {"Sec-Fetch-Site": "cross-site"}])
async def test_projection_routes_refuse_foreign_origins_and_hosts(tmp_path, headers):
    async with control_center(tmp_path, free_port(), view=False) as (_, client, _):
        for path in ROUTES:
            status, body = await get(client, path, headers=headers)
            assert (status, body["code"]) == (403, "forbidden_origin"), (path, headers)


@pytest.mark.parametrize(("path", "fragment"), [
    ("/api/conversations/transcript?conversation_id=a&mode=SECRET", "mode must be one of"),
    ("/api/conversations/transcript", "conversation_id is required"),
    ("/api/conversations/export?conversation_id=a&SECRET=1", "unexpected query parameter"),
    ("/api/conversations/search?q=" + "SECRET" * 40, "q must be at most"),
    ("/api/conversations/search?q=x&limit=SECRET", "limit"),
])
async def test_invalid_parameters_are_refused_before_core_without_echo(tmp_path, path, fragment):
    async with control_center(tmp_path, free_port()) as (_, client, _):
        status, body = await get(client, path)
        assert (status, body["ok"], body["code"]) == (400, False, "invalid_request")
        assert fragment in body["error"] and "SECRET" not in body["error"]


async def test_core_down_is_503_journaled_once_and_not_configured_is_explicit(tmp_path):
    port = free_port()
    async with control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        for path in ROUTES * 2:
            status, body = await get(client, path)
            assert (status, body["code"]) == (503, "core_unreachable"), path
        lines = [line for line in read_jsonl_tail(control.journal.trace_path, limit=100) if line["kind"] == UNAVAILABLE_KIND]
        assert len(lines) == 1
    (tmp_path / "bare").mkdir()
    async with control_center(tmp_path / "bare", port, view=False) as (_, client, _):
        for path in ROUTES:
            status, body = await get(client, path)
            assert (status, body["code"]) == (503, "not_configured"), path


async def test_a_too_large_transcript_and_a_store_failure_keep_their_codes(tmp_path, monkeypatch):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        await append(core, [make_event(T.USER_TRANSCRIPT_ACCEPTED, f"u{i}", ms=i) for i in range(4)])
        monkeypatch.setattr(transcript_module, "MAX_TRANSCRIPT_EVENTS", 2)
        status, body = await get(client, "/api/conversations/transcript", params={"conversation_id": "conv-a"})
        assert (status, body["code"], body["core_status"]) == (413, "transcript_too_large", 413)
        assert "export" in body["error"]

        async def broken(*args, **kwargs):
            raise ConversationEventStoreError("disk I/O error")

        monkeypatch.setattr(core.conversation_events, "search_events", broken)
        status, body = await get(client, "/api/conversations/search", params={"q": "x"})
        assert (status, body["code"]) == (503, "conversation_events_unavailable")


async def test_a_core_stream_broken_mid_export_reaches_the_browser_as_incomplete(tmp_path, monkeypatch):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
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
        response = await client.get("/api/conversations/export", params={"conversation_id": "conv-a"})
        assert response.status == 200  # headers were already sent when Core broke
        received = bytearray()
        with pytest.raises(aiohttp.ClientPayloadError):
            async for chunk in response.content.iter_chunked(65536):
                received.extend(chunk)
        assert not read_export(bytes(received).splitlines(keepends=True)).complete
        lines = [line for line in read_jsonl_tail(control.journal.trace_path, limit=100) if line["kind"] == UNAVAILABLE_KIND]
        assert [(line["data"]["code"], line["data"]["operation"]) for line in lines] == [("export_interrupted", "export")]


async def test_export_rereads_a_rotated_token_before_the_first_byte(tmp_path):
    port = free_port()
    async with control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        async with core_running(tmp_path / "core", port, token=OTHER_TOKEN) as (core, _):
            status, body = await get(client, "/api/conversations")  # lane opened with the stale token
            assert (status, body["code"]) == (502, "core_unauthorized")
            await append(core, [make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", conversation_id="conv-r")])
            token_file.write_text(OTHER_TOKEN, encoding="utf-8")
            response = await client.get("/api/conversations/export", params={"conversation_id": "conv-r"})
            assert response.status == 200
            result = read_export((await response.read()).splitlines(keepends=True))
            assert result.complete and len(result.events) == 1
            assert json.loads((await response.read()).splitlines()[0])["conversation_id"] == "conv-r"



# ------------------------------------------------ Slice 06 rework: busy, disconnect, offset

async def test_core_busy_reaches_the_browser_as_429_and_is_not_a_failure_episode(tmp_path, monkeypatch):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        started, release = asyncio.Event(), asyncio.Event()
        original = core.conversation_events.search_events

        async def slow(*args, **kwargs):
            started.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(core.conversation_events, "search_events", slow)
        first = asyncio.create_task(get(client, "/api/conversations/search", params={"q": "vol"}))
        await asyncio.wait_for(started.wait(), 5)
        status, body = await get(client, "/api/conversations/search", params={"q": "autre"})
        assert (status, body["code"], body["core_status"]) == (429, "search_busy", 429)
        assert "déjà en cours" in body["error"]
        release.set()
        assert (await first)[0] == 200
        lines = [line for line in read_jsonl_tail(control.journal.trace_path, limit=100) if line["kind"] == UNAVAILABLE_KIND]
        assert lines == []


async def test_a_browser_that_leaves_cancels_the_search_in_core(tmp_path, monkeypatch):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, _, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        started, outcomes = asyncio.Event(), []

        async def hanging(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                outcomes.append("cancelled")
                raise

        monkeypatch.setattr(core.conversation_events, "search_events", hanging)
        # Served like production (`ControlCenter.start`: plain AppRunner, which does not
        # cancel a handler whose browser left; TestServer would cancel it itself).
        ui_port = free_port()
        runner = web.AppRunner(control._app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", ui_port).start()
        try:
            async with aiohttp.ClientSession() as browser:
                with pytest.raises(asyncio.TimeoutError):
                    async with browser.get(f"http://127.0.0.1:{ui_port}/api/conversations/search", params={"q": "vol"},
                                           timeout=aiohttp.ClientTimeout(total=0.5)) as response:
                        await response.read()
            await asyncio.wait_for(started.wait(), 5)
            for _ in range(50):
                if outcomes:
                    break
                await asyncio.sleep(0.1)
            assert outcomes == ["cancelled"] and core.conversation_event_queries.search_slots.in_use == 0
        finally:
            await runner.cleanup()


async def test_the_transcript_relay_streams_cores_text_with_the_browser_offset(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        await append(core, transcript_scenario())
        response = await client.get("/api/conversations/transcript",
                                    params={"conversation_id": "conv-t", "mode": "detailed", "utc_offset_minutes": "-300"})
        assert response.status == 200 and response.headers["Content-Type"] == "text/plain; charset=utf-8"
        direct = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        try:
            assert await response.text() == await direct.get_conversation_transcript(
                "conv-t", mode=TranscriptMode.DETAILED, utc_offset_minutes=-300)
        finally:
            await direct.close()
        status, body = await get(client, "/api/conversations/transcript",
                                 params={"conversation_id": "conv-t", "utc_offset_minutes": "SECRET"})
        assert (status, body["code"]) == (400, "invalid_request") and "SECRET" not in body["error"]
