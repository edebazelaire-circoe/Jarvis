"""Task13A durable Live lifecycle authority; no provider or watchdog."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.live_lifecycle import LiveLifecycleService
from jarvis.domain.live_lifecycle import (
    LiveCloseEvidence, LiveLifecycleConflict, LiveLifecycleOperation, LiveLifecycleState,
    LiveOwnerKind, LiveSessionRecord,
)


NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


class TestClock:
    __test__ = False

    def __init__(self, now=NOW):
        self.value = now

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)

    def set(self, value):
        self.value = value


async def opened(path, *, diagnostics=None):
    repository = SQLiteStateRepository(path)
    await repository.initialize()
    return repository, LiveLifecycleService(repository, diagnostics, clock=TestClock())


async def reserve(service, session="session-a", owner="owner-a", at=NOW):
    service.clock.set(at)
    return await service.reserve(session, owner)


async def bound_active(service, session="session-a", owner="owner-a"):
    record = await reserve(service, session, owner)
    service.clock.advance(.5)
    record = await service.mark_start(session, owner, record.owner_epoch, record.revision)
    service.clock.advance(.5)
    record = await service.bind(session, owner, record.owner_epoch, record.revision,
                                "provider-a")
    service.clock.advance(1)
    return await service.transition(session, owner, record.owner_epoch, record.revision,
                                    LiveLifecycleState.ACTIVE)


async def test_concurrent_reserve_across_connections_admits_one_global_owner(tmp_path):
    path = tmp_path / "state.sqlite"
    repo_a, service_a = await opened(path)
    repo_b, service_b = await opened(path)
    try:
        results = await asyncio.gather(
            reserve(service_a, "session-a", "owner-a"),
            reserve(service_b, "session-b", "owner-b"),
            return_exceptions=True,
        )
        records = [value for value in results if isinstance(value, LiveSessionRecord)]
        conflicts = [value for value in results if isinstance(value, LiveLifecycleConflict)]
        assert len(records) == len(conflicts) == 1
        assert conflicts[0].code == "live_lease_held"
        assert (await repo_a.get_unresolved_live_session()) == records[0]
    finally:
        await repo_a.close()
        await repo_b.close()


async def test_restart_persists_full_record_and_reserve_retry_is_idempotent(tmp_path):
    path = tmp_path / "state.sqlite"
    repository, service = await opened(path)
    record = await bound_active(service)
    service.clock.advance(1)
    record = await service.usage("session-a", "owner-a", record.owner_epoch, record.revision,
                                 1.0, .75)
    await repository.close()
    repository, service = await opened(path)
    try:
        assert await service.status("session-a") == record
        assert await service.status() == record
        assert await reserve(service) == record
    finally:
        await repository.close()


async def test_stale_owner_epoch_revision_and_invalid_transition_are_fenced(tmp_path):
    repository, service = await opened(tmp_path / "state.sqlite")
    try:
        record = await reserve(service)
        with pytest.raises(LiveLifecycleConflict, match="live_stale_owner"):
            await service.heartbeat("session-a", "old-owner", record.owner_epoch, record.revision,
                                    )
        with pytest.raises(LiveLifecycleConflict, match="live_stale_owner"):
            await service.heartbeat("session-a", "owner-a", record.owner_epoch + 1, record.revision,
                                    )
        with pytest.raises(LiveLifecycleConflict, match="live_stale_revision"):
            await service.heartbeat("session-a", "owner-a", record.owner_epoch, record.revision + 1,
                                    )
        with pytest.raises(LiveLifecycleConflict, match="live_invalid_transition"):
            await service.transition("session-a", "owner-a", record.owner_epoch, record.revision,
                                     LiveLifecycleState.IDLE_CANDIDATE)
        assert (await service.status("session-a")) == record
    finally:
        await repository.close()


async def test_expired_lease_blocks_new_start_and_only_one_reaper_claims(tmp_path):
    path = tmp_path / "state.sqlite"
    repo_a, service_a = await opened(path)
    repo_b, service_b = await opened(path)
    record = await reserve(service_a)
    expired = NOW + timedelta(seconds=31)
    try:
        with pytest.raises(LiveLifecycleConflict, match="live_lease_held"):
            await reserve(service_b, "session-b", "owner-b", expired)
        service_a.clock.set(expired)
        service_b.clock.set(expired)
        claims = await asyncio.gather(
            service_a.claim_reap("session-a", "reaper-a", record.revision),
            service_b.claim_reap("session-a", "reaper-b", record.revision),
            return_exceptions=True,
        )
        claimed = [value for value in claims if isinstance(value, LiveSessionRecord)]
        refused = [value for value in claims if isinstance(value, LiveLifecycleConflict)]
        assert len(claimed) == len(refused) == 1
        assert claimed[0].state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
        assert claimed[0].owner_epoch == record.owner_epoch + 1
        assert refused[0].code == "live_stale_revision"
        winner = claimed[0]
        other = "reaper-b" if winner.owner_incarnation_id == "reaper-a" else "reaper-a"
        service_a.clock.set(expired + timedelta(seconds=1))
        with pytest.raises(LiveLifecycleConflict, match="live_reap_not_eligible"):
            await service_a.claim_reap("session-a", other, winner.revision)
        service_a.clock.set(winner.lease_deadline + timedelta(seconds=1))
        transferred = await service_a.claim_reap("session-a", other, winner.revision)
        assert transferred.owner_incarnation_id == other
        assert transferred.owner_kind is LiveOwnerKind.REAPER
        assert transferred.owner_epoch == winner.owner_epoch + 1
        with pytest.raises(LiveLifecycleConflict, match="live_stale_owner"):
            await service_a.heartbeat("session-a", "owner-a", record.owner_epoch,
                                      transferred.revision)
    finally:
        await repo_a.close()
        await repo_b.close()


async def test_stopped_requires_matching_confirmed_provider_receipt(tmp_path):
    repository, service = await opened(tmp_path / "state.sqlite")
    try:
        record = await bound_active(service)
        service.clock.advance(1)
        record = await service.transition("session-a", "owner-a", record.owner_epoch, record.revision,
                                          LiveLifecycleState.STOPPING, "user")
        service.clock.advance(1)
        with pytest.raises(LiveLifecycleConflict, match="live_identity_conflict"):
            await service.finalize("session-a", "owner-a", record.owner_epoch, record.revision,
                                   "provider-other", 2, 1, "user",
                                   LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        with pytest.raises(LiveLifecycleConflict, match="live_identity_conflict"):
            await service.finalize("session-a", "owner-a", record.owner_epoch, record.revision,
                                   None, 2, 1, "user",
                                   LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        assert (await service.status("session-a")).state is LiveLifecycleState.STOPPING
        with pytest.raises(LiveLifecycleConflict, match="live_close_unconfirmed"):
            await service.finalize("session-a", "owner-a", record.owner_epoch, record.revision,
                                   "provider-a", 2, None, "user",
                                   LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        stopped = await service.finalize("session-a", "owner-a", record.owner_epoch, record.revision,
                                         "provider-a", 2, 0, "user",
                                         LiveCloseEvidence.PROVIDER_SESSION_CLOSED)
        assert stopped.state is LiveLifecycleState.STOPPED
        assert stopped.provider_usage_seconds == 0 and stopped.provider_usage_final
        assert stopped.stopped_at == NOW + timedelta(seconds=4)
        assert await service.finalize("session-a", "owner-a", stopped.owner_epoch, record.revision,
                                      "provider-a", 2, 0, "user",
                                      LiveCloseEvidence.PROVIDER_SESSION_CLOSED) == stopped
        replacement = await reserve(service, "session-b", "owner-b", NOW + timedelta(seconds=5))
        assert replacement.state is LiveLifecycleState.STARTING
    finally:
        await repository.close()


async def test_prestart_cancellation_releases_but_sent_without_provider_id_stays_unknown(tmp_path):
    repository, service = await opened(tmp_path / "state.sqlite")
    try:
        reserved = await reserve(service, "not-sent", "owner")
        stopping = await service.transition(
            reserved.session_id, "owner", reserved.owner_epoch, reserved.revision,
            LiveLifecycleState.STOPPING, "cancelled_before_start",
        )
        stopped = await service.finalize(
            stopping.session_id, "owner", stopping.owner_epoch, stopping.revision,
            None, 0, None, "cancelled_before_start",
            LiveCloseEvidence.START_NOT_SENT,
        )
        assert stopped.state is LiveLifecycleState.STOPPED
        assert stopped.close_evidence is LiveCloseEvidence.START_NOT_SENT

        with pytest.raises(LiveLifecycleConflict, match="live_identity_conflict"):
            await service.bind("not-sent", "owner", stopped.owner_epoch, stopped.revision,
                               "provider-too-late")

        uncertain = await reserve(service, "sent-unknown-id", "owner", NOW + timedelta(seconds=3))
        uncertain = await service.mark_start(
            uncertain.session_id, "owner", uncertain.owner_epoch, uncertain.revision,
        )
        uncertain = await service.transition(
            uncertain.session_id, "owner", uncertain.owner_epoch, uncertain.revision,
            LiveLifecycleState.UNKNOWN_REAP_REQUIRED, "start_result_unknown",
        )
        with pytest.raises(LiveLifecycleConflict, match="live_close_unconfirmed"):
            await service.finalize(
                uncertain.session_id, "owner", uncertain.owner_epoch, uncertain.revision,
                None, 0, None, "start_result_unknown",
                LiveCloseEvidence.START_NOT_SENT,
            )
        with pytest.raises(LiveLifecycleConflict, match="live_identity_conflict"):
            await service.finalize(
                uncertain.session_id, "owner", uncertain.owner_epoch, uncertain.revision,
                None, 0, None, "start_result_unknown",
                LiveCloseEvidence.PROVIDER_SESSION_CLOSED,
            )
        claimed = await service.claim_reap(uncertain.session_id, "reaper", uncertain.revision)
        with pytest.raises(LiveLifecycleConflict, match="live_identity_conflict"):
            await service.finalize(
                claimed.session_id, "reaper", claimed.owner_epoch, claimed.revision,
                None, 0, None, "reap_unknown_provider_id",
                LiveCloseEvidence.PROVIDER_SESSION_CLOSED,
            )
        with pytest.raises(LiveLifecycleConflict, match="live_lease_held"):
            await reserve(service, "replacement", "other", NOW + timedelta(seconds=9))
        assert (await service.status()).state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
    finally:
        await repository.close()


async def test_mark_start_unknown_response_retries_without_advancing_twice(tmp_path):
    repository, service = await opened(tmp_path / "state.sqlite")
    record = await reserve(service)
    original = repository.cas_live_session
    first = True

    async def ambiguous(value, *, expected_revision):
        nonlocal first
        result = await original(value, expected_revision=expected_revision)
        if first:
            first = False
            raise OSError("mark response lost")
        return result

    repository.cas_live_session = ambiguous
    try:
        service.clock.advance(1)
        with pytest.raises(OSError, match="mark response lost"):
            await service.mark_start("session-a", "owner-a", record.owner_epoch, record.revision)
        marked = await service.mark_start(
            "session-a", "owner-a", record.owner_epoch, record.revision,
        )
        assert marked.start_may_have_been_sent and marked.revision == record.revision + 1
    finally:
        await repository.close()


async def test_timestamps_and_usage_counters_never_move_backwards(tmp_path):
    repository, service = await opened(tmp_path / "state.sqlite")
    try:
        record = await bound_active(service)
        service.clock.advance(2)
        record = await service.usage(
            record.session_id, "owner-a", record.owner_epoch, record.revision,
            2, 1,
        )
        service.clock.set(NOW + timedelta(seconds=3))
        with pytest.raises(ValueError, match="backwards"):
            await service.heartbeat(
                record.session_id, "owner-a", record.owner_epoch, record.revision,
            )
        service.clock.set(NOW + timedelta(seconds=5))
        with pytest.raises(ValueError, match="cannot decrease"):
            await service.usage(
                record.session_id, "owner-a", record.owner_epoch, record.revision,
                1, 1,
            )
        assert await service.status(record.session_id) == record
    finally:
        await repository.close()


async def test_storage_unknown_after_commit_retries_same_identity_without_duplicate(tmp_path):
    class Diagnostics:
        def __init__(self):
            self.rows = []

        def emit(self, kind, message, *, level="info", data=None):
            self.rows.append({"kind": kind, "message": message, "level": level, "data": data})

    diagnostics = Diagnostics()
    repository, service = await opened(tmp_path / "state.sqlite", diagnostics=diagnostics)
    original = repository.reserve_live_session
    first = True

    async def ambiguous(value):
        nonlocal first
        result = await original(value)
        if first:
            first = False
            raise OSError("PRIVATE_SQLITE_DETAIL")
        return result

    repository.reserve_live_session = ambiguous
    try:
        with pytest.raises(OSError, match="PRIVATE_SQLITE_DETAIL"):
            await reserve(service)
        retried = await reserve(service)
        assert retried.revision == 1
        assert await service.status() == retried
        encoded = json.dumps(diagnostics.rows)
        assert "PRIVATE_SQLITE_DETAIL" not in encoded
        assert diagnostics.rows[0]["kind"] == "live.lifecycle.persistence_failed"
    finally:
        await repository.close()


async def test_cas_unknown_after_bind_commit_is_idempotent_and_precommit_failure_writes_nothing(tmp_path):
    repository, service = await opened(tmp_path / "state.sqlite")
    original_reserve = repository.reserve_live_session

    async def unavailable(_value):
        raise OSError("database unavailable")

    repository.reserve_live_session = unavailable
    with pytest.raises(OSError, match="database unavailable"):
        await reserve(service)
    assert await service.status() is None
    repository.reserve_live_session = original_reserve
    record = await reserve(service)
    service.clock.advance(.5)
    record = await service.mark_start("session-a", "owner-a", record.owner_epoch, record.revision)
    original_cas = repository.cas_live_session
    first = True

    async def ambiguous(value, *, expected_revision):
        nonlocal first
        result = await original_cas(value, expected_revision=expected_revision)
        if first:
            first = False
            raise OSError("response lost")
        return result

    repository.cas_live_session = ambiguous
    try:
        with pytest.raises(OSError, match="response lost"):
            await service.bind("session-a", "owner-a", record.owner_epoch, record.revision,
                               "provider-a")
        retried = await service.bind("session-a", "owner-a", record.owner_epoch, record.revision,
                                     "provider-a")
        assert retried.provider_session_id == "provider-a" and retried.revision == 3
    finally:
        await repository.close()


@pytest.mark.parametrize("source", [
    LiveLifecycleState.STARTING, LiveLifecycleState.ACTIVE,
    LiveLifecycleState.IDLE_CANDIDATE, LiveLifecycleState.STOPPING,
])
def test_every_nonterminal_operational_state_can_converge_to_unknown(source):
    assert LiveLifecycleState.UNKNOWN_REAP_REQUIRED in {
        target for target in LiveLifecycleState if LiveSessionRecord(
            session_id="session", provider_session_id=(None if source is LiveLifecycleState.STARTING else "provider"),
            owner_incarnation_id="owner", owner_epoch=1, owner_kind=LiveOwnerKind.PRIMARY, state=source,
            start_may_have_been_sent=source is not LiveLifecycleState.STARTING,
            heartbeat_at=NOW, lease_deadline=NOW + timedelta(seconds=30),
            created_at=NOW, updated_at=NOW, state_entered_at=NOW,
            activated_at=(None if source is LiveLifecycleState.STARTING else NOW),
            stopped_at=None, active_seconds=0, provider_usage_seconds=None,
            provider_usage_final=False,
            close_reason=("user" if source is LiveLifecycleState.STOPPING else None),
            close_evidence=None, last_operation=LiveLifecycleOperation.RESERVE, revision=1,
        ).permits(target)
    }


@pytest.mark.parametrize("mutation", [
    "extra", "missing", "bad_state", "bool_revision", "naive_time",
    "long_id", "negative_usage", "infinite_usage", "long_lease", "false_final",
])
def test_record_strict_shape_and_bounds(mutation):
    record = LiveSessionRecord(
        session_id="session", provider_session_id=None, owner_incarnation_id="owner",
        owner_epoch=1, owner_kind=LiveOwnerKind.PRIMARY, state=LiveLifecycleState.STARTING,
        start_may_have_been_sent=False,
        heartbeat_at=NOW, lease_deadline=NOW + timedelta(seconds=30),
        created_at=NOW, updated_at=NOW, state_entered_at=NOW,
        activated_at=None, stopped_at=None, active_seconds=0,
        provider_usage_seconds=None, provider_usage_final=False,
        close_reason=None, close_evidence=None,
        last_operation=LiveLifecycleOperation.RESERVE, revision=1,
    ).to_payload()
    if mutation == "extra": record["raw_provider_payload"] = {}
    elif mutation == "missing": record.pop("owner_epoch")
    elif mutation == "bad_state": record["state"] = "error"
    elif mutation == "bool_revision": record["revision"] = True
    elif mutation == "naive_time": record["heartbeat_at"] = "2026-09-12T12:00:00"
    elif mutation == "long_id": record["session_id"] = "x" * 129
    elif mutation == "negative_usage": record["active_seconds"] = -1
    elif mutation == "infinite_usage": record["active_seconds"] = float("inf")
    elif mutation == "long_lease": record["lease_deadline"] = (NOW + timedelta(seconds=301)).isoformat()
    elif mutation == "false_final":
        record.update({"state": "stopped", "provider_session_id": "provider",
                       "stopped_at": NOW.isoformat(), "close_reason": "user",
                       "close_evidence": "provider_session_closed"})
    with pytest.raises((ValueError, TypeError)):
        LiveSessionRecord.from_payload(record)
