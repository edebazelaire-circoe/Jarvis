import asyncio
import threading
from dataclasses import replace

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.back_brain import BackBrainProvenance, BackBrainResult, BackBrainSubmitRequest, BackBrainWorkPayload
from jarvis.domain.v2 import BrainTurnInput, BrainTurnSource, Job, JobProgress, JobStatus
from jarvis.domain.voice_admission import admitted_turn_binding
from jarvis.domain.voice_event_codec import encode_voice_event
from jarvis.domain.voice_events import UserTranscriptRevised
from jarvis.domain.voice_frontend import VoiceCorrelation
from jarvis.core.brain_service import stable_identity
from tests.unit.test_voice_turn_admission import canonical_input


class ControlledWorker:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []
        self.cancels = []
        self.cleanup_confirmed = True

    async def execute(self, job):
        self.calls.append(job)
        self.started.set()
        await self.release.wait()
        return BackBrainResult("Résultat durable exact.", "controlled", "configured-model", "owned-session").to_payload()

    async def cancel_owned(self, job_id):
        self.cancels.append(job_id)
        if self.cleanup_confirmed:
            self.release.set()
        return self.cleanup_confirmed

    async def cleanup_owned(self, job_id):
        return self.cleanup_confirmed

    async def cancel(self, job_id):
        await self.cancel_owned(job_id)


@pytest.fixture
async def stack(tmp_path):
    worker = ControlledWorker()
    core = JarvisCoreApplication(data_root=tmp_path, workers={"back_brain": worker})
    await core.start()
    try:
        yield core, worker, tmp_path
    finally:
        worker.cleanup_confirmed = True
        worker.release.set()
        await core.stop()


async def admitted(core, *, conversation_id=None, item="a", text="Cherche ces informations."):
    request, frontend = await canonical_input(core, conversation_id, item=item, text=text,
        source=getattr(core, "_test_frontend_source", None))
    core._test_frontend_source = frontend
    accepted = await core.voice_admission.admit_voice_turn(request)
    return request, accepted


async def submit(core, admission):
    return await core.back_brain.submit(BackBrainSubmitRequest(admission.conversation_id, admission.correlation_id))


async def settle(core, job_id):
    task = core.jobs._running.get(job_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), 2)


async def pending_job(core, admission):
    turn = await core.state.get_turn(admission.turn_id)
    binding = admitted_turn_binding(turn)
    projection = await core.voice_ledger.back_brain_projection(admission.conversation_id, binding=binding)
    provenance = BackBrainProvenance(admission.conversation_id, admission.source, binding.session_id,
        binding.canonical_turn_id, binding.transcript_id, binding.transcript_revision, binding.provider_item_id, projection["revision"])
    identity = "back-brain-" + stable_identity(admission.conversation_id, admission.correlation_id)
    return Job(id=identity, kind="back_brain", requested_by_conversation_id=admission.conversation_id,
               idempotency_key=identity, payload=BackBrainWorkPayload(binding.text, projection["context_text"], provenance).to_payload())


async def test_acceptance_is_immediate_and_concurrent_retry_starts_one_worker(stack):
    core, worker, _ = stack
    request, admission = await admitted(core)
    values = await asyncio.wait_for(asyncio.gather(*(submit(core, admission) for _ in range(8))), 2)
    assert len({value.job_id for value in values}) == 1
    assert sum(not value.duplicate for value in values) == 1
    await asyncio.wait_for(worker.started.wait(), 1)
    assert len(worker.calls) == 1 and not worker.release.is_set()
    await core.brain.submit(BrainTurnInput(conversation_id=request.conversation_id, correlation_id=admission.correlation_id,
        text=request.text, addressing=request.addressing, source=BrainTurnSource.REALTIME, provider_item_id=request.provider_item_id))
    assert len(await core.state.list_turns(request.conversation_id)) == 1
    assert (await core.state.get_turn(admission.turn_id)).metadata["backend_dispatch_reserved"] is True


async def test_result_retains_old_origin_without_speech_and_survives_restart(stack):
    core, worker, root = stack
    request, first = await admitted(core)
    accepted = await submit(core, first)
    await asyncio.wait_for(worker.started.wait(), 1)
    _, second = await admitted(core, conversation_id=request.conversation_id, item="b", text="Nouvelle question.")
    queue = core.events.subscribe()
    worker.release.set()
    await settle(core, accepted.job_id)
    status = await core.back_brain.status(request.conversation_id, accepted.job_id)
    assert status["status"] == "completed" and status["source_current"] is False
    assert status["provenance"]["source"] == first.source.to_payload()
    assert status["result"]["text"] == "Résultat durable exact."
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    core.events.unsubscribe(queue)
    assert not any(event.message_type in {"speech.request", "brain.speech.requested"} for event in events)
    assert (await core.state.get_current_brain_source(request.conversation_id)) == second.source
    assert all(turn.kind.value == "user" for turn in await core.state.list_turns(request.conversation_id))
    await core.stop()
    restarted = JarvisCoreApplication(data_root=root, workers={"back_brain": ControlledWorker()})
    await restarted.start()
    try:
        assert await restarted.back_brain.status(request.conversation_id, accepted.job_id) == status
        retry = await submit(restarted, first)
        assert retry.job_id == accepted.job_id and retry.duplicate
        assert restarted.jobs.workers["back_brain"].calls == []
    finally:
        await restarted.stop()


async def test_old_source_cannot_be_launched_late(stack):
    core, worker, _ = stack
    request, first = await admitted(core)
    await admitted(core, conversation_id=request.conversation_id, item="b", text="Nouvelle intention.")
    with pytest.raises(ValueError, match="no longer current"):
        await submit(core, first)
    assert await core.state.list_jobs() == ()
    assert "backend_dispatch_reserved" not in (await core.state.get_turn(first.turn_id)).metadata
    assert worker.calls == []


async def test_cancel_unknown_keeps_owner_slot_and_core_open_until_retry(stack):
    core, worker, _ = stack
    request, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 1)
    worker.cleanup_confirmed = False
    unknown = await asyncio.wait_for(core.back_brain.cancel(request.conversation_id, accepted.job_id), 1)
    assert unknown["status"] == "running" and unknown["cancellation"] == "cleanup_unknown"
    assert accepted.job_id in core.jobs._running
    await asyncio.wait_for(core.stop(), 1)
    assert core.health.status == "cleanup_unknown"
    assert await core.state.get_job(accepted.job_id) is not None
    worker.cleanup_confirmed = True
    await asyncio.wait_for(core.stop(), 1)
    assert core.health.status == "stopped" and not core.jobs._running


async def test_cancel_queued_job_never_calls_worker_or_spawns_it(stack):
    core, worker, _ = stack
    request, first = await admitted(core)
    job_a = await submit(core, first)
    await asyncio.wait_for(worker.started.wait(), 1)
    _, second = await admitted(core, conversation_id=request.conversation_id, item="b", text="Deuxième travail.")
    job_b = await submit(core, second)
    status = await core.back_brain.cancel(request.conversation_id, job_b.job_id)
    assert status["status"] == "cancelled" and status["cancellation"] == "confirmed"
    assert worker.cancels == [] and [job.id for job in worker.calls] == [job_a.job_id]


async def test_worker_cancelled_error_cannot_release_unknown_owner_or_slot(stack):
    core, worker, _ = stack
    request, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 1)
    worker.cleanup_confirmed = False
    task = core.jobs._running[accepted.job_id]
    task.cancel()
    async def became_unknown():
        for _ in range(100):
            current = await core.state.get_job(accepted.job_id)
            if current.cancellation == "cleanup_unknown":
                return current
            await asyncio.sleep(.001)
        raise AssertionError("cleanup uncertainty was not retained")
    current = await asyncio.wait_for(became_unknown(), 1)
    assert current.status is JobStatus.RUNNING and not task.done()
    assert accepted.job_id in core.jobs._running
    queue = core.events.subscribe()
    worker.cleanup_confirmed = True
    final = await asyncio.wait_for(core.back_brain.cancel(request.conversation_id, accepted.job_id), 1)
    assert final["status"] == "cancelled" and task.done()
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    core.events.unsubscribe(queue)
    assert sum(event.message_type == "job.cancelled" for event in events) == 1


@pytest.mark.parametrize("cancel_requested", [False, True])
async def test_pending_native_cleanup_retains_result_and_completes_without_forced_cancel(stack, cancel_requested):
    core, worker, _ = stack
    request, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 1)
    worker.cleanup_confirmed = False
    queue = core.events.subscribe()
    worker.release.set()
    async def pending_result():
        for _ in range(100):
            state = await core.state.get_job(accepted.job_id)
            if state.cancellation == "cleanup_unknown":
                return state
            await asyncio.sleep(.001)
        raise AssertionError("pending cleanup not exposed")
    pending = await asyncio.wait_for(pending_result(), 1)
    assert pending.status is JobStatus.RUNNING and pending.result["text"] == "Résultat durable exact."
    assert pending.cancel_requested is False and accepted.job_id in core.jobs._running
    if cancel_requested:
        status = await core.back_brain.cancel(request.conversation_id, accepted.job_id)
        assert status["status"] == "running" and status["cancel_requested"] is True
    worker.cleanup_confirmed = True  # Native membership reaches zero; no extra cancel to release it.
    await settle(core, accepted.job_id)
    status = await core.back_brain.status(request.conversation_id, accepted.job_id)
    assert status["status"] == ("cancelled" if cancel_requested else "completed")
    assert status["result"]["text"] == "Résultat durable exact."
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    core.events.unsubscribe(queue)
    terminal = [event for event in events if event.message_type in {"job.completed", "job.cancelled", "job.failed"}]
    assert len(terminal) == 1 and terminal[0].message_type == f"job.{status['status']}"


@pytest.mark.parametrize("boundary", ["before_terminal_transition", "after_terminal_persistence"])
async def test_cancel_racing_natural_completion_has_one_consistent_terminal(stack, monkeypatch, boundary):
    core, worker, _ = stack
    request, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 1)
    reached, release = asyncio.Event(), asyncio.Event()
    owner = core.jobs.owned
    change, publish = owner._change, owner._publish
    if boundary == "before_terminal_transition":
        async def delayed_change(job_id, **changes):
            if changes.get("status") is JobStatus.COMPLETED:
                reached.set()
                await release.wait()
            return await change(job_id, **changes)
        monkeypatch.setattr(owner, "_change", delayed_change)
    else:
        async def delayed_publish(job, suffix):
            if suffix == "completed":
                reached.set()
                await release.wait()
            await publish(job, suffix)
        monkeypatch.setattr(owner, "_publish", delayed_publish)
    queue = core.events.subscribe()
    worker.release.set()
    try:
        await asyncio.wait_for(reached.wait(), 1)
        cancellation = asyncio.create_task(core.back_brain.cancel(request.conversation_id, accepted.job_id))
        if boundary == "before_terminal_transition":
            for _ in range(100):
                if (await core.state.get_job(accepted.job_id)).cancel_requested:
                    break
                await asyncio.sleep(.001)
            else:
                raise AssertionError("cancel request did not reach durable state")
            release.set()
        response = await asyncio.wait_for(cancellation, 1)
        release.set()
        await settle(core, accepted.job_id)
        expected = "cancelled" if boundary == "before_terminal_transition" else "completed"
        assert response["status"] == expected
        final = await core.back_brain.status(request.conversation_id, accepted.job_id)
        assert final["status"] == expected
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        terminal = [event for event in events if event.message_type in {"job.completed", "job.cancelled", "job.failed"}]
        assert len(terminal) == 1 and terminal[0].message_type == f"job.{expected}"
        requested = [index for index, event in enumerate(events) if event.message_type == "job.cancel_requested"]
        if requested:
            assert not any(event.message_type == "job.completed" for event in events[requested[0]:])
    finally:
        release.set()
        core.events.unsubscribe(queue)


async def test_speculative_unavailable_is_durable_non_authorizing_reference(stack):
    core, worker, root = stack
    request, _ = await canonical_input(core, committed=False)
    value = BackBrainSubmitRequest(request.conversation_id, scope="speculative_analysis", session_id=request.session_id, delegation_id="delegation-1")
    responses = await asyncio.gather(*(core.back_brain.submit(value) for _ in range(4)))
    assert all(result.status == "unavailable" and result.job_id is None for result in responses)
    projection = await core.back_brain.list(request.conversation_id)
    assert projection["tasks"] == [] and len(projection["advisory_unavailable"]) == 1
    advisory = projection["advisory_unavailable"][0]
    reference = advisory["reference"]
    assert reference["authorizes_actions"] is False and reference["dependencies"][0]["committed"] is False
    assert await core.state.list_jobs() == () and await core.state.list_turns(request.conversation_id) == ()
    assert worker.calls == []
    await core.stop()
    restarted = JarvisCoreApplication(data_root=root)
    await restarted.start()
    try:
        assert (await restarted.back_brain.list(request.conversation_id))["advisory_unavailable"] == [advisory]
    finally:
        await restarted.stop()


async def test_advisory_correction_preserves_exact_origin_and_staleness_after_restart(stack):
    core, worker, root = stack
    request, frontend = await canonical_input(core, committed=False, text="Compare ces deux options initiales.")
    value = BackBrainSubmitRequest(request.conversation_id, scope="speculative_analysis", session_id=request.session_id, delegation_id="delegation-original")
    await core.back_brain.submit(value)
    original = (await core.back_brain.list(request.conversation_id))["advisory_unavailable"][0]
    correlation = VoiceCorrelation(request.session_id, turn_id=request.canonical_turn_id, provider_input_id=request.provider_item_id)
    changed = UserTranscriptRevised(request.transcript_id, "Correction : compare trois options.", 2)
    await core.voice_ledger.ingest(request.conversation_id, request.session_id, [encode_voice_event(frontend.event(changed, correlation=correlation))])
    revised = (await core.back_brain.list(request.conversation_id))["advisory_unavailable"][0]
    assert revised["freshness"] == "stale" and revised["reference"] == original["reference"]
    assert revised["reference"]["dependencies"][0]["text"] == request.text
    assert revised["reference"]["dependencies"][0]["revision"] == 1
    await core.stop()
    restarted = JarvisCoreApplication(data_root=root)
    await restarted.start()
    try:
        assert (await restarted.back_brain.list(request.conversation_id))["advisory_unavailable"] == [revised]
        assert await restarted.state.list_jobs() == () and await restarted.state.list_turns(request.conversation_id) == ()
    finally:
        await restarted.stop()


async def test_job_context_uses_exact_immutable_dependencies_not_global_revision(stack):
    core, worker, _ = stack
    request, first = await admitted(core, text="La contrainte admise initiale.")
    _, second = await admitted(core, conversation_id=request.conversation_id, item="b", text="Analyse cette contrainte.")
    accepted = await submit(core, second)
    await asyncio.wait_for(worker.started.wait(), 1)
    job = await core.state.get_job(accepted.job_id)
    payload = BackBrainWorkPayload.from_payload(job.payload)
    assert [dependency.turn_id for dependency in payload.provenance.context_dependencies] == [first.turn_id]
    assert payload.context_text == "user: " + request.text
    await canonical_input(core, request.conversation_id, item="unrelated", text="Bruit provisoire sans admission", committed=False, source=core._test_frontend_source)
    original = await core.state.get_turn(first.turn_id)
    await core.state.save_turn(replace(original, content="Tentative de réécriture ignorée"))
    assert await core.state.get_turn(first.turn_id) == original  # Existing INSERT OR IGNORE immutability.
    status = await core.back_brain.status(request.conversation_id, accepted.job_id)
    assert status["source_current"] is True and status["dependencies_current"] is True and status["fresh"] is True
    assert (await core.voice_ledger.snapshot(request.conversation_id))["snapshot"]["revision"] > payload.provenance.snapshot_revision
    # Corruption is not a legitimate correction of immutable USER history.
    await core.state._run(lambda c: c.execute("UPDATE turns SET data=json_set(data,'$.content','corrupt') WHERE id=?", (first.turn_id,)))
    stale = await core.back_brain.status(request.conversation_id, accepted.job_id)
    assert stale["source_current"] is True and stale["dependencies_current"] is False and stale["fresh"] is False
    assert (await core.state.get_job(accepted.job_id)).payload == job.payload


async def test_two_sqlite_connections_join_one_atomic_acceptance_and_conflicts_fail(stack):
    core, worker, root = stack
    _, admission = await admitted(core)
    accepted = await submit(core, admission)
    job = await core.state.get_job(accepted.job_id)
    second = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
    await second.initialize()
    try:
        values = await asyncio.gather(*(repository.accept_admitted_job(replace(job, status=JobStatus.PENDING, revision=0), admission.turn_id)
                                       for repository in [core.state, second] * 6))
        assert all(not created and stored.id == job.id for stored, created in values)
        payload = BackBrainWorkPayload.from_payload(job.payload)
        for changed in (replace(payload, request_text="autre autorité"), replace(payload, context_text="contexte réécrit")):
            with pytest.raises(ValueError, match="conflicting immutable"):
                await second.accept_admitted_job(replace(job, status=JobStatus.PENDING, revision=0, payload=changed.to_payload()), admission.turn_id)
    finally:
        await second.close()


async def test_first_acceptance_race_on_two_initialized_connections_is_atomic(stack):
    core, worker, root = stack
    _, admission = await admitted(core)
    job = await pending_job(core, admission)
    second = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
    await second.initialize()
    ready, release = asyncio.Queue(), asyncio.Event()
    async def accept(repository):
        await ready.put(True)
        await release.wait()
        return await repository.accept_admitted_job(job, admission.turn_id)
    calls = [asyncio.create_task(accept(repository)) for repository in (core.state, second)]
    try:
        await asyncio.wait_for(ready.get(), 1)
        await asyncio.wait_for(ready.get(), 1)
        assert await core.state.list_jobs() == ()
        assert "backend_dispatch_reserved" not in (await core.state.get_turn(admission.turn_id)).metadata
        release.set()
        values = await asyncio.wait_for(asyncio.gather(*calls), 2)
        assert sum(created for _, created in values) == 1
        assert all(stored == job for stored, _ in values)
        assert len(await core.state.list_jobs()) == 1
        assert (await core.state.get_turn(admission.turn_id)).metadata["backend_dispatch_reserved"] is True
        assert worker.calls == []  # Repository acceptance itself has no executor.
    finally:
        release.set()
        await asyncio.gather(*calls, return_exceptions=True)
        await second.close()


async def test_capacity_sixteen_refuses_without_partial_source_reservation(stack):
    core, worker, _ = stack
    request, first = await admitted(core)
    await submit(core, first)
    await asyncio.wait_for(worker.started.wait(), 1)
    for index in range(1, 16):
        _, admission = await admitted(core, conversation_id=request.conversation_id, item=f"pending-{index}", text=f"Travail {index}")
        await submit(core, admission)
    _, overflow = await admitted(core, conversation_id=request.conversation_id, item="overflow", text="Une demande de trop")
    refused = await submit(core, overflow)
    assert refused.status == "unavailable" and refused.reason == "back_brain_capacity"
    assert len(await core.state.list_jobs()) == 16
    assert "backend_dispatch_reserved" not in (await core.state.get_turn(overflow.turn_id)).metadata
    assert len(worker.calls) == 1


async def test_progress_is_durable_before_event_and_terminal_error_has_stable_code(stack, monkeypatch):
    core, _, root = stack
    class ControlledFailure(RuntimeError):
        code = "back_brain_timeout"
    class ProgressWorker(ControlledWorker):
        async def execute_with_progress(self, job, progress):
            self.calls.append(job)
            await progress.emit(job.id, JobProgress(phase="research", fraction=0.25, public_summary="Faits en cours"))
            self.started.set()
            await self.release.wait()
            raise ControlledFailure("sensitive details never published")
    worker = ProgressWorker()
    core.jobs.workers["back_brain"] = worker
    observed = []
    publish = core.events.publish
    async def check(event):
        if event.message_type in {"brain.work.progress", "job.failed"}:
            stored = await core.state.get_job(event.payload["job_id"])
            if event.message_type == "brain.work.progress":
                assert stored.progress["fraction"] == 0.25
            else:
                assert stored.status is JobStatus.FAILED and stored.error == "back_brain_timeout"
            observed.append(event.message_type)
        await publish(event)
    monkeypatch.setattr(core.events, "publish", check)
    request, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 1)
    assert (await core.back_brain.status(request.conversation_id, accepted.job_id))["progress"]["phase"] == "research"
    worker.release.set()
    await settle(core, accepted.job_id)
    assert observed == ["brain.work.progress", "job.failed"]
    status = await core.back_brain.status(request.conversation_id, accepted.job_id)
    assert status["error"] == "back_brain_timeout" and status["progress"]["fraction"] == 0.25
    await core.stop()
    restarted = JarvisCoreApplication(data_root=root)
    await restarted.start()
    try:
        assert await restarted.back_brain.status(request.conversation_id, accepted.job_id) == status
    finally:
        await restarted.stop()


@pytest.mark.parametrize("mutation", ["snapshot_revision", "source", "text", "order"])
async def test_atomic_accept_rejects_forged_provenance_without_reservation(stack, monkeypatch, mutation):
    core, worker, _ = stack
    _, admission = await admitted(core)
    original = core.state.accept_admitted_job
    async def corrupt(job, turn_id, **kwargs):
        payload = BackBrainWorkPayload.from_payload(job.payload)
        if mutation == "snapshot_revision":
            payload = replace(payload, provenance=replace(payload.provenance, snapshot_revision=0))
        elif mutation == "source":
            payload = replace(payload, provenance=replace(payload.provenance, source=replace(admission.source, intent_epoch=admission.source.intent_epoch + 1)))
        elif mutation == "text":
            payload = replace(payload, request_text="texte falsifié")
        else:
            await core.state._run(lambda c: c.execute("UPDATE voice_conversation_snapshots SET data=json_set(data,'$.turns',json('[]'),'$.active_turn_id',NULL)"))
        return await original(replace(job, payload=payload.to_payload()), turn_id, **kwargs)
    monkeypatch.setattr(core.state, "accept_admitted_job", corrupt)
    with pytest.raises(ValueError):
        await submit(core, admission)
    assert await core.state.list_jobs() == () and worker.calls == []
    assert "backend_dispatch_reserved" not in (await core.state.get_turn(admission.turn_id)).metadata


async def test_terminal_persistence_failure_retries_owned_result_before_one_completed_event(stack, monkeypatch):
    core, worker, _ = stack
    _, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 1)
    queue = core.events.subscribe()
    original = core.state.transition_job
    failed = False
    async def fail(value, **kwargs):
        nonlocal failed
        if value.status is JobStatus.COMPLETED and not failed:
            failed = True
            raise OSError("controlled persistence failure")
        return await original(value, **kwargs)
    monkeypatch.setattr(core.state, "transition_job", fail)
    worker.release.set()
    await settle(core, accepted.job_id)
    stored = await core.state.get_job(accepted.job_id)
    assert stored.status is JobStatus.COMPLETED and stored.result["text"] == "Résultat durable exact."
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    core.events.unsubscribe(queue)
    assert sum(event.message_type == "job.completed" for event in events) == 1


@pytest.mark.parametrize("boundary", ["accept", "start"])
async def test_postcommit_caller_cancel_keeps_submission_and_start_owned(stack, monkeypatch, boundary):
    core, worker, _ = stack
    _, admission = await admitted(core)
    committed, release = threading.Event(), threading.Event()
    original = core.state._thread
    trapped = False
    async def blocked(fn, *args):
        nonlocal trapped
        if not trapped and fn.__name__ == ("accept" if boundary == "accept" else "transition"):
            trapped = True
            def transaction(*values):
                result = fn(*values)
                committed.set()
                assert release.wait(2)
                return result
            return await original(transaction, *args)
        return await original(fn, *args)
    monkeypatch.setattr(core.state, "_thread", blocked)
    caller = asyncio.create_task(submit(core, admission))
    cancel = None
    try:
        assert await asyncio.to_thread(committed.wait, 1)
        if boundary == "accept":
            caller.cancel()
        else:
            acceptance = await asyncio.wait_for(caller, 1)
            cancel = asyncio.create_task(core.back_brain.cancel(admission.conversation_id, acceptance.job_id))
            await asyncio.sleep(0)
        release.set()
        if boundary == "accept":
            with pytest.raises(asyncio.CancelledError):
                await caller
            acceptance = await asyncio.wait_for(submit(core, admission), 1)
            await asyncio.wait_for(worker.started.wait(), 1)
            assert len(worker.calls) == 1
            assert (await core.state.get_job(acceptance.job_id)).status is JobStatus.RUNNING
        else:
            status = await asyncio.wait_for(cancel, 1)
            assert status["status"] == "cancelled" and worker.calls == []
        assert len(await core.state.list_jobs()) == 1
    finally:
        release.set()
        await asyncio.gather(caller, *([cancel] if cancel else []), return_exceptions=True)


async def test_persistent_transition_failure_keeps_owner_and_stop_bounded_until_recovery(stack, monkeypatch):
    core, worker, _ = stack
    _, admission = await admitted(core)
    original = core.state.transition_job
    outage = True
    seen = asyncio.Event()
    async def fail(value, **kwargs):
        if outage:
            seen.set()
            raise OSError("storage unavailable")
        return await original(value, **kwargs)
    monkeypatch.setattr(core.state, "transition_job", fail)
    core.jobs.owned.cleanup_timeout_s = .05
    accepted = await submit(core, admission)
    try:
        await asyncio.wait_for(seen.wait(), 1)
        state = await core.back_brain.status(admission.conversation_id, accepted.job_id)
        assert state["persistence_error"] == "state_persistence_unavailable"
        assert state["status"] == "pending" and worker.calls == []
        assert accepted.job_id in core.jobs._running
        await asyncio.wait_for(core.stop(), .8)
        assert core.health.status == "state_persistence_unknown"
        assert accepted.job_id in core.jobs._running
    finally:
        outage = False
    await asyncio.wait_for(core.stop(), 1)
    assert core.health.status == "stopped" and worker.calls == []


@pytest.mark.parametrize("boundary", ["start", "after_cleanup"])
async def test_transient_owned_read_failure_recovers_without_orphan_or_reexecution(stack, monkeypatch, boundary):
    core, worker, _ = stack
    _, admission = await admitted(core)
    original = core.state.get_job
    count = 0
    async def fail_once(job_id):
        nonlocal count
        if asyncio.current_task().get_name().startswith("jarvis-job-"):
            count += 1
            if count == (1 if boundary == "start" else 3):
                raise OSError("controlled owned read failure")
        return await original(job_id)
    monkeypatch.setattr(core.state, "get_job", fail_once)
    accepted = await submit(core, admission)
    worker.release.set()
    await settle(core, accepted.job_id)
    status = await core.back_brain.status(admission.conversation_id, accepted.job_id)
    assert status["status"] == "completed"
    assert status["result"]["text"] == "Résultat durable exact."
    assert len(worker.calls) == 1
    assert (await submit(core, admission)).duplicate
    assert len(worker.calls) == 1 and not core.jobs._running


@pytest.mark.parametrize("terminal", [False, True])
async def test_work_projection_failure_never_orphans_authoritative_job(stack, monkeypatch, terminal):
    core, worker, _ = stack
    _, admission = await admitted(core)
    original = core.jobs._observe_work
    failed = False
    async def observe(job, status, **kwargs):
        nonlocal failed
        if (job.status is JobStatus.COMPLETED) == terminal and not failed:
            failed = True
            raise OSError("controlled projection outage")
        return await original(job, status, **kwargs)
    monkeypatch.setattr(core.jobs, "_observe_work", observe)
    accepted = await submit(core, admission)
    worker.release.set()
    await settle(core, accepted.job_id)
    stored = await core.state.get_job(accepted.job_id)
    assert failed and stored.status is JobStatus.COMPLETED
    assert stored.result["text"] == "Résultat durable exact."
    assert len(worker.calls) == 1 and not core.jobs._running


@pytest.mark.parametrize("boundary", ["owned_read", "stop_listing"])
async def test_persistent_storage_read_failure_preserves_owner_and_bounds_stop(stack, monkeypatch, boundary):
    core, worker, _ = stack
    _, admission = await admitted(core)
    original = core.state.get_job if boundary == "owned_read" else core.state.list_active_back_brain_jobs
    outage, seen = True, asyncio.Event()
    async def failing(*args, **kwargs):
        if outage and (boundary == "stop_listing" or asyncio.current_task().get_name().startswith("jarvis-job-")):
            seen.set()
            raise OSError("controlled read outage")
        return await original(*args, **kwargs)
    monkeypatch.setattr(core.state, "get_job" if boundary == "owned_read" else "list_active_back_brain_jobs", failing)
    core.jobs.owned.cleanup_timeout_s = .05
    accepted = await submit(core, admission)
    try:
        if boundary == "owned_read":
            await asyncio.wait_for(seen.wait(), 1)
        await asyncio.wait_for(core.stop(), .8)
        assert seen.is_set() and core.health.status == "state_persistence_unknown"
        if boundary == "owned_read":
            assert accepted.job_id in core.jobs._running
        else:
            assert core.jobs.owned._stop_task and not core.jobs.owned._stop_task.done()
        assert core.jobs.owned.persistence_failures
    finally:
        outage = False
    await asyncio.wait_for(core.stop(), 1)
    assert core.health.status == "stopped" and not core.jobs._running
    if boundary == "owned_read":
        assert worker.calls == []


async def test_stop_during_postcommit_submission_keeps_continuation_owned_until_return(stack, monkeypatch):
    core, worker, _ = stack
    _, admission = await admitted(core)
    committed, release = threading.Event(), threading.Event()
    original = core.state._thread
    async def blocked(fn, *args):
        if fn.__name__ == "accept":
            def transaction(*values):
                result = fn(*values)
                committed.set()
                assert release.wait(2)
                return result
            return await original(transaction, *args)
        return await original(fn, *args)
    monkeypatch.setattr(core.state, "_thread", blocked)
    core.jobs.owned.cleanup_timeout_s = .05
    caller = asyncio.create_task(submit(core, admission))
    try:
        assert await asyncio.to_thread(committed.wait, 1)
        await asyncio.wait_for(core.stop(), .8)
        assert core.health.status == "state_persistence_unknown"
        assert core.back_brain._submissions and worker.calls == []
    finally:
        release.set()
        accepted = await asyncio.wait_for(caller, 1)
    assert (await core.state.get_job(accepted.job_id)).status is JobStatus.CANCELLED
    await asyncio.wait_for(core.stop(), 1)
    assert core.health.status == "stopped" and worker.calls == []


@pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.RUNNING])
async def test_restart_interrupts_accepted_nonterminal_job_without_replay(stack, status):
    core, worker, root = stack
    request, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 1)
    await core.back_brain.cancel(request.conversation_id, accepted.job_id)
    job = await core.state.get_job(accepted.job_id)
    # Controlled durable crash image: no process exists and no restart execution is claimed.
    await core.state.save_job(replace(job, status=status, cancellation="none", completed_at=None))
    await core.state.close()
    core.health.status = "stopped"
    restarted_worker = ControlledWorker()
    restarted = JarvisCoreApplication(data_root=root, workers={"back_brain": restarted_worker})
    await restarted.start()
    try:
        recovered = await restarted.back_brain.status(request.conversation_id, job.id)
        assert recovered["status"] == "interrupted" and recovered["error"] == "core_restarted"
        assert (await submit(restarted, admission)).duplicate
        assert restarted_worker.calls == []
    finally:
        await restarted.stop()
