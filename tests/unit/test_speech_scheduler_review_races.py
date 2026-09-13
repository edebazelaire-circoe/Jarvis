"""Independent Task08 review: advisory presence cannot revoke useful speech.

Exercise the real bridge callbacks and guarded native-write boundary. Controlled
provider/device boundaries supply no synthetic COMPLETE or heard-text evidence.
"""
from __future__ import annotations

import asyncio
import base64
import inspect

import pytest

from jarvis.domain.speaker import OwnerState
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, SpeechRequest
from jarvis.runtime.output_admission import OutputAdmissionState
from jarvis.runtime.realtime_audio import (
    BargeInAuthority, RealtimeConversationBridge, SoundDeviceRealtimeAudio,
)
from tests.fakes.audio_device import BufferedOutputStream
from tests.fakes.speech_context import context, source
from tests.unit.test_owner_barge_in import FakeOwnerSource
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeCore, FakeVoiceSession, build_scheduler,
)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


class ConnectedCore(FakeCore):
    async def events(self, *, on_connected=None):
        self.subscriptions += 1
        if on_connected is not None:
            result = on_connected()
            if inspect.isawaitable(result):
                await result
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event


class ReservedSession(FakeVoiceSession):
    def __init__(self):
        super().__init__()
        self.reservations = []
        self.cancelled_outputs = []
        self.release_provider = asyncio.Event()

    async def speak_reserved(self, request, *, output_id):
        self.spoken.append(request)
        self.reservations.append(output_id)
        self.active_output_id = output_id
        await self.release_provider.wait()
        return output_id

    async def invalidate_unstarted_output(self, output_id):
        self.cancelled_outputs.append(output_id)
        await super().invalidate_unstarted_output(output_id)


class ReconnectingCore(ConnectedCore):
    def __init__(self):
        super().__init__()
        self.reconnecting = asyncio.Event()
        self.reconnect_allowed = asyncio.Event()
        self.attempts = 0

    async def events(self, *, on_connected=None):
        self.attempts += 1
        if self.attempts > 1:
            self.reconnecting.set()
            await self.reconnect_allowed.wait()
        async for event in super().events(on_connected=on_connected):
            yield event


async def test_eof_keeps_source_unknown_until_actual_subscription_reconnects():
    core, session = ReconnectingCore(), ReservedSession()
    scheduler = build_scheduler(core, session, output_timeout_s=.05)
    try:
        await scheduler.start()
        await until(lambda: scheduler.presentation_snapshot()["source_complete"])
        await core.close_stream()
        await asyncio.wait_for(core.reconnecting.wait(), 1)
        # Let any illicit post-EOF query finish. This is the actual stream loop,
        # not a direct call to the scheduler's source-invalidating helper.
        refresh = scheduler._source_refresh
        if refresh is not None:
            await asyncio.wait_for(asyncio.gather(refresh, return_exceptions=True), 1)
        scheduler._enqueue(SpeechRequest(
            conversation_id=CONVERSATION, correlation_id="corr-1", id="during-gap",
            text="Résultat disponible après raccord.", kind=SpeechKind.RESULT, source=source(),
        ))
        assert not scheduler.presentation_snapshot()["source_complete"]
        assert session.reservations == []
        core.reconnect_allowed.set()
        await until(lambda: bool(session.reservations))
        assert scheduler.presentation_snapshot()["source_complete"]
        assert [request.id for request in session.spoken] == ["during-gap"]
    finally:
        core.reconnect_allowed.set()
        session.release_provider.set()
        await asyncio.wait_for(scheduler.stop(), 2)


@pytest.mark.parametrize("late_events", [False, True], ids=["query_only", "source_and_speech"])
async def test_stop_owns_query_cancellation_and_ignores_its_late_success(late_events):
    class ClosingQueryCore(ConnectedCore):
        def __init__(self):
            super().__init__()
            self.query_started = asyncio.Event()
            self.query_cancelled = asyncio.Event()
            self.query_cleanup = asyncio.Event()

        async def speech_context(self, conversation_id):
            self.query_started.set()
            try:
                await self.query_cleanup.wait()
            except asyncio.CancelledError:
                self.query_cancelled.set()
                await self.query_cleanup.wait()
            return context(conversation_id)

    core, session = ClosingQueryCore(), ReservedSession()
    scheduler = build_scheduler(core, session, output_timeout_s=1)
    stop = None
    try:
        await scheduler.start()
        await asyncio.wait_for(core.query_started.wait(), 1)
        stop = asyncio.create_task(scheduler.stop())
        await asyncio.wait_for(core.query_cancelled.wait(), 1)
        assert not stop.done()
        if late_events:
            await core.publish(ProtocolEnvelope(
                message_type="brain.turn.accepted", conversation_id=CONVERSATION,
                payload={**context(CONVERSATION), "revision": 1, "correlation_id": "corr-1"},
            ))
            await core.publish(ProtocolEnvelope(
                message_type="brain.speech.requested", conversation_id=CONVERSATION,
                payload=SpeechRequest(
                    conversation_id=CONVERSATION, correlation_id="corr-1", id="after-stop",
                    text="Ne doit pas démarrer pendant le Stop.", kind=SpeechKind.RESULT, source=source(),
                ).to_payload(),
            ))
            # The slow query cleanup deliberately leaves time for already
            # subscribed work to run. Stop must have fenced that work first.
            await asyncio.sleep(.02)
            assert session.reservations == []
        core.query_cleanup.set()
        await asyncio.wait_for(asyncio.shield(stop), 1)
        assert not scheduler.running
        assert not scheduler.presentation_snapshot()["source_complete"]
        assert session.reservations == []
        assert not scheduler._source_queries
        assert not scheduler._presentation_expiries
        assert not scheduler._presentation_cancels
    finally:
        core.query_cleanup.set()
        session.release_provider.set()
        if stop is not None:
            await asyncio.wait_for(asyncio.gather(stop, return_exceptions=True), 2)
        await asyncio.wait_for(scheduler.stop(), 2)


@pytest.mark.parametrize("presence", ["provider_vad", "solo_owner_candidate"])
@pytest.mark.parametrize("already_written", [False, True], ids=["reserved", "device_written"])
async def test_false_presence_preserves_current_speech_without_replaying_written_output(presence, already_written):
    core, session = ConnectedCore(), ReservedSession()
    scheduler = build_scheduler(core, session, output_timeout_s=.05)
    audio = SoundDeviceRealtimeAudio()
    device = BufferedOutputStream()
    audio._output = device
    audio._loop = asyncio.get_running_loop()
    bridge = RealtimeConversationBridge(
        core=core, session=session, conversation_id=CONVERSATION, audio=audio,
        continuous=True, on_addressed=lambda: None, on_mute=lambda: None,
        on_user_speech=scheduler.note_user_speech,
        on_interruption=scheduler.note_interruption,
        on_output_event=scheduler.note_output_event,
        output_admission=scheduler.output_admission,
        barge_in_authority=BargeInAuthority.OWNER, owner_source=FakeOwnerSource(),
    )
    request = SpeechRequest(
        conversation_id=CONVERSATION, correlation_id="corr-1", id="current-answer",
        text="Le résultat actuel reste utile.", kind=SpeechKind.RESULT,
        source=source(),
    )
    pcm = b"\1\0" * 240
    try:
        await scheduler.start()
        await until(lambda: scheduler.presentation_snapshot()["source_complete"])
        scheduler._enqueue(request)
        await until(lambda: bool(session.reservations))
        output_id = session.reservations[0]
        token = scheduler.output_admission(output_id)
        assert token is not None

        async def deliver(seq):
            await bridge._play_audio(seq, ProtocolEnvelope(
                message_type="realtime.audio", payload={
                    "output_id": output_id, "speech_id": request.id,
                    "pcm_b64": base64.b64encode(pcm).decode(),
                },
            ))

        if already_written:
            session.release_provider.set()
            await deliver(1)
            assert device.writes == [pcm]
            assert token.state is OutputAdmissionState.WRITTEN

        # No admitted turn or authorized interruption occurs at either callback.
        if presence == "solo_owner_candidate":
            await bridge._hold_for_candidate(OwnerState.CANDIDATE)
            await bridge._hold_for_candidate(OwnerState.REJECTED)
        else:
            await bridge._note_user_speech(True)
            await bridge._note_user_speech(False)
        session.release_provider.set()

        await deliver(2)
        assert device.writes == [pcm] * (2 if already_written else 1)
        assert session.cancelled_outputs == []
        assert token.state is OutputAdmissionState.WRITTEN
        assert scheduler.presentation_snapshot()["current_source"] == source().to_payload()

        # A duplicate notification must not regenerate or replay an already
        # written response. Presence did not create a new intent or request.
        scheduler._enqueue(request)
        await asyncio.sleep(0)
        assert session.reservations == [output_id]
        assert scheduler.pending_count == 0
        assert core.turns == []
    finally:
        session.release_provider.set()
        device.consume()
        await asyncio.wait_for(scheduler.stop(), 2)
        assert await asyncio.wait_for(audio.close(), 2)
