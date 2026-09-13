import asyncio
from datetime import datetime, timezone
import time

import pytest

from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.voice_events import UserCommitSource, UserTranscriptCommitted, UserTranscriptDelta, VoiceEvent
from jarvis.domain.voice_frontend import VoiceContext, VoiceCorrelation, VoiceObservation
from jarvis.runtime.front_brain_sidecar import FrontBrainSidecar, FrontBrainSidecarConfig
from tests.fakes.front_brain import FakeFrontBrainAnalyzer


def event(revision=1, text="bonjour", *, final=False, item="item", session="session"):
    payload = UserTranscriptCommitted("transcript-" + item, text, revision, UserCommitSource.PROVIDER) if final else UserTranscriptDelta("transcript-" + item, text, revision)
    return VoiceEvent(str(revision), revision, VoiceCorrelation(session, turn_id="turn-" + item, provider_input_id=item),
                      VoiceObservation(datetime.now(timezone.utc), time.monotonic_ns()), payload)


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(.001)


def sidecar(analyzer, **config):
    result = FrontBrainSidecar(analyzer, session_id="session", configuration_id="config",
        config=FrontBrainSidecarConfig(debounce_s=.01, min_interval_s=0, **config))
    result.update_context(VoiceContext(), source=None, source_complete=True)
    result.start()
    return result


@pytest.mark.asyncio
async def test_reader_updates_coalesce_only_after_item_permission_and_stop_cancels():
    analyzer = FakeFrontBrainAnalyzer(gate=asyncio.Event(), clock_ns=time.monotonic_ns)
    worker = sidecar(analyzer)
    try:
        for revision in range(1, 101):
            worker.observe(event(revision, "a"))
        await asyncio.sleep(.02)
        assert analyzer.call_count == 0
        worker.allow_item("item", "permission")
        await until(lambda: analyzer.call_count == 1)
        assert analyzer.requests[0].input.text == "a" * 100
        assert analyzer.active_count == 1
    finally:
        await asyncio.wait_for(worker.close(), 1)
    assert analyzer.active_count == 0 and analyzer.cancelled_count == 1


@pytest.mark.asyncio
async def test_final_same_text_replaces_partial_cancels_old_and_reserves_final_budget():
    analyzer = FakeFrontBrainAnalyzer(gate=asyncio.Event(), clock_ns=time.monotonic_ns)
    worker = sidecar(analyzer)
    try:
        worker.allow_item("item", "permission")
        worker.observe(event())
        await until(lambda: analyzer.call_count == 1)
        worker.observe(event(2, "bonjour", final=True))
        source = SpeechSource("core-turn", "correlation", "intent", 1)
        worker.update_source(source=source, source_complete=True)
        worker.admit_item("item", source)
        await until(lambda: analyzer.call_count == 2)
        assert analyzer.cancelled_count == 1 and analyzer.active_count == 1
        assert analyzer.requests[-1].input.committed
        assert analyzer.requests[-1].origin_source == source
        assert analyzer.requests[-1].request_id != analyzer.requests[0].request_id
        assert worker._items["item"].reservation == 2 * worker.config.reservation_per_call
        worker.admit_item("item", source)
        await asyncio.sleep(.02)
        assert analyzer.call_count == 2
    finally:
        await asyncio.wait_for(worker.close(), 1)


@pytest.mark.asyncio
async def test_long_utterance_never_exceeds_partial_budget_but_final_still_runs():
    analyzer = FakeFrontBrainAnalyzer(clock_ns=time.monotonic_ns)
    worker = sidecar(analyzer)
    try:
        worker.allow_item("item", "permission")
        for revision in range(1, 12):
            worker.observe(event(revision, "x"))
            await asyncio.sleep(.02)
        assert analyzer.call_count == 2
        worker.observe(event(12, "x" * 11, final=True))
        worker.update_source(source=SpeechSource("core", "corr", "intent", 1), source_complete=True)
        worker.admit_item("item", SpeechSource("core", "corr", "intent", 1))
        await until(lambda: analyzer.call_count == 3)
        assert analyzer.requests[-1].input.committed
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_rejection_tombstones_and_retention_saturation_do_not_regrant():
    analyzer = FakeFrontBrainAnalyzer(clock_ns=time.monotonic_ns)
    worker = sidecar(analyzer, max_items=2)
    try:
        worker.reject_item("item", "owner")
        worker.allow_item("item", "late-permission")
        worker.observe(event())
        worker.reject_item("second", "owner")
        worker.allow_item("third", "permission")
        worker.observe(event(item="third"))
        await asyncio.sleep(.03)
        assert analyzer.call_count == 0
        assert worker._disabled and len(worker._items) == 2
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_revision_gap_and_old_session_never_analyzed():
    analyzer = FakeFrontBrainAnalyzer(clock_ns=time.monotonic_ns)
    worker = sidecar(analyzer)
    try:
        worker.allow_item("item", "permission")
        worker.observe(event(session="old"))
        worker.observe(event(5))
        await asyncio.sleep(.03)
        assert analyzer.call_count == 0
        assert worker._items["item"].rejected
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_failure_and_timeout_leave_worker_available_for_final():
    analyzer = FakeFrontBrainAnalyzer(failure=RuntimeError("private backend text"), clock_ns=time.monotonic_ns)
    worker = sidecar(analyzer)
    try:
        worker.allow_item("item", "permission")
        worker.observe(event())
        await until(lambda: analyzer.call_count == 1)
        worker.observe(event(2, "bonjour", final=True))
        worker.update_source(source=SpeechSource("core", "corr", "intent", 1), source_complete=True)
        worker.admit_item("item", SpeechSource("core", "corr", "intent", 1))
        await until(lambda: analyzer.call_count == 2)
        assert not worker._worker.done()
    finally:
        await worker.close()
