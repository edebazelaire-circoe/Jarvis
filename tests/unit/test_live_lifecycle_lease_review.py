"""Independent Task13A fault probes; all storage and transports are local."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import json

import pytest

from jarvis.domain.live_lifecycle import LiveCloseEvidence, LiveLifecycleConflict, LiveLifecycleState, LiveOwnerKind, live_seconds, parse_live_time
from jarvis.core.live_lifecycle import LiveLifecycleService
from jarvis.core.live_lifecycle import LiveLifecycleService
from tests.unit.test_live_lifecycle_lease import NOW, bound_active, opened, reserve
from tests.unit.test_live_lifecycle_protocol import protocol  # noqa: F401


async def test_clock_regression_does_not_rewind_a_durable_heartbeat(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        service.clock.set(NOW + timedelta(seconds=10))
        row = await service.heartbeat(row.session_id, "owner-a", 1, row.revision)
        service.clock.set(NOW + timedelta(seconds=5))
        with pytest.raises((ValueError, LiveLifecycleConflict)):
            await service.heartbeat(row.session_id, "owner-a", 1, row.revision)
        assert await service.status() == row
    finally:
        await repo.close()


@pytest.mark.parametrize("field", ["owner_epoch", "expected_revision"])
async def test_idempotent_mark_start_still_validates_integer_identity(tmp_path, field):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await reserve(service)
        await service.mark_start(row.session_id, "owner-a", 1, 1)
        args = dict(session_id=row.session_id, owner_incarnation_id="owner-a",
                    owner_epoch=1, expected_revision=1)
        args[field] = True
        with pytest.raises(ValueError):
            await service.mark_start(**args)
    finally:
        await repo.close()


async def test_reap_retry_cannot_mistake_primary_transition_for_claim(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await reserve(service)
        row = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                       LiveLifecycleState.UNKNOWN_REAP_REQUIRED, "transport_lost")
        with pytest.raises(LiveLifecycleConflict):
            await service.claim_reap(row.session_id, "owner-a", row.revision - 1)
        claimed = await service.claim_reap(row.session_id, "owner-a", row.revision)
        assert claimed.owner_kind is LiveOwnerKind.REAPER and claimed.owner_epoch == 2
    finally:
        await repo.close()


@pytest.mark.parametrize("operation", ["status", "reserve"])
async def test_index_payload_state_divergence_cannot_release_global_slot(tmp_path, operation):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        await repo._run(lambda conn: conn.execute(
            "UPDATE live_sessions SET state='stopped' WHERE session_id=?", (row.session_id,)))
        # A corrupt terminal projection must never hide an ACTIVE durable body.
        with pytest.raises((ValueError, RuntimeError)):
            if operation == "status":
                await service.status()
            else:
                await reserve(service, "replacement", "owner-b")
    finally:
        await repo.close()


async def test_primary_key_payload_identity_divergence_fails_closed(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await reserve(service)
        await repo._run(lambda conn: conn.execute(
            "UPDATE live_sessions SET session_id='different' WHERE session_id=?", (row.session_id,)))
        with pytest.raises(RuntimeError, match="columns disagree"):
            await service.status("different")
        with pytest.raises(RuntimeError, match="columns disagree"):
            await service.status()
    finally:
        await repo.close()


def test_oversized_integer_usage_is_validation_error_not_overflow():
    with pytest.raises(ValueError):
        live_seconds(10 ** 1000, "active_seconds")


def test_oversized_integer_lease_is_validation_error_not_overflow():
    with pytest.raises(ValueError, match="invalid Live lease duration"):
        LiveLifecycleService(object(), lease_seconds=10 ** 1000)


async def test_idempotent_heartbeat_requires_exact_previous_revision(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        service.clock.advance(1)
        heartbeat = await service.heartbeat(row.session_id, "owner-a", 1, row.revision)
        with pytest.raises(LiveLifecycleConflict, match="live_stale_revision"):
            await service.heartbeat(row.session_id, "owner-a", 1, heartbeat.revision + 10)
        service.clock.advance(5)
        assert await service.heartbeat(row.session_id, "owner-a", 1, row.revision) == heartbeat
    finally:
        await repo.close()


async def test_transition_reason_shape_and_retry_semantics_are_exact(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await reserve(service)
        row = await service.mark_start(row.session_id, "owner-a", 1, row.revision)
        row = await service.bind(row.session_id, "owner-a", 1, row.revision, "provider-a")
        with pytest.raises(ValueError, match="non-closing"):
            await service.transition(row.session_id, "owner-a", 1, row.revision,
                                     LiveLifecycleState.ACTIVE, "unexpected")
        row = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                       LiveLifecycleState.ACTIVE)
        stopping = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                             LiveLifecycleState.STOPPING, "shutdown")
        with pytest.raises(LiveLifecycleConflict, match="live_stale_revision"):
            await service.transition(row.session_id, "owner-a", 1, row.revision,
                                     LiveLifecycleState.STOPPING, "different")
        assert await service.transition(row.session_id, "owner-a", 1, row.revision,
                                        LiveLifecycleState.STOPPING, "shutdown") == stopping
    finally:
        await repo.close()


def test_oversized_lease_configuration_is_validation_error_not_overflow():
    with pytest.raises(ValueError):
        LiveLifecycleService(None, lease_seconds=10 ** 1000)


async def test_sqlite_primary_key_must_match_record_session_identity(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        await repo._run(lambda conn: conn.execute(
            "UPDATE live_sessions SET session_id='different' WHERE session_id=?", (row.session_id,)))
        with pytest.raises((ValueError, RuntimeError)):
            await service.status("different")
    finally:
        await repo.close()


@pytest.mark.parametrize("timestamp", ["9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00"])
def test_timezone_normalization_outside_datetime_range_is_validation_error(timestamp):
    with pytest.raises(ValueError):
        parse_live_time(timestamp, "at")


async def test_usage_cannot_change_a_terminal_receipt(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        row = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                       LiveLifecycleState.STOPPING, "user")
        row = await service.finalize(row.session_id, "owner-a", 1, row.revision,
                                     "provider-a", 2, 2, "user",
                                     LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        with pytest.raises(ValueError, match="reserved for finalize"):
            await service.usage(row.session_id, "owner-a", 1, row.revision,
                                3, 3, True)
        assert await service.status(row.session_id) == row
    finally:
        await repo.close()


async def test_cumulative_usage_cannot_claim_provider_finality(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        with pytest.raises(ValueError, match="reserved for finalize"):
            await service.usage(row.session_id, "owner-a", 1, row.revision,
                                1, 1, True)
        assert await service.status(row.session_id) == row
        payload = row.to_payload()
        payload.update(provider_usage_seconds=1, provider_usage_final=True)
        with pytest.raises(ValueError, match="requires STOPPED"):
            type(row).from_payload(payload)
    finally:
        await repo.close()


@pytest.mark.parametrize("operation", ["mark_start", "bind", "finalize"])
@pytest.mark.parametrize("revision_offset", [0, 1])
async def test_completed_operation_does_not_accept_current_or_future_revision(tmp_path, operation, revision_offset):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await reserve(service)
        row = await service.mark_start(row.session_id, "owner-a", 1, row.revision)
        if operation != "mark_start":
            row = await service.bind(row.session_id, "owner-a", 1, row.revision, "provider")
        if operation == "finalize":
            row = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                           LiveLifecycleState.STOPPING, "user")
            row = await service.finalize(row.session_id, "owner-a", 1, row.revision,
                                         "provider", 1, 1, "user", LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        with pytest.raises(LiveLifecycleConflict):
            if operation == "mark_start":
                await service.mark_start(row.session_id, "owner-a", 1, row.revision + revision_offset)
            elif operation == "bind":
                await service.bind(row.session_id, "owner-a", 1, row.revision + revision_offset, "provider")
            else:
                await service.finalize(row.session_id, "owner-a", 1, row.revision + revision_offset,
                                       "provider", 1, 1, "user", LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        assert await service.status(row.session_id) == row
    finally:
        await repo.close()


async def test_final_retry_cannot_drop_known_usage(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        row = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                       LiveLifecycleState.STOPPING, "user")
        stopped = await service.finalize(row.session_id, "owner-a", 1, row.revision,
                                         "provider-a", 1, 1, "user", LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        with pytest.raises(LiveLifecycleConflict):
            await service.finalize(row.session_id, "owner-a", 1, row.revision,
                                   "provider-a", 1, None, "user", LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        assert await service.status(row.session_id) == stopped
    finally:
        await repo.close()


async def test_duplicate_protocol_keys_never_reserve_an_owner(protocol):
    _, client = protocol
    body = json.dumps(dict(session_id="s", owner_incarnation_id="owner"))
    body = body[:-1] + ',"session_id":"other"}'
    http = await client._http()
    async with http.post(client.base_url + "/v1/live/sessions/reserve",
                         headers=client.headers, data=body) as response:
        assert response.status == 400
    assert await client.live_session_status() is None


async def test_ambiguous_reap_commit_retry_survives_elapsed_core_clock(tmp_path, monkeypatch):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        service.clock.advance(31)
        original = repo.cas_live_session
        failed = False

        async def lose_response(value, *, expected_revision):
            nonlocal failed
            answer = await original(value, expected_revision=expected_revision)
            if not failed:
                failed = True
                raise OSError("commit response lost")
            return answer

        monkeypatch.setattr(repo, "cas_live_session", lose_response)
        with pytest.raises(OSError):
            await service.claim_reap(row.session_id, "reaper", row.revision)
        committed = await service.status()
        service.clock.advance(1)
        retried = await service.claim_reap(row.session_id, "reaper", row.revision)
        assert retried == committed
        assert retried.owner_epoch == 2 and retried.owner_kind is LiveOwnerKind.REAPER
    finally:
        await repo.close()


async def test_heartbeat_commit_retry_does_not_renew_twice_when_core_clock_advances(tmp_path, monkeypatch):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        service.clock.advance(1)
        original = repo.cas_live_session
        failed = False

        async def lose_response(value, *, expected_revision):
            nonlocal failed
            answer = await original(value, expected_revision=expected_revision)
            if not failed:
                failed = True
                raise OSError("heartbeat commit response lost")
            return answer

        monkeypatch.setattr(repo, "cas_live_session", lose_response)
        with pytest.raises(OSError):
            await service.heartbeat(row.session_id, "owner-a", 1, row.revision)
        committed = await service.status()
        service.clock.advance(1)
        assert await service.heartbeat(row.session_id, "owner-a", 1, row.revision) == committed
        assert (await service.status()).lease_deadline == committed.lease_deadline
    finally:
        await repo.close()


async def test_heartbeat_stale_revision_is_not_acknowledged_as_unrelated_usage_commit(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        before = await bound_active(service)
        service.clock.advance(1)
        current = await service.usage(before.session_id, "owner-a", 1, before.revision, 1, 1)
        service.clock.advance(1)
        with pytest.raises(LiveLifecycleConflict):
            await service.heartbeat(before.session_id, "owner-a", 1, before.revision)
        assert await service.status() == current
    finally:
        await repo.close()


@pytest.mark.parametrize("operation", ["mark_start", "bind", "transition", "usage", "claim_reap"])
async def test_operation_retry_never_mistakes_heartbeat_for_its_commit(tmp_path, operation):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        if operation in {"mark_start", "bind"}:
            row = await reserve(service)
            row = await service.mark_start(row.session_id, "owner-a", 1, row.revision)
            if operation == "bind":
                row = await service.bind(row.session_id, "owner-a", 1, row.revision, "provider")
        else:
            row = await bound_active(service)
            if operation == "usage":
                row = await service.usage(row.session_id, "owner-a", 1, row.revision, 1, 1)
            elif operation == "claim_reap":
                service.clock.advance(31)
                row = await service.claim_reap(row.session_id, "reaper", row.revision)
        service.clock.advance(1)
        current = await service.heartbeat(row.session_id, row.owner_incarnation_id,
                                          row.owner_epoch, row.revision)
        service.clock.advance(1)
        with pytest.raises(LiveLifecycleConflict):
            if operation == "mark_start":
                await service.mark_start(row.session_id, "owner-a", 1, row.revision)
            elif operation == "bind":
                await service.bind(row.session_id, "owner-a", 1, row.revision, "provider")
            elif operation == "transition":
                await service.transition(row.session_id, "owner-a", 1, row.revision, LiveLifecycleState.ACTIVE)
            elif operation == "usage":
                await service.usage(row.session_id, "owner-a", 1, row.revision, 1, 1)
            else:
                await service.claim_reap(row.session_id, "reaper", row.revision)
        assert await service.status() == current
    finally:
        await repo.close()


async def test_transition_stopped_cannot_reuse_a_finalize_receipt(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await bound_active(service)
        row = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                       LiveLifecycleState.STOPPING, "user")
        stopped = await service.finalize(row.session_id, "owner-a", 1, row.revision,
                                         "provider-a", 1, 1, "user", LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        with pytest.raises(LiveLifecycleConflict):
            await service.transition(row.session_id, "owner-a", 1, row.revision,
                                     LiveLifecycleState.STOPPED)
        assert await service.status(row.session_id) == stopped
    finally:
        await repo.close()


async def test_future_caller_timestamps_cannot_override_core_lease(protocol):
    _, client = protocol
    http = await client._http()
    async with http.post(client.base_url + "/v1/live/sessions/reserve", headers=client.headers,
                         json=dict(session_id="future", owner_incarnation_id="owner",
                                   heartbeat_at="2199-01-01T00:00:00+00:00",
                                   lease_deadline="2199-01-01T00:00:30+00:00")) as response:
        assert response.status == 400
    assert await client.live_session_status() is None


async def test_late_started_identity_and_cleanup_remain_available_during_core_stop(protocol, monkeypatch):
    core, client = protocol
    row = await client.reserve_live_session("in-flight", "owner")
    row = await client.mark_live_session_start(row.session_id, "owner", 1, row.revision)
    entered, release = asyncio.Event(), asyncio.Event()
    original = core._stop_brain_notice_loop

    async def held_cleanup():
        entered.set()
        await release.wait()
        await original()

    monkeypatch.setattr(core, "_stop_brain_notice_loop", held_cleanup)
    stopping = asyncio.create_task(core.stop())
    try:
        await entered.wait()
        assert await client.live_session_status() == row
        # session.started is evidence of an already marked start, not permission
        # to activate. Losing this ID would remove the reaper's only lookup key.
        bound = await client.bind_live_session(row.session_id, "owner", 1, row.revision, "late-provider")
        assert bound.provider_session_id == "late-provider"
        stopped = await client.transition_live_session(row.session_id, "owner", 1, bound.revision,
                                                       LiveLifecycleState.STOPPING, "shutdown")
        final = await client.finalize_live_session(row.session_id, "owner", 1, stopped.revision,
                                                   "late-provider", 0, 0, "shutdown",
                                                   LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        assert final.state is LiveLifecycleState.STOPPED and final.provider_usage_final
        assert await client.live_session_status() is None
    finally:
        release.set()
        await stopping


async def test_core_stop_fences_new_reservation_before_first_cleanup_await(protocol, monkeypatch):
    core, client = protocol
    entered, release = asyncio.Event(), asyncio.Event()
    original = core._stop_brain_notice_loop

    async def held_cleanup():
        entered.set()
        await release.wait()
        await original()

    monkeypatch.setattr(core, "_stop_brain_notice_loop", held_cleanup)
    stopping = asyncio.create_task(core.stop())
    try:
        await entered.wait()
        http = await client._http()
        async with http.post(client.base_url + "/v1/live/sessions/reserve", headers=client.headers,
                             json=dict(session_id="late", owner_incarnation_id="late-owner")) as response:
            assert response.status == 503
        assert await core.live_lifecycle.status() is None
    finally:
        release.set()
        await stopping


async def test_service_admission_gate_blocks_primary_activation_but_allows_cleanup(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await reserve(service)
        row = await service.mark_start(row.session_id, "owner-a", 1, row.revision)
        row = await service.bind(row.session_id, "owner-a", 1, row.revision, "provider-a")
        service.accepting_new = lambda: False
        with pytest.raises(LiveLifecycleConflict, match="live_core_not_accepting"):
            await service.transition(row.session_id, "owner-a", 1, row.revision,
                                     LiveLifecycleState.ACTIVE)
        stopping = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                             LiveLifecycleState.STOPPING, "shutdown")
        stopped = await service.finalize(stopping.session_id, "owner-a", 1, stopping.revision,
                                         "provider-a", 0, 0, "shutdown",
                                         LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        assert stopped.state is LiveLifecycleState.STOPPED
        with pytest.raises(LiveLifecycleConflict, match="live_core_not_accepting"):
            await service.reserve("replacement", "owner-b")
    finally:
        await repo.close()


async def test_service_admission_gate_blocks_start_marker_and_prestart_cleanup_survives(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await reserve(service)
        service.accepting_new = lambda: False
        with pytest.raises(LiveLifecycleConflict, match="live_core_not_accepting"):
            await service.mark_start(row.session_id, "owner-a", 1, row.revision)
        stopping = await service.transition(row.session_id, "owner-a", 1, row.revision,
                                             LiveLifecycleState.STOPPING, "shutdown")
        stopped = await service.finalize(stopping.session_id, "owner-a", 1, stopping.revision,
                                         None, 0, None, "shutdown", LiveCloseEvidence.START_NOT_SENT)
        assert stopped.state is LiveLifecycleState.STOPPED
    finally:
        await repo.close()
