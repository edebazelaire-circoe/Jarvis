"""Task08 scheduling probes; clocks and source authority are synthetic."""
import asyncio
from dataclasses import replace

import pytest

from jarvis.domain.speech_presentation import SpeechDependency, semantic_text_spans
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, SpeechRequest
from tests.fakes.speech_context import context, source
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeClock, FakeCore, FakeVoiceSession, build_scheduler,
    busy_surface, finish_speech, release_surface, wait_for,
)


def request(text="Result", *, correlation="corr-1", epoch=1, kind=SpeechKind.RESULT, **kwargs):
    return SpeechRequest(CONVERSATION, text, correlation_id=correlation, source=source(correlation, epoch=epoch), kind=kind, **kwargs)


@pytest.mark.parametrize("age", [29.1, 35.9])
async def test_old_progress_and_late_results_do_not_override_new_intent(age):
    clock = FakeClock()
    selected = build_scheduler(FakeCore(), FakeVoiceSession(), clock=clock)
    progress = request("Old preamble", kind=SpeechKind.PROGRESS, created_at=clock.now())
    selected._enqueue(progress)
    clock.advance(age)
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    result = request("Old result still available", outcome_id="durable-outcome", created_at=clock.now())
    selected._enqueue(result)
    assert selected._pop_next() is None
    snapshot = selected.presentation_snapshot()
    assert [(item["status"], item["reason"]) for item in snapshot["candidates"]] == [("superseded", "stale_source"), ("deferred", "stale_source")]
    assert snapshot["candidates"][1]["outcome_id"] == "durable-outcome"


async def test_unknown_source_and_missing_reservation_are_explicitly_deferred():
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    selected._enqueue(SpeechRequest(CONVERSATION, "Unknown origin"))
    selected.session.speak_reserved = None
    selected._enqueue(request())
    assert selected._pop_next() is None
    assert {item["reason"] for item in selected.presentation_snapshot()["candidates"]} == {"unknown_source", "output_admission_unavailable"}


async def test_nonintent_revision_and_old_work_invalidation_preserve_current_result():
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    current = replace(request(), source=source("corr-1", work_id="reused"))
    selected._enqueue(current)
    await selected.handle_core_event(ProtocolEnvelope(message_type="brain.state.updated", payload={"revision": 1}))
    await selected.handle_core_event(ProtocolEnvelope(message_type="brain.state.updated", payload={"revision": 2}))
    selected.update_speech_context(context(CONVERSATION, invalid=(SpeechDependency("reused", "older-origin"),)))
    assert selected._pop_next() == current


async def test_multichunk_exact_text_and_replanning_between_chunks():
    core, session = FakeCore(), FakeVoiceSession()
    selected = build_scheduler(core, session)
    text = "First 29.1 seconds.\n\nSecond 35.9 seconds.\n\nThird."
    chain = request(text, chunks=semantic_text_spans(text), outcome_id="outcome")
    await selected.start()
    try:
        selected._enqueue(chain)
        await wait_for(lambda: len(session.spoken) == 1)
        await finish_speech(selected, session)
        await wait_for(lambda: len(session.spoken) == 2)
        assert selected.output_admission(session.active_output_id).begin_write()
        selected.output_admission(session.active_output_id).finish_write(succeeded=True)
        selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
        await finish_speech(selected, session)
        await asyncio.sleep(.02)
        assert [item.text for item in session.spoken] == [text[span.start:span.end] for span in chain.chunks[:2]]
        assert len({item.id for item in session.spoken}) == 2
        assert all(item.id != chain.id and item.outcome_id == "outcome" for item in session.spoken)
        assert selected.presentation_snapshot()["candidates"][2]["status"] == "deferred"
    finally:
        await selected.stop()


async def test_interruption_cancels_tails_without_replaying_chain_id():
    core, session = FakeCore(), FakeVoiceSession()
    selected = build_scheduler(core, session)
    chain = request("First.\n\nSecond.")
    await selected.start()
    try:
        selected._enqueue(chain)
        await wait_for(lambda: len(session.spoken) == 1)
        selected.note_interruption(None)
        await finish_speech(selected, session, status="cancelled")
        selected._enqueue(chain)
        await asyncio.sleep(.02)
        assert len(session.spoken) == 1
        assert selected.presentation_snapshot()["candidates"][1]["reason"] == "interrupted_chain"
    finally:
        await selected.stop()


async def test_queue_and_diagnostics_are_bounded_without_forgetting_ids():
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    for index in range(400):
        selected._enqueue(request(str(index)))
    assert len(selected._pending) <= 64 and len(selected._deferred) <= 64
    assert len(selected.presentation_snapshot()["candidates"]) <= 256
    assert len(selected._seen_speech_ids) == 400


async def test_late_old_origin_cannot_supersede_current_reused_work():
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    current = replace(request("Current", correlation="corr-2", epoch=2),
                      source=source("corr-2", epoch=2, work_id="reused"), work_id="reused", supersedes_key="reused")
    selected._enqueue(current)
    old = replace(request("Late old", kind=SpeechKind.RESULT), source=source("corr-1", work_id="reused"),
                  work_id="reused", supersedes_key="reused")
    selected._enqueue(old)
    assert selected._pop_next() == current
    assert selected._deferred[old.id] == old


async def test_useful_same_source_supersedes_unstarted_selected_progress_once():
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    progress = request("Progress", kind=SpeechKind.PROGRESS, work_id="work", supersedes_key="work")
    selected._enqueue(progress)
    assert selected._pop_next() == progress
    entered, release = asyncio.Event(), asyncio.Event()
    original = selected.session.speak_reserved
    async def blocked(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    selected.session.speak_reserved = blocked
    selected.output_timeout_s = .01
    launch = asyncio.create_task(selected._speak(progress))
    try:
        await entered.wait()
        token = selected.output_admission(selected._active.output_id)
        result = request("Result", work_id="work", supersedes_key="work")
        selected._enqueue(result)
        selected._enqueue(result)
        assert token.begin_write() is False
        await asyncio.sleep(0)
        release.set()
        await launch
        assert len(selected._presentation_cancelled) == 1
        assert selected._pop_next() == result
    finally:
        release.set()
        await asyncio.gather(launch, return_exceptions=True)
        await selected.stop()


async def test_reconciliation_queries_have_a_hard_bound():
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    selected._running = selected._stream_connected = True
    release = asyncio.Event()
    async def delayed_query(*args):
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass  # Controlled adapter cleanup that still owns work.
        return context(CONVERSATION)
    selected.core.speech_context = delayed_query
    try:
        for _ in range(30):
            selected._source_unknown("revision_gap")
            await asyncio.sleep(0)
        assert len(selected._source_queries) <= 8
        assert selected._source_complete is False
    finally:
        release.set()
        await selected.stop()
