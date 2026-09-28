"""Live end of speech by local evidence (Slice 02, `jarvis-voice-stale-speech-presentation`).

Complements the judge tests T1/T2 (`test_speech_scheduler_live_completion.py`) with
the contract points they do not pin:

- on real GPT-Live, back-to-back speeches SHARE one provider output id and one
  `realtime.output_started` (`openai_live_frontend.py` only resets `_output_id` on
  user input): the end must come from local quiescence, never from a fresh id;
- the release basis is traced (`voice.speech.completed`.completion_basis,
  `release_after_quiescence_ms`) and reaches the conversation-events journal;
- no audio within `live_first_audio_timeout_s` releases as `unconfirmed`, without
  blocking the chain and without the 30 s net;
- a barge-in during the grace wins; the net, when it fires on Live, is counted;
- the classic surface (`response_done`) keeps its behaviour: Live evidence is
  ignored there and no first-audio deadline applies.

Same production chain as T1/T2 (`RealtimeConversationBridge._consume` →
`on_output_event` → `SpeechScheduler`) on a `VirtualTimeLoop`.
"""

from __future__ import annotations

import asyncio

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, SpeechRequest, utc_now
from jarvis.domain.voice_playback import LIVE_OUTPUT_AUDIBLE, LIVE_OUTPUT_QUIESCENT
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import (
    OUTPUT_STALLED,
    OUTPUT_UNCONFIRMED,
    SPEECH_COMPLETED,
    SPEECH_DECIDED,
    SPEECH_INTERRUPTED,
    SpeechScheduler,
)
from jarvis.testlab.virtual.harness import ImmediateOutputStream
from tests.fakes.conversation_events import queued, recording_forwarder
from tests.fakes.live_output_surface import FRAME_MS, VOICE_FRAME_B64, LiveOutputSurface
from tests.fakes.speech_context import context, source
from tests.fakes.virtual_time_loop import VirtualWallClock, run_virtual
from tests.unit.test_v2_speech_scheduler import CONVERSATION, FakeCore, FakeVoiceSession, RecordingJournal, finish_speech

GRACE_S = SpeechScheduler.LIVE_COMPLETION_GRACE_MS / 1000
RELEASE_MARGIN_S = 0.25
BUDGET_S = 90.0


class SharedOutputLiveSurface(LiveOutputSurface):
    """GPT-Live as it really is: one provider output id for back-to-back speeches.

    Kept in this file on purpose: `tests/fakes/live_output_surface.py` belongs to
    the Slice 01 judge tests.
    """

    OUTPUT_ID = "live-output-shared"

    def __init__(self, plan) -> None:  # noqa: ANN001
        super().__init__(plan)
        self._announced = False

    async def _render(self, request: SpeechRequest) -> None:
        if not self._outputs:
            self._outputs.append(self.OUTPUT_ID)
        common = {"output_id": self.OUTPUT_ID, "response_id": None, "item_id": None, "speech_id": None}
        loop = asyncio.get_running_loop()
        for audio_ms, silence_ms in self.plan(request):
            for _ in range(max(1, audio_ms // FRAME_MS)):
                if self.playback_suppressed:
                    return
                if not self._announced:
                    self._announced = True
                    await self._provider.put(ProtocolEnvelope(message_type="realtime.output_started", payload=common))
                await self._provider.put(ProtocolEnvelope(message_type="realtime.audio",
                                                          payload={**common, "pcm_b64": VOICE_FRAME_B64}))
                self.frames.append((self.OUTPUT_ID, loop.time()))
                await asyncio.sleep(FRAME_MS / 1000)
            if silence_ms:
                await asyncio.sleep(silence_ms / 1000)


def said(text: str, speech_id: str) -> SpeechRequest:
    return SpeechRequest(CONVERSATION, text, kind=SpeechKind.RESULT, correlation_id="corr-1",
                         source=source("corr-1"), id=speech_id)


async def rig(surface, *, output_timeout_s=None, bridge=True, relayed=None):  # noqa: ANN001
    loop = asyncio.get_running_loop()
    journal = RecordingJournal()
    forwarder = recording_forwarder()
    scheduler = SpeechScheduler(core=FakeCore(), conversation_id=CONVERSATION, session=surface, journal=journal,
                                clock=VirtualWallClock(loop, utc_now()), reconnect_delay_s=0.0,
                                output_timeout_s=output_timeout_s, conversation_events=forwarder)
    scheduler.update_speech_context(context(CONVERSATION))
    consumer = None
    if bridge:
        audio = SoundDeviceRealtimeAudio()
        audio._output = ImmediateOutputStream()

        async def on_output_event(event):  # noqa: ANN001
            if relayed is not None:
                relayed.append(event.message_type)
            await scheduler.note_output_event(event)

        live_bridge = RealtimeConversationBridge(
            core=FakeCore(), session=surface, conversation_id=CONVERSATION, audio=audio,
            continuous=True, auto_turn=True, clock=loop.time,
            on_addressed=lambda: None, on_mute=lambda: None,
            on_output_event=on_output_event,
            on_interruption=scheduler.note_interruption,
            on_user_speech=scheduler.note_user_speech,
            output_admission=scheduler.output_admission,
            journal=journal,
        )
        scheduler.output_alive = live_bridge.output_pending
        consumer = asyncio.create_task(live_bridge._consume(surface.events()), name="test-live-bridge")
    await scheduler.start()
    return scheduler, journal, forwarder, consumer


async def close(surface, scheduler, consumer) -> None:  # noqa: ANN001
    await scheduler.stop()
    await surface.close()
    if consumer is not None:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)


async def until(predicate, *, budget_s: float = BUDGET_S) -> None:  # noqa: ANN001
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while not predicate() and loop.time() < deadline:
        await asyncio.sleep(0.01)


def data_of(journal, kind: str, speech_id: str) -> list[dict]:  # noqa: ANN001
    return [event["data"] for event in journal.of(kind) if event["data"].get("speech_id") == speech_id]


def decisions(journal, speech_id: str) -> list[tuple[str, str]]:  # noqa: ANN001
    return [(data["status"], data["reason"]) for data in data_of(journal, SPEECH_DECIDED, speech_id)]


def test_back_to_back_speeches_on_one_shared_provider_output_each_end_by_local_quiescence():
    async def scenario():
        surface = SharedOutputLiveSurface(lambda request: [(2000, 0)])
        scheduler, journal, forwarder, consumer = await rig(surface)
        try:
            scheduler._enqueue(said("Première phrase.", "speech-a"))
            scheduler._enqueue(said("Seconde phrase.", "speech-b"))
            await until(lambda: len(surface.spoken) == 2)
            await until(lambda: journal.count(SPEECH_COMPLETED) == 2)
            return list(surface.spoken_at), journal, queued(forwarder)
        finally:
            await close(surface, scheduler, consumer)

    spoken_at, journal, events = run_virtual(scenario())
    assert len(spoken_at) == 2
    gap = spoken_at[1] - spoken_at[0]
    # Never before the first speech's audio is over, never later than grace + margin.
    assert 2.0 <= gap < 2.0 + GRACE_S + RELEASE_MARGIN_S, gap
    assert ("completed", "output_completed") in decisions(journal, "speech-a")
    [completed] = data_of(journal, SPEECH_COMPLETED, "speech-a")
    assert completed["completion_basis"] == "local_quiescence"
    assert GRACE_S * 1000 <= completed["release_after_quiescence_ms"] < GRACE_S * 1000 + 50
    assert journal.of(SPEECH_INTERRUPTED) == [] and journal.of(OUTPUT_STALLED) == []
    assert journal.of(OUTPUT_UNCONFIRMED) == []
    # Visible in the conversation-events journal (timeline), not only in trace.jsonl.
    closes = [event for event in events if event.event_type is T.MOUTH_SPEECH_COMPLETED]
    assert [event.speech_id for event in closes] == ["speech-a", "speech-b"]
    attributes = dict(closes[0].attributes)
    assert attributes["completion_basis"] == "local_quiescence"
    assert attributes["release_after_quiescence_ms"] >= GRACE_S * 1000


def test_a_gap_shorter_than_the_grace_on_a_shared_output_restarts_the_grace():
    def plan(request: SpeechRequest):
        return [(1000, 150), (1000, 0)] if request.text.startswith("Première") else [(500, 0)]

    async def scenario():
        surface = SharedOutputLiveSurface(plan)
        scheduler, journal, _forwarder, consumer = await rig(surface)
        try:
            scheduler._enqueue(said("Première phrase, en deux rafales.", "speech-a"))
            scheduler._enqueue(said("Seconde phrase.", "speech-b"))
            await until(lambda: len(surface.spoken) == 2)
            first_frames = [at for _, at in surface.frames if at < surface.spoken_at[-1]]
            return list(surface.spoken_at), first_frames, journal
        finally:
            await close(surface, scheduler, consumer)

    spoken_at, first_frames, journal = run_virtual(scenario())
    audio_end = first_frames[-1] + FRAME_MS / 1000
    assert audio_end <= spoken_at[1] < audio_end + GRACE_S + RELEASE_MARGIN_S
    assert ("completed", "output_completed") in decisions(journal, "speech-a")


def test_a_live_speech_whose_audio_never_comes_is_released_unconfirmed_without_blocking_its_chain():
    def plan(request: SpeechRequest):
        return [] if request.text.startswith("Muette") else [(500, 0)]

    async def scenario():
        surface = SharedOutputLiveSurface(plan)
        scheduler, journal, forwarder, consumer = await rig(surface)
        try:
            scheduler._enqueue(said("Muette.", "speech-mute"))
            scheduler._enqueue(said("Audible.", "speech-next"))
            await until(lambda: len(surface.spoken) == 2)
            await until(lambda: journal.count(SPEECH_COMPLETED) == 2)
            return list(surface.spoken_at), journal, queued(forwarder), set(scheduler._blocked_chains)
        finally:
            await close(surface, scheduler, consumer)

    spoken_at, journal, events, blocked = run_virtual(scenario())
    timeout = SpeechScheduler.LIVE_FIRST_AUDIO_TIMEOUT_S
    assert timeout < SpeechScheduler.OUTPUT_TIMEOUT_S
    assert timeout - 0.01 <= spoken_at[1] - spoken_at[0] < timeout + RELEASE_MARGIN_S
    [unconfirmed] = journal.of(OUTPUT_UNCONFIRMED)
    assert unconfirmed["level"] == "warning"
    assert unconfirmed["data"]["code"] == "speech_output_unconfirmed"
    assert unconfirmed["data"]["speech_id"] == "speech-mute"
    [completed] = data_of(journal, SPEECH_COMPLETED, "speech-mute")
    assert (completed["completion_basis"], completed["status"]) == ("unconfirmed", "unconfirmed")
    assert ("completed", "output_unconfirmed") in decisions(journal, "speech-mute")
    assert data_of(journal, SPEECH_INTERRUPTED, "speech-mute") == []
    assert journal.of(OUTPUT_STALLED) == [] and blocked == set()
    [close_event] = [event for event in events
                     if event.event_type is T.MOUTH_SPEECH_COMPLETED and event.speech_id == "speech-mute"]
    assert dict(close_event.attributes)["completion_basis"] == "unconfirmed"
    [next_completed] = data_of(journal, SPEECH_COMPLETED, "speech-next")
    assert next_completed["completion_basis"] == "local_quiescence"


def test_a_barge_in_during_the_grace_wins_over_the_local_completion():
    async def scenario():
        surface = SharedOutputLiveSurface(lambda request: [(1000, 0)])
        scheduler, journal, forwarder, consumer = await rig(surface)
        try:
            scheduler._enqueue(said("Phrase coupée.", "speech-cut"))
            await until(lambda: len(surface.frames) >= 50)
            await asyncio.sleep(GRACE_S / 2)  # Audio over, grace running.
            scheduler.note_interruption(None)
            await until(lambda: journal.count(SPEECH_INTERRUPTED) == 1, budget_s=5.0)
            return journal, queued(forwarder)
        finally:
            await close(surface, scheduler, consumer)

    journal, events = run_virtual(scenario())
    assert len(data_of(journal, SPEECH_INTERRUPTED, "speech-cut")) == 1
    [close_event] = [event for event in events if event.event_type is T.MOUTH_SPEECH_INTERRUPTED]
    assert dict(close_event.attributes)["reason"] == "user_barge_in"
    assert data_of(journal, SPEECH_COMPLETED, "speech-cut") == []
    assert ("interrupted", "delivery_not_complete") in decisions(journal, "speech-cut")
    assert journal.of(OUTPUT_STALLED) == []


def test_the_safety_net_firing_on_a_live_speech_is_a_counted_warning():
    """Audio heard, no quiescence ever proven (device without drain): only the net ends it."""

    async def scenario():
        surface = SharedOutputLiveSurface(lambda request: [])
        scheduler, journal, _forwarder, _ = await rig(surface, output_timeout_s=2.0, bridge=False)
        try:
            scheduler._enqueue(said("Sans drain.", "speech-net"))
            await until(lambda: len(surface.spoken) == 1)
            await scheduler.note_output_event(ProtocolEnvelope(message_type=LIVE_OUTPUT_AUDIBLE,
                                                               payload={"output_id": "live-output-shared"}))
            await until(lambda: journal.count(SPEECH_INTERRUPTED) == 1, budget_s=10.0)
            return journal, scheduler.output_stall_count
        finally:
            await close(surface, scheduler, None)

    journal, count = run_virtual(scenario())
    [stalled] = journal.of(OUTPUT_STALLED)
    assert stalled["level"] == "warning"
    data = stalled["data"]
    assert (data["code"], data["without_output_final"], data["audio_heard"], data["stall_count"]) == (
        "speech_output_stalled", True, True, 1)
    assert count == 1
    assert journal.of(OUTPUT_UNCONFIRMED) == []


def test_the_bridge_relays_live_audibility_and_quiescence_to_the_mouth():
    relayed: list[str] = []

    async def scenario():
        surface = SharedOutputLiveSurface(lambda request: [(200, 0)])
        scheduler, journal, _forwarder, consumer = await rig(surface, relayed=relayed)
        try:
            scheduler._enqueue(said("Courte.", "speech-short"))
            await until(lambda: journal.count(SPEECH_COMPLETED) == 1, budget_s=5.0)
        finally:
            await close(surface, scheduler, consumer)

    run_virtual(scenario())
    live = [kind for kind in relayed if kind in (LIVE_OUTPUT_AUDIBLE, LIVE_OUTPUT_QUIESCENT)]
    assert live and live[0] == LIVE_OUTPUT_AUDIBLE and live[-1] == LIVE_OUTPUT_QUIESCENT
    # Never two audibility notices without a quiescence between them (once per burst).
    assert all(not (a == b == LIVE_OUTPUT_AUDIBLE) for a, b in zip(live, live[1:]))


def test_a_classic_surface_ignores_live_evidence_and_keeps_its_response_done_end():
    """Parity: `response_done` stays the only end; no grace, no first-audio deadline."""

    async def scenario():
        session = FakeVoiceSession()
        scheduler, journal, forwarder, _ = await rig(session, output_timeout_s=30.0, bridge=False)
        scheduler.live_first_audio_timeout_s = 0.2
        try:
            scheduler._enqueue(said("Phrase classique.", "speech-classic"))
            await until(lambda: len(session.spoken) == 1, budget_s=5.0)
            for kind in (LIVE_OUTPUT_AUDIBLE, LIVE_OUTPUT_QUIESCENT):
                await scheduler.note_output_event(ProtocolEnvelope(message_type=kind, payload={"output_id": None}))
            await asyncio.sleep(SpeechScheduler.LIVE_FIRST_AUDIO_TIMEOUT_S + 1.0)
            still_speaking = scheduler._active is not None and journal.count(SPEECH_COMPLETED) == 0
            await finish_speech(scheduler, session)
            await until(lambda: journal.count(SPEECH_COMPLETED) == 1, budget_s=5.0)
            return still_speaking, journal, queued(forwarder)
        finally:
            await close(session, scheduler, None)

    still_speaking, journal, events = run_virtual(scenario())
    assert still_speaking, "a classic speech ended on Live evidence or on the first-audio deadline"
    [completed] = data_of(journal, SPEECH_COMPLETED, "speech-classic")
    assert completed["completion_basis"] == "provider_response_done"
    assert "release_after_quiescence_ms" not in completed and "status" not in completed
    assert journal.of(OUTPUT_UNCONFIRMED) == [] and journal.of(OUTPUT_STALLED) == []
    assert ("completed", "output_completed") in decisions(journal, "speech-classic")
    [close_event] = [event for event in events if event.event_type is T.MOUTH_SPEECH_COMPLETED]
    assert dict(close_event.attributes)["completion_basis"] == "provider_response_done"
