"""Provider-fake tests for the GPT-Live sideband close boundary."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.adapters.openai_live_sideband import AiohttpLiveSidebandTransport, OpenAILiveSidebandCloser


class FakeSidebandTransport:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[object] = asyncio.Queue()
        self.sent: list[dict[str, object]] = []
        self.receiving = asyncio.Event()
        self.closed = 0
        self.closed_event = asyncio.Event()
        self.send_gate: asyncio.Event | None = None

    async def send_json(self, value):
        assert self.receiving.is_set()
        self.sent.append(value)
        if self.send_gate is not None:
            await self.send_gate.wait()

    async def receive_json(self):
        self.receiving.set()
        value = await self.incoming.get()
        if isinstance(value, BaseException):
            raise value
        return value

    async def close(self):
        self.closed += 1
        self.closed_event.set()


def closed_event(*, session_id="provider-a", reason="close_requested", seconds=4.5):
    return {
        "type": "session.closed", "event_id": "provider-event",
        "reason": reason, "session": {"id": session_id, "status": "active"},
        "usage": {"seconds": seconds},
    }


async def accept_receipt(_receipt):
    return None


def test_oversized_integer_cleanup_timeout_is_a_stable_validation_error():
    with pytest.raises(ValueError, match="cleanup timeout"):
        OpenAILiveSidebandCloser(lambda _id: None, cleanup_timeout_seconds=10 ** 1000)


@pytest.mark.parametrize("raw", ["\ud800", "[" * 2000 + "]" * 2000, "{"])
async def test_native_json_decode_failures_are_stable_validation_errors(raw):
    import aiohttp

    class Socket:
        async def receive(self):
            return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, raw, "")

    with pytest.raises(ValueError):
        await AiohttpLiveSidebandTransport(None, Socket()).receive_json()


async def test_receiver_exists_before_exact_close_and_matching_receipt_is_returned():
    transport = FakeSidebandTransport()
    transport.incoming.put_nowait({"type": "session.usage.updated", "usage": {"seconds": 3}})
    transport.incoming.put_nowait(closed_event())
    closer = OpenAILiveSidebandCloser(lambda _session_id: asyncio.sleep(0, result=transport))
    receipt = await closer.close_session("provider-a", accept_receipt)
    await asyncio.wait_for(transport.closed_event.wait(), timeout=.1)
    assert transport.sent == [{"type": "session.close"}]
    assert receipt.provider_session_id == "provider-a"
    assert receipt.reason == "close_requested" and receipt.usage_seconds == 4.5
    assert transport.closed == 1
    assert all(message["type"] not in {"session.start", "session.input_audio.append"}
               for message in transport.sent)


async def test_terminal_receipt_is_delivered_even_if_close_send_never_returns():
    transport = FakeSidebandTransport()
    transport.send_gate = asyncio.Event()
    transport.incoming.put_nowait(closed_event())
    observed = []

    async def retain(receipt):
        observed.append(receipt)

    closer = OpenAILiveSidebandCloser(lambda _id: asyncio.sleep(0, result=transport))
    receipt = await asyncio.wait_for(closer.close_session("provider-a", retain), timeout=.1)
    assert observed == [receipt]
    assert transport.sent == [{"type": "session.close"}]


@pytest.mark.parametrize("event", [
    closed_event(session_id="wrong"),
    closed_event(reason="invented"),
    closed_event(seconds=None),
    closed_event(seconds=float("inf")),
    {"type": "session.closed", "reason": "close_requested", "session": {"id": "provider-a"}},
])
async def test_wrong_or_malformed_terminal_event_never_becomes_a_receipt(event):
    transport = FakeSidebandTransport()
    transport.incoming.put_nowait(event)
    closer = OpenAILiveSidebandCloser(lambda _session_id: asyncio.sleep(0, result=transport))
    with pytest.raises(ValueError):
        await closer.close_session("provider-a", accept_receipt)
    await asyncio.wait_for(transport.closed_event.wait(), timeout=.1)
    assert transport.sent == [{"type": "session.close"}] and transport.closed == 1


async def test_eof_timeout_and_attach_error_never_return_close_evidence():
    eof = FakeSidebandTransport()
    eof.incoming.put_nowait(None)
    with pytest.raises(EOFError):
        await OpenAILiveSidebandCloser(lambda _id: asyncio.sleep(0, result=eof)).close_session(
            "provider-a", accept_receipt,
        )

    blocked = FakeSidebandTransport()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            OpenAILiveSidebandCloser(lambda _id: asyncio.sleep(0, result=blocked)).close_session(
                "provider-a", accept_receipt,
            ),
            timeout=.02,
        )
    await asyncio.wait_for(blocked.closed_event.wait(), timeout=.1)
    assert blocked.closed == 1

    async def rejected(_session_id):
        raise PermissionError("HTTP-like 401")
    with pytest.raises(PermissionError):
        await OpenAILiveSidebandCloser(rejected).close_session("provider-a", accept_receipt)


async def test_cancelled_close_cancels_reader_and_closes_transport():
    transport = FakeSidebandTransport()
    closer = OpenAILiveSidebandCloser(lambda _id: asyncio.sleep(0, result=transport))
    task = asyncio.create_task(closer.close_session("provider-a", accept_receipt))
    await transport.receiving.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(transport.closed_event.wait(), timeout=.1)
    assert transport.closed == 1
