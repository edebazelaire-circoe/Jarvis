"""Independent Task13B recovery probes; no provider, microphone or inference."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json

import pytest

from jarvis.adapters.openai_live_sideband import AiohttpLiveSidebandTransport, OpenAILiveSidebandCloser
from jarvis.core.live_reaper import LiveLifecycleWatchdog
from jarvis.core.live_lifecycle import LiveLifecycleService
from jarvis.domain.live_lifecycle import LiveLifecycleConflict, LiveLifecycleState
from jarvis.ports.live_sideband import LiveTerminalReceipt
from tests.unit.test_live_lifecycle_lease import opened, reserve, bound_active


@pytest.fixture(autouse=True)
async def no_recovery_tasks_leak_between_probes():
    existing = set(asyncio.all_tasks())
    yield
    deadline = asyncio.get_running_loop().time() + .5
    while True:
        pending = [task for task in asyncio.all_tasks() - existing
                   if not task.done() and task.get_name().startswith("jarvis-live-")]
        if not pending or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(.005)
    assert not pending, f"Recovery tasks still owned after test released every barrier: {pending}"


@dataclass
class ReviewWire:
    incoming: asyncio.Queue = field(default_factory=asyncio.Queue)
    reader_installed: asyncio.Event = field(default_factory=asyncio.Event)
    sent: list[dict] = field(default_factory=list)
    close_calls: int = 0
    send_gate: asyncio.Event | None = None
    cleanup_gate: asyncio.Event | None = None
    closed_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def send_json(self, value):
        assert self.reader_installed.is_set(), "terminal reader must precede close"
        self.sent.append(value)
        if self.send_gate is not None:
            await self.send_gate.wait()

    async def receive_json(self):
        self.reader_installed.set()
        value = await self.incoming.get()
        if isinstance(value, BaseException):
            raise value
        return value

    async def close(self):
        self.close_calls += 1
        if self.cleanup_gate is not None:
            await self.cleanup_gate.wait()
        self.closed_event.set()


def closed(**changes):
    value = {"type": "session.closed", "session": {"id": "provider", "status": "active"},
             "reason": "close_requested", "usage": {"seconds": 2.5}}
    value.update(changes)
    return value


def closer_for(wire):
    async def connect(provider_id):
        assert provider_id == "provider"
        return wire
    return OpenAILiveSidebandCloser(connect)


async def observe_receipt(_receipt):
    pass  # Adapter-only probes do not own or pretend to persist a Core receipt.


async def test_recovery_only_sends_close_after_terminal_reader_is_installed():
    wire = ReviewWire()
    for ignored in [
        {"type": "session.started", "session": {"id": "provider"}},
        {"type": "session.usage.updated", "usage": {"seconds": 100}},
        {"type": "session.output_audio.delta", "delta": "irrelevant"},
    ]:
        wire.incoming.put_nowait(ignored)
    wire.incoming.put_nowait(closed())
    result = await closer_for(wire).close_session("provider", observe_receipt)
    await asyncio.wait_for(wire.closed_event.wait(), .5)
    assert (result.provider_session_id, result.reason, result.usage_seconds) == ("provider", "close_requested", 2.5)
    assert wire.sent == [{"type": "session.close"}]
    assert wire.close_calls == 1


@pytest.mark.parametrize("terminal", [
    None,
    closed(session={"id": "wrong"}),
    closed(reason="stopped"),
    closed(reason=None),
    closed(usage={}),
    closed(usage={"seconds": True}),
    closed(usage={"seconds": -1}),
    closed(usage={"seconds": float("inf")}),
    closed(usage={"seconds": 10 ** 1000}),
    closed(session=[]),
])
async def test_ambiguous_or_malformed_terminal_never_becomes_a_receipt(terminal):
    wire = ReviewWire()
    wire.incoming.put_nowait(terminal)
    with pytest.raises((ValueError, EOFError)):
        await closer_for(wire).close_session("provider", observe_receipt)
    await asyncio.wait_for(wire.closed_event.wait(), .5)
    assert wire.sent == [{"type": "session.close"}]
    assert wire.close_calls == 1


async def test_cancel_close_wait_releases_reader_and_transport():
    wire = ReviewWire()
    task = asyncio.create_task(closer_for(wire).close_session("provider", observe_receipt))
    await wire.reader_installed.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, .5)
    await asyncio.wait_for(wire.closed_event.wait(), .5)
    assert wire.close_calls == 1
    assert not any(t.get_name() == "jarvis-live-sideband-reader" and not t.done()
                   for t in asyncio.all_tasks())


@pytest.mark.parametrize("malformation", ["duplicate", "nonfinite_extra", "float_overflow_extra", "oversized"])
async def test_native_transport_rejects_invalid_json_before_receipt_projection(malformation):
    import aiohttp
    text = json.dumps(closed())
    if malformation == "duplicate":
        text = text.replace('"seconds": 2.5', '"seconds": -1, "seconds": 2.5')
    elif malformation == "nonfinite_extra":
        text = text[:-1] + ',"extra":NaN}'
    elif malformation == "float_overflow_extra":
        text = text[:-1] + ',"extra":1e999}'
    else:
        text = " " * (4 * 1024 * 1024 + 1) + text

    class Socket:
        async def receive(self):
            return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, text, "")

    transport = AiohttpLiveSidebandTransport(None, Socket())
    with pytest.raises(ValueError):
        await transport.receive_json()


async def test_reaper_releases_expired_never_sent_reservation_without_provider_command(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    wire = ReviewWire()
    watchdog = LiveLifecycleWatchdog(service, closer_for(wire), incarnation_id="review-reaper")
    try:
        row = await reserve(service)
        service.clock.advance(31)
        await watchdog.run_once()
        assert (await service.status(row.session_id)).state is LiveLifecycleState.STOPPED
        assert await service.status() is None
        assert wire.sent == []
    finally:
        await repo.close()


async def test_terminal_receipt_is_retained_before_transport_cleanup_finishes(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    gate = asyncio.Event()

    class HeldCleanup(ReviewWire):
        async def close(self):
            self.close_calls += 1
            while not gate.is_set():
                try:
                    await gate.wait()
                except asyncio.CancelledError:
                    continue  # models cleanup already owned by native transport

    wire = HeldCleanup()
    watchdog = LiveLifecycleWatchdog(service, closer_for(wire), incarnation_id="review-reaper",
                                     attempt_timeout_seconds=.03, shutdown_timeout_seconds=.03)
    operation = None
    try:
        row = await bound_active(service)
        service.clock.advance(31)
        wire.incoming.put_nowait(closed(session={"id": "provider-a"}))
        async def connector(provider_id):
            assert provider_id == "provider-a"
            return wire
        watchdog.closer = OpenAILiveSidebandCloser(connector)
        operation = asyncio.create_task(watchdog.run_once())
        for _ in range(100):
            if wire.close_calls:
                break
            await asyncio.sleep(.001)
        assert wire.close_calls == 1
        assert watchdog.pending_receipt is not None or (await service.status(row.session_id)).state is LiveLifecycleState.STOPPED
    finally:
        gate.set()
        if operation is not None:
            await asyncio.wait_for(operation, 1)
        await repo.close()


async def test_shutdown_is_bounded_while_transport_cleanup_resists_cancellation(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    gate, cleaning = asyncio.Event(), asyncio.Event()

    class HeldCleanup(ReviewWire):
        async def close(self):
            self.close_calls += 1
            cleaning.set()
            while not gate.is_set():
                try:
                    await gate.wait()
                except asyncio.CancelledError:
                    continue

    wire = HeldCleanup()
    async def connector(_provider_id):
        return wire
    watchdog = LiveLifecycleWatchdog(service, OpenAILiveSidebandCloser(connector),
                                     attempt_timeout_seconds=.03, shutdown_timeout_seconds=.03)
    stop = None
    try:
        await bound_active(service)
        service.clock.advance(31)
        wire.incoming.put_nowait(closed(session={"id": "provider-a"}))
        watchdog.start()
        await asyncio.wait_for(cleaning.wait(), .5)
        stop = asyncio.create_task(watchdog.stop())
        done, _ = await asyncio.wait({stop}, timeout=.15)
        assert stop in done, "Stop must retain cleanup ownership without waiting forever"
    finally:
        gate.set()
        if stop is not None:
            await asyncio.wait_for(stop, 1)
        await watchdog.stop()
        await repo.close()


async def test_running_recovery_attempt_keeps_its_lease_nonstealable(tmp_path):
    repo, _ = await opened(tmp_path / "state.sqlite")
    service = LiveLifecycleService(repo, lease_seconds=1)
    entered, release = asyncio.Event(), asyncio.Event()

    class HeldCloser:
        async def close_session(self, provider_id, on_receipt):
            entered.set()
            await release.wait()
            receipt = LiveTerminalReceipt(provider_id, "close_requested", 1)
            await on_receipt(receipt)
            return receipt

    watchdog = LiveLifecycleWatchdog(service, HeldCloser(), incarnation_id="owned-reaper",
                                     attempt_timeout_seconds=.45, shutdown_timeout_seconds=.03)
    attempt = None
    try:
        row = await service.reserve("session", "primary")
        row = await service.mark_start(row.session_id, "primary", 1, row.revision)
        row = await service.bind(row.session_id, "primary", 1, row.revision, "provider")
        row = await service.transition(row.session_id, "primary", 1, row.revision,
                                       LiveLifecycleState.UNKNOWN_REAP_REQUIRED, "lost")
        await service.claim_reap(row.session_id, "owned-reaper", row.revision)
        # The original .95s/1s race is now rejected by the constructor below.
        # A valid bounded attempt keeps its claim while its receiver is active.
        await asyncio.sleep(.3)
        attempt = asyncio.create_task(watchdog.run_once())
        await asyncio.wait_for(entered.wait(), .3)
        await asyncio.sleep(.3)
        assert not attempt.done()
        current = await service.status()
        with pytest.raises(LiveLifecycleConflict, match="live_reap_not_eligible"):
            await service.claim_reap(row.session_id, "other-reaper", current.revision)
    finally:
        release.set()
        if attempt is not None:
            await asyncio.gather(attempt, return_exceptions=True)
        await watchdog.stop()
        await repo.close()


@pytest.mark.parametrize("attempt_timeout", [.500001, .95, 1.0])
def test_attempt_budget_without_half_lease_margin_is_rejected(attempt_timeout):
    service = LiveLifecycleService(None, lease_seconds=1)
    with pytest.raises(ValueError):
        LiveLifecycleWatchdog(service, attempt_timeout_seconds=attempt_timeout)


@pytest.mark.parametrize("after_commit", [False, True])
async def test_terminal_storage_retry_retains_exact_receipt_without_another_provider_close(tmp_path, monkeypatch, after_commit):
    repo, service = await opened(tmp_path / "state.sqlite")
    wire = ReviewWire()
    wire.incoming.put_nowait(closed(session={"id": "provider-a"}))
    diagnostics = []

    class Sink:
        def emit(self, kind, message, **fields):
            diagnostics.append({"kind": kind, "message": message, **fields})

    async def connector(_provider_id):
        return wire
    watchdog = LiveLifecycleWatchdog(service, OpenAILiveSidebandCloser(connector), diagnostics=Sink())
    original = service.finalize
    failed = False

    async def uncertain(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            if after_commit:
                await original(*args, **kwargs)
            raise OSError("PRIVATE_STORAGE_SECRET")
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "finalize", uncertain)
    try:
        row = await bound_active(service)
        service.clock.advance(31)
        await watchdog.run_once()
        assert watchdog.pending_receipt == LiveTerminalReceipt("provider-a", "close_requested", 2.5)
        service.clock.advance(1)
        await watchdog.run_once()
        assert watchdog.pending_receipt is None
        stopped = await service.status(row.session_id)
        assert stopped.state is LiveLifecycleState.STOPPED
        assert stopped.provider_usage_seconds == 2.5 and stopped.provider_usage_final
        assert wire.sent == [{"type": "session.close"}]
        assert "PRIVATE_STORAGE_SECRET" not in json.dumps(diagnostics)
    finally:
        await watchdog.stop()
        await repo.close()


@pytest.mark.parametrize("event", [
    None,
    {"type": "error", "error": {"code": "invalid_api_key", "message": "PRIVATE_PROVIDER_SECRET"}},
    {"type": "error", "error": {"code": "rate_limit_exceeded", "message": "PRIVATE_PROVIDER_SECRET"}},
    closed(session={"id": "wrong"}),
    closed(usage={"seconds": None}),
])
async def test_recovery_ambiguities_remain_unknown_with_sanitized_diagnostics(tmp_path, event):
    repo, service = await opened(tmp_path / "state.sqlite")
    wire = ReviewWire()
    wire.incoming.put_nowait(event)
    if event is not None:
        wire.incoming.put_nowait(None)
    diagnostics = []

    class Sink:
        def emit(self, kind, message, **fields):
            diagnostics.append({"kind": kind, "message": message, **fields})

    async def connector(_provider_id):
        return wire
    watchdog = LiveLifecycleWatchdog(service, OpenAILiveSidebandCloser(connector), diagnostics=Sink(),
                                     attempt_timeout_seconds=.1)
    try:
        await bound_active(service)
        service.clock.advance(31)
        await watchdog.run_once()
        assert (await service.status()).state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
        assert watchdog.pending_receipt is None
        assert wire.sent == [{"type": "session.close"}]
        assert "PRIVATE_PROVIDER_SECRET" not in json.dumps(diagnostics)
    finally:
        await watchdog.stop()
        await repo.close()


async def test_received_terminal_survives_a_blocked_close_send(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    gate = asyncio.Event()
    wire = ReviewWire(send_gate=gate)
    wire.incoming.put_nowait(closed(session={"id": "provider-a"}))

    async def connector(_provider_id):
        return wire
    watchdog = LiveLifecycleWatchdog(service, OpenAILiveSidebandCloser(connector),
                                     attempt_timeout_seconds=.03)
    try:
        row = await bound_active(service)
        service.clock.advance(31)
        await watchdog.run_once()
        stored = await service.status(row.session_id)
        assert stored.state is LiveLifecycleState.STOPPED or watchdog.pending_receipt is not None
    finally:
        gate.set()
        await watchdog.stop()
        await repo.close()
