"""Core-owned watchdog for unresolved, possibly billable Live sessions."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import math
import uuid

from jarvis.domain.live_lifecycle import (
    LiveCloseEvidence, LiveLifecycleConflict, LiveLifecycleState, LiveOwnerKind,
    LiveSessionRecord, live_id,
)
from jarvis.ports.live_sideband import LiveSidebandCloser, LiveTerminalReceipt


@dataclass(frozen=True, slots=True)
class PendingLiveReceipt:
    session_id: str
    receipt: LiveTerminalReceipt

    def __post_init__(self) -> None:
        live_id(self.session_id, "session_id")


class LiveLifecycleWatchdog:
    """Claim expired ownership and retry documented attach-close recovery."""

    def __init__(self, lifecycle, closer: LiveSidebandCloser | None = None, diagnostics=None,
                 *, incarnation_id: str | None = None, poll_seconds: float = 1.0,
                 retry_min_seconds: float = 1.0, retry_max_seconds: float = 15.0,
                 attempt_timeout_seconds: float = 5.0,
                 shutdown_timeout_seconds: float = 0.25) -> None:
        values = (
            (poll_seconds, "poll"), (retry_min_seconds, "retry minimum"),
            (retry_max_seconds, "retry maximum"), (attempt_timeout_seconds, "attempt"),
            (shutdown_timeout_seconds, "shutdown"),
        )
        for value, name in values:
            try:
                valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                         and math.isfinite(value) and value > 0)
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(f"invalid Live reaper {name} duration")
        if retry_min_seconds > retry_max_seconds:
            raise ValueError("Live reaper retry bounds are reversed")
        if attempt_timeout_seconds > lifecycle.lease_seconds / 2:
            raise ValueError("Live reaper attempt must not exceed half its lease")
        self.lifecycle = lifecycle
        self.closer = closer
        self.diagnostics = diagnostics
        self.incarnation_id = incarnation_id or f"reaper-{uuid.uuid4()}"
        self.poll_seconds = float(poll_seconds)
        self.retry_min_seconds = float(retry_min_seconds)
        self.retry_max_seconds = float(retry_max_seconds)
        self.attempt_timeout_seconds = float(attempt_timeout_seconds)
        self.shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._task: asyncio.Task[None] | None = None
        self._lingering_task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._closing = False
        self._pending: PendingLiveReceipt | None = None
        self._next_attempt_at = 0.0
        self._backoff = self.retry_min_seconds
        self.attempts = 0

    @property
    def pending_receipt(self) -> LiveTerminalReceipt | None:
        return self._pending.receipt if self._pending is not None else None

    def _emit(self, kind: str, record: LiveSessionRecord | None = None,
              *, error: BaseException | None = None,
              receipt: LiveTerminalReceipt | None = None) -> None:
        if self.diagnostics is None:
            return
        data: dict[str, object] = {
            "attempts": self.attempts,
            "pending_receipt": self._pending is not None,
        }
        if record is not None:
            data.update({
                "session_id": record.session_id,
                "state": record.state.value,
                "owner_epoch": record.owner_epoch,
                "owner_kind": record.owner_kind.value,
                "revision": record.revision,
            })
        if receipt is not None:
            data.update({"close_reason": receipt.reason, "provider_usage_seconds": receipt.usage_seconds})
        if error is not None:
            data["error_type"] = type(error).__name__
        try:
            self.diagnostics.emit(kind, "Live lifecycle watchdog update", data=data,
                                  level="error" if error is not None else "info")
        except Exception:
            pass

    def start(self) -> None:
        if self._lingering_task is not None and not self._lingering_task.done():
            raise RuntimeError("previous Live watchdog owner is still stopping")
        if self._task is None:
            self._closing = False
            self._task = asyncio.create_task(self._run(), name="jarvis-live-lifecycle-watchdog")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        self._closing = True
        self._wake.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.shutdown_timeout_seconds)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            if not task.done():
                self._lingering_task = task
                task.add_done_callback(self._consume_lingering)
            if asyncio.current_task() is not None and asyncio.current_task().cancelling():
                raise

    def _consume_lingering(self, task: asyncio.Task[None]) -> None:
        if self._lingering_task is task:
            self._lingering_task = None
        try:
            task.exception()
        except (BaseException, asyncio.InvalidStateError):
            pass

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._schedule_retry()
                self._emit("live.reaper.failed", error=exc)
            if self._closing:
                return
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    def _schedule_retry(self) -> None:
        self._next_attempt_at = asyncio.get_running_loop().time() + self._backoff
        self._backoff = min(self._backoff * 2, self.retry_max_seconds)

    def _retry_ready(self) -> bool:
        return asyncio.get_running_loop().time() >= self._next_attempt_at

    async def _claim_or_owned(self, record: LiveSessionRecord) -> LiveSessionRecord | None:
        if (record.owner_kind is LiveOwnerKind.REAPER
                and record.owner_incarnation_id == self.incarnation_id):
            return record
        try:
            return await self.lifecycle.claim_reap(
                record.session_id, self.incarnation_id, record.revision,
            )
        except LiveLifecycleConflict as exc:
            if exc.code in {"live_reap_not_eligible", "live_stale_revision", "live_stale_owner"}:
                return None
            raise

    async def _renew_if_due(self, record: LiveSessionRecord) -> LiveSessionRecord:
        now = self.lifecycle._now()
        if record.lease_deadline > now + timedelta(seconds=self.lifecycle.lease_seconds / 2):
            return record
        return await self.lifecycle.heartbeat(
            record.session_id, self.incarnation_id, record.owner_epoch, record.revision,
        )

    async def run_once(self) -> None:
        pending = self._pending
        record = await self.lifecycle.status(pending.session_id) if pending is not None else await self.lifecycle.status()
        if record is None:
            self._backoff = self.retry_min_seconds
            self._next_attempt_at = 0.0
            return
        if pending is not None and record.state is LiveLifecycleState.STOPPED:
            receipt = pending.receipt
            if (record.provider_session_id != receipt.provider_session_id
                    or record.provider_usage_seconds != receipt.usage_seconds
                    or record.close_reason != receipt.reason):
                raise LiveLifecycleConflict("live_identity_conflict")
            self._pending = None
            self._backoff = self.retry_min_seconds
            self._next_attempt_at = 0.0
            self._emit("live.reaper.receipt_reconciled", record, receipt=receipt)
            return
        owned = await self._claim_or_owned(record)
        if owned is None:
            return
        record = await self._renew_if_due(owned)

        if self._pending is not None:
            await self._persist_receipt(record, self._pending.receipt)
            return

        if not record.start_may_have_been_sent:
            stopped = await self.lifecycle.finalize(
                record.session_id, self.incarnation_id, record.owner_epoch, record.revision,
                None, 0, None, "start_not_sent", LiveCloseEvidence.START_NOT_SENT,
            )
            self._emit("live.reaper.finalized", stopped)
            return

        if record.provider_session_id is None or self.closer is None or not self._retry_ready():
            return
        if record.state is not LiveLifecycleState.STOPPING:
            record = await self.lifecycle.transition(
                record.session_id, self.incarnation_id, record.owner_epoch, record.revision,
                LiveLifecycleState.STOPPING, "sideband_close_requested",
            )
        # A network attempt always starts with a full Core-authored lease. Merely
        # checking the half-life above is insufficient when the remaining lease
        # is shorter than the bounded attach/read budget.
        record = await self.lifecycle.heartbeat(
            record.session_id, self.incarnation_id, record.owner_epoch, record.revision,
        )
        self.attempts += 1
        async def persist(receipt: LiveTerminalReceipt) -> None:
            if (not isinstance(receipt, LiveTerminalReceipt)
                    or receipt.provider_session_id != record.provider_session_id):
                raise ValueError("Live sideband receipt identity mismatch")
            self._pending = PendingLiveReceipt(record.session_id, receipt)
            self._emit("live.reaper.receipt_observed", record, receipt=receipt)
            await self._persist_receipt(record, receipt)
        try:
            receipt = await asyncio.wait_for(
                self.closer.close_session(record.provider_session_id, persist),
                timeout=self.attempt_timeout_seconds,
            )
            if (not isinstance(receipt, LiveTerminalReceipt)
                    or receipt.provider_session_id != record.provider_session_id):
                raise ValueError("Live sideband receipt identity mismatch")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._pending is not None:
                self._schedule_retry()
                self._emit("live.reaper.receipt_persistence_pending", record, error=exc,
                           receipt=self._pending.receipt)
                return
            try:
                record = await self.lifecycle.transition(
                    record.session_id, self.incarnation_id, record.owner_epoch, record.revision,
                    LiveLifecycleState.UNKNOWN_REAP_REQUIRED, "sideband_close_unconfirmed",
                )
            except Exception:
                pass
            self._schedule_retry()
            self._emit("live.reaper.close_unconfirmed", record, error=exc)
            return

    async def _persist_receipt(self, record: LiveSessionRecord,
                               receipt: LiveTerminalReceipt) -> None:
        if record.provider_session_id != receipt.provider_session_id:
            raise LiveLifecycleConflict("live_identity_conflict")
        if record.state is not LiveLifecycleState.STOPPING:
            record = await self.lifecycle.transition(
                record.session_id, self.incarnation_id, record.owner_epoch, record.revision,
                LiveLifecycleState.STOPPING, "sideband_receipt_observed",
            )
        stopped = await self.lifecycle.finalize(
            record.session_id, self.incarnation_id, record.owner_epoch, record.revision,
            receipt.provider_session_id, record.active_seconds, receipt.usage_seconds,
            receipt.reason, LiveCloseEvidence.PROVIDER_SESSION_CLOSED,
        )
        self._pending = None
        self._backoff = self.retry_min_seconds
        self._next_attempt_at = 0.0
        self._emit("live.reaper.finalized", stopped, receipt=receipt)
