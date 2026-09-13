"""Independent crash/ownership probes; real local HTTP/SQLite, no provider."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.live_lifecycle import LiveCloseEvidence, LiveLifecycleState
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.live_primary_owner import DurableLiveSessionOwner
from tests.unit.test_live_lifecycle_protocol import protocol  # noqa: F401


async def dispose(owner):
    await owner.close()
    retry = owner._receipt_retry
    if retry is not None and not retry.done():
        retry.cancel()
        await asyncio.gather(retry, return_exceptions=True)


async def active(client, name="ownership-review"):
    owner = DurableLiveSessionOwner(client, name, owner_incarnation_id="primary-review")
    await owner.reserve()
    await owner.before_start_send()
    await owner.session_started("provider-review")
    return owner


@pytest.mark.parametrize("operation", ["reserve", "mark"])
async def test_unknown_commit_response_retries_exact_primary_operation(protocol, monkeypatch, operation):
    _, client = protocol
    owner = DurableLiveSessionOwner(client, "unknown-commit", owner_incarnation_id="primary-review")
    name = "reserve_live_session" if operation == "reserve" else "mark_live_session_start"
    original = getattr(client, name)
    calls = []

    async def lost_once(*args, **kwargs):
        calls.append((args, kwargs))
        result = await original(*args, **kwargs)
        if len(calls) == 1:
            raise OSError("controlled response lost after commit")
        return result

    if operation == "mark":
        await owner.reserve()
    monkeypatch.setattr(client, name, lost_once)
    invoke = owner.reserve if operation == "reserve" else owner.before_start_send
    try:
        with pytest.raises(OSError):
            await invoke()
        committed = await client.live_session_status("unknown-commit")
        await invoke()
        assert owner.record == committed
        assert calls[0] == calls[1]
        assert owner.record.start_may_have_been_sent is (operation == "mark")
    finally:
        await dispose(owner)


async def test_two_primary_owners_cannot_reserve_same_logical_identity(protocol):
    _, client = protocol
    owners = [DurableLiveSessionOwner(client, "same-logical", owner_incarnation_id=f"owner-{n}")
              for n in range(2)]
    try:
        results = await asyncio.gather(*(owner.reserve() for owner in owners), return_exceptions=True)
        assert sum(isinstance(result, CoreProtocolError) for result in results) == 1
        winner = next(owner for owner in owners if owner.record is not None)
        assert await client.live_session_status("same-logical") == winner.record
        assert sum(owner._heartbeat_task is not None for owner in owners) == 1
    finally:
        await asyncio.gather(*(dispose(owner) for owner in owners))


async def test_stolen_epoch_fences_heartbeat_and_cannot_stop_new_owner(protocol):
    core, client = protocol
    core.live_lifecycle.lease_seconds = 1
    owner = await active(client)
    fenced = asyncio.Event()
    owner.set_fenced_callback(lambda: signal(fenced))
    try:
        await owner.mark_unknown("controlled_disconnect")
        before = owner.record
        claimed = await client.claim_live_session_reap(before.session_id, "other-reaper", before.revision)
        assert claimed.owner_epoch > before.owner_epoch
        await asyncio.wait_for(fenced.wait(), 1)
        assert owner.fenced
        with pytest.raises(RuntimeError):
            owner.assert_active()
        await owner.begin_stop("user_stop")
        assert owner.record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
        assert await client.live_session_status(before.session_id) == claimed
    finally:
        await dispose(owner)


async def signal(event):
    event.set()


@pytest.mark.parametrize("status", [500, 503])
async def test_terminal_receipt_survives_retryable_http_storage_failure(protocol, monkeypatch, status):
    _, client = protocol
    owner = await active(client)
    original = client.finalize_live_session
    attempts = []
    recovered = asyncio.Event()

    async def unavailable_once(*args, **kwargs):
        attempts.append((args, kwargs))
        if len(attempts) == 1:
            raise CoreProtocolError(status, "storage_unavailable", "controlled storage outage")
        result = await original(*args, **kwargs)
        recovered.set()
        return result

    monkeypatch.setattr(client, "finalize_live_session", unavailable_once)
    try:
        with pytest.raises(CoreProtocolError):
            await owner.session_closed("provider-review", "close_requested", 4.0)
        await asyncio.wait_for(recovered.wait(), .6)
        assert owner.record.state is LiveLifecycleState.STOPPED
        assert owner.record.provider_usage_seconds == 4.0
        assert attempts[0] == attempts[1]
    finally:
        await dispose(owner)


async def test_identical_receipt_during_retry_preserves_original_frozen_counters(protocol, monkeypatch):
    _, client = protocol
    owner = await active(client)
    original = client.finalize_live_session
    unavailable = True

    async def controlled_finalize(*args, **kwargs):
        if unavailable:
            raise OSError("controlled outage")
        return await original(*args, **kwargs)

    monkeypatch.setattr(client, "finalize_live_session", controlled_finalize)
    try:
        with pytest.raises(OSError):
            await owner.session_closed("provider-review", "close_requested", 4.0)
        retained = owner._pending_receipt
        await asyncio.sleep(.01)
        unavailable = False
        await owner.session_closed("provider-review", "close_requested", 4.0)
        assert owner.record.state is LiveLifecycleState.STOPPED
        assert owner.record.active_seconds == retained[3]
        assert owner.record.provider_usage_seconds == 4.0
    finally:
        await dispose(owner)


async def test_conflicting_receipt_never_replaces_valid_retained_terminal(protocol, monkeypatch):
    _, client = protocol
    owner = await active(client)
    original = client.finalize_live_session
    unavailable = True

    async def controlled_finalize(*args, **kwargs):
        if unavailable:
            raise OSError("controlled outage")
        return await original(*args, **kwargs)

    monkeypatch.setattr(client, "finalize_live_session", controlled_finalize)
    try:
        with pytest.raises(OSError):
            await owner.session_closed("provider-review", "close_requested", 4.0)
        retained = owner._pending_receipt
        for provider, reason, seconds in [("wrong-provider", "close_requested", 4.0),
                                          ("provider-review", "expired", 4.0),
                                          ("provider-review", "close_requested", 5.0)]:
            with pytest.raises(RuntimeError):
                await owner.session_closed(provider, reason, seconds)
            assert owner._pending_receipt == retained
        unavailable = False
        await asyncio.wait_for(owner._closed.wait(), .6)
        assert owner.record.provider_usage_seconds == 4.0
        assert owner.record.close_reason == "close_requested"
        with pytest.raises(RuntimeError):
            await owner.session_closed("provider-review", "expired", 4.0)
    finally:
        await dispose(owner)


async def test_cancellation_during_terminal_commit_keeps_receipt_owned(protocol, monkeypatch):
    _, client = protocol
    owner = await active(client)
    original = client.finalize_live_session
    entered = asyncio.Event()
    recovered = asyncio.Event()
    calls = []

    async def held_first_finalize(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            entered.set()
            await asyncio.Event().wait()
        result = await original(*args, **kwargs)
        recovered.set()
        return result

    monkeypatch.setattr(client, "finalize_live_session", held_first_finalize)
    task = asyncio.create_task(owner.session_closed("provider-review", "close_requested", 4.0))
    try:
        await asyncio.wait_for(entered.wait(), .5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(recovered.wait(), .6)
        assert owner.record.state is LiveLifecycleState.STOPPED
        assert calls[0] == calls[1]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await dispose(owner)


async def test_late_primary_receipt_converges_after_reaper_finalizes(protocol):
    _, client = protocol
    owner = await active(client)
    try:
        await owner.mark_unknown("controlled_disconnect")
        prior = owner.record
        claimed = await client.claim_live_session_reap(prior.session_id, "recovery-owner", prior.revision)
        with pytest.raises(CoreProtocolError):
            await owner.session_closed("provider-review", "close_requested", 4.0)
        terminal = await client.finalize_live_session(
            claimed.session_id, claimed.owner_incarnation_id, claimed.owner_epoch,
            claimed.revision, "provider-review", 0.0, 4.0, "close_requested",
            LiveCloseEvidence.PROVIDER_SESSION_CLOSED,
        )
        assert terminal.state is LiveLifecycleState.STOPPED
        retry = owner._receipt_retry
        if retry is not None:
            await asyncio.wait_for(asyncio.shield(retry), .7)
        assert await client.live_session_status(prior.session_id) == terminal
    finally:
        await dispose(owner)


async def test_takeover_without_terminal_does_not_discard_only_close_receipt(protocol, monkeypatch):
    _, client = protocol
    owner = await active(client)
    try:
        await owner.mark_unknown("controlled_disconnect")
        prior = owner.record
        claimed = await client.claim_live_session_reap(prior.session_id, "recovery-owner", prior.revision)
        original = client.finalize_live_session
        stale_attempts = []

        async def observed_finalize(*args, **kwargs):
            if args[1] == owner.owner_incarnation_id:
                stale_attempts.append(args)
            return await original(*args, **kwargs)

        monkeypatch.setattr(client, "finalize_live_session", observed_finalize)
        with pytest.raises(CoreProtocolError):
            await owner.session_closed("provider-review", "close_requested", 4.0)
        await asyncio.sleep(.2)
        assert await client.live_session_status(prior.session_id) == claimed
        assert owner._pending_receipt is not None, "Takeover is not durable terminal evidence"
        assert owner._pending_receipt[:3] == ("provider-review", "close_requested", 4.0)
        assert owner._receipt_retry is not None and not owner._receipt_retry.done()
        assert len(stale_attempts) <= 3, "Fenced mutation retry must back off"
        terminal = await original(
            claimed.session_id, claimed.owner_incarnation_id, claimed.owner_epoch,
            claimed.revision, "provider-review", 0.0, 4.0, "close_requested",
            LiveCloseEvidence.PROVIDER_SESSION_CLOSED,
        )
        await asyncio.wait_for(asyncio.shield(owner._receipt_retry), .7)
        assert owner.record == terminal
        assert owner._pending_receipt is None
    finally:
        await dispose(owner)


async def test_close_retains_then_joins_recoverable_receipt_without_heartbeat_leak(protocol, monkeypatch):
    _, client = protocol
    owner = await active(client)
    heartbeat = owner._heartbeat_task
    original = client.finalize_live_session
    unavailable = True

    async def controlled_finalize(*args, **kwargs):
        if unavailable:
            raise OSError("controlled storage outage")
        return await original(*args, **kwargs)

    monkeypatch.setattr(client, "finalize_live_session", controlled_finalize)
    try:
        with pytest.raises(OSError):
            await owner.session_closed("provider-review", "close_requested", 4.0)
        retry = owner._receipt_retry
        await asyncio.wait_for(owner.close(), .5)
        assert heartbeat.done()
        assert retry is owner._receipt_retry and not retry.done()
        assert owner._pending_receipt is not None
        unavailable = False
        await asyncio.wait_for(asyncio.shield(retry), .6)
        assert owner.record.state is LiveLifecycleState.STOPPED
        await owner.close()
        assert not owner._stop_persistence
        assert retry.done()
    finally:
        await dispose(owner)


async def test_close_keeps_slow_stop_mutation_owned_until_it_converges(protocol, monkeypatch):
    _, client = protocol
    owner = await active(client)
    heartbeat = owner._heartbeat_task
    original = client.transition_live_session
    entered, release = asyncio.Event(), asyncio.Event()

    async def held_stop(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(client, "transition_live_session", held_stop)
    stop = owner.request_stop("user_stop")
    try:
        await asyncio.wait_for(entered.wait(), .5)
        await asyncio.wait_for(owner.close(), .5)
        assert heartbeat.done()
        assert stop in owner._stop_persistence and not stop.done()
        release.set()
        await asyncio.wait_for(asyncio.shield(stop), .5)
        await asyncio.sleep(0)
        assert not owner._stop_persistence
        assert owner.record.state is LiveLifecycleState.STOPPING
        await owner.session_closed("provider-review", "close_requested", 4.0)
        await owner.close()
        assert owner.record.state is LiveLifecycleState.STOPPED
    finally:
        release.set()
        await asyncio.gather(stop, return_exceptions=True)
        await dispose(owner)
