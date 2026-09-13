"""Conversation-facing admission/status over the existing durable JobService."""
from __future__ import annotations

import asyncio
from dataclasses import replace

from jarvis.core.brain_service import stable_identity
from jarvis.domain.back_brain import BackBrainAdvisoryReference, BackBrainProvenance, BackBrainSubmission, BackBrainSubmitRequest, BackBrainWorkPayload, back_brain_job_id
from jarvis.domain.back_brain import BackBrainTaskList, BackBrainTaskSnapshot, BackBrainUnavailable
from jarvis.domain.back_brain import BackBrainAdvisoryDependency, BackBrainAdvisorySnapshot
from jarvis.domain.back_brain import BackBrainSpeculativeProvenance, speculative_job_id
from jarvis.domain.v2 import Job, utc_now
from jarvis.domain.voice_admission import admitted_turn_binding, admitted_turn_order
from jarvis.domain.speech_presentation import speech_id
from jarvis.ports.v2 import OwnedJobWorker


class BackBrainTaskService:
    def __init__(self, jobs, conversations, ledger):
        self.jobs, self.conversations, self.ledger = jobs, conversations, ledger
        self.state = conversations.state
        self._submit_lock = asyncio.Lock()
        self.stopping = False
        self._submissions = {}

    async def _conversation(self, conversation_id):
        speech_id(conversation_id, "conversation_id")
        if await self.state.get_conversation(conversation_id) is None:
            raise KeyError(conversation_id)

    async def submit(self, request: BackBrainSubmitRequest) -> BackBrainSubmission:
        if not isinstance(request, BackBrainSubmitRequest):
            raise ValueError("typed back brain submission required")
        if self.stopping:
            return BackBrainSubmission(status="unavailable", reason="back_brain_stopping")
        key = (request.conversation_id, request.scope, request.source_correlation_id, request.session_id, request.delegation_id)
        task = self._submissions.get(key)
        joined = task is not None
        if task is None:
            if len(self._submissions) >= 32:
                return BackBrainSubmission(status="unavailable", reason="back_brain_capacity")
            async def accepted_continuation():
                async with self._submit_lock:
                    return await self._submit(request)
            task = asyncio.create_task(accepted_continuation(), name="jarvis-back-brain-submit")
            self._submissions[key] = task
            def finished(done):
                self._submissions.pop(key, None)
                if not done.cancelled():
                    done.exception()  # Caller may have disconnected; retrieve owned failure.
            task.add_done_callback(finished)
        result = await asyncio.shield(task)
        return replace(result, duplicate=True) if joined and result.status == "accepted" else result

    async def stop(self):
        self.stopping = True
        pending = tuple(self._submissions.values())
        if pending:
            _, unfinished = await asyncio.wait(pending, timeout=self.jobs.owned.cleanup_timeout_s)
            if unfinished:
                return False
        return True

    async def _submit(self, request: BackBrainSubmitRequest) -> BackBrainSubmission:
        if not isinstance(request, BackBrainSubmitRequest):
            raise ValueError("typed back brain submission required")
        if self.stopping:
            return BackBrainSubmission(status="unavailable", reason="back_brain_stopping")
        await self._conversation(request.conversation_id)
        if request.scope == "speculative_analysis":
            return await self._submit_speculative(request)
        job_id = back_brain_job_id(request.conversation_id, request.source_correlation_id)
        existing = await self.state.get_job(job_id)
        if existing:
            payload = BackBrainWorkPayload.from_payload(existing.payload)
            if payload.provenance.source.correlation_id != request.source_correlation_id or existing.requested_by_conversation_id != request.conversation_id:
                raise ValueError("persisted job source conflict")
            return BackBrainSubmission("accepted", existing.id, True, provenance=payload.provenance)
        if not isinstance(self.jobs.workers.get("back_brain"), OwnedJobWorker):
            return BackBrainSubmission(status="unavailable", reason="backend_worker_unavailable")
        source = await self.state.get_brain_source(request.conversation_id, request.source_correlation_id)
        if source is None:
            raise ValueError("unknown Core source")
        turn = await self.state.get_turn(source.turn_id)
        binding = admitted_turn_binding(turn) if turn else None
        if binding is None or admitted_turn_order(turn) is None or binding.addressing.value != "addressed":
            raise ValueError("back brain requires addressed canonical admission")
        projection = await self.ledger.back_brain_projection(request.conversation_id, binding=binding)
        proof = BackBrainProvenance(request.conversation_id, source, binding.session_id, binding.canonical_turn_id,
            binding.transcript_id, binding.transcript_revision, binding.provider_item_id, projection["revision"], projection["context_dependencies"])
        payload = BackBrainWorkPayload(binding.text, projection["context_text"], proof)
        job = Job(id=job_id, kind="back_brain", payload=payload.to_payload(), requested_by_conversation_id=request.conversation_id,
                  idempotency_key=job_id)
        try:
            stored, created = await self.jobs.owned.accept(job, source.turn_id)
        except BackBrainUnavailable as exc:
            return BackBrainSubmission(status="unavailable", reason=exc.code)
        accepted = BackBrainWorkPayload.from_payload(stored.payload)
        return BackBrainSubmission("accepted", stored.id, not created, provenance=accepted.provenance)

    async def _submit_speculative(self, request):
        job_id = speculative_job_id(request.conversation_id, request.session_id, request.delegation_id)
        existing = await self.state.get_job(job_id)
        if existing is not None:
            proof = BackBrainWorkPayload.from_payload(existing.payload).provenance
            if not isinstance(proof, BackBrainSpeculativeProvenance) or (proof.conversation_id, proof.session_id, proof.delegation_id) != (request.conversation_id, request.session_id, request.delegation_id):
                raise ValueError("speculative identity conflict")
            return BackBrainSubmission("accepted", existing.id, True, provenance=proof)
        worker = self.jobs.workers.get("back_brain")
        capability = getattr(worker, "supports_speculative_analysis", None)
        if not isinstance(worker, OwnedJobWorker) or not callable(capability) or capability() is not True:
            await self._retain_unavailable(request)
            return BackBrainSubmission(status="unavailable", reason="restricted_execution_unavailable")
        projection = await self.ledger.back_brain_projection(request.conversation_id, session_id=request.session_id)
        if not projection["dependencies_complete"]:
            return BackBrainSubmission(status="unavailable", reason="analysis_context_unavailable")
        dependencies = tuple(BackBrainAdvisoryDependency.from_payload(d) for d in projection["dependencies"] if d["session_id"] == request.session_id)
        try:
            proof = BackBrainSpeculativeProvenance(request.conversation_id, request.session_id, request.delegation_id, projection["revision"], dependencies)
            payload = BackBrainWorkPayload("\n".join(d.text for d in dependencies), "", proof, scope="speculative_analysis")
        except ValueError:
            return BackBrainSubmission(status="unavailable", reason="analysis_context_unavailable")
        job = Job(id=job_id, kind="back_brain", payload=payload.to_payload(), requested_by_conversation_id=request.conversation_id, idempotency_key=job_id)
        try:
            stored, created = await self.jobs.owned.accept(job)
        except BackBrainUnavailable as exc:
            return BackBrainSubmission(status="unavailable", reason=exc.code)
        return BackBrainSubmission("accepted", stored.id, not created, provenance=BackBrainWorkPayload.from_payload(stored.payload).provenance)

    async def _retain_unavailable(self, request):
        reference_id = "advisory-" + stable_identity(request.conversation_id, request.session_id, request.delegation_id)
        if await self.state.get_back_brain_advisory(reference_id) is not None:
            return
        projection = await self.ledger.back_brain_projection(request.conversation_id, session_id=request.session_id)
        value = BackBrainAdvisoryReference(reference_id, request.conversation_id, request.session_id, request.delegation_id,
            projection["revision"], tuple(BackBrainAdvisoryDependency.from_payload(d)
                for d in projection["dependencies"] if d["session_id"] == request.session_id), utc_now().isoformat())
        await self.state.save_back_brain_advisory(value)

    async def status(self, conversation_id, job_id):
        await self._conversation(conversation_id)
        speech_id(job_id, "job_id")
        job = await self.state.get_job(job_id)
        if job is None or job.kind != "back_brain" or job.requested_by_conversation_id != conversation_id:
            raise KeyError(job_id)
        payload = BackBrainWorkPayload.from_payload(job.payload)
        if isinstance(payload.provenance, BackBrainSpeculativeProvenance):
            snapshot = (await self.ledger.snapshot(conversation_id))["snapshot"]
            freshness = self._advisory_freshness(payload.provenance, snapshot)
            source_current = snapshot is not None and snapshot["current_session_id"] == payload.provenance.session_id
            dependencies_current = None if freshness == "unknown" else freshness == "current"
        else:
            source_current, dependencies_current = await self.state.back_brain_freshness(conversation_id, payload.provenance.source, payload.provenance.context_dependencies)
        return BackBrainTaskSnapshot.from_payload({"schema_version": 1, "job_id": job.id, "conversation_id": conversation_id,
                "status": job.status.value, "revision": job.revision, "cancellation": job.cancellation, "cancel_requested": job.cancel_requested,
                "provenance": payload.provenance.to_payload(), "source_current": source_current,
                "dependencies_current": dependencies_current, "fresh": source_current and dependencies_current is True,
                "progress": job.progress, "result": job.result, "error": job.error,
                "created_at": job.created_at.isoformat(), "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "persistence_error": self.jobs.owned.persistence_failures.get(job.id),
                "authorizes_actions": False}).to_payload()

    async def list(self, conversation_id, *, limit=32):
        await self._conversation(conversation_id)
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError("invalid back brain list limit")
        selected = await self.state.list_conversation_jobs(conversation_id, limit=limit)
        references = await self.state.list_back_brain_advisories(conversation_id, limit=limit)
        snapshot = (await self.ledger.snapshot(conversation_id, checkpoint=bool(references)))["snapshot"]
        advisory = [BackBrainAdvisorySnapshot(value, self._advisory_freshness(value, snapshot)) for value in references]
        return BackBrainTaskList.from_payload({"schema_version": 1, "conversation_id": conversation_id,
                "tasks": [await self.status(conversation_id, job.id) for job in selected],
                "advisory_unavailable": [value.to_payload() for value in advisory]}).to_payload()

    @staticmethod
    def _advisory_freshness(reference, snapshot):
        if snapshot is None:
            return "unknown"
        if snapshot["current_session_id"] != reference.session_id:
            return "stale"
        unknown = False
        for dependency in reference.dependencies:
            current = next((item for item in snapshot["users"] if item["correlation"]["session_id"] == dependency.session_id and item["transcript_id"] == dependency.transcript_id), None)
            if current is None:
                unknown = True
            elif (current["revision"], current["text"], current["correlation"]["provider_input_id"], current["committed"]) != (dependency.revision, dependency.text, dependency.provider_item_id, dependency.committed):
                return "stale"
        return "unknown" if unknown else "current"

    async def cancel(self, conversation_id, job_id):
        # An already-owned immutable acceptance gives a safe synchronous fence,
        # even while the SQLite start transaction is finishing on its worker.
        if self.jobs.owned._origins.get(job_id) != conversation_id:
            await self.status(conversation_id, job_id)
        await self.jobs.owned.cancel(job_id)
        return await self.status(conversation_id, job_id)
