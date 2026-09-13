"""Voice-process owner for one durable GPT-Live primary incarnation.

Every lifecycle mutation is serialized through one lock.  Provider transport
operations stay in the frontend adapter; this owner only establishes durable
authority and fencing around them.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import math
import time
import uuid

from jarvis.domain.live_lifecycle import (
    LiveCloseEvidence, LiveLifecycleState, LiveSessionRecord,
)
from jarvis.ports.live_sideband import LiveTerminalReceipt


class DurableLiveSessionOwner:
    """Serialize the primary lease, identity, usage and terminal evidence."""

    def __init__(self, core, session_id: str, *, owner_incarnation_id: str | None = None,
                 on_fenced: Callable[[], Awaitable[None]] | None = None) -> None:
        self.core = core
        self.session_id = session_id
        self.owner_incarnation_id = owner_incarnation_id or f"voice-{uuid.uuid4()}"
        self._on_fenced = on_fenced
        self._lock = asyncio.Lock()
        self._record: LiveSessionRecord | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._fenced = False
        self._activated_monotonic: float | None = None
        self._provider_usage: float | None = None
        self._pending_receipt: tuple[str, str, float, float] | None = None
        self._receipt_retry: asyncio.Task[None] | None = None
        self._closed = asyncio.Event()
        self._stop_persistence: set[asyncio.Task[None]] = set()

    @property
    def record(self) -> LiveSessionRecord | None:
        return self._record

    @property
    def fenced(self) -> bool:
        return self._fenced

    @property
    def start_marked(self) -> bool:
        return bool(self._record and self._record.start_may_have_been_sent)

    def set_fenced_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._on_fenced = callback

    def _active_seconds(self) -> float:
        if self._activated_monotonic is None:
            return self._record.active_seconds if self._record else 0.0
        return max(self._record.active_seconds if self._record else 0.0,
                   time.monotonic() - self._activated_monotonic)

    async def reserve(self) -> LiveSessionRecord:
        async with self._lock:
            if self._record is None:
                self._record = await self.core.reserve_live_session(
                    self.session_id, self.owner_incarnation_id,
                )
                self._start_heartbeat()
            return self._record

    async def before_start_send(self) -> None:
        """Durably mark the ambiguous boundary immediately before session.start."""
        async with self._lock:
            self._require_owned()
            if self._stop_requested:
                await self._finalize_not_sent_locked("stop_before_start")
                raise RuntimeError("Live start was stopped before provider send")
            record = self._record
            assert record is not None
            self._record = await self.core.mark_live_session_start(
                self.session_id, self.owner_incarnation_id,
                record.owner_epoch, record.revision,
            )
            # Cancellation/Stop can latch while the mark request is in flight,
            # including after Core committed but before its response arrived.
            # Once marked, no provider ID exists yet and only UNKNOWN is honest.
            if self._stop_requested:
                record = self._record
                self._record = await self.core.transition_live_session(
                    self.session_id, self.owner_incarnation_id,
                    record.owner_epoch, record.revision,
                    LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
                    "stop_during_mark",
                )
                raise RuntimeError("Live start stopped at durable send barrier")

    async def session_started(self, provider_session_id: str) -> bool:
        """Bind provider identity and publish ACTIVE before local availability."""
        async with self._lock:
            self._require_owned()
            record = self._record
            assert record is not None
            self._record = await self.core.bind_live_session(
                self.session_id, self.owner_incarnation_id, record.owner_epoch,
                record.revision, provider_session_id,
            )
            if self._stop_requested:
                self._record = await self.core.transition_live_session(
                    self.session_id, self.owner_incarnation_id,
                    self._record.owner_epoch, self._record.revision,
                    LiveLifecycleState.STOPPING, "stop_during_start",
                )
                return False
            self._record = await self.core.transition_live_session(
                self.session_id, self.owner_incarnation_id,
                self._record.owner_epoch, self._record.revision,
                LiveLifecycleState.ACTIVE,
            )
            self._activated_monotonic = time.monotonic()
            return True

    async def usage_updated(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("invalid Live usage")
        try:
            valid = math.isfinite(seconds) and seconds >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("invalid Live usage")
        async with self._lock:
            self._require_owned()
            record = self._record
            assert record is not None
            value = float(seconds)
            if self._provider_usage is not None and value < self._provider_usage:
                raise ValueError("Live cumulative usage decreased")
            self._record = await self.core.update_live_session_usage(
                self.session_id, self.owner_incarnation_id,
                record.owner_epoch, record.revision, self._active_seconds(), value,
            )
            self._provider_usage = value
        if self._stop_requested:
            # Stop/receipt owners may have queued behind this slow mutation.
            # Give them a bounded chance to persist before the caller releases
            # its Core client; never cancel their commit-ambiguous HTTP calls.
            pending = tuple(task for task in self._stop_persistence if not task.done())
            if pending:
                await asyncio.wait(pending, timeout=.25)
            retry = self._receipt_retry
            if retry is not None and not retry.done():
                await asyncio.wait({retry}, timeout=.25)

    async def idle_candidate(self) -> None:
        """Record a validated idle decision before requesting provider close."""
        async with self._lock:
            self._require_owned()
            record = self._record
            assert record is not None
            if record.state is LiveLifecycleState.IDLE_CANDIDATE:
                return
            if record.state is not LiveLifecycleState.ACTIVE:
                raise RuntimeError("Live owner is not active")
            self._record = await self.core.transition_live_session(
                self.session_id, self.owner_incarnation_id,
                record.owner_epoch, record.revision,
                LiveLifecycleState.IDLE_CANDIDATE,
            )

    async def session_closed(self, provider_session_id: str, reason: str,
                             usage_seconds: float) -> None:
        """Persist the strict terminal receipt before the adapter exposes STOPPED."""
        receipt = LiveTerminalReceipt(provider_session_id, reason, usage_seconds)
        record = self._record
        if record is None or record.provider_session_id != receipt.provider_session_id:
            raise RuntimeError("Live terminal receipt identity mismatch")
        if record.state is LiveLifecycleState.STOPPED:
            if (record.close_evidence is LiveCloseEvidence.PROVIDER_SESSION_CLOSED
                    and record.provider_session_id == receipt.provider_session_id
                    and record.close_reason == receipt.reason
                    and record.provider_usage_seconds == receipt.usage_seconds):
                return
            raise RuntimeError("conflicting Live terminal receipt")
        identity = (receipt.provider_session_id, receipt.reason, receipt.usage_seconds)
        if self._pending_receipt is not None:
            if self._pending_receipt[:3] != identity:
                raise RuntimeError("conflicting Live terminal receipt")
            candidate = self._pending_receipt
        else:
            candidate = (*identity, self._active_seconds())
        # Freeze both provider and local counters once. Exact retries after a
        # committed-but-lost response must resend byte-for-byte semantics.
        self._pending_receipt = candidate
        try:
            async with self._lock:
                await self._persist_receipt_locked()
        except asyncio.CancelledError:
            self._ensure_receipt_retry()
            raise
        except Exception:
            self._ensure_receipt_retry()
            raise

    def request_stop(self, reason: str) -> asyncio.Task[None]:
        """Latch stop synchronously and own its possibly slow Core mutation."""
        self._stop_requested = True
        task = asyncio.create_task(self._begin_stop(reason), name="jarvis-live-stop-persistence")
        self._stop_persistence.add(task)
        task.add_done_callback(self._stop_persistence.discard)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return task

    async def begin_stop(self, reason: str) -> None:
        await asyncio.shield(self.request_stop(reason))

    async def _begin_stop(self, reason: str) -> None:
        async with self._lock:
            if self._record is None or self._record.state is LiveLifecycleState.STOPPED:
                return
            if not self._record.start_may_have_been_sent:
                await self._finalize_not_sent_locked(reason)
                return
            if self._record.state not in {
                LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
            }:
                record = self._record
                self._record = await self.core.transition_live_session(
                    self.session_id, self.owner_incarnation_id,
                    record.owner_epoch, record.revision,
                    LiveLifecycleState.STOPPING, reason,
                )

    async def mark_unknown(self, reason: str) -> None:
        async with self._lock:
            record = self._record
            if record is None or record.state is LiveLifecycleState.STOPPED:
                return
            if not record.start_may_have_been_sent:
                await self._finalize_not_sent_locked(reason)
                return
            if record.state is not LiveLifecycleState.UNKNOWN_REAP_REQUIRED:
                self._record = await self.core.transition_live_session(
                    self.session_id, self.owner_incarnation_id,
                    record.owner_epoch, record.revision,
                    LiveLifecycleState.UNKNOWN_REAP_REQUIRED, reason,
                )

    def request_unknown(self, reason: str) -> asyncio.Task[None]:
        task = asyncio.create_task(self.mark_unknown(reason), name="jarvis-live-unknown-persistence")
        self._stop_persistence.add(task)
        task.add_done_callback(self._stop_persistence.discard)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return task

    async def close(self) -> None:
        task, self._heartbeat_task = self._heartbeat_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        retry = self._receipt_retry
        if retry is not None and retry.done():
            await asyncio.gather(retry, return_exceptions=True)

    def assert_active(self) -> None:
        record = self._record
        if (self._fenced or self._stop_requested or record is None
                or record.state is not LiveLifecycleState.ACTIVE):
            raise RuntimeError("Live owner is not active")

    def _require_owned(self) -> None:
        if self._fenced:
            raise RuntimeError("Live owner lease is fenced")
        if self._record is None:
            raise RuntimeError("Live owner is not reserved")

    async def _finalize_not_sent_locked(self, reason: str) -> None:
        record = self._record
        assert record is not None
        if record.state is LiveLifecycleState.STOPPED:
            return
        if record.state not in {LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED}:
            self._record = record = await self.core.transition_live_session(
                self.session_id, self.owner_incarnation_id,
                record.owner_epoch, record.revision,
                LiveLifecycleState.STOPPING, reason,
            )
        self._record = await self.core.finalize_live_session(
            self.session_id, self.owner_incarnation_id,
            record.owner_epoch, record.revision, None, 0.0, None, reason,
            LiveCloseEvidence.START_NOT_SENT,
        )
        self._closed.set()

    async def _persist_receipt_locked(self) -> None:
        receipt = self._pending_receipt
        record = self._record
        if receipt is None or record is None or record.state is LiveLifecycleState.STOPPED:
            self._pending_receipt = None
            return
        provider_id, reason, usage, active_seconds = receipt
        if record.provider_session_id != provider_id:
            raise RuntimeError("Live terminal receipt identity mismatch")
        if record.state not in {LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED}:
            self._record = record = await self.core.transition_live_session(
                self.session_id, self.owner_incarnation_id,
                record.owner_epoch, record.revision,
                LiveLifecycleState.STOPPING, reason,
            )
        self._record = await self.core.finalize_live_session(
            self.session_id, self.owner_incarnation_id,
            record.owner_epoch, record.revision, provider_id,
            active_seconds, usage, reason,
            LiveCloseEvidence.PROVIDER_SESSION_CLOSED,
        )
        self._provider_usage = usage
        self._pending_receipt = None
        self._closed.set()

    def _ensure_receipt_retry(self) -> None:
        if self._receipt_retry is None or self._receipt_retry.done():
            self._receipt_retry = asyncio.create_task(
                self._retry_receipt(), name="jarvis-live-receipt-persistence",
            )

    async def _retry_receipt(self) -> None:
        # First retry queues directly behind any in-flight serialized CAS. It
        # then backs off after a real failure; this avoids leaking an HTTP task
        # past shutdown merely because storage became available immediately.
        delay = 0.0
        while self._pending_receipt is not None:
            await asyncio.sleep(delay)
            if self._fenced:
                if await self._reconcile_fenced_receipt():
                    return
                delay = min(max(.1, delay * 2), 5.0)
                continue
            try:
                async with self._lock:
                    await self._persist_receipt_locked()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if getattr(exc, "code", None) in {
                    "live_stale_owner", "live_stale_revision",
                    "live_invalid_transition", "live_identity_conflict",
                } and await self._reconcile_fenced_receipt():
                    return
                delay = min(max(.1, delay * 2), 5.0)

    async def _reconcile_fenced_receipt(self) -> bool:
        """Converge after a reaper takeover; never fight its newer epoch."""
        receipt = self._pending_receipt
        if receipt is None:
            return True
        try:
            current = await self.core.live_session_status(self.session_id)
        except Exception:
            return False
        provider_id, reason, usage, _active = receipt
        if current is not None and current.state is LiveLifecycleState.STOPPED:
            if (current.provider_session_id == provider_id
                    and current.close_reason == reason
                    and current.provider_usage_seconds == usage
                    and current.close_evidence is LiveCloseEvidence.PROVIDER_SESSION_CLOSED):
                self._record = current
                self._pending_receipt = None
                self._closed.set()
                return True
            self._fenced = True
            return False
        if current is not None and (
            current.owner_incarnation_id != self.owner_incarnation_id
            or self._record is not None and current.owner_epoch != self._record.owner_epoch
        ):
            self._fenced = True
            return False
        return False

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat(), name="jarvis-live-primary-heartbeat",
            )

    async def _heartbeat(self) -> None:
        while True:
            record = self._record
            if record is None or record.state is LiveLifecycleState.STOPPED:
                return
            lease = max(1.0, (record.lease_deadline - record.heartbeat_at).total_seconds())
            await asyncio.sleep(max(.25, min(30.0, lease / 3)))
            fenced = False
            try:
                async with self._lock:
                    record = self._record
                    if record is None or record.state is LiveLifecycleState.STOPPED:
                        return
                    self._record = await self.core.heartbeat_live_session(
                        self.session_id, self.owner_incarnation_id,
                        record.owner_epoch, record.revision,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._fenced = True
                fenced = True
            if fenced:
                if self._on_fenced is not None:
                    try:
                        await self._on_fenced()
                    except Exception:
                        pass
                return
