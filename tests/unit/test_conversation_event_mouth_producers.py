"""Mouth and reflex Conversation Events recorded by `SpeechScheduler` (Slice 03b).

Every case runs the real scheduler with the fakes of `test_v2_speech_scheduler`
and a real `ConversationEventForwarder` that is never started: `record()` only
queues, so the test reads exactly what would be sent to Core. Each event with a
`trace_ref` must join exactly one journal line (`conversation_event_id`).
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.conversation_event_emitter import PRODUCER_BRAIN_SERVICE
from jarvis.domain.conversation_events import (
    ConversationActor,
    ConversationEventType as T,
    derive_conversation_event_id,
    encode_conversation_event,
    reconstruct_conversation,
)
from jarvis.domain.v2 import PlaybackCursor, SpeechKind, utc_now
from jarvis.runtime.conversation_event_forwarder import PRODUCER_SPEECH_SCHEDULER
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.fakes.conversation_events import assert_each_trace_ref_joins_one_line, queued, recording_forwarder
from tests.fakes.speech_context import context
import tests.unit.test_v2_speech_scheduler as scheduler_tests
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION,
    FakeClock,
    FakeCore,
    FakeVoiceSession,
    RecordingJournal,
    busy_surface,
    finish_speech,
    release_surface,
    speech_envelope,
    wait_for,
)
from tests.unit.test_voice_duplex import ControllableSession, EmptyCore


@pytest.fixture(autouse=True)
def _fresh_speech_origin():
    # `speech_envelope` dates requests from `test_v2_speech_scheduler.ORIGIN`, which
    # that module re-anchors per test with its own autouse fixture. Without the same
    # here, a transient speech created at import time expires (60 s fallback TTL)
    # when the full suite reaches this file late.
    scheduler_tests.ORIGIN = utc_now()


def build(core, session, journal, *, clock=None, forwarder=None):
    forwarder = forwarder if forwarder is not None else recording_forwarder()
    scheduler = SpeechScheduler(core=core, conversation_id=CONVERSATION, session=session, journal=journal,
                                clock=clock, reconnect_delay_s=0.0, output_timeout_s=5.0,
                                conversation_events=forwarder)
    scheduler.update_speech_context(context(CONVERSATION))
    return scheduler, forwarder


def core_parent(speech_id: str) -> str:
    return derive_conversation_event_id(producer=PRODUCER_BRAIN_SERVICE, event_type=T.BRAIN_SPEECH_REQUESTED,
                                        conversation_id=CONVERSATION, source_ids=(speech_id,))


def types(events):
    return [event.event_type for event in events]


async def test_a_completed_speech_records_queued_started_completed_joined_to_the_journal_and_core():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Voici la réponse.", kind=SpeechKind.RESULT, speech_id="speech-ok",
                                           work_id="work-1"))
        await wait_for(lambda: len(session.spoken) == 1)
        await finish_speech(scheduler, session)
        await journal.wait_until(lambda: journal.count("voice.speech.completed") == 1)
    finally:
        await scheduler.stop()

    events = queued(forwarder)
    assert types(events) == [T.MOUTH_SPEECH_QUEUED, T.MOUTH_SPEECH_STARTED, T.MOUTH_SPEECH_COMPLETED]
    queued_event, started, completed = events
    for event in events:
        assert event.producer == PRODUCER_SPEECH_SCHEDULER and event.actor is ConversationActor.MOUTH
        assert (event.conversation_id, event.speech_id, event.correlation_id, event.work_id) == (
            CONVERSATION, "speech-ok", "corr-1", "work-1")
        assert event.session_id == "test-session"
        # The mouth span joins the Core request it plays (brain.speech.requested).
        assert event.parent_event_id == core_parent("speech-ok")
    assert started.span_id == completed.span_id == "speech-ok"
    assert started.content == "Voici la réponse." and completed.content is None and queued_event.content is None
    assert completed.started_at == started.started_at and completed.ended_at >= started.started_at
    assert dict(completed.attributes)["output_id"] == dict(started.attributes)["output_id"]
    assert_each_trace_ref_joins_one_line(events, journal.events)
    [item] = [item for item in reconstruct_conversation(events) if item.span_id == "speech-ok"]
    assert (item.status, item.text, item.anomalies) == ("completed", "Voici la réponse.", ())


async def test_a_barge_in_closes_the_span_as_interrupted_with_the_heard_milliseconds():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Je regarde tous les vols.", speech_id="speech-cut"))
        await wait_for(lambda: len(session.spoken) == 1)
        scheduler.note_interruption(PlaybackCursor(speech_id="speech-cut", played_ms=1200))
        await finish_speech(scheduler, session, status="cancelled")
        await journal.wait_until(lambda: journal.count("voice.speech.interrupted") == 1)
    finally:
        await scheduler.stop()

    events = queued(forwarder)
    closes = [event for event in events if event.event_type is T.MOUTH_SPEECH_INTERRUPTED]
    assert len(closes) == 1
    attributes = dict(closes[0].attributes)
    assert (attributes["played_ms"], attributes["status"], attributes["reason"]) == (1200, "cancelled", "user_barge_in")
    assert_each_trace_ref_joins_one_line(events, journal.events)
    [item] = [item for item in reconstruct_conversation(events) if item.span_id == "speech-cut"]
    assert item.status == "interrupted" and item.status != "completed"


async def test_superseded_and_expired_speech_are_closes_distinct_from_completion():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    clock = FakeClock()
    scheduler, forwarder = build(core, session, journal, clock=clock)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(speech_envelope("Je regarde les messages.", work_id="work-1", speech_id="speech-old",
                                           created_offset_s=1))
        await core.publish(speech_envelope("Je cherche encore.", speech_id="speech-ttl", ttl_s=5, created_offset_s=2))
        await wait_for(lambda: scheduler.pending_count == 2)
        await core.publish(speech_envelope("Trois messages attendent.", kind=SpeechKind.RESULT, work_id="work-1",
                                           speech_id="speech-new", created_offset_s=3))
        await journal.wait_until(lambda: journal.count("voice.speech.superseded") == 1)
        clock.advance(30)
        await release_surface(scheduler, held)
        await wait_for(lambda: session.active_output_id is not None)
        await finish_speech(scheduler, session)
        await journal.wait_until(lambda: journal.count("voice.speech.completed") == 1)
    finally:
        await scheduler.stop()

    events = queued(forwarder)
    by_speech = {(event.speech_id, event.event_type): event for event in events}
    superseded = by_speech[("speech-old", T.MOUTH_SPEECH_SUPERSEDED)]
    expired = by_speech[("speech-ttl", T.MOUTH_SPEECH_EXPIRED)]
    assert dict(superseded.attributes)["reason"] == "superseded" and dict(expired.attributes)["reason"] == "ttl"
    # Never started: the close carries what was withheld and no start time.
    assert superseded.content == "Je regarde les messages." and superseded.started_at is None
    assert ("speech-new", T.MOUTH_SPEECH_COMPLETED) in by_speech
    assert_each_trace_ref_joins_one_line(events, journal.events)
    statuses = {item.span_id: item.status for item in reconstruct_conversation(events) if item.span_id}
    assert statuses == {"speech-old": "superseded", "speech-ttl": "expired", "speech-new": "completed"}


async def test_stopping_the_voice_expires_queued_speech_as_a_recorded_close():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    await busy_surface(scheduler)
    await core.publish(speech_envelope("Voici la réponse.", kind=SpeechKind.RESULT, speech_id="speech-bg"))
    await wait_for(lambda: scheduler.pending_count == 1)
    await scheduler.stop()

    [expired] = [event for event in queued(forwarder) if event.event_type is T.MOUTH_SPEECH_EXPIRED]
    assert dict(expired.attributes)["reason"] == "voice_background"
    assert_each_trace_ref_joins_one_line(queued(forwarder), journal.events)


async def test_a_failed_speak_is_one_failed_close_and_the_following_interrupted_line_carries_no_event():
    class FailingSession(FakeVoiceSession):
        async def speak_reserved(self, request, *, output_id):  # noqa: ANN001
            raise ConnectionResetError("PRIVATE provider detail")

    core, session, journal = FakeCore(), FailingSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Voici.", kind=SpeechKind.RESULT, speech_id="speech-fail"))
        await journal.wait_until(lambda: journal.count("voice.speech.interrupted") == 1)
    finally:
        await scheduler.stop()

    events = queued(forwarder)
    assert types(events) == [T.MOUTH_SPEECH_QUEUED, T.MOUTH_SPEECH_FAILED]
    failed = events[1]
    assert dict(failed.attributes)["code"] == "speech_speak_failed"
    assert dict(failed.attributes)["error_class"] == "ConnectionResetError"
    assert "PRIVATE" not in repr(encode_conversation_event(failed))
    # Never started: kept as diagnostic evidence, without the text nobody heard.
    assert failed.content is None and failed.started_at is None
    [item] = [item for item in reconstruct_conversation(events) if item.event_type is T.MOUTH_SPEECH_FAILED]
    assert item.visibility.value == "diagnostic" and item.text is None
    assert "conversation_event_id" not in journal.of("voice.speech.interrupted")[0]["data"]
    assert_each_trace_ref_joins_one_line(events, journal.events)


async def test_a_multi_paragraph_request_records_one_span_per_chunk_with_the_core_request_as_parent():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Premier paragraphe.\n\nSecond paragraphe.", kind=SpeechKind.RESULT,
                                           speech_id="speech-chain"))
        for count in (1, 2):
            await wait_for(lambda: len(session.spoken) == count)
            await finish_speech(scheduler, session)
        await journal.wait_until(lambda: journal.count("voice.speech.completed") == 2)
    finally:
        await scheduler.stop()

    started = [event for event in queued(forwarder) if event.event_type is T.MOUTH_SPEECH_STARTED]
    assert [event.content for event in started] == ["Premier paragraphe.\n\n", "Second paragraphe."]
    assert len({event.speech_id for event in started}) == 2 and "speech-chain" not in {e.speech_id for e in started}
    assert {event.parent_event_id for event in started} == {core_parent("speech-chain")}
    assert_each_trace_ref_joins_one_line(queued(forwarder), journal.events)


async def test_a_requeued_speech_records_queued_once_and_one_journal_line_joins_it():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    request = speech_envelope("Réponse.", kind=SpeechKind.RESULT, speech_id="speech-twice")
    from jarvis.domain.v2 import SpeechRequest

    parsed = SpeechRequest.from_payload(request.payload)
    scheduler._note_queued(parsed)
    scheduler._note_queued(parsed)  # `_replan` re-queues a deferred request the same way

    assert types(queued(forwarder)) == [T.MOUTH_SPEECH_QUEUED]
    assert forwarder.counters.repeated == 1
    lines = journal.of("voice.speech.queued")
    assert [("conversation_event_id" in line["data"]) for line in lines] == [True, False]
    assert_each_trace_ref_joins_one_line(queued(forwarder), journal.events)


async def test_a_spoken_reflex_is_an_instant_joined_to_its_journal_line():
    journal = RecordingJournal()
    forwarder = recording_forwarder()
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id="conversation", session=ControllableSession(),
                                journal=journal, reflex_delay_s=.01, conversation_events=forwarder)
    scheduler.update_speech_context(context("conversation", "c"))
    scheduler._running = True
    from jarvis.domain.v2 import ProtocolEnvelope

    await scheduler.handle_core_event(ProtocolEnvelope(message_type="brain.work.started", payload={
        "conversation_id": "conversation", "correlation_id": "c", "work_id": "work"}))
    scheduler.request_reflex("Compare les prix", correlation_id="c")
    scheduler._reflex.due = asyncio.get_running_loop().time() - .001
    scheduler._reflex.next_check = scheduler._reflex.due
    await scheduler._maybe_speak_reflex()
    await scheduler.stop()

    [reflex] = queued(forwarder)
    assert reflex.event_type is T.MOUTH_REFLEX_STARTED and reflex.correlation_id == "c"
    assert reflex.span_id is None and reflex.content is None  # generated by the provider: text unknown here
    line = journal.of("voice.reflex.started")[0]
    assert dict(reflex.attributes)["output_id"] == line["data"]["output_id"]
    assert_each_trace_ref_joins_one_line([reflex], journal.events)


async def test_without_a_recorder_the_journal_lines_are_unchanged():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = SpeechScheduler(core=core, conversation_id=CONVERSATION, session=session, journal=journal,
                                reconnect_delay_s=0.0, output_timeout_s=5.0)
    scheduler.update_speech_context(context(CONVERSATION))
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Voici.", kind=SpeechKind.RESULT, speech_id="speech-plain"))
        await wait_for(lambda: len(session.spoken) == 1)
        await finish_speech(scheduler, session)
        await journal.wait_until(lambda: journal.count("voice.speech.completed") == 1)
    finally:
        await scheduler.stop()
    assert all("conversation_event_id" not in event["data"] for event in journal.events)


async def test_a_broken_recorder_never_reaches_speech_delivery():
    class Exploding:
        def record(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise RuntimeError("recorder bug")

        def derive_event_id(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise RuntimeError("recorder bug")

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, _ = build(core, session, journal, forwarder=Exploding())
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Voici.", kind=SpeechKind.RESULT, speech_id="speech-robust"))
        await wait_for(lambda: len(session.spoken) == 1)
        await finish_speech(scheduler, session)
        await journal.wait_until(lambda: journal.count("voice.speech.completed") == 1)
    finally:
        await scheduler.stop()
    assert session.texts() == ["Voici."]
    # queued and started failed; no start recorded, so no close is attempted
    assert journal.count("voice.conversation_events.producer_failed") == 2


async def test_muting_while_jarvis_speaks_closes_the_span_once_as_interrupted_by_the_background():
    """Auto-turn key / idle timeout / shutdown → `stop()` cancels `_speak`: the span must still close."""
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    await core.publish(speech_envelope("Je regarde tous les vols.", kind=SpeechKind.RESULT, speech_id="speech-muted"))
    await wait_for(lambda: len(session.spoken) == 1)
    await journal.wait_until(lambda: journal.count("voice.speech.started") == 1)
    await scheduler.stop()  # the output never ended

    closes = [event for event in queued(forwarder) if event.speech_id == "speech-muted"
              and event.event_type not in (T.MOUTH_SPEECH_QUEUED, T.MOUTH_SPEECH_STARTED)]
    assert [event.event_type for event in closes] == [T.MOUTH_SPEECH_INTERRUPTED]
    [close] = closes
    assert dict(close.attributes)["reason"] == "voice_background" and "status" in dict(close.attributes)
    assert close.trace_ref is None  # no journal line is written on this path
    assert close.content is None and close.started_at is not None
    assert journal.count("voice.speech.interrupted") == 0
    [item] = [item for item in reconstruct_conversation(queued(forwarder)) if item.span_id == "speech-muted"]
    assert item.status == "interrupted" and not item.anomalies
    assert_each_trace_ref_joins_one_line(queued(forwarder), journal.events)


async def test_muting_after_a_completed_speech_adds_no_close():
    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    await core.publish(speech_envelope("Voici.", kind=SpeechKind.RESULT, speech_id="speech-done"))
    await wait_for(lambda: len(session.spoken) == 1)
    await finish_speech(scheduler, session)
    await journal.wait_until(lambda: journal.count("voice.speech.completed") == 1)
    await scheduler.stop()

    assert [event.event_type for event in queued(forwarder)] == [
        T.MOUTH_SPEECH_QUEUED, T.MOUTH_SPEECH_STARTED, T.MOUTH_SPEECH_COMPLETED]


class HoldingSession(FakeVoiceSession):
    """`speak_reserved` waits for the test: a cancel or an invalidation can land before the start."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def speak_reserved(self, request, *, output_id):  # noqa: ANN001
        self.entered.set()
        await self.release.wait()
        return await super().speak_reserved(request, output_id=output_id)


async def test_a_cancel_during_speak_reserved_records_no_close_for_a_span_never_started():
    core, session, journal = FakeCore(), HoldingSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    await core.publish(speech_envelope("Jamais entendu.", kind=SpeechKind.RESULT, speech_id="speech-held"))
    await asyncio.wait_for(session.entered.wait(), 2)
    await scheduler.stop()  # mute while the provider has not accepted the output yet

    assert types(queued(forwarder)) == [T.MOUTH_SPEECH_QUEUED]
    public = reconstruct_conversation(queued(forwarder), include_diagnostic=False)
    assert public == ()  # nothing the user could read as spoken


async def test_an_output_invalidated_before_its_start_records_no_interrupted_close():
    core, session, journal = FakeCore(), HoldingSession(), RecordingJournal()
    scheduler, forwarder = build(core, session, journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Plus vrai.", kind=SpeechKind.RESULT, speech_id="speech-revoked"))
        await asyncio.wait_for(session.entered.wait(), 2)
        active = scheduler._active
        scheduler._invalidate_presentation(active, "dependency_revoked")  # what `_replan` does on a revision
        session.release.set()
        await wait_for(lambda: len(session.spoken) == 1)
        await release_surface(scheduler, active.output_id, status="cancelled")
        await journal.wait_until(lambda: journal.count("voice.speech.interrupted") == 1)
    finally:
        await scheduler.stop()

    assert types(queued(forwarder)) == [T.MOUTH_SPEECH_QUEUED]
    assert journal.count("voice.speech.started") == 0
    assert "conversation_event_id" not in journal.of("voice.speech.interrupted")[0]["data"]
