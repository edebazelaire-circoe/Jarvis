"""Control Center `/api/conversations...` routes over a real Core (Slice 04).

Chain: browser -> `ControlCenter` (origin guard) -> `ConversationEventView` ->
`CoreConversationEventReader` (loopback, token file) -> `LocalProtocolServer` ->
store. Contract: `docs/conversation-events.md`, "Query and live API".
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
import json
import time

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.conversation_event_emitter import journal_trace
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_event_query import encode_event_page, encode_summary_page
from jarvis.domain.conversation_event_store import ConversationEventStoreError
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.conversation_event_view import (
    RECOVERED_KIND, UNAVAILABLE_KIND, ConversationEventView, ConversationEventViewError, CoreConversationEventReader,
)
from jarvis.runtime.journal import read_jsonl_tail
from tests.fakes.conversation_events import make_event
from tests.integration.test_conversation_event_query_protocol import free_port

TOKEN = "c" * 48
OTHER_TOKEN = "d" * 48
VOICE = "voice.speech_scheduler"


def mouth(index: int, conversation_id: str = "conv-a", **fields):
    return make_event(T.MOUTH_SPEECH_QUEUED, f"s{index}", producer=VOICE, conversation_id=conversation_id,
                      ms=index, **fields)


@asynccontextmanager
async def core_running(tmp_path, port: int, token: str = TOKEN):
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=token)
    await server.start()
    try:
        yield core, server
    finally:
        await server.stop()
        await core.stop()


@asynccontextmanager
async def control_center(tmp_path, port: int, *, view: bool = True):
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    token_file = tmp_path / "core.token"
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path, conversation_event_view=(
        ConversationEventView(CoreConversationEventReader(host="127.0.0.1", port=port, token_file=token_file),
                              journal=None, timeout_s=3.0) if view else None))
    if view:
        control.conversation_event_view.journal = control.journal
    client = TestClient(TestServer(control._app))
    await client.start_server()
    try:
        yield control, client, token_file
    finally:
        await client.close()
        await control.conversation_event_view.aclose()


async def get(client, path: str, **kwargs):
    response = await client.get(path, **kwargs)
    return response.status, await response.json()


async def test_the_control_center_serves_the_same_pages_as_core(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        await core.conversation_events.append_many([mouth(i, session_id="sess-1") for i in range(5)])
        await core.conversation_events.append_many([mouth(9, conversation_id="conv-b")])
        direct = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        try:
            status, body = await get(client, "/api/conversations/events",
                                     params={"conversation_id": "conv-a", "limit": "2", "after_sequence": "1"})
            assert status == 200
            assert body == encode_event_page(await direct.list_conversation_events("conv-a", after_sequence=1, limit=2))
            status, body = await get(client, "/api/conversations", params={"limit": "1"})
            assert status == 200 and body == encode_summary_page(await direct.list_event_conversations(limit=1))
            status, body = await get(client, "/api/conversations/sessions", params={"conversation_id": "conv-a"})
            assert status == 200 and [s["session_id"] for s in body["summaries"]] == ["sess-1"]
            status, body = await get(client, "/api/conversations/lookup",
                                     params={"field": "speech_id", "value": mouth(3).speech_id})
            assert status == 200 and [e["event"]["event_id"] for e in body["events"]] == [mouth(3).event_id]
            status, body = await get(client, f"/api/conversations/events/{mouth(2).event_id}")
            assert status == 200 and body["event"]["event_id"] == mouth(2).event_id and body["sequence"] >= 1
            # reload (full walk) == Core's event set
            ids, after = [], 0
            while True:
                status, page = await get(client, "/api/conversations/events",
                                         params={"conversation_id": "conv-a", "limit": "2", "after_sequence": str(after)})
                ids += [item["event"]["event_id"] for item in page["events"]]
                after = page["next_cursor"]
                if not page["has_more"]:
                    break
            assert ids == [mouth(i).event_id for i in range(5)]
        finally:
            await direct.close()


async def test_a_long_poll_through_the_control_center_returns_on_append(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        started = time.monotonic()
        poll = asyncio.create_task(get(client, "/api/conversations/events",
                                       params={"conversation_id": "conv-a", "wait_ms": "20000"}))
        await asyncio.sleep(0.4)
        assert not poll.done()
        await core.conversation_events.append(mouth(1))
        status, body = await asyncio.wait_for(poll, 5)
        assert status == 200 and [e["event"]["event_id"] for e in body["events"]] == [mouth(1).event_id]
        assert time.monotonic() - started < 4


@pytest.mark.parametrize("headers", [{"Origin": "http://evil.example"}, {"Origin": "null"},
                                     {"Host": "evil.example:17654"}, {"Origin": "http://127.0.0.1.evil.example"}])
async def test_conversation_reads_refuse_foreign_origins_and_hosts(tmp_path, headers):
    async with control_center(tmp_path, free_port(), view=False) as (_, client, _):
        for path in ("/api/conversations", "/api/conversations/events?conversation_id=a",
                     "/api/conversations/events/cev-" + "0" * 64 + "/trace"):
            status, body = await get(client, path, headers=headers)
            assert (status, body["code"]) == (403, "forbidden_origin"), (path, headers)
        # the rest of the Control Center keeps its historical rule (GET not guarded)
        response = await client.get("/api/trace", headers=headers if "Origin" in headers else {})
        assert response.status == 200


async def test_loopback_origins_are_accepted(tmp_path):
    async with control_center(tmp_path, free_port(), view=False) as (_, client, _):
        for origin in ("http://127.0.0.1:17654", "http://localhost:17654", "http://[::1]:17654"):
            status, body = await get(client, "/api/conversations", headers={"Origin": origin})
            assert (status, body["code"]) == (503, "not_configured")


async def test_core_down_is_an_explicit_error_journaled_once_then_recovery(tmp_path):
    port = free_port()
    async with control_center(tmp_path, port) as (control, client, token_file):
        for _ in range(3):  # token file missing: `jarvis core` never started
            status, body = await get(client, "/api/conversations/events", params={"conversation_id": "conv-a"})
            assert (status, body["ok"], body["code"]) == (503, False, "core_unreachable") and body["error"]
        token_file.write_text(TOKEN, encoding="utf-8")
        status, body = await get(client, "/api/conversations")  # token present, port closed
        assert (status, body["code"]) == (503, "core_unreachable")
        async with core_running(tmp_path, port):
            status, body = await get(client, "/api/conversations")
            assert status == 200 and body["summaries"] == []
        lines = [line for line in read_jsonl_tail(control.journal.trace_path, limit=100)
                 if line["kind"].startswith("ui.conversation_events")]
        assert [line["kind"] for line in lines] == [UNAVAILABLE_KIND, RECOVERED_KIND]
        assert lines[0]["level"] == "warning" and lines[0]["data"]["code"] == "core_unreachable"


async def test_core_store_failure_and_rotated_token(tmp_path, monkeypatch):
    port = free_port()
    async with control_center(tmp_path, port) as (_, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        async with core_running(tmp_path / "first", port) as (core, _):
            async def broken(*args, **kwargs):
                raise ConversationEventStoreError("disk I/O error")

            monkeypatch.setattr(core.conversation_events, "list_conversations", broken)
            status, body = await get(client, "/api/conversations")
            assert (status, body["code"], body["core_status"]) == (503, "conversation_events_unavailable", 503)
            assert "disk" not in body["error"]
        # Core restarts with a new token: the reader re-reads the token file after a 401.
        token_file.write_text(OTHER_TOKEN, encoding="utf-8")
        async with core_running(tmp_path / "second", port, token=OTHER_TOKEN):
            status, body = await get(client, "/api/conversations")
            assert status == 200


@pytest.mark.parametrize(("path", "fragment"), [
    ("/api/conversations/events?conversation_id=a&limit=SECRET", "limit"),
    ("/api/conversations/events", "conversation_id is required"),
    ("/api/conversations/events?conversation_id=a&SECRET=1", "unexpected query parameter"),
    ("/api/conversations/lookup?field=SECRET&value=v", "field must be one of"),
    ("/api/conversations/events/cev-SECRET", "event_id must match"),
    ("/api/conversations/events/cev-SECRET/trace", "event_id must match"),
])
async def test_invalid_parameters_are_refused_before_core_without_echo(tmp_path, path, fragment):
    async with control_center(tmp_path, free_port()) as (_, client, _):
        status, body = await get(client, path)
        assert (status, body["ok"], body["code"]) == (400, False, "invalid_request")
        assert fragment in body["error"] and "SECRET" not in body["error"]


async def test_trace_drill_down_route(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        started = make_event(T.MOUTH_SPEECH_STARTED, "m1", producer=VOICE, trace_ref=journal_trace("voice.speech.started"))
        started = replace(started, occurred_at=now, started_at=now)  # the journal line below is written now
        user = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", producer="core.voice_admission")
        await core.conversation_events.append_many([started, user])
        control.journal.emit("tool.call", "PRIVATE", data={"arguments": {"q": "PRIVATE"}})
        control.journal.emit("voice.speech.started", "Speech generation requested",
                             data={"speech_id": started.speech_id, "conversation_event_id": started.event_id,
                                   "text": "PRIVATE"})
        status, body = await get(client, f"/api/conversations/events/{started.event_id}/trace")
        assert status == 200 and body["status"] == "found" and body["sequence"] >= 1
        [entry] = body["scan"]["entries"]
        assert entry["message"] == "Speech generation requested" and entry["redacted_keys"] == ["text"]
        assert "PRIVATE" not in json.dumps(body)
        status, body = await get(client, f"/api/conversations/events/{user.event_id}/trace")
        assert (status, body["code"]) == (404, "trace_not_applicable")
        status, body = await get(client, "/api/conversations/events/cev-" + "a" * 64 + "/trace")
        assert (status, body["code"]) == (404, "conversation_event_not_found")


async def test_status_exposes_forwarder_loss_counters(tmp_path):
    from tests.fakes.conversation_events import recording_forwarder

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, conversation_events=recording_forwarder())
    counters = control._conversation_event_counters()
    assert counters["pending"] == 0 and {"enqueued", "dropped_queue_full", "dropped_rejected"} <= set(counters)
    assert ControlCenter(runtime_root=tmp_path / "x", project_root=tmp_path)._conversation_event_counters() is None


# ------------------------------------------------------ rework (QA S1, S3, nits)

class BlockingReader:
    """`ConversationEventReader` double: long-polls block until released, plain reads answer at once."""

    def __init__(self) -> None:
        self.waits: list[int] = []
        self.release = asyncio.Event()
        self.cancelled = 0
        self.closed = False

    async def list_conversation_events(self, conversation_id, **query):
        from jarvis.domain.conversation_event_store import ConversationEventPage

        self.waits.append(query["wait_ms"])
        if query["wait_ms"]:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        return ConversationEventPage((), query["after_sequence"], False, 0)

    async def get_conversation_event(self, event_id):
        return None

    async def close(self):
        self.closed = True


async def test_long_polls_over_the_cap_are_sent_as_plain_polls(tmp_path):
    reader = BlockingReader()
    view = ConversationEventView(reader, max_long_polls=3)
    polls = [asyncio.create_task(view.events("conv-a", after_sequence=0, limit=10, visibility=None, wait_ms=20_000))
             for _ in range(5)]
    await asyncio.sleep(0.1)
    assert sorted(reader.waits) == [0, 0, 20_000, 20_000, 20_000]
    assert (view.long_polls, view.long_polls_downgraded) == (3, 2)
    assert await view.event("cev-" + "0" * 64) is None  # detail reads never wait behind long-polls
    reader.release.set()
    await asyncio.gather(*polls)
    assert view.long_polls == 0


async def test_a_long_poll_whose_browser_left_cancels_its_core_request(tmp_path):
    reader = BlockingReader()
    view = ConversationEventView(reader)
    gone = False
    poll = asyncio.create_task(view.events("conv-a", after_sequence=0, limit=10, visibility=None, wait_ms=20_000,
                                           disconnected=lambda: gone))
    await asyncio.sleep(0.1)
    gone = True
    started = time.monotonic()
    with pytest.raises(ConversationEventViewError) as caught:
        await asyncio.wait_for(poll, 2)
    assert caught.value.code == "client_disconnected"
    assert reader.cancelled == 1 and view.long_polls == 0 and time.monotonic() - started < 1.0


async def test_a_closed_view_answers_stopping_and_never_reopens_a_session(tmp_path):
    port = free_port()
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    reader = CoreConversationEventReader(host="127.0.0.1", port=port, token_file=token_file)
    view = ConversationEventView(reader)
    await view.aclose()
    for _ in range(2):
        with pytest.raises(ConversationEventViewError) as caught:
            await view.conversations(before_sequence=None, limit=5)
        assert (caught.value.status, caught.value.code) == (503, "control_center_stopping")
    assert reader._lanes == {}
    with pytest.raises(ConnectionError):
        reader._client("read")


async def test_the_reader_uses_bounded_separate_sessions_and_a_401_rereads_the_token_without_closing_them(tmp_path):
    port = free_port()
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    reader = CoreConversationEventReader(host="127.0.0.1", port=port, token_file=token_file)
    try:
        async with core_running(tmp_path / "a", port):
            await reader.list_event_conversations(limit=1)
            poll = asyncio.create_task(reader.list_conversation_events("conv-a", after_sequence=0, limit=5,
                                                                       wait_ms=1_500))
            await asyncio.sleep(0.2)
            read_client, read_session = reader._lanes["read"]
            poll_client, poll_session = reader._lanes["poll"]
            assert read_session is not poll_session
            assert (read_session.connector.limit, poll_session.connector.limit) == (16, 10)
            await poll
        token_file.write_text(OTHER_TOKEN, encoding="utf-8")
        async with core_running(tmp_path / "b", port, token=OTHER_TOKEN):
            slow = asyncio.create_task(reader.list_conversation_events("conv-a", after_sequence=0, limit=5,
                                                                       wait_ms=1_000))
            await reader.list_event_conversations(limit=1)  # 401 -> token re-read -> retried
            await slow  # the in-flight poll on the other session was not closed under it
            assert reader._lanes["read"] == (read_client, read_session) and not read_session.closed
            assert reader._lanes["poll"] == (poll_client, poll_session) and not poll_session.closed
            assert read_client.token == poll_client.token == OTHER_TOKEN
    finally:
        await reader.close()


async def test_a_browser_leaving_a_control_center_long_poll_frees_core(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        # Served like production (`ControlCenter.start`: plain AppRunner, no handler
        # cancellation on disconnect; TestServer would cancel handlers itself).
        ui_port = free_port()
        runner = web.AppRunner(control._app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", ui_port).start()
        browser = aiohttp.ClientSession()
        request = asyncio.create_task(browser.get(f"http://127.0.0.1:{ui_port}/api/conversations/events",
                                                  params={"conversation_id": "conv-a", "wait_ms": "25000"}))
        await wait_until(lambda: core.conversation_events.watched_conversations == 1)
        assert control.conversation_event_view.long_polls == 1
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        await browser.close()  # the tab went away
        try:
            await wait_until(lambda: control.conversation_event_view.long_polls == 0, timeout_s=3)
            await wait_until(lambda: core.conversation_events.watched_conversations == 0, timeout_s=4)
        finally:
            await runner.cleanup()


async def test_many_browser_long_polls_never_starve_detail_reads(tmp_path):
    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        await core.conversation_events.append(mouth(1))
        polls = [asyncio.create_task(get(client, "/api/conversations/events",
                                         params={"conversation_id": "conv-quiet", "wait_ms": "20000"}))
                 for _ in range(30)]
        await wait_until(lambda: control.conversation_event_view.long_polls == 8)
        started = time.monotonic()
        status, body = await get(client, f"/api/conversations/events/{mouth(1).event_id}")
        assert status == 200 and time.monotonic() - started < 2.0
        await wait_until(lambda: control.conversation_event_view.long_polls_downgraded == 22)
        await core.conversation_events.append(mouth(2, conversation_id="conv-quiet"))
        results = await asyncio.wait_for(asyncio.gather(*polls), 10)
        assert all(status == 200 for status, _ in results)


@pytest.mark.parametrize("headers", [{"Host": "evil.com@127.0.0.1"}, {"Host": "127.0.0.1#.evil.com"},
                                     {"Origin": "http://evil.com@127.0.0.1"}, {"Sec-Fetch-Site": "cross-site"},
                                     {"Origin": "http://127.0.0.1:17654/path"}])
async def test_the_guard_compares_exact_hosts_and_refuses_cross_site_fetches(tmp_path, headers):
    async with control_center(tmp_path, free_port(), view=False) as (_, client, _):
        status, body = await get(client, "/api/conversations", headers=headers)
        assert (status, body["code"]) == (403, "forbidden_origin")
        status, body = await get(client, "/api/conversations", headers={"Sec-Fetch-Site": "same-origin"})
        assert (status, body["code"]) == (503, "not_configured")  # the guard let it through


async def test_an_unexpected_drill_down_failure_is_an_explicit_503_journaled_once(tmp_path, monkeypatch):
    from jarvis.runtime import control_center as control_center_module

    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        event = make_event(T.MOUTH_SPEECH_STARTED, "m1", producer=VOICE, trace_ref=journal_trace("voice.speech.started"))
        await core.conversation_events.append(event)

        def broken(*args, **kwargs):
            raise TypeError("PRIVATE detail")

        monkeypatch.setattr(control_center_module, "drill_down", broken)
        for _ in range(3):
            status, body = await get(client, f"/api/conversations/events/{event.event_id}/trace")
            assert (status, body["code"]) == (503, "trace_drill_down_failed") and "PRIVATE" not in body["error"]
        monkeypatch.undo()
        status, _ = await get(client, f"/api/conversations/events/{event.event_id}/trace")
        assert status == 200
        lines = [line for line in read_jsonl_tail(control.journal.trace_path, limit=100)
                 if line["kind"].startswith("ui.conversation_event_trace")]
        assert [line["kind"] for line in lines] == ["ui.conversation_event_trace_unreadable",
                                                    "ui.conversation_event_trace_recovered"]
        assert lines[0]["data"]["code"] == "trace_drill_down_failed" and "PRIVATE" not in json.dumps(lines)


async def test_concurrent_drill_downs_are_bounded(tmp_path, monkeypatch):
    import threading

    from jarvis.runtime import control_center as control_center_module

    port = free_port()
    async with core_running(tmp_path, port) as (core, _), control_center(tmp_path, port) as (control, client, token_file):
        token_file.write_text(TOKEN, encoding="utf-8")
        event = make_event(T.MOUTH_SPEECH_STARTED, "m1", producer=VOICE, trace_ref=journal_trace("voice.speech.started"))
        await core.conversation_events.append(event)
        gate, running = threading.Event(), []

        def slow(stored_event, path):
            running.append(1)
            gate.wait(5)
            return {"ok": True, "status": "not_found"}

        monkeypatch.setattr(control_center_module, "drill_down", slow)
        monkeypatch.setattr(control_center_module, "TRACE_SLOT_WAIT_S", 0.3)
        path = f"/api/conversations/events/{event.event_id}/trace"
        first = [asyncio.create_task(get(client, path)) for _ in range(2)]
        await wait_until(lambda: len(running) == 2)
        status, body = await get(client, path)
        assert (status, body["code"]) == (503, "trace_busy") and len(running) == 2
        gate.set()
        assert [status for status, _ in await asyncio.gather(*first)] == [200, 200]


async def wait_until(predicate, *, timeout_s: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.02)
