"""Independent controlled Task12D regressions; no provider or device calls."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from jarvis.domain.v2 import SpeechRequest
from jarvis.ports.v2 import supports_reflex
from jarvis.domain.voice_events import VoiceDelegationRequested
from jarvis.domain.voice_frontend import VoiceCorrelation, VoiceOperationKind, VoiceOperationStatus
from jarvis.runtime.live_delegation import LiveDelegationController
from jarvis.runtime.live_frontend_session import (
    MAX_APPEND_CHUNK_UTF8, LiveFrontendSession, append_segments,
)
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from tests.integration.test_live_duplex_session import SPECULATIVE, LiveWire
from tests.fakes.voice_frontend import FakeVoiceFrontend
from tests.unit.test_live_delegation import Core, Session, ready, wait_closed


def trigger(frontend, identity="delegation"):
    return frontend.event(VoiceDelegationRequested(1), correlation=VoiceCorrelation(
        "live-session", provider_delegation_id=identity))


async def test_local_correction_during_status_request_prevents_stale_result_append():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(())
    session = Session(frontend, core)
    session.input_observation_revision = 1
    calls = 0

    async def status(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            # Local transcript is newer than the server snapshot in flight.
            session.input_observation_revision += 1
            return {"status": "completed", "fresh": True, "result": {"text": "obsolete answer"}}
        return {"status": "completed", "fresh": False, "result": {"text": "obsolete answer"}}

    core.back_brain_task_status = status
    controller = LiveDelegationController(session, poll_interval_s=.001, brain_orchestration=False)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    assert not any(kind is VoiceOperationKind.SPOKEN_RESULT for kind, _, _ in frontend.calls)
    assert calls == 2


async def test_stale_progress_is_not_injected_as_quiet_context():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(({"status": "running", "fresh": False, "progress": {"public_summary": "obsolete fact"}},
                 {"status": "completed", "fresh": False, "result": {"text": "obsolete answer"}}))
    controller = LiveDelegationController(Session(frontend, core), poll_interval_s=.001, brain_orchestration=False)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    assert not any(kind is VoiceOperationKind.QUIET_CONTEXT for kind, _, _ in frontend.calls)


@pytest.mark.parametrize("answer", ["x" * 501, "exact answer"])
async def test_rejected_or_unconfirmed_append_never_logs_presented_or_retries(answer):
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    attempts = []

    async def unknown(update, *, operation):
        attempts.append(update.text)
        return SimpleNamespace(status=None)

    frontend.append_spoken_result = unknown
    core = Core(({"status": "completed", "fresh": True, "result": {"text": answer}},))
    session = Session(frontend, core)
    statuses = []
    session.journal = SimpleNamespace(emit=lambda *_, data, **__: statuses.append(data["status"]))
    controller = LiveDelegationController(session, poll_interval_s=.001, brain_orchestration=False)
    event = trigger(frontend)
    assert controller.offer(event)
    await wait_closed(controller)
    assert controller.offer(event)
    assert "presented" not in statuses
    assert len(attempts) == (0 if len(answer) > 500 else 1)


async def test_retention_saturation_does_not_rearm_old_delegation():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(({"status": "completed", "fresh": False},) * 140)
    controller = LiveDelegationController(Session(frontend, core), poll_interval_s=.001, brain_orchestration=False)
    for index in range(129):
        controller.offer(trigger(frontend, f"delegation-{index}"))
        await wait_closed(controller)
    submitted = sum(call[0] == "submit" for call in core.calls)
    assert controller.offer(trigger(frontend, "delegation-0"))
    await wait_closed(controller)
    assert sum(call[0] == "submit" for call in core.calls) == submitted
    assert len(controller._seen) <= 128


async def test_canonical_flush_blocks_submission_but_not_reader_or_microphone():
    gate, blocked = asyncio.Event(), asyncio.Event()
    batches, submissions = [], []

    class HeldCore:
        async def bind_voice_session(self, *_):
            return {"result": {"disposition": "applied"}}

        async def submit_voice_observations(self, _conversation, _session, events):
            blocked.set()
            await gate.wait()
            batches.extend(events)
            return {"results": [{"disposition": "applied"} for _ in events]}

        async def submit_back_brain_task(self, *args, **kwargs):
            submissions.append((args, kwargs))
            return SimpleNamespace(status="unavailable", job_id=None)

    wire = LiveWire()
    session = await LiveFrontendSession.connect(api_key="unused", voice="marin", context={},
        connector=lambda: asyncio.sleep(0, result=wire), architecture_config=SPECULATIVE)
    await session.attach_core(HeldCore(), "conversation")
    observed = []

    async def consume():
        async for event in session.events():
            observed.append(event)

    reader = asyncio.create_task(consume())
    try:
        wire.push({"type": "session.input_transcript.delta", "delta": "untrusted provisional",
                   "start_ms": 0, "end_ms": 10})
        wire.push({"type": "session.delegation.created", "offset_ms": 10,
                   "delegation": {"id": "d", "type": "delegation", "target": "client"}})
        await asyncio.wait_for(blocked.wait(), 1)
        wire.push({"type": "session.output_audio.delta", "delta": base64.b64encode(b"\1\0" * 20).decode()})
        async with asyncio.timeout(1):
            while not any(event.message_type == "realtime.audio" for event in observed):
                await asyncio.sleep(0)
        await asyncio.wait_for(session.send_audio(b"\0\0" * 20), 1)
        assert not submissions
        assert any(event["type"] == "session.input_audio.append" for event in wire.sent)
        gate.set()
        async with asyncio.timeout(1):
            while not submissions:
                await asyncio.sleep(0)
        assert session.input_observation_revision == 1
        assert "untrusted provisional" in str(batches)
        assert not any("pcm" in str(event).lower() for event in batches)
        assert not any(event["type"].startswith(("response.", "conversation.", "input_audio_buffer.")) for event in wire.sent)
    finally:
        gate.set()
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_controller_journal_failure_does_not_change_result_injection():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(({"status": "completed", "fresh": True, "result": {"text": "exact answer"}},))
    session = Session(frontend, core)

    def broken(*_, **__):
        raise OSError("journal unavailable")

    session.journal = SimpleNamespace(emit=broken)
    controller = LiveDelegationController(session, poll_interval_s=.001, brain_orchestration=False)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    assert [value.text for kind, _, value in frontend.calls if kind is VoiceOperationKind.SPOKEN_RESULT] == ["exact answer"]


async def test_ack_journal_contains_identity_but_no_result_text_or_heard_claim(tmp_path):
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    async def acknowledged(update, *, operation):
        return SimpleNamespace(status=VoiceOperationStatus.COMPLETED)
    frontend.append_spoken_result = acknowledged
    core = Core(({"status": "completed", "fresh": True, "result": {"text": "private exact answer"}},))
    session = Session(frontend, core)
    session.journal = RuntimeJournal(tmp_path)
    controller = LiveDelegationController(session, poll_interval_s=.001, brain_orchestration=False)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    rows = read_jsonl_tail(session.journal.trace_path)
    assert [row["data"]["status"] for row in rows] == ["accepted", "append_acknowledged"]
    assert all(row["data"]["path"] == "speculative" for row in rows)
    assert all(row["data"]["job_id"] == "stable-job" for row in rows)
    assert "private exact answer" not in str(rows)
    assert not any(word in str(rows) for word in ("heard", "presented"))


class BrainCore:
    """Core canonique minimal : ledger accepté, tours cerveau enregistrés."""

    def __init__(self) -> None:
        self.turns: list[tuple[str, dict]] = []

    async def bind_voice_session(self, *_):
        return {"result": {"disposition": "applied"}}

    async def submit_voice_observations(self, _conversation, _session, events):
        return {"results": [{"disposition": "applied"} for _ in events]}

    async def register_voice_speech(self, *_):
        return {"result": {"disposition": "applied"}}

    async def submit_brain_turn(self, conversation_id, **values):
        self.turns.append((conversation_id, values))
        return {"turn_id": "turn", "duplicate": False}

    async def submit_back_brain_task(self, conversation_id, **values):
        self.turns.append(("speculative", {"conversation_id": conversation_id, **values}))
        return SimpleNamespace(status="unavailable", job_id=None)


async def live_session(wire, core, *, grace=.01, config=None, journal=None):
    session = await LiveFrontendSession.connect(api_key="unused", voice="marin", context={},
        connector=lambda: asyncio.sleep(0, result=wire), architecture_config=config)
    await session.attach_core(core, "conversation", journal=journal)
    if session._delegations is not None:
        session._delegations.trailing_grace_s = grace
    return session


def drain(session):
    async def consume():
        async for _ in session.events():
            pass
    return asyncio.create_task(consume())


async def test_delegation_opens_one_brain_turn_with_the_reconstructed_request():
    wire, core = LiveWire(), BrainCore()
    session = await live_session(wire, core)
    reader = drain(session)
    try:
        for index, fragment in enumerate(("Prépare", " un plan", " détaillé")):
            wire.push({"type": "session.input_transcript.delta", "event_id": f"i{index}",
                       "delta": fragment, "start_ms": index * 200, "end_ms": index * 200 + 100})
        wire.push({"type": "session.delegation.created", "event_id": "d1", "offset_ms": 9200,
                   "delegation": {"id": "item-a", "type": "delegation", "target": "client"}})
        # Le modèle accuse réception tout seul : cela n'efface pas la demande.
        wire.push({"type": "session.output_transcript.delta", "event_id": "o1",
                   "delta": "Oui, je m'en charge.", "start_ms": 9200, "end_ms": 9400})
        wire.push({"type": "session.delegation.created", "event_id": "d2", "offset_ms": 9250,
                   "delegation": {"id": "item-a", "type": "delegation", "target": "client"}})
        async with asyncio.timeout(2):
            while not core.turns or session._delegations._tasks:
                await asyncio.sleep(0)
        assert len(core.turns) == 1
        conversation, values = core.turns[0]
        assert conversation == "conversation"
        assert values["content"] == "Prépare un plan détaillé"
        assert values["correlation_id"] == "live:conversation:item-a"
        assert values["source"] == "realtime" and values["addressing"] == "addressed"
        assert values["provider_item_id"] == "item-a"
        assert session.pending_request_text() is None
    finally:
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_trailing_deltas_inside_the_grace_join_the_submitted_request():
    wire, core = LiveWire(), BrainCore()
    session = await live_session(wire, core, grace=.25)
    reader = drain(session)
    try:
        wire.push({"type": "session.input_transcript.delta", "event_id": "i0",
                   "delta": "Compare les deux", "start_ms": 0, "end_ms": 100})
        wire.push({"type": "session.delegation.created", "event_id": "d1", "offset_ms": 100,
                   "delegation": {"id": "item-b", "type": "delegation", "target": "client"}})
        async with asyncio.timeout(1):
            while session.input_observation_revision < 1:
                await asyncio.sleep(0)
        wire.push({"type": "session.input_transcript.delta", "event_id": "i1",
                   "delta": " architectures", "start_ms": 100, "end_ms": 140})
        async with asyncio.timeout(3):
            while not core.turns:
                await asyncio.sleep(0)
        assert core.turns[0][1]["content"] == "Compare les deux architectures"
    finally:
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_delegation_without_request_text_never_submits_an_empty_turn(tmp_path):
    wire, core = LiveWire(), BrainCore()
    journal = RuntimeJournal(tmp_path)
    session = await live_session(wire, core, journal=journal)
    reader = drain(session)
    try:
        wire.push({"type": "session.delegation.created", "event_id": "d1", "offset_ms": 40,
                   "delegation": {"id": "item-c", "type": "delegation", "target": "client"}})
        async with asyncio.timeout(2):
            while not session._delegations._seen or session._delegations._tasks:
                await asyncio.sleep(0)
        assert core.turns == []
    finally:
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)
    rows = [row for row in read_jsonl_tail(journal.trace_path) if row["kind"] == "voice.live.delegation"]
    assert [row["data"]["status"] for row in rows] == ["empty_request"]
    assert rows[0]["data"]["offset_ms"] == 40
    # Le repli spéculatif trace `unavailable` sur ce même flux : la voie doit
    # rester lisible sans confondre les deux échecs.
    assert rows[0]["data"]["path"] == "brain_turn"


async def test_disabled_brain_orchestration_keeps_the_speculative_submission():
    wire, core = LiveWire(), BrainCore()
    session = await live_session(wire, core, config=SPECULATIVE)
    reader = drain(session)
    try:
        wire.push({"type": "session.input_transcript.delta", "event_id": "i0",
                   "delta": "Analyse ça", "start_ms": 0, "end_ms": 50})
        wire.push({"type": "session.delegation.created", "event_id": "d1", "offset_ms": 50,
                   "delegation": {"id": "item-d", "type": "delegation", "target": "client"}})
        async with asyncio.timeout(2):
            while not core.turns:
                await asyncio.sleep(0)
        scope, values = core.turns[0]
        assert scope == "speculative" and values["scope"] == "speculative_analysis"
        assert values["delegation_id"] == "item-d"
        assert not any("content" in entry for _, entry in core.turns)
    finally:
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


def test_segments_respect_the_append_bound_and_prefer_sentence_boundaries():
    short = "Deux est plus petit que trois."
    assert append_segments(short) == [short]
    long_text = " ".join(f"Phrase numéro {index} de la réponse du cerveau." for index in range(40))
    segments = append_segments(long_text)
    assert len(segments) >= 4
    assert all(len(chunk.encode("utf-8")) <= MAX_APPEND_CHUNK_UTF8 for chunk in segments)
    assert all(chunk.endswith(".") for chunk in segments)
    assert " ".join(segments) == long_text
    hard = "x" * 2000
    assert all(len(chunk.encode("utf-8")) <= MAX_APPEND_CHUNK_UTF8 for chunk in append_segments(hard))
    assert "".join(append_segments(hard)) == hard


async def test_long_result_is_spoken_in_ordered_bounded_appends():
    wire, core = LiveWire(), BrainCore()
    session = await live_session(wire, core)
    reader = drain(session)
    try:
        text = " ".join(f"Point {index} du résultat complet du cerveau." for index in range(50))
        assert len(text.encode("utf-8")) > 2000
        await asyncio.wait_for(session.speak(SpeechRequest(conversation_id="conversation", text=text, id="speech"), output_id="out"), 3)
        appends = [message for message in wire.sent if message["type"] == "session.commentary.append"]
        assert len(appends) >= 4
        assert all(len(message["content"].encode("utf-8")) <= MAX_APPEND_CHUNK_UTF8 for message in appends)
        assert " ".join(message["content"] for message in appends) == text
    finally:
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_short_result_still_produces_exactly_one_append():
    wire, core = LiveWire(), BrainCore()
    session = await live_session(wire, core)
    reader = drain(session)
    try:
        await asyncio.wait_for(session.speak(SpeechRequest(conversation_id="conversation", text="Deux est plus petit que trois.", id="speech"),
                                             output_id="out"), 3)
        appends = [message for message in wire.sent if message["type"] == "session.commentary.append"]
        assert [message["content"] for message in appends] == ["Deux est plus petit que trois."]
    finally:
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_suppressed_playback_stops_the_remaining_chunks_and_is_traced(tmp_path):
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    journal = RuntimeJournal(tmp_path)
    session = LiveFrontendSession(frontend, "live-session")
    session.journal = journal
    text = " ".join(f"Point {index} du résultat complet du cerveau." for index in range(50))
    original = frontend.append_spoken_result

    async def one_then_suppressed(update, *, operation):
        result = await original(update, operation=operation)
        session.suppress_playback_until_session_end()
        return result

    frontend.append_spoken_result = one_then_suppressed
    await session.speak(SpeechRequest(conversation_id="conversation", text=text, id="speech"), output_id="out")
    spoken = [value.text for kind, _, value in frontend.calls if kind is VoiceOperationKind.SPOKEN_RESULT]
    assert len(spoken) == 1
    rows = [row for row in read_jsonl_tail(journal.trace_path) if row["kind"] == "voice.live.speech_truncated"]
    assert rows and rows[0]["data"]["chunks"] == 1
    assert rows[0]["data"]["dropped_bytes"] > 0
    assert "résultat complet" not in str(rows)


def test_duplex_has_no_reflex_surface_so_the_brain_never_double_acknowledges():
    """En duplex, le modèle Live accuse déjà réception tout seul.

    Le préambule de l'ordonnanceur est une capacité optionnelle de la surface :
    sans `speak_reflex`/`invalidate_reflex`, `decide_reflex` le désactive et
    seule la parole de RÉSULTAT atteint le canal commentaire.
    """
    assert not supports_reflex(LiveFrontendSession)
    assert not hasattr(LiveFrontendSession, 'speak_reflex')
    assert not hasattr(LiveFrontendSession, 'invalidate_reflex')


async def test_per_word_deltas_rebuild_the_sentence_without_inserted_separators():
    """GPT-Live émet un delta par mot, ponctuation et trait d'union compris.

    Les fragments portent leur propre espace de tête (" Jarvis", ", lance",
    "-moi") : on les concatène bruts, puis on normalise une seule fois. Insérer
    un séparateur détacherait la virgule et le trait d'union.
    """
    wire, core = LiveWire(), BrainCore()
    session = await live_session(wire, core)
    reader = drain(session)
    try:
        fragments = (" Jarvis", ",", " lance", "-moi", " une", " analyse", " détaillée", " du", " dépôt", ".")
        for index, fragment in enumerate(fragments):
            wire.push({"type": "session.input_transcript.delta", "event_id": f"w{index}",
                       "delta": fragment, "start_ms": index * 200, "end_ms": index * 200 + 100})
        wire.push({"type": "session.delegation.created", "event_id": "d1", "offset_ms": 6800,
                   "delegation": {"id": "item-w", "type": "delegation", "target": "client"}})
        async with asyncio.timeout(2):
            while not core.turns:
                await asyncio.sleep(0)
        assert core.turns[0][1]["content"] == "Jarvis, lance-moi une analyse détaillée du dépôt."
    finally:
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


# ---------------------------------------------------------------------------
# Relais spontané : le résultat d'un sous-agent fini doit atteindre le canal
# commentaire et être dit, comme dans l'architecture simple. GPT-Live n'annonce
# jamais la fin d'une sortie ; tout ce que l'ordonnanceur comptait dessus s'y
# bloquait (file muette à vie, chaîne de paragraphes enterrée).
# ---------------------------------------------------------------------------

NOTICE = ("J'ai fini l'analyse de l'architecture. " * 12).strip()


async def relay(wire, journal=None, *, output_timeout_s=.2):
    """Ordonnanceur de parole réel branché sur une session Live réelle."""
    from tests.unit.test_v2_speech_scheduler import FakeCore, build_scheduler
    core = FakeCore()
    session = await live_session(wire, BrainCore(), journal=journal)
    scheduler = build_scheduler(core, session, journal=journal, output_timeout_s=output_timeout_s)
    await scheduler.start()
    return core, session, scheduler


def commentary(wire):
    return [m["content"] for m in wire.sent if m["type"] == "session.commentary.append"]


async def appended(wire, text, *, timeout=3):
    """Attendre que le canal commentaire porte `text` entier, puis rendre ses ajouts."""
    async with asyncio.timeout(timeout):
        while " ".join(" ".join(commentary(wire)).split()) != " ".join(text.split()):
            await asyncio.sleep(0)
    return commentary(wire)


async def test_a_provider_output_never_mutes_the_relay_for_the_rest_of_the_session():
    """Une sortie du fournisseur ne se referme jamais : elle ne doit rien occuper.

    Le bridge annonce `realtime.output_started` dès que le modèle Live parle de
    lui-même. Comptée comme sortie vivante, elle ne serait jamais retirée — et
    le résultat du sous-agent, arrivé après, n'aurait plus jamais son tour.
    """
    from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind
    from tests.unit.test_v2_speech_scheduler import speech_envelope
    wire = LiveWire()
    core, session, scheduler = await relay(wire)
    reader = drain(session)
    try:
        wire.push({"type": "session.output_transcript.delta", "event_id": "o1",
                   "delta": "Je m'en charge.", "start_ms": 0, "end_ms": 100})
        async with asyncio.timeout(3):
            while session.active_output_id is None:
                await asyncio.sleep(0)
        await scheduler.note_output_event(ProtocolEnvelope(
            message_type="realtime.output_started", payload={"output_id": session.active_output_id}))
        await core.publish(speech_envelope("Le sous-agent a fini.", kind=SpeechKind.RESULT))
        assert await appended(wire, "Le sous-agent a fini.") == ["Le sous-agent a fini."]
    finally:
        await asyncio.wait_for(scheduler.stop(), 3)
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_a_multi_paragraph_result_is_appended_whole_and_chunked_under_the_bound():
    """Aucun paragraphe n'est enterré, et le découpage sous 450 octets sert.

    Sans fin de sortie, chaque maillon d'une chaîne de paragraphes finissait
    « interrompu » : la chaîne était bloquée et seul le premier était dit. La
    surface reçoit donc le texte entier et le découpe elle-même.
    """
    from jarvis.domain.v2 import SpeechKind
    from tests.unit.test_v2_speech_scheduler import speech_envelope
    wire = LiveWire()
    text = NOTICE + "\n\n" + NOTICE
    assert len(text.encode("utf-8")) > MAX_APPEND_CHUNK_UTF8
    core, session, scheduler = await relay(wire)
    reader = drain(session)
    try:
        await core.publish(speech_envelope(text, kind=SpeechKind.RESULT))
        contents = await appended(wire, text)
        assert len(contents) >= 2
        assert all(len(chunk.encode("utf-8")) <= MAX_APPEND_CHUNK_UTF8 for chunk in contents)
    finally:
        await asyncio.wait_for(scheduler.stop(), 3)
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_a_surface_that_ends_its_outputs_keeps_the_paragraph_chain():
    """Le découpage par paragraphe reste entier pour une surface normale."""
    from jarvis.domain.v2 import SpeechKind
    from tests.unit.test_v2_speech_scheduler import (
        FakeCore, FakeVoiceSession, build_scheduler, finish_speech, speech_envelope, wait_for)
    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session, output_timeout_s=.2)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Premier paragraphe.\n\nSecond paragraphe.", kind=SpeechKind.RESULT))
        for _ in range(2):
            await wait_for(lambda: session.active_output_id is not None)
            await finish_speech(scheduler, session)
        assert session.texts() == ["Premier paragraphe.\n\n", "Second paragraphe."]
    finally:
        await asyncio.wait_for(scheduler.stop(), 3)


async def test_an_oversized_result_stays_under_the_ledger_text_bound():
    """La fusion des paragraphes reste bornée par `MAX_SPEECH_CHUNK_TEXT`.

    C'est aussi la borne du texte annoncé au ledger (`register_speech`, 8192) :
    fusionner sans elle ferait refuser la parole entière, donc perdre tout le
    résultat au lieu d'en perdre la queue.
    """
    from jarvis.domain.speech_presentation import MAX_SPEECH_CHUNK_TEXT
    from jarvis.domain.v2 import SpeechKind
    from tests.unit.test_v2_speech_scheduler import FakeCore, build_scheduler, speech_envelope

    class Live(SimpleNamespace):
        requires_local_quiescence_without_output_final = True

    paragraph = ("Une phrase du résultat du sous-agent. " * 40).strip()
    text = "\n\n".join(paragraph for _ in range(8))
    assert len(text) > MAX_SPEECH_CHUNK_TEXT
    core = FakeCore()
    scheduler = build_scheduler(core, Live(session_id="live", active_output_id=None), output_timeout_s=.2)
    scheduler._enqueue(SpeechRequest.from_payload(
        speech_envelope(text, kind=SpeechKind.RESULT).payload))
    chains = [candidate.chunk for candidate in scheduler._candidates.values()]
    assert 1 < len(chains) < 8
    assert all(chunk.span.end - chunk.span.start <= MAX_SPEECH_CHUNK_TEXT for chunk in chains)
