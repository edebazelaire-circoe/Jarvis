"""Task08 scheduling probes; clocks and source authority are synthetic."""
import asyncio
from dataclasses import replace

import pytest

from jarvis.domain.speech_presentation import SpeechDependency, semantic_text_spans
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, SpeechRequest
from tests.fakes.speech_context import context, source
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeClock, FakeCore, FakeVoiceSession, RecordingJournal, build_scheduler,
    busy_surface, finish_speech, release_surface, wait_for,
)


def request(text="Result", *, correlation="corr-1", epoch=1, kind=SpeechKind.RESULT, **kwargs):
    return SpeechRequest(CONVERSATION, text, correlation_id=correlation, source=source(correlation, epoch=epoch), kind=kind, **kwargs)


@pytest.mark.parametrize("age", [29.1, 35.9])
async def test_old_progress_is_dropped_by_a_new_intent_but_its_result_is_still_said(age):
    """La progression décrivait un instant passé : sa vérité s'est évaporée.
    Le résultat, lui, reste vrai — il est reporté sur l'intention courante et
    dit, au lieu d'attendre une intention qui ne reviendra jamais."""
    clock = FakeClock()
    selected = build_scheduler(FakeCore(), FakeVoiceSession(), clock=clock)
    progress = request("Old preamble", kind=SpeechKind.PROGRESS, created_at=clock.now())
    selected._enqueue(progress)
    clock.advance(age)
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    result = request("Old result still available", outcome_id="durable-outcome", created_at=clock.now())
    selected._enqueue(result)
    snapshot = selected.presentation_snapshot()
    assert [(item["status"], item["reason"]) for item in snapshot["candidates"]] == [("superseded", "stale_source"), ("eligible", "carried_over")]
    assert snapshot["candidates"][1]["outcome_id"] == "durable-outcome"
    assert selected._pop_next() == result


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
        # Une intention neuve n'ampute plus une réponse à moitié dite : la
        # fin de la phrase est reportée, pas enterrée.
        await wait_for(lambda: len(session.spoken) == 3)
        assert [item.text for item in session.spoken] == [text[span.start:span.end] for span in chain.chunks]
        assert len({item.id for item in session.spoken}) == 3
        assert all(item.id != chain.id and item.outcome_id == "outcome" for item in session.spoken)
        assert selected.presentation_snapshot()["candidates"][2]["status"] == "started"
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
    """L'autorité vient de l'intention, pas de l'heure de rédaction.

    Une réponse reportée est dite — sauf quand l'intention courante occupe
    déjà le même emplacement de parole (même `supersedes_key`, même travail) :
    elle serait alors l'ancienne version de ce qui vient d'être dit. Jamais
    l'inverse : le retardataire n'efface pas le travail courant.
    """
    journal = RecordingJournal()
    selected = build_scheduler(FakeCore(), FakeVoiceSession(), journal=journal)
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    current = replace(request("Current", correlation="corr-2", epoch=2),
                      source=source("corr-2", epoch=2, work_id="reused"), work_id="reused", supersedes_key="reused")
    selected._enqueue(current)
    old = replace(request("Late old", kind=SpeechKind.RESULT), source=source("corr-1", work_id="reused"),
                  work_id="reused", supersedes_key="reused")
    selected._enqueue(old)
    assert selected._pop_next() == current
    assert old.id not in selected._deferred
    # Retirée, donc soldée à voix haute dans la trace : jamais un silence nu.
    [abandoned] = journal.of("voice.speech.abandoned")
    assert abandoned["level"] == "warning" and abandoned["data"]["text"] == "Late old"


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


async def test_a_spontaneous_relay_is_only_speakable_once_it_carries_the_current_intent():
    """Le canal des relais spontanés était muet de bout en bout.

    `BrainOrchestrator.announce_notice` — la seule voie par laquelle le cerveau
    annonce la fin d'un sous-agent sans qu'aucun tour l'attende — publiait sa
    parole sous une corrélation neuve, à laquelle personne n'avait alloué de
    source. Ici, on voit ce que l'ordonnanceur en faisait : rien, pour
    toujours. Et ce que corrige l'emprunt de l'intention courante.
    """
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    selected.update_speech_context(context(CONVERSATION, "corr-7", epoch=7))

    orphan = SpeechRequest(CONVERSATION, "Le sous-agent a fini.", correlation_id="brain-notice:x", kind=SpeechKind.RESULT)
    selected._enqueue(orphan)
    assert selected._pop_next() is None
    assert [item["reason"] for item in selected.presentation_snapshot()["candidates"]] == ["unknown_source"]

    relay = request("Le sous-agent a fini.", correlation="corr-7", epoch=7)
    selected._enqueue(relay)
    assert selected._pop_next() == relay


async def test_the_error_withheld_on_16_09_is_now_spoken_instead_of_being_buried():
    """Le 16/09/2026 à 07:38:57, l'erreur du handover est restée
    `deferred`/`stale_source` et personne n'a rien entendu. Le commentaire du
    code promettait que « le cerveau la redira sur l'intention courante » ; le
    19/09 a montré que la promesse n'était pas tenue. Une panne rédigée est
    désormais dite, sur l'intention courante."""
    journal = RecordingJournal()
    selected = build_scheduler(FakeCore(), FakeVoiceSession(), journal=journal)
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))

    stale = request("La console a pris la main.", correlation="corr-1", epoch=1, kind=SpeechKind.ERROR)
    selected._enqueue(stale)

    assert selected._pop_next() == stale
    assert journal.of("voice.speech.error_withheld") == []
    assert journal.of("voice.speech.abandoned") == []


async def test_a_durable_answer_of_a_past_intent_is_carried_over_and_spoken():
    """L'utilisateur pose une question, reparle avant la réponse : la réponse à
    la première question a encore du sens et doit être dite.

    Décision utilisateur du 19/09/2026 : « une réponse sans retard faut qu'elle
    soit dite si c'est cohérent avec le contexte ». Une intention passée ne
    revient jamais ; la différer était donc l'enterrer. Seul le cerveau retire
    une parole durable, en désignant son travail (`BrainEventKind.SUPERSEDED`).
    """
    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))

    answer = request("Ton écran montre trois fenêtres.", correlation="corr-1", epoch=1, kind=SpeechKind.RESULT)
    selected._enqueue(answer)

    assert [item["reason"] for item in selected.presentation_snapshot()["candidates"]] == ["carried_over"]
    assert selected._pop_next() == answer


async def test_a_durable_answer_the_brain_retires_is_settled_out_loud_in_the_trace():
    """L'autre moitié : quand elle n'a plus de sens, elle est soldée
    explicitement — jamais laissée en suspens dans un silence d'`info`."""
    journal = RecordingJournal()
    selected = build_scheduler(FakeCore(), FakeVoiceSession(), journal=journal)
    answer = replace(request("Ton écran montre trois fenêtres."), source=source("corr-1", work_id="work-a"))
    selected._enqueue(answer)
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2,
                                           invalid=(SpeechDependency("work-a", "corr-1"),)))

    assert selected._pop_next() is None
    [abandoned] = journal.of("voice.speech.abandoned")
    assert abandoned["level"] == "warning"
    assert abandoned["data"]["reason"] == "dependency_revoked"
