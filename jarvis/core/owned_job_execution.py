"""Owned execution for admitted agent jobs, within the existing JobService."""
from __future__ import annotations

import asyncio
import math
from dataclasses import replace

from jarvis.domain.back_brain import BackBrainProgress, BackBrainResult, BackBrainUnavailable, BackBrainWorkPayload
from jarvis.domain.v2 import JobStatus, ProtocolEnvelope, utc_now
from jarvis.domain.work_state import WorkLink, WorkStatus
from jarvis.ports.v2 import OwnedJobWorker, ProgressReportingJobWorker

ACTIVE = {JobStatus.PENDING, JobStatus.RUNNING}
WORKER_ERROR_CODES = frozenset({"back_brain_provider_unavailable", "back_brain_invalid_kind",
    "back_brain_speculative_unavailable", "back_brain_source_mismatch", "back_brain_worker_busy",
    "back_brain_execution_failed", "back_brain_invalid_result", "back_brain_cleanup_unknown", "back_brain_timeout"})


class OwnedJobExecution:
    def __init__(self, service, *, cleanup_timeout_s=5.0):
        self.service = service
        self.cleanup_timeout_s = cleanup_timeout_s
        self._slots = asyncio.Semaphore(1)
        self._locks = {}
        self._executing = set()
        self._cleanup = {}
        self._cancellations = {}
        self._cancel_intents = set()
        self._worker_ready = {}
        self._origins = {}
        self.stopping = False
        self.diagnostic_failures = 0
        self.persistence_failures = {}
        self._stop_task = None

    def _diagnostic(self, kind, message, *, level="info", data):
        try:
            self.service.diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Diagnostics never become a second job authority or erase a result.
            self.diagnostic_failures += 1

    async def accept(self, job, turn_id=None):
        if self.stopping:
            raise BackBrainUnavailable("back_brain_stopping")
        worker = self.service.workers.get("back_brain")
        if not isinstance(worker, OwnedJobWorker):
            raise BackBrainUnavailable("back_brain_worker_unavailable")
        stored, created = (await self.service.state.accept_speculative_job(job) if turn_id is None
                           else await self.service.state.accept_admitted_job(job, turn_id))
        # Only the transaction winner schedules. Lost responses/restarts never replay.
        if created and not self.stopping:
            from jarvis.core.v2_services import _WorkLink
            self._locks[stored.id] = asyncio.Lock()
            self._origins[stored.id] = stored.requested_by_conversation_id
            self._worker_ready[stored.id] = asyncio.Event()
            source = getattr(BackBrainWorkPayload.from_payload(stored.payload).provenance, "source", None)
            if source is not None:
                self.service._work_links[stored.id] = WorkLink(work_id=stored.id, correlation_id=source.correlation_id)
                self.service._links[stored.id] = _WorkLink(work_id=stored.id, correlation_id=source.correlation_id)
            self.service._running[stored.id] = asyncio.create_task(self._execute(stored), name=f"jarvis-job-{stored.id}")
        elif created:
            await self.cancel(stored.id)
        await self._publish(stored, "accepted")
        return stored, created

    async def _change(self, job_id, **changes):
        lock = self._locks.setdefault(job_id, asyncio.Lock())
        while True:
            try:
                async with lock:
                    current = await self.service.state.get_job(job_id)
                    if current is None or current.status not in ACTIVE:
                        self.persistence_failures.pop(job_id, None)
                        return current
                    if changes.get("status") is JobStatus.COMPLETED and (current.cancel_requested or job_id in self._cancel_intents):
                        changes = {**changes, "status": JobStatus.CANCELLED, "cancel_requested": True, "cancellation": "confirmed", "error": None}
                    updated = replace(current, **changes, revision=current.revision + 1)
                    if not await self.service.state.transition_job(updated, expected_revision=current.revision):
                        continue  # Another durable transition won; reconcile, never replay work.
                    self.persistence_failures.pop(job_id, None)
                    return updated
            except asyncio.CancelledError:
                # A native transaction may already have committed. Re-read before acting.
                self._cancel_intents.add(job_id)
                changes = {**changes, "cancel_requested": True}
            except Exception as exc:
                if job_id not in self.persistence_failures:
                    self._diagnostic("core.job.state_failed", "job finalization remains owned", level="error",
                        data={"job_id": job_id, "exception_type": type(exc).__name__, "code": "state_persistence_unavailable"})
                self.persistence_failures[job_id] = "state_persistence_unavailable"
                try:
                    await asyncio.sleep(.05)
                except asyncio.CancelledError:
                    self._cancel_intents.add(job_id)
                    changes = {**changes, "cancel_requested": True}

    async def _read_owned(self, job_id):
        while True:
            try:
                current = await self.service.state.get_job(job_id)
                self.persistence_failures.pop(job_id, None)
                return current
            except asyncio.CancelledError:
                self._cancel_intents.add(job_id)
            except Exception as exc:
                if job_id not in self.persistence_failures:
                    self._diagnostic("core.job.state_failed", "job state read remains owned", level="error",
                        data={"job_id": job_id, "exception_type": type(exc).__name__, "code": "state_persistence_unavailable"})
                self.persistence_failures[job_id] = "state_persistence_unavailable"
                try:
                    await asyncio.sleep(.05)
                except asyncio.CancelledError:
                    self._cancel_intents.add(job_id)

    async def _publish(self, job, suffix):
        proof = BackBrainWorkPayload.from_payload(job.payload).provenance
        source = getattr(proof, "source", None)
        self._diagnostic(f"core.job.{suffix}", "back brain job lifecycle", level="error" if suffix == "failed" else "warning" if suffix == "cleanup_unknown" else "info",
                         data={"job_id": job.id, "conversation_id": job.requested_by_conversation_id,
                               "correlation_id": source.correlation_id if source else None, "revision": job.revision, "status": job.status.value,
                               "cancellation": job.cancellation, "code": job.error})
        try:
            await self.service.events.publish(ProtocolEnvelope(
                message_type=f"job.{suffix}", conversation_id=job.requested_by_conversation_id,
                correlation_id=source.correlation_id if source else None,
                payload={"job_id": job.id, "kind": job.kind, "revision": job.revision,
                         "status": job.status.value, "source": source.to_payload() if source else None,
                         "provenance": proof.to_payload(), "authorizes_actions": False,
                         "cancellation": job.cancellation, "result": job.result, "error_class": job.error}))
        except Exception as exc:
            # Durable state is authoritative; event failure must never rewrite a result.
            self._diagnostic("core.job.publication_failed", "job event publication failed", level="warning",
                                          data={"job_id": job.id, "event": suffix, "exception_type": type(exc).__name__})

    async def _observe_work(self, job, status, **kwargs):
        if job.payload.get("scope") == "speculative_analysis":
            return  # No committed turn or Brain work generation is invented.
        try:
            await self.service._observe_work(job, status, **kwargs)
        except Exception as exc:
            self._diagnostic("core.job.projection_failed", "durable job retained after work projection failure", level="warning",
                data={"job_id": job.id, "exception_type": type(exc).__name__})

    async def _cleanup_owned(self, job_id, *, cancel=False):
        worker = self.service.workers["back_brain"]
        pending = self._cleanup.get(job_id)
        if pending is not None and pending.done() and not pending.cancelled() and pending.exception() is None and pending.result() is True:
            return True
        if pending is None or pending.done():
            operation = worker.cancel_owned if cancel else worker.cleanup_owned
            pending = asyncio.create_task(operation(job_id), name=f"jarvis-job-cleanup-{job_id}")
            self._cleanup[job_id] = pending
        try:
            return await asyncio.wait_for(asyncio.shield(pending), self.cleanup_timeout_s) is True
        except Exception as exc:
            self._diagnostic("core.job.cleanup_unknown", "job cleanup is unconfirmed", level="warning",
                                          data={"job_id": job_id, "exception_type": type(exc).__name__})
            return False

    async def _execute(self, job):
        try:
            async with self._slots:
                current = await self._read_owned(job.id)
                if current.status not in ACTIVE or current.cancellation != "none":
                    return
                self._executing.add(job.id)
                running = await self._change(job.id, status=JobStatus.RUNNING, started_at=utc_now())
                if running.cancel_requested or job.id in self._cancel_intents:
                    cancelled = await self._change(job.id, status=JobStatus.CANCELLED, cancel_requested=True,
                        cancellation="confirmed", completed_at=utc_now())
                    await self._publish(cancelled, "cancelled")
                    return
                await self._publish(running, "started")
                await self._observe_work(running, WorkStatus.RUNNING)
                worker = self.service.workers["back_brain"]
                try:
                    sink = _OwnedProgress(self, running)
                    if job.id in self._cancel_intents:
                        raise asyncio.CancelledError
                    self._worker_ready[job.id].set()
                    result = await (worker.execute_with_progress(running, sink) if isinstance(worker, ProgressReportingJobWorker) else worker.execute(running))
                    result = BackBrainResult.from_payload(result).to_payload()
                    status, error = JobStatus.COMPLETED, None
                except asyncio.CancelledError:
                    result, status, error = None, JobStatus.CANCELLED, None
                    await self._change(job.id, cancel_requested=True, cancellation="requested")
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    error = code if isinstance(code, str) and code in WORKER_ERROR_CODES else "back_brain_execution_failed"
                    result, status = None, JobStatus.FAILED
                # Even failure must retain process ownership until cleanup is known.
                announced_unknown = False
                while True:
                    try:
                        if await self._cleanup_owned(job.id, cancel=job.id in self._cancel_intents):
                            break
                    except asyncio.CancelledError:
                        await self._change(job.id, cancel_requested=True, cancellation="cleanup_unknown")
                        continue
                    if not announced_unknown:
                        unknown = await self._change(job.id, cancellation="cleanup_unknown", result=result, error=error)
                        await self._publish(unknown, "cleanup_unknown")
                        announced_unknown = True
                    try:
                        await asyncio.sleep(.05)
                    except asyncio.CancelledError:
                        await self._change(job.id, cancel_requested=True, cancellation="cleanup_unknown")
                current = await self._read_owned(job.id)
                if current.cancel_requested:
                    status, error = JobStatus.CANCELLED, None
                terminal = await self._change(job.id, status=status, result=result, error=error,
                                              cancellation="confirmed" if status is JobStatus.CANCELLED else "none", completed_at=utc_now())
                await self._publish(terminal, terminal.status.value)
                await self._observe_work(terminal, WorkStatus(terminal.status.value), error_class=error)
        except asyncio.CancelledError:
            # Normal cancellation is issued only by cancel() after owned cleanup.
            raise
        except Exception as exc:
            # Persistence failure cannot be relabelled as completed/cancelled.
            self._diagnostic("core.job.state_failed", "job state transition failed", level="error",
                                          data={"job_id": job.id, "exception_type": type(exc).__name__})
        finally:
            ready = self._worker_ready.pop(job.id, None)
            if ready:
                ready.set()
            self._executing.discard(job.id)
            self.service._running.pop(job.id, None)
            self._origins.pop(job.id, None)
            self.service._work_links.pop(job.id, None)
            self.service._links.pop(job.id, None)
            pending = self._cleanup.get(job.id)
            if pending is None or pending.done():
                self._cleanup.pop(job.id, None)
            self._locks.pop(job.id, None)

    async def cancel(self, job_id):
        self._cancel_intents.add(job_id)
        pending = self._cancellations.get(job_id)
        if pending is None:
            pending = asyncio.create_task(self._cancel(job_id), name=f"jarvis-job-cancel-{job_id}")
            self._cancellations[job_id] = pending
            pending.add_done_callback(lambda finished: self._cancellations.pop(job_id, None))
        try:
            return await asyncio.wait_for(asyncio.shield(pending), self.cleanup_timeout_s + .1)
        except TimeoutError:
            return await self.service.state.get_job(job_id)  # Still owned; status exposes pending persistence/cleanup.

    async def _cancel(self, job_id):
        current = await self._read_owned(job_id)
        if current is None:
            raise KeyError(job_id)
        if current.status not in ACTIVE:
            self._cancel_intents.discard(job_id)
            return current
        requested = await self._change(job_id, cancellation="requested", cancel_requested=True)
        if requested.status not in ACTIVE:
            return requested
        await self._publish(requested, "cancel_requested")
        ready = self._worker_ready.get(job_id)
        if job_id in self._executing and ready is not None:
            try:
                await asyncio.wait_for(asyncio.shield(ready.wait()), self.cleanup_timeout_s)
            except TimeoutError:
                unknown = await self._change(job_id, cancellation="cleanup_unknown")
                await self._publish(unknown, "cleanup_unknown")
                return unknown
        latest = await self._read_owned(job_id)
        if latest.status not in ACTIVE:
            self._cancel_intents.discard(job_id)
            return latest
        if job_id in self._executing and not await self._cleanup_owned(job_id, cancel=True):
            unknown = await self._change(job_id, cancellation="cleanup_unknown")
            await self._publish(unknown, "cleanup_unknown")
            return unknown
        task = self.service._running.get(job_id)
        if task is not None and job_id in self._executing:
            done, _ = await asyncio.wait({task}, timeout=self.cleanup_timeout_s)
            if not done:
                unknown = await self._change(job_id, cancellation="cleanup_unknown")
                await self._publish(unknown, "cleanup_unknown")
                return unknown
            await asyncio.gather(task, return_exceptions=True)
        latest = await self._read_owned(job_id)
        if latest.status not in ACTIVE:
            self._cancel_intents.discard(job_id)
            return latest
        terminal = await self._change(job_id, status=JobStatus.CANCELLED, cancellation="confirmed", completed_at=utc_now(), error=None)
        await self._publish(terminal, terminal.status.value)
        source = getattr(BackBrainWorkPayload.from_payload(terminal.payload).provenance, "source", None)
        if source is not None:
            self.service._work_links[job_id] = WorkLink(work_id=job_id, correlation_id=source.correlation_id)
        await self._observe_work(terminal, WorkStatus(terminal.status.value))
        self.service._work_links.pop(job_id, None)
        self._locks.pop(job_id, None)
        self._cancel_intents.discard(job_id)
        return terminal

    async def stop(self):
        self.stopping = True
        if "back_brain" not in self.service.workers:
            return True  # No owned agent execution exists in a legacy/headless composition.
        self._cancel_intents.update(self._origins)
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop_owned(), name="jarvis-back-brain-stop")
        try:
            return await asyncio.wait_for(asyncio.shield(self._stop_task), min(.5, self.cleanup_timeout_s + .25))
        except TimeoutError:
            return False

    async def _stop_owned(self):
        while True:
            try:
                result = await self._stop_once()
                self.persistence_failures.pop("core_stop", None)
                if result:
                    return True
                await asyncio.sleep(.05)
            except Exception as exc:
                if "core_stop" not in self.persistence_failures:
                    self._diagnostic("core.job.state_failed", "job stop reconciliation remains owned", level="error",
                        data={"exception_type": type(exc).__name__, "code": "state_persistence_unavailable"})
                self.persistence_failures["core_stop"] = "state_persistence_unavailable"
                await asyncio.sleep(.05)

    async def _stop_once(self):
        jobs = await self.service.state.list_active_back_brain_jobs()
        self._cancel_intents.update(job.id for job in jobs)
        for job in jobs:
            state = await self.cancel(job.id)
            if state.status in ACTIVE:
                return False
        return not await self.service.state.list_active_back_brain_jobs()


class _OwnedProgress:
    def __init__(self, owner, job):
        self.owner, self.job, self.last = owner, job, None

    async def emit(self, job_id, progress):
        if job_id != self.job.id:
            raise ValueError("progress belongs to another job")
        if progress.fraction is not None and (type(progress.fraction) not in (float, int) or not math.isfinite(progress.fraction) or not 0 <= progress.fraction <= 1):
            raise ValueError("invalid job progress fraction")
        now = self.owner.service.clock.now()
        if self.last is not None and (now - self.last).total_seconds() < self.owner.service.progress_min_interval_s:
            return
        payload = BackBrainProgress.from_payload(progress.to_payload()).to_payload()
        if len(progress.phase) > 256 or len(progress.public_summary) > 1000:
            raise ValueError("job progress exceeds bounds")
        updated = await self.owner._change(job_id, progress=payload)
        if updated.status not in ACTIVE or updated.cancellation != "none":
            return
        self.last = now
        source = getattr(BackBrainWorkPayload.from_payload(updated.payload).provenance, "source", None)
        try:
            await self.owner.service.events.publish(ProtocolEnvelope(message_type="brain.work.progress" if source else "job.progress",
                conversation_id=updated.requested_by_conversation_id, correlation_id=source.correlation_id if source else None,
                payload={"job_id": job_id, "work_id": job_id, "source": source.to_payload() if source else None, "authorizes_actions": False, "revision": updated.revision, **payload}))
            if source is not None:
                await self.owner.service._observe_progress(updated, progress)
        except Exception as exc:
            self.owner._diagnostic("core.job.projection_failed", "durable job progress retained after projection failure", level="warning",
                data={"job_id": job_id, "exception_type": type(exc).__name__})
