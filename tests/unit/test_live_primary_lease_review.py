"""Independent primary Live lease review; controlled wire, real Core HTTP/SQLite."""
import asyncio

import pytest

from jarvis.domain.live_lifecycle import LiveLifecycleState
from jarvis.runtime.live_frontend_session import LiveFrontendSession
from tests.unit.test_live_lifecycle_protocol import protocol  # noqa: F401


class LeaseCheckingWire:
    """Provider ACKs only; assertions inspect durable Core at each wire boundary."""

    def __init__(self, client):
        self.client = client
        self.incoming = asyncio.Queue()
        self.sent = []
        self.records_at_send = []
        self.close_calls = 0
        self.close_reason = "close_requested"
        self.close_sent = asyncio.Event()
        self.allow_active_close = False

    async def send_json(self, message):
        record = await self.client.live_session_status()
        self.records_at_send.append(record)
        self.sent.append(message)
        if message["type"] == "session.start":
            assert record is not None, "Provider start preceded durable reservation"
            assert record.start_may_have_been_sent, "Provider start preceded durable mark"
            assert record.state is LiveLifecycleState.STARTING
            self.incoming.put_nowait({
                "type": "session.started", "event_id": "provider-start",
                "session": {"id": "provider-primary", "status": "active"},
            })
        elif message["type"] == "session.close":
            self.close_sent.set()
            assert record is not None
            assert self.allow_active_close or record.state in {
                LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
            }
            self.incoming.put_nowait({
                "type": "session.closed", "event_id": "provider-close",
                "session": {"id": "provider-primary", "status": "active"},
                "reason": self.close_reason, "usage": {"seconds": 3.5},
            })

    async def receive_json(self):
        return await self.incoming.get()

    async def close(self):
        self.close_calls += 1


async def test_primary_wire_is_fenced_by_durable_reserve_mark_and_final_receipt(protocol):
    _, client = protocol
    conversation = await client.create_conversation()
    wire = LeaseCheckingWire(client)

    async def connector():
        assert await client.live_session_status() is not None, "Connector preceded reservation"
        return wire

    session = None
    try:
        session = await asyncio.wait_for(LiveFrontendSession.connect(
            api_key="controlled-secret", voice="marin", context={},
            core=client, conversation_id=conversation["id"], connector=connector,
            start_timeout_s=.5, close_timeout_s=.5, queue_limit=2,
        ), 2)
        record = await client.live_session_status()
        assert record is not None
        assert record.session_id == session.session_id
        assert record.provider_session_id == "provider-primary"
        assert record.state is LiveLifecycleState.ACTIVE
        await asyncio.wait_for(session.close(), 2)
        terminal = await client.live_session_status(session.session_id)
        assert terminal.state is LiveLifecycleState.STOPPED
        assert terminal.provider_usage_seconds == 3.5
        assert terminal.provider_usage_final is True
        assert await client.live_session_status() is None
        assert [message["type"] for message in wire.sent] == ["session.start", "session.close"]
    finally:
        if session is not None:
            await asyncio.wait_for(session.close(), 2)


async def test_failed_reservation_never_calls_connector(protocol, monkeypatch):
    _, client = protocol
    conversation = await client.create_conversation()
    connections = []

    async def refuse(*args, **kwargs):
        raise OSError("controlled storage unavailable")

    async def connector():
        connections.append(True)
        raise AssertionError("Reservation failed; connector must not run")

    monkeypatch.setattr(client, "reserve_live_session", refuse)
    with pytest.raises(Exception):
        await asyncio.wait_for(LiveFrontendSession.connect(
            api_key="controlled-secret", voice="marin", context={},
            core=client, conversation_id=conversation["id"], connector=connector,
            start_timeout_s=.05, close_timeout_s=.05,
        ), 1)
    assert connections == []


async def test_failed_mark_cannot_send_billable_start(protocol, monkeypatch):
    _, client = protocol
    conversation = await client.create_conversation()
    wire = LeaseCheckingWire(client)

    async def refuse(*args, **kwargs):
        raise OSError("controlled mark failure before commit")

    monkeypatch.setattr(client, "mark_live_session_start", refuse)
    with pytest.raises(Exception):
        await asyncio.wait_for(LiveFrontendSession.connect(
            api_key="controlled-secret", voice="marin", context={},
            core=client, conversation_id=conversation["id"],
            connector=lambda: asyncio.sleep(0, result=wire),
            start_timeout_s=.1, close_timeout_s=.1,
        ), 1)
    assert not any(message["type"] == "session.start" for message in wire.sent)


async def test_cancel_at_bind_retains_provider_id_but_never_publishes_active(protocol, monkeypatch):
    _, client = protocol
    conversation = await client.create_conversation()
    wire = LeaseCheckingWire(client)
    bind_entered, release_bind = asyncio.Event(), asyncio.Event()
    original_bind = client.bind_live_session
    original_transition = client.transition_live_session
    transitions = []

    async def held_bind(*args, **kwargs):
        bind_entered.set()
        await release_bind.wait()
        return await original_bind(*args, **kwargs)

    async def observed_transition(*args, **kwargs):
        target = kwargs.get("target", args[4] if len(args) > 4 else None)
        transitions.append(target)
        return await original_transition(*args, **kwargs)

    monkeypatch.setattr(client, "bind_live_session", held_bind)
    monkeypatch.setattr(client, "transition_live_session", observed_transition)
    call = asyncio.create_task(LiveFrontendSession.connect(
        api_key="controlled-secret", voice="marin", context={},
        core=client, conversation_id=conversation["id"],
        connector=lambda: asyncio.sleep(0, result=wire),
        start_timeout_s=.5, close_timeout_s=.5,
    ))
    try:
        await asyncio.wait_for(bind_entered.wait(), 1)
        assert not call.done()
        call.cancel()
        await asyncio.sleep(0)
        release_bind.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, 2)
        assert LiveLifecycleState.ACTIVE not in transitions
        assert any(message["type"] == "session.close" for message in wire.sent)
        assert await client.live_session_status() is None
    finally:
        release_bind.set()
        if not call.done():
            call.cancel()
        await asyncio.wait_for(asyncio.gather(call, return_exceptions=True), 2)


@pytest.mark.parametrize("failure_after_commit", [False, True])
async def test_terminal_receipt_retry_retains_cas_and_exact_payload(
    protocol, monkeypatch, failure_after_commit,
):
    from jarvis.runtime.live_primary_owner import DurableLiveSessionOwner

    _, client = protocol
    owner = DurableLiveSessionOwner(client, "receipt-retry", owner_incarnation_id="review-owner")
    original = client.finalize_live_session
    calls = []
    recovered = asyncio.Event()

    async def flaky_finalize(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            if failure_after_commit:
                await original(*args, **kwargs)
            raise OSError("controlled finalization transport/storage failure")
        result = await original(*args, **kwargs)
        recovered.set()
        return result

    await owner.reserve()
    await owner.before_start_send()
    await owner.session_started("provider-primary")
    monkeypatch.setattr(client, "finalize_live_session", flaky_finalize)
    try:
        with pytest.raises(OSError):
            await owner.session_closed("provider-primary", "close_requested", 3.5)
        await asyncio.wait_for(recovered.wait(), 1)
        record = await client.live_session_status("receipt-retry")
        assert record.state is LiveLifecycleState.STOPPED
        assert record.provider_usage_seconds == 3.5
        assert owner.record == record
        assert calls[0] == calls[1], "Retry must preserve exact terminal elapsed/usage and revision"
    finally:
        await owner.close()
        # A failing review must not leave its intentionally blocked retry alive.
        retry = owner._receipt_retry
        if retry is not None and not retry.done():
            retry.cancel()
            await asyncio.gather(retry, return_exceptions=True)


async def test_primary_heartbeat_and_concurrent_usage_share_one_cas_owner(protocol, monkeypatch):
    from jarvis.runtime.live_primary_owner import DurableLiveSessionOwner

    core, client = protocol
    core.live_lifecycle.lease_seconds = 1
    owner = DurableLiveSessionOwner(client, "serialized-owner", owner_incarnation_id="review-owner")
    heartbeat_seen = asyncio.Event()
    heartbeat = client.heartbeat_live_session
    usage = client.update_live_session_usage
    concurrent = 0
    peak = 0

    async def observed_call(method, *args, **kwargs):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        try:
            await asyncio.sleep(.03)
            return await method(*args, **kwargs)
        finally:
            concurrent -= 1

    async def observed_heartbeat(*args, **kwargs):
        result = await observed_call(heartbeat, *args, **kwargs)
        heartbeat_seen.set()
        return result

    async def observed_usage(*args, **kwargs):
        return await observed_call(usage, *args, **kwargs)

    monkeypatch.setattr(client, "heartbeat_live_session", observed_heartbeat)
    monkeypatch.setattr(client, "update_live_session_usage", observed_usage)
    await owner.reserve()
    await owner.before_start_send()
    await owner.session_started("provider-primary")
    try:
        await asyncio.wait_for(asyncio.gather(*(owner.usage_updated(2.0) for _ in range(16))), 2)
        await asyncio.wait_for(heartbeat_seen.wait(), 1)
        assert peak == 1
        assert not owner.fenced
        assert owner.record.provider_usage_seconds == 2.0
        await owner.session_closed("provider-primary", "close_requested", 3.5)
    finally:
        await owner.close()


async def test_unknown_provider_terminal_reason_cannot_release_durable_lease(protocol):
    from jarvis.domain.voice_frontend import VoiceOperationStatus

    _, client = protocol
    conversation = await client.create_conversation()
    wire = LeaseCheckingWire(client)
    wire.close_reason = "looks_closed_but_not_a_provider_reason"
    session = await asyncio.wait_for(LiveFrontendSession.connect(
        api_key="controlled-secret", voice="marin", context={},
        core=client, conversation_id=conversation["id"],
        connector=lambda: asyncio.sleep(0, result=wire),
        start_timeout_s=.2, close_timeout_s=.1,
    ), 1)
    try:
        result = await asyncio.wait_for(session.close(), 1)
        assert result.status is VoiceOperationStatus.UNKNOWN
        record = await client.live_session_status()
        assert record is not None and record.state is not LiveLifecycleState.STOPPED
    finally:
        await asyncio.wait_for(session.close(), 1)


@pytest.mark.parametrize("committed_before_cancel", [False, True])
async def test_cancel_at_mark_barrier_never_sends_start(protocol, monkeypatch, committed_before_cancel):
    _, client = protocol
    conversation = await client.create_conversation()
    wire = LeaseCheckingWire(client)
    entered, release = asyncio.Event(), asyncio.Event()
    original = client.mark_live_session_start

    async def held_mark(*args, **kwargs):
        result = await original(*args, **kwargs) if committed_before_cancel else None
        entered.set()
        await release.wait()
        return result if committed_before_cancel else await original(*args, **kwargs)

    monkeypatch.setattr(client, "mark_live_session_start", held_mark)
    existing_tasks = set(asyncio.all_tasks())
    call = asyncio.create_task(LiveFrontendSession.connect(
        api_key="controlled-secret", voice="marin", context={},
        core=client, conversation_id=conversation["id"],
        connector=lambda: asyncio.sleep(0, result=wire),
        start_timeout_s=.2, close_timeout_s=.1,
    ))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        call.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, 1)
        assert not any(message["type"] == "session.start" for message in wire.sent)
        record = await client.live_session_status()
        assert record is None or record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
        heartbeat_tasks = [task for task in asyncio.all_tasks() - existing_tasks
                           if task.get_name() == "jarvis-live-primary-heartbeat"]
        assert not heartbeat_tasks, "Failed connect retained primary heartbeat after transport cleanup"
    finally:
        release.set()
        if not call.done():
            call.cancel()
        await asyncio.wait_for(asyncio.gather(call, return_exceptions=True), 1)
        leaked = [task for task in asyncio.all_tasks() - existing_tasks
                  if task.get_name() == "jarvis-live-primary-heartbeat"]
        for task in leaked:
            task.cancel()
        await asyncio.gather(*leaked, return_exceptions=True)


async def test_pending_core_usage_cannot_block_urgent_provider_close(protocol, monkeypatch):
    _, client = protocol
    conversation = await client.create_conversation()
    wire = LeaseCheckingWire(client)
    wire.allow_active_close = True  # Urgent close still runs if STOPPING storage is unavailable.
    entered, release = asyncio.Event(), asyncio.Event()
    original = client.update_live_session_usage

    async def held_usage(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(client, "update_live_session_usage", held_usage)
    session = await LiveFrontendSession.connect(
        api_key="controlled-secret", voice="marin", context={},
        core=client, conversation_id=conversation["id"],
        connector=lambda: asyncio.sleep(0, result=wire),
        start_timeout_s=.2, close_timeout_s=.05,
    )
    usage_task = asyncio.create_task(session._lifecycle_owner.usage_updated(1.0))
    close_task = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        close_task = asyncio.create_task(session.close())
        await asyncio.wait_for(wire.close_sent.wait(), .3)
        await asyncio.wait_for(asyncio.shield(close_task), .3)
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(usage_task, return_exceptions=True), 1)
        if close_task is not None:
            await asyncio.wait_for(asyncio.gather(close_task, return_exceptions=True), 1)
        else:
            await asyncio.wait_for(session.close(), 1)
        # The bounded UNKNOWN return deliberately leaves terminal persistence
        # owned. Do not tear down its Core/client while that owner is settling.
        async with asyncio.timeout(2):
            while session._lifecycle_owner.record.state is not LiveLifecycleState.STOPPED:
                await asyncio.sleep(.005)


async def test_real_http_storage_error_preserves_receipt_retry(protocol, monkeypatch):
    from jarvis.runtime.live_primary_owner import DurableLiveSessionOwner

    core, client = protocol
    owner = DurableLiveSessionOwner(client, "http-receipt", owner_incarnation_id="review-owner")
    original = core.state.cas_live_session
    failed = False
    recovered = asyncio.Event()

    async def flaky_storage(record, **kwargs):
        nonlocal failed
        if record.state is LiveLifecycleState.STOPPED and not failed:
            failed = True
            raise OSError("controlled SQLite finalization failure")
        result = await original(record, **kwargs)
        if record.state is LiveLifecycleState.STOPPED:
            recovered.set()
        return result

    await owner.reserve()
    await owner.before_start_send()
    await owner.session_started("provider-primary")
    monkeypatch.setattr(core.state, "cas_live_session", flaky_storage)
    try:
        with pytest.raises(Exception):
            await owner.session_closed("provider-primary", "close_requested", 3.5)
        await asyncio.wait_for(recovered.wait(), 1)
        assert (await client.live_session_status("http-receipt")).state is LiveLifecycleState.STOPPED
    finally:
        await owner.close()
        retry = owner._receipt_retry
        if retry is not None and not retry.done():
            retry.cancel()
            await asyncio.gather(retry, return_exceptions=True)
