"""Fault injection for the Core-owned Live lifecycle watchdog."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.core.live_reaper import LiveLifecycleWatchdog
from jarvis.domain.live_lifecycle import LiveLifecycleState
from jarvis.ports.live_sideband import LiveTerminalReceipt
from tests.unit.test_live_lifecycle_lease import bound_active, opened


class FakeCloser:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    async def close_session(self, provider_session_id: str, on_receipt):
        self.calls.append(provider_session_id)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        if isinstance(outcome, LiveTerminalReceipt):
            await on_receipt(outcome)
        return outcome


async def expired_active(service):
    row = await bound_active(service)
    service.clock.advance(31)
    return row


def watchdog(service, closer=None, *, owner="watchdog"):
    return LiveLifecycleWatchdog(
        service, closer, incarnation_id=owner, poll_seconds=.01,
        retry_min_seconds=.01, retry_max_seconds=.04,
        attempt_timeout_seconds=.05, shutdown_timeout_seconds=.1,
    )


async def test_attempt_budget_must_leave_half_the_lease_as_scheduling_margin(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    service.lease_seconds = 1
    try:
        with pytest.raises(ValueError, match="half its lease"):
            LiveLifecycleWatchdog(service, attempt_timeout_seconds=.51)
    finally:
        await repo.close()


async def test_expired_session_is_claimed_closed_and_final_receipt_persisted(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        await expired_active(service)
        closer = FakeCloser([LiveTerminalReceipt("provider-a", "close_requested", 7)])
        await watchdog(service, closer).run_once()
        stopped = await service.status("session-a")
        assert stopped.state is LiveLifecycleState.STOPPED
        assert stopped.provider_usage_seconds == 7 and stopped.provider_usage_final
        assert stopped.close_reason == "close_requested"
        assert closer.calls == ["provider-a"]
    finally:
        await repo.close()


@pytest.mark.parametrize("outcome", [
    TimeoutError(), EOFError(), PermissionError(), ConnectionError(),
    LiveTerminalReceipt("wrong-provider", "close_requested", 1),
])
async def test_unconfirmed_sideband_outcomes_remain_unknown_and_back_off(tmp_path, outcome):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        await expired_active(service)
        closer = FakeCloser([outcome])
        reaper = watchdog(service, closer)
        await reaper.run_once()
        row = await service.status()
        assert row.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
        assert reaper.pending_receipt is None and reaper.attempts == 1
        await reaper.run_once()
        assert closer.calls == ["provider-a"]
    finally:
        await repo.close()


async def test_two_watchdogs_race_but_only_claim_winner_attaches(tmp_path):
    path = tmp_path / "state.sqlite"
    repo_a, service_a = await opened(path)
    repo_b, service_b = await opened(path)
    try:
        await expired_active(service_a)
        service_b.clock.set(service_a.clock.value)
        closer_a = FakeCloser([LiveTerminalReceipt("provider-a", "close_requested", 1)])
        closer_b = FakeCloser([LiveTerminalReceipt("provider-a", "close_requested", 1)])
        await asyncio.gather(
            watchdog(service_a, closer_a, owner="reaper-a").run_once(),
            watchdog(service_b, closer_b, owner="reaper-b").run_once(),
        )
        assert len(closer_a.calls) + len(closer_b.calls) == 1
        assert (await service_a.status("session-a")).state is LiveLifecycleState.STOPPED
    finally:
        await repo_a.close()
        await repo_b.close()


async def test_terminal_receipt_survives_ambiguous_sqlite_finalize_without_second_close(tmp_path, monkeypatch):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        await expired_active(service)
        closer = FakeCloser([LiveTerminalReceipt("provider-a", "expired", 9)])
        reaper = watchdog(service, closer)
        original = repo.cas_live_session
        lost = False

        async def lose_final_response(value, *, expected_revision):
            nonlocal lost
            answer = await original(value, expected_revision=expected_revision)
            if value.state is LiveLifecycleState.STOPPED and not lost:
                lost = True
                raise OSError("sqlite response lost")
            return answer

        monkeypatch.setattr(repo, "cas_live_session", lose_final_response)
        await reaper.run_once()
        assert reaper.pending_receipt is not None and closer.calls == ["provider-a"]
        await reaper.run_once()
        assert reaper.pending_receipt is None and closer.calls == ["provider-a"]
        assert (await service.status("session-a")).state is LiveLifecycleState.STOPPED
    finally:
        await repo.close()


async def test_prestart_reservation_finalizes_without_sideband_only_after_claim_eligibility(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    try:
        row = await service.reserve("not-started", "primary")
        closer = FakeCloser([])
        reaper = watchdog(service, closer)
        await reaper.run_once()
        assert (await service.status()).state is LiveLifecycleState.STARTING
        service.clock.set(row.lease_deadline)
        await reaper.run_once()
        assert (await service.status("not-started")).state is LiveLifecycleState.STOPPED
        assert closer.calls == []
    finally:
        await repo.close()


async def test_watchdog_shutdown_is_bounded_and_cancels_blocked_attach(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    entered = asyncio.Event()

    async def blocked():
        entered.set()
        await asyncio.Future()

    try:
        await expired_active(service)
        reaper = watchdog(service, FakeCloser([blocked]))
        reaper.start()
        await entered.wait()
        await asyncio.wait_for(reaper.stop(), timeout=.2)
        assert (await service.status()).state in {
            LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
        }
    finally:
        await repo.close()
