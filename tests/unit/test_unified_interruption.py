"""Interruption unifiée (Slice 05) : l'utilisateur reprend la main, rien n'est tué.

Décision du 28/09/2026 (`tasks/jarvis-voice-stale-speech-presentation`,
« Interruption unifiée ») : toute prise de parole de l'utilisateur pendant que
Jarvis parle ou réfléchit gèle la file (`floor_taken`, non éligible) jusqu'à la
décision d'adressage du nouveau tour :

- tour adressé / incertain promu (intention nouvelle de Core) ⇒ règles de la
  Slice 04 (`held_for_brain`) ;
- bruit, non adressé, tour refusé ⇒ la file reprend telle quelle ;
- aucune décision ⇒ dégel tracé après `floor_taken_max_s` (compté depuis la
  fin de la parole de l'utilisateur).

Les juges de la Slice 01 (T7, T7b, T7c) sont dans
`test_speech_presentation_revalidation.py` ; ce fichier couvre le reste du
contrat : chemin réflexion, adressé, filet, VAD bloqué, refus, idempotence,
visibilité, ordre du bridge. Temps virtuel, pas de réseau.
"""

from __future__ import annotations

import asyncio

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, SpeechRequest, utc_now
from jarvis.domain.voice_playback import FLOOR_DECIDED, FLOOR_TAKEN
from jarvis.runtime.realtime_audio import RealtimeConversationBridge
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.testlab.virtual.harness import FakeAudio, FakeRealtimeSession
from tests.fakes.conversation_events import assert_each_trace_ref_joins_one_line, queued, recording_forwarder
from tests.fakes.speech_context import context, source
from tests.fakes.virtual_time_loop import VirtualWallClock, run_virtual
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION,
    FakeCore,
    FakeVoiceSession,
    RecordingJournal,
    finish_speech,
)

PLAYING = "Voici une longue réponse…"
QUEUED = "Et une seconde chose."


class CancellingCore(FakeCore):
    """Core qui accepte l'abandon du tour en réflexion et le compte."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled_turns: list[str] = []

    async def cancel_brain_turn(self, conversation_id: str, *, correlation_id: str):
        del conversation_id
        self.cancelled_turns.append(correlation_id)
        return {"cancelled": True}


def say(text: str, *, correlation: str = "corr-1", kind: SpeechKind = SpeechKind.RESULT, epoch: int = 1) -> SpeechRequest:
    return SpeechRequest(CONVERSATION, text, kind=kind, correlation_id=correlation,
                         source=source(correlation, epoch=epoch))


def scheduler_for(session, journal, *, core=None, forwarder=None, **options) -> SpeechScheduler:
    loop = asyncio.get_running_loop()
    scheduler = SpeechScheduler(core=core or FakeCore(), conversation_id=CONVERSATION, session=session,
                                journal=journal, clock=VirtualWallClock(loop, utc_now()), reconnect_delay_s=0.0,
                                output_timeout_s=None, conversation_events=forwarder, **options)
    scheduler.update_speech_context(context(CONVERSATION))
    return scheduler


async def cut_while_speaking(scheduler: SpeechScheduler, session: FakeVoiceSession) -> None:
    """PLAYING part, QUEUED attend ; l'utilisateur coupe (séquence du bridge) puis se tait."""
    scheduler._enqueue(say(PLAYING))
    scheduler._enqueue(say(QUEUED))
    while len(session.spoken) < 1:
        await asyncio.sleep(0.01)
    scheduler.note_user_speech(True)
    scheduler.note_interruption(None)
    await finish_speech(scheduler, session, status="cancelled")
    await asyncio.sleep(0.5)
    scheduler.note_user_speech(False)


def reasons(journal: RecordingJournal) -> list[str]:
    return [entry["data"]["reason"] for entry in journal.of("voice.floor_released")]


# ------------------------------------------------------------- chemin parole


def test_noise_after_a_cut_resumes_the_queue_as_it_was():
    async def scenario():
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        await scheduler.start()
        try:
            await cut_while_speaking(scheduler, session)
            await asyncio.sleep(1.0)
            frozen = list(session.texts())
            scheduler.note_floor_decided("noise")
            await asyncio.sleep(0.2)
            return frozen, session.texts(), journal
        finally:
            await scheduler.stop()

    frozen, spoken, journal = run_virtual(scenario())
    assert frozen == [PLAYING]
    assert spoken == [PLAYING, QUEUED]
    [taken] = journal.of("voice.floor_taken")
    assert taken["data"]["while"] == "speaking"
    assert reasons(journal) == ["noise"]


def test_an_addressed_turn_hands_the_old_answer_to_the_brain_instead_of_saying_it():
    """Tour adressé ⇒ intention nouvelle de Core ⇒ règles de la Slice 04 : QUEUED retenue, jamais dite."""

    async def scenario():
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        await scheduler.start()
        try:
            await cut_while_speaking(scheduler, session)
            scheduler.note_floor_decided("addressed", correlation_id="corr-2")
            await asyncio.sleep(1.0)
            assert scheduler._floor is not None, "une supposition de surface a levé le gel avant Core"
            await scheduler.handle_core_event(ProtocolEnvelope(
                message_type="brain.turn.accepted",
                payload={**context(CONVERSATION, "corr-2", epoch=2), "revision": 2}, conversation_id=CONVERSATION))
            await asyncio.sleep(1.0)
            fresh = say("Il fait beau.", correlation="corr-2", epoch=2)
            scheduler._enqueue(fresh)
            await asyncio.sleep(0.5)
            held = next(item for item in scheduler.presentation_snapshot()["candidates"] if item["speech_id"].startswith(
                next(key for key, value in scheduler._candidates.items() if value.request.text == QUEUED)))
            return session.texts(), held, journal
        finally:
            await scheduler.stop()

    spoken, held, journal = run_virtual(scenario())
    assert spoken == [PLAYING, "Il fait beau."]
    assert (held["status"], held["reason"]) == ("deferred", "held_for_brain")
    [released] = journal.of("voice.floor_released")
    assert released["data"]["reason"] == "addressed" and released["data"]["decision"] == "addressed"
    assert released["data"]["decided_correlation_id"] == "corr-2"


def test_an_uncertain_turn_keeps_the_queue_frozen_until_the_brain_promotes_it():
    async def scenario():
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        await scheduler.start()
        try:
            await cut_while_speaking(scheduler, session)
            scheduler.note_floor_decided("uncertain", correlation_id="corr-2")
            await asyncio.sleep(2.0)
            frozen = list(session.texts())
            # Promotion : Core publie l'intention du tour incertain.
            await scheduler.handle_core_event(ProtocolEnvelope(
                message_type="brain.intent.revised",
                payload={**context(CONVERSATION, "corr-2", epoch=2), "revision": 2}, conversation_id=CONVERSATION))
            await asyncio.sleep(0.5)
            return frozen, session.texts(), journal
        finally:
            await scheduler.stop()

    frozen, spoken, journal = run_virtual(scenario())
    assert frozen == [PLAYING] and spoken == [PLAYING]
    assert reasons(journal) == ["addressed"]


def test_a_turn_core_refuses_resumes_the_queue():
    async def scenario():
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        await scheduler.start()
        try:
            await cut_while_speaking(scheduler, session)
            scheduler.note_floor_decided("rejected")
            await asyncio.sleep(0.2)
            return session.texts(), journal
        finally:
            await scheduler.stop()

    spoken, journal = run_virtual(scenario())
    assert spoken == [PLAYING, QUEUED]
    assert reasons(journal) == ["rejected"]


# ---------------------------------------------------------------- filet


def test_without_any_decision_the_freeze_ends_after_its_bound_counted_from_the_end_of_user_speech():
    async def scenario():
        loop = asyncio.get_running_loop()
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        await scheduler.start()
        try:
            await cut_while_speaking(scheduler, session)
            quiet_at = loop.time()
            await asyncio.sleep(scheduler.floor_taken_max_s - 0.1)
            before = list(session.texts())
            while len(session.spoken) < 2:
                await asyncio.sleep(0.01)
            return before, loop.time() - quiet_at, journal
        finally:
            await scheduler.stop()

    before, resumed_after, journal = run_virtual(scenario())
    assert before == [PLAYING]
    assert SpeechScheduler.FLOOR_TAKEN_MAX_S <= resumed_after < SpeechScheduler.FLOOR_TAKEN_MAX_S + 0.25
    [released] = journal.of("voice.floor_released")
    assert released["level"] == "warning" and released["data"]["code"] == "floor_taken_timeout"
    assert released["data"]["reason"] == "timeout"


def test_a_long_sentence_does_not_consume_the_bound():
    """L'utilisateur parle 6 s (> filet) : la file reste gelée tant qu'il parle, puis le filet repart de sa fin."""

    async def scenario():
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        await scheduler.start()
        try:
            scheduler._enqueue(say(PLAYING))
            scheduler._enqueue(say(QUEUED))
            while len(session.spoken) < 1:
                await asyncio.sleep(0.01)
            scheduler.note_user_speech(True)
            scheduler.note_interruption(None)
            await finish_speech(scheduler, session, status="cancelled")
            await asyncio.sleep(6.0)
            scheduler.note_user_speech(False)
            await asyncio.sleep(scheduler.floor_taken_max_s - 0.5)
            return session.texts(), scheduler._floor is not None
        finally:
            await scheduler.stop()

    spoken, still_frozen = run_virtual(scenario())
    assert spoken == [PLAYING] and still_frozen


def test_a_vad_stuck_on_speech_does_not_keep_the_floor_forever():
    """Le gel ne s'ajoute pas au bâillon d'un VAD bloqué : il tombe à `user_speech_hold_s` + filet.

    (Ce qui reste bloqué ensuite est la garde « l'utilisateur parle » de la
    sélection, antérieure à cette Slice et hors de son contrat.)
    """

    async def scenario():
        loop = asyncio.get_running_loop()
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        await scheduler.start()
        try:
            scheduler._enqueue(say(PLAYING))
            scheduler._enqueue(say(QUEUED))
            while len(session.spoken) < 1:
                await asyncio.sleep(0.01)
            scheduler.note_user_speech(True)
            cut_at = loop.time()
            scheduler.note_interruption(None)
            await finish_speech(scheduler, session, status="cancelled")
            while scheduler._floor is not None:
                await asyncio.sleep(0.05)
            return loop.time() - cut_at, scheduler, journal
        finally:
            await scheduler.stop()

    elapsed, scheduler, journal = run_virtual(scenario())
    bound = scheduler.user_speech_hold_s + scheduler.floor_taken_max_s
    assert bound <= elapsed < bound + 0.25
    [released] = journal.of("voice.floor_released")
    assert released["data"]["reason"] == "timeout" and released["data"]["user_speaking"] is True


# ------------------------------------------------------------ chemin réflexion


def test_a_cut_while_thinking_abandons_that_turn_only_and_freezes_the_rest():
    """Réflexion : le tour coupé est purgé et Core prié de l'abandonner ; le reste de la file est gelé."""

    async def scenario():
        core, session, journal = CancellingCore(), FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal, core=core)
        await scheduler.start()
        try:
            await scheduler.note_output_event(ProtocolEnvelope(message_type="realtime.output_started",
                                                               payload={"output_id": "out-surface"}))
            earlier = say("Le rapport est prêt.", correlation="corr-0")
            thinking = say("Je réfléchis encore.", correlation="corr-1")
            scheduler._enqueue(earlier)
            scheduler._enqueue(thinking)
            await scheduler.note_output_event(ProtocolEnvelope(FLOOR_TAKEN, {"while": "thinking",
                                                                             "correlation_id": "corr-1"}))
            await scheduler.abandon_turn("corr-1")
            await scheduler.note_output_event(ProtocolEnvelope(message_type="realtime.response_done",
                                                               payload={"output_id": "out-surface", "status": "completed"}))
            await asyncio.sleep(1.0)
            frozen = list(session.texts())
            await scheduler.note_output_event(ProtocolEnvelope(FLOOR_DECIDED, {"decision": "noise"}))
            await asyncio.sleep(0.2)
            return frozen, session.texts(), core.cancelled_turns, journal
        finally:
            await scheduler.stop()

    frozen, spoken, cancelled, journal = run_virtual(scenario())
    assert frozen == []
    assert spoken == ["Le rapport est prêt."]
    assert cancelled == ["corr-1"]
    [taken] = journal.of("voice.floor_taken")
    assert (taken["data"]["while"], taken["data"]["correlation_id"]) == ("thinking", "corr-1")
    assert reasons(journal) == ["noise"]


# ------------------------------------------------------- idempotence, erreurs


def test_the_floor_is_taken_once_per_cut_and_decisions_without_a_freeze_do_nothing():
    async def scenario():
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        scheduler.note_floor_decided("noise")
        scheduler.note_floor_taken("speaking")
        scheduler.note_floor_taken("thinking")
        scheduler.note_floor_decided("not-a-decision")
        still = scheduler._floor is not None
        scheduler.note_floor_decided("unaddressed")
        await scheduler.stop()
        return still, journal

    still, journal = run_virtual(scenario())
    assert still
    assert [entry["data"]["while"] for entry in journal.of("voice.floor_taken")] == ["speaking"]
    assert reasons(journal) == ["unaddressed"]
    assert [entry["data"]["reason"] for entry in journal.of("voice.speech.ignored")] == ["invalid_floor_decision"]


def test_a_frozen_error_is_not_reported_as_withheld_for_a_stale_intent():
    async def scenario():
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        scheduler.note_floor_taken("speaking")
        scheduler._enqueue(say("Le rapport a échoué.", kind=SpeechKind.ERROR))
        decided = [entry["data"]["reason"] for entry in journal.of("voice.speech.presentation_decided")]
        await scheduler.stop()
        return decided, journal

    decided, journal = run_virtual(scenario())
    assert "floor_taken" in decided
    assert journal.of("voice.speech.error_withheld") == []


# ------------------------------------------------------------- visibilité


def test_taking_and_releasing_the_floor_are_conversation_events_joined_to_their_journal_lines():
    async def scenario():
        session, journal, forwarder = FakeVoiceSession(), RecordingJournal(), recording_forwarder()
        scheduler = scheduler_for(session, journal, forwarder=forwarder)
        scheduler.note_floor_taken("thinking", correlation_id="corr-1")
        await asyncio.sleep(0.3)
        scheduler.note_floor_decided("noise")
        await scheduler.stop()
        return [event for event in queued(forwarder)
                if event.event_type in (T.MOUTH_FLOOR_TAKEN, T.MOUTH_FLOOR_RELEASED)], journal

    events, journal = run_virtual(scenario())
    assert [event.event_type for event in events] == [T.MOUTH_FLOOR_TAKEN, T.MOUTH_FLOOR_RELEASED]
    taken, released = (dict(event.attributes) for event in events)
    assert taken == {"while": "thinking"}
    assert released["while"] == "thinking" and released["reason"] == "noise" and released["duration_ms"] >= 300
    assert all(event.content is None for event in events)
    assert_each_trace_ref_joins_one_line(events, journal.events)


# ---------------------------------------------------------------- bridge


def test_the_bridge_takes_the_floor_before_it_awaits_the_device_stop():
    """Rien d'ancien ne peut partir pendant l'arrêt du périphérique : le gel précède la première attente."""

    async def scenario():
        session, journal = FakeRealtimeSession(), RecordingJournal()
        scheduler = scheduler_for(session, journal)
        audio = FakeAudio()
        seen: list[object] = []
        original = audio.stop_output

        async def stop_output():
            seen.append(None if scheduler._floor is None else scheduler._floor.while_)
            return await original()

        audio.stop_output = stop_output
        bridge = RealtimeConversationBridge(
            core=FakeCore(), session=session, conversation_id=CONVERSATION, audio=audio,
            continuous=True, auto_turn=True, clock=asyncio.get_running_loop().time,
            on_addressed=lambda: None, on_mute=lambda: None,
            on_output_event=scheduler.note_output_event, on_interruption=scheduler.note_interruption,
            on_turn_abandoned=scheduler.abandon_turn, journal=journal)
        # Le cerveau tient la main sans parler : chemin réflexion.
        bridge._brain_floor_correlation = "corr-1"
        bridge._brain_floor_at = bridge._clock()
        await bridge._barge_in()
        await scheduler.stop()
        return seen, journal

    seen, journal = run_virtual(scenario())
    assert seen == ["thinking"]
    [taken] = journal.of("voice.floor_taken")
    assert taken["data"]["correlation_id"] == "corr-1"
    assert journal.count("voice.brain_turn_abandoned") == 1


class RefusingCore(FakeCore):
    async def submit_brain_turn(self, conversation_id: str, **kwargs):  # noqa: ANN001
        del conversation_id, kwargs
        raise ConnectionError("core unreachable")


def test_the_bridge_tells_the_mouth_what_each_classified_segment_turned_out_to_be():
    """Bruit ⇒ `noise` ; tour adressé accepté ⇒ `addressed` (corrélation du tour) ; refusé ⇒ `rejected`."""

    async def scenario():
        decisions: list[tuple[str, object]] = []

        async def on_output_event(event: ProtocolEnvelope) -> None:
            if event.message_type == FLOOR_DECIDED:
                decisions.append((event.payload["decision"], event.payload["correlation_id"]))

        def bridge(core) -> RealtimeConversationBridge:
            return RealtimeConversationBridge(
                core=core, session=FakeRealtimeSession(), conversation_id=CONVERSATION, audio=FakeAudio(),
                continuous=True, auto_turn=True, clock=asyncio.get_running_loop().time,
                on_addressed=lambda: None, on_mute=lambda: None, on_output_event=on_output_event,
                journal=RecordingJournal())

        accepting, refusing = bridge(FakeCore()), bridge(RefusingCore())
        await accepting._handle_admitted_transcript(ProtocolEnvelope("realtime.transcript", {"text": "hum"}))
        await accepting._handle_admitted_transcript(ProtocolEnvelope(
            "realtime.transcript", {"text": "Jarvis, quelle heure est-il ?", "item_id": "item-1"}))
        correlation = accepting._last_correlation_id
        await refusing._handle_admitted_transcript(ProtocolEnvelope(
            "realtime.transcript", {"text": "Jarvis, quelle heure est-il ?", "item_id": "item-2"}))
        return decisions, correlation

    decisions, correlation = run_virtual(scenario())
    assert correlation is not None
    assert decisions == [("noise", None), ("addressed", correlation), ("rejected", None)]
