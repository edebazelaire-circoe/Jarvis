from dataclasses import replace
import asyncio

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import AddressingDecision, BrainRunStatus, BrainTurnInput, BrainTurnResult
from jarvis.domain.voice_admission import VoiceTurnAdmissionRequest
from jarvis.domain.voice_event_codec import encode_voice_event
from jarvis.domain.voice_events import UserCommitSource, UserTranscriptCommitted, UserTranscriptDelta, UserTurnOpened, VoiceActivitySource
from jarvis.domain.voice_frontend import VoiceCorrelation
from tests.fakes.voice_frontend import FakeVoiceFrontend


class RecordingBackend:
    def __init__(self):
        self.calls = []

    async def run_turn(self, turn, state, emit):
        self.calls.append(turn)
        return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.COMPLETED)


@pytest.fixture
async def admission_stack(tmp_path):
    backend = RecordingBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        yield core, backend
    finally:
        await core.stop()


async def canonical_input(core, conversation_id=None, *, item="a", text="  Une question exacte.\n", committed=True, source=None, previous_turn_id=None):
    if conversation_id is None:
        conversation_id = (await core.conversations.create()).id
        await core.voice_ledger.bind_session(conversation_id, "session-a")
    source = source or FakeVoiceFrontend()
    correlation = VoiceCorrelation("session-a", turn_id="canonical-" + item, provider_input_id="item-" + item)
    payload = (UserTranscriptCommitted("transcript-" + item, text, 1, UserCommitSource.PROVIDER)
               if committed else UserTranscriptDelta("transcript-" + item, text, 1))
    result = await core.voice_ledger.ingest(conversation_id, "session-a", [
        encode_voice_event(source.event(UserTurnOpened(previous_turn_id, VoiceActivitySource.PROVIDER), correlation=correlation)),
        encode_voice_event(source.event(payload, correlation=correlation)),
    ])
    assert all(item["disposition"] in ("applied", "duplicate") for item in result["results"])
    request = VoiceTurnAdmissionRequest(conversation_id=conversation_id, text=text, addressing=AddressingDecision.ADDRESSED,
        session_id="session-a", canonical_turn_id=correlation.turn_id, transcript_id="transcript-" + item,
        transcript_revision=1, provider_item_id=correlation.provider_input_id)
    return request, source


async def test_concurrent_admission_is_durable_unique_and_never_dispatches(admission_stack):
    core, backend = admission_stack
    request, _ = await canonical_input(core)
    queue = core.events.subscribe()
    observations = []
    original_publish = core.events.publish

    async def inspect_publish(event):
        if event.message_type in {"voice.turn.admitted", "brain.source.changed"}:
            stored = await core.state.get_current_brain_source(request.conversation_id)
            assert stored is not None
            assert (await core.state.get_turn(stored.turn_id)).content == request.text
            assert await core.state.get_voice_snapshot(request.conversation_id) is not None
            observations.append(event)
        await original_publish(event)

    core.events.publish = inspect_publish
    values = await asyncio.wait_for(asyncio.gather(*(core.voice_admission.admit_voice_turn(request) for _ in range(4))), 3)
    assert sum(not value.duplicate for value in values) == 1
    assert len({value.turn_id for value in values}) == 1
    assert values[0].source.correlation_id == values[0].correlation_id
    assert values[0].source.turn_id != request.canonical_turn_id
    assert values[0].correlation_id.startswith("voice-source-")
    assert [event.message_type for event in observations].count("brain.source.changed") == 4
    context = await core.brain.speech_context(request.conversation_id)
    assert next(event.payload for event in observations if event.message_type == "brain.source.changed") == context
    turns = await core.conversations.list_turns(request.conversation_id)
    assert len(turns) == 1 and turns[0].content == request.text
    assert len(await core.history.read(conversation_id=request.conversation_id)) == 1
    assert backend.calls == [] and core.brain.active_turn_count == 0
    assert await core.state.list_jobs() == ()
    assert all(not event.message_type.startswith(("brain.work", "brain.speech")) for event in observations)
    core.events.unsubscribe(queue)


@pytest.mark.parametrize("changes", [
    {"text": "different"}, {"session_id": "session-other"}, {"canonical_turn_id": "canonical-other"},
    {"transcript_id": "other"}, {"transcript_revision": 2}, {"provider_item_id": "item-other"},
])
async def test_admission_requires_exact_committed_server_evidence(admission_stack, changes):
    core, backend = admission_stack
    request, _ = await canonical_input(core)
    with pytest.raises(ValueError):
        await core.voice_admission.admit_voice_turn(replace(request, **changes))
    assert await core.conversations.list_turns(request.conversation_id) == ()
    assert backend.calls == []


async def test_partial_and_conflicting_same_binding_are_rejected(admission_stack):
    core, _ = admission_stack
    request, _ = await canonical_input(core, committed=False)
    with pytest.raises(ValueError, match="committed"):
        await core.voice_admission.admit_voice_turn(request)
    committed, _ = await canonical_input(core)
    first = await core.voice_admission.admit_voice_turn(committed)
    with pytest.raises(ValueError, match="conflicts"):
        await core.voice_admission.admit_voice_turn(replace(committed, addressing=AddressingDecision.UNCERTAIN))
    assert (await core.brain.speech_context(committed.conversation_id))["current_speech_source"] == first.source.to_payload()


async def test_old_retry_does_not_reactivate_and_uncertain_does_not_change_source(admission_stack):
    core, backend = admission_stack
    a, source = await canonical_input(core)
    admitted_a = await core.voice_admission.admit_voice_turn(a)
    b, _ = await canonical_input(core, a.conversation_id, item="b", text="Autre intention", source=source)
    admitted_b = await core.voice_admission.admit_voice_turn(b)
    retry = await core.voice_admission.admit_voice_turn(a)
    assert retry.source == admitted_a.source and retry.duplicate
    assert admitted_b.source.intent_epoch > admitted_a.source.intent_epoch
    uncertain, _ = await canonical_input(core, a.conversation_id, item="c", text="Peut-être ambiant", source=source)
    queue = core.events.subscribe()
    admitted_c = await core.voice_admission.admit_voice_turn(replace(uncertain, addressing=AddressingDecision.UNCERTAIN))
    assert admitted_c.source.intent_epoch > admitted_b.source.intent_epoch
    assert (await core.brain.speech_context(a.conversation_id))["current_speech_source"] == admitted_b.source.to_payload()
    assert (await queue.get()).message_type == "voice.turn.admitted" and queue.empty()
    assert backend.calls == []
    core.events.unsubscribe(queue)


@pytest.mark.parametrize("failure_step", ["checkpoint", "history", "allocate"])
async def test_retry_after_crash_window_recovers_exactly_one_turn(tmp_path, failure_step):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    request, _ = await canonical_input(core)
    queue = core.events.subscribe()

    async def failed(*args, **kwargs):
        raise OSError("controlled persistence interruption")

    if failure_step == "checkpoint":
        core.voice_admission.persist_turn = failed
    elif failure_step == "history":
        core.history.append = failed
    else:
        core.state.allocate_brain_source = failed
    try:
        with pytest.raises(OSError):
            await core.voice_admission.admit_voice_turn(request)
        assert queue.empty()
        assert await core.state.get_voice_snapshot(request.conversation_id) is not None
    finally:
        core.events.unsubscribe(queue)
        await core.stop()
    restarted = JarvisCoreApplication(data_root=tmp_path)
    await restarted.start()
    try:
        accepted = await restarted.voice_admission.admit_voice_turn(request)
        assert (await restarted.voice_admission.admit_voice_turn(request)).duplicate
        assert (await restarted.state.get_turn(accepted.turn_id)).content == request.text
        assert len(await restarted.history.read(conversation_id=request.conversation_id)) == 1
        assert len(await restarted.conversations.list_turns(request.conversation_id)) == 1
    finally:
        await restarted.stop()


async def test_backend_submission_reuses_direct_turn_and_dispatches_once(admission_stack):
    core, backend = admission_stack
    request, _ = await canonical_input(core)
    admission = await core.voice_admission.admit_voice_turn(request)
    turn = BrainTurnInput(conversation_id=request.conversation_id, text=request.text,
                          correlation_id=admission.correlation_id, provider_item_id=request.provider_item_id)
    results = await asyncio.wait_for(asyncio.gather(*(core.brain.submit(turn) for _ in range(3))), 3)
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
    assert len(backend.calls) == 1
    assert all(result.turn_id == admission.turn_id for result in results)
    assert sum(not result.duplicate for result in results) == 1
    assert len(await core.conversations.list_turns(request.conversation_id)) == 1
    assert (await core.voice_admission.admit_voice_turn(request)).duplicate
    assert len(backend.calls) == 1


async def test_restart_retains_admission_identity_and_monotone_epochs(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    request, source = await canonical_input(core)
    first = await core.voice_admission.admit_voice_turn(request)
    await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        retry = await core.voice_admission.admit_voice_turn(request)
        assert retry == replace(first, duplicate=True)
        newer, _ = await canonical_input(core, request.conversation_id, item="b", source=source)
        second = await core.voice_admission.admit_voice_turn(newer)
        assert second.source.intent_epoch > first.source.intent_epoch
        assert (await core.voice_admission.admit_voice_turn(request)).source == first.source
        assert (await core.brain.speech_context(request.conversation_id))["current_speech_source"] == second.source.to_payload()
    finally:
        await core.stop()


async def test_dispatch_of_old_direct_admission_keeps_newer_current_intent(admission_stack):
    core, backend = admission_stack
    a, source = await canonical_input(core, text="Ancienne question")
    first = await core.voice_admission.admit_voice_turn(a)
    b, _ = await canonical_input(core, a.conversation_id, item="b", text="Intention actuelle", source=source)
    second = await core.voice_admission.admit_voice_turn(b)
    await core.brain.submit(BrainTurnInput(conversation_id=a.conversation_id, text=a.text,
                           correlation_id=first.correlation_id, provider_item_id=a.provider_item_id))
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
    assert len(backend.calls) == 1
    assert (await core.brain.speech_context(a.conversation_id))["current_speech_source"] == second.source.to_payload()
    assert core.brain._states[a.conversation_id].current_user_intent == b.text
    assert core.brain._confirmed_turn_order[a.conversation_id] == second.source.intent_epoch


@pytest.mark.parametrize("executed_before_restart", [False, True])
async def test_restart_distinguishes_unexecuted_admission_from_reserved_dispatch(tmp_path, executed_before_restart):
    backend = RecordingBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    request, _ = await canonical_input(core)
    admission = await core.voice_admission.admit_voice_turn(request)
    turn = BrainTurnInput(conversation_id=request.conversation_id, text=request.text,
        correlation_id=admission.correlation_id, provider_item_id=request.provider_item_id)
    if executed_before_restart:
        await core.brain.submit(turn)
        await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
    await core.stop()
    backend = RecordingBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        result = await core.brain.submit(turn)
        await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
        assert result.turn_id == admission.turn_id
        assert result.duplicate is executed_before_restart
        assert len(backend.calls) == (0 if executed_before_restart else 1)
        assert len(await core.conversations.list_turns(request.conversation_id)) == 1
        assert (await core.state.get_brain_source(request.conversation_id, admission.correlation_id)) == admission.source
    finally:
        await core.stop()


async def test_admission_diagnostic_has_correlations_without_transcript(admission_stack):
    core, _ = admission_stack
    request, _ = await canonical_input(core)
    records = []

    class Sink:
        def emit(self, kind, message, *, data=None, level="info"):
            records.append((kind, level, data))

    core.voice_admission.diagnostics = Sink()
    result = await core.voice_admission.admit_voice_turn(request)
    assert records == [("core.voice.turn_admitted", "info", {
        "conversation_id": request.conversation_id, "correlation_id": result.correlation_id,
        "session_id": request.session_id, "turn_id": result.turn_id, "duplicate": False, "source_activated": True,
    })]
    assert request.text not in repr(request)


async def test_dispatch_reservation_atomic_only_for_direct_user_and_immutable(admission_stack):
    core, _ = admission_stack
    request, _ = await canonical_input(core)
    admission = await core.voice_admission.admit_voice_turn(request)
    original = await core.state.get_turn(admission.turn_id)
    second_connection = SQLiteStateRepository(core.state.path)
    await second_connection.initialize()
    try:
        claims = await asyncio.wait_for(asyncio.gather(*(
            (core.state if index % 2 else second_connection).claim_admitted_backend_dispatch(admission.turn_id)
            for index in range(12))), 3)
    finally:
        await second_connection.close()
    assert sum(claims) == 1
    stored = await core.state.get_turn(admission.turn_id)
    assert replace(stored, metadata=original.metadata) == original
    assert stored.metadata == {**original.metadata, "backend_dispatch_reserved": True}
    assert (await core.history.read(conversation_id=request.conversation_id))[0].metadata == original.metadata
    from jarvis.domain.v2 import TurnKind
    ordinary = await core.conversations.append_turn(request.conversation_id, TurnKind.USER, "Ordinary", correlation_id="ordinary")
    assistant = await core.conversations.append_turn(request.conversation_id, TurnKind.ASSISTANT, "Assistant row fixture",
        correlation_id="assistant", metadata={"voice_admission": request.to_payload()})
    assert not await core.state.claim_admitted_backend_dispatch(ordinary.id)
    assert not await core.state.claim_admitted_backend_dispatch(assistant.id)
    assert not await core.state.claim_admitted_backend_dispatch("missing")


async def test_crash_after_dispatch_reservation_does_not_automatically_launch(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    request, _ = await canonical_input(core)
    admission = await core.voice_admission.admit_voice_turn(request)
    assert await core.state.claim_admitted_backend_dispatch(admission.turn_id)
    await core.stop()
    backend = RecordingBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        result = await core.brain.submit(BrainTurnInput(conversation_id=request.conversation_id, text=request.text,
            correlation_id=admission.correlation_id, provider_item_id=request.provider_item_id))
        assert result.duplicate and result.turn_id == admission.turn_id
        assert backend.calls == [] and core.brain.active_turn_count == 0
    finally:
        await core.stop()


@pytest.mark.parametrize("observed_backwards", [False, True])
async def test_first_late_old_admission_stays_old_after_restart_and_backend_submit(tmp_path, observed_backwards):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    if observed_backwards:
        b, frontend = await canonical_input(core, item="b", text="Intention actuelle", previous_turn_id="canonical-a")
        a, _ = await canonical_input(core, b.conversation_id, text="Ancienne intention", source=frontend)
    else:
        a, frontend = await canonical_input(core, text="Ancienne intention")
        b, _ = await canonical_input(core, a.conversation_id, item="b", text="Intention actuelle", source=frontend,
                                     previous_turn_id="canonical-a")
    admitted_b = await core.voice_admission.admit_voice_turn(b)
    await core.stop()
    backend = RecordingBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        admitted_a = await core.voice_admission.admit_voice_turn(a)
        assert admitted_a.source.intent_epoch > admitted_b.source.intent_epoch
        assert await core.state.get_current_brain_source(a.conversation_id) == admitted_b.source
        await core.brain.submit(BrainTurnInput(conversation_id=a.conversation_id, text=a.text,
            correlation_id=admitted_a.correlation_id, provider_item_id=a.provider_item_id))
        await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
        assert len(backend.calls) == 1
        assert await core.state.get_current_brain_source(a.conversation_id) == admitted_b.source
        assert core.brain.working_state(a.conversation_id).current_user_intent == b.text
    finally:
        await core.stop()


async def test_failed_source_publication_retry_after_newer_admission_does_not_republish_old(admission_stack):
    core, _ = admission_stack
    a, frontend = await canonical_input(core)
    original = core.events.publish
    failed = False
    delivered = []

    async def fail_once(event):
        nonlocal failed
        if event.message_type == "brain.source.changed" and not failed:
            failed = True
            raise OSError("controlled publish failure")
        delivered.append(event)
        await original(event)

    core.events.publish = fail_once
    with pytest.raises(OSError):
        await core.voice_admission.admit_voice_turn(a)
    b, _ = await canonical_input(core, a.conversation_id, item="b", source=frontend)
    admitted_b = await core.voice_admission.admit_voice_turn(b)
    assert (await core.voice_admission.admit_voice_turn(a)).duplicate
    changed = [item for item in delivered if item.message_type == "brain.source.changed"]
    assert len(changed) == 1
    assert changed[0].payload["current_speech_source"] == admitted_b.source.to_payload()


@pytest.mark.parametrize("field", ["empty", "extra", "text", "conversation", "correlation", "turn", "source", "provider_item", "addressing"])
async def test_dispatch_binding_validation_covers_full_direct_record(admission_stack, field):
    import json
    from jarvis.domain.v2 import jsonable
    core, _ = admission_stack
    request, _ = await canonical_input(core)
    admission = await core.voice_admission.admit_voice_turn(request)
    record = await core.state.get_turn(admission.turn_id)
    value = jsonable(record)
    if field == "empty":
        value["metadata"]["voice_admission"] = {}
    elif field == "extra":
        value["metadata"]["voice_admission"]["correlation_id"] = admission.correlation_id
    elif field == "text":
        value["content"] = "Different text"
    elif field == "conversation":
        value["conversation_id"] = "different"
    elif field == "correlation":
        value["correlation_id"] = "different"
    elif field == "turn":
        value["id"] = "different"
    elif field == "source":
        value["metadata"]["source"] = "text"
    elif field == "provider_item":
        value["metadata"]["provider_item_id"] = "different"
    else:
        value["metadata"]["addressing"] = "uncertain"
    # Controlled malformed persisted fixture; no new endpoint or production bypass.
    raw = json.dumps(value)
    await core.state._run(lambda conn: conn.execute("UPDATE turns SET data=? WHERE id=?", (raw, admission.turn_id)))
    assert not await core.state.claim_admitted_backend_dispatch(admission.turn_id)
    assert "backend_dispatch_reserved" not in (await core.state.get_turn(admission.turn_id)).metadata


async def test_late_uncertain_backend_promotion_uses_canonical_order(admission_stack):
    core, backend = admission_stack
    older, frontend = await canonical_input(core, text="Ancienne question")
    older = replace(older, addressing=AddressingDecision.UNCERTAIN)
    newer, _ = await canonical_input(core, older.conversation_id, item="b", text="Intention actuelle", source=frontend)
    admitted_b = await core.voice_admission.admit_voice_turn(newer)
    admitted_a = await core.voice_admission.admit_voice_turn(older)
    assert admitted_a.source.intent_epoch > admitted_b.source.intent_epoch
    original = backend.run_turn

    async def useful_result(turn, state, emit):
        return replace(await original(turn, state, emit), public_summary="Résultat disponible de l'ancienne question")

    backend.run_turn = useful_result
    await core.brain.submit(BrainTurnInput(conversation_id=older.conversation_id, text=older.text,
        correlation_id=admitted_a.correlation_id, provider_item_id=older.provider_item_id, addressing=older.addressing))
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
    assert len(backend.calls) == 1
    assert await core.state.get_current_brain_source(older.conversation_id) == admitted_b.source
    assert core.brain.working_state(older.conversation_id).current_user_intent == newer.text


async def test_canonical_newer_but_lower_epoch_cannot_roll_back_watermark(admission_stack):
    core, _ = admission_stack
    older, frontend = await canonical_input(core, text="Ancienne question")
    newer, _ = await canonical_input(core, older.conversation_id, item="b", text="Question suivante", source=frontend)
    admitted_b = await core.voice_admission.admit_voice_turn(replace(newer, addressing=AddressingDecision.UNCERTAIN))
    admitted_a = await core.voice_admission.admit_voice_turn(older)
    assert admitted_a.source.intent_epoch > admitted_b.source.intent_epoch
    assert not await core.state.activate_brain_source(older.conversation_id, admitted_b.source)
    assert await core.state.get_current_brain_source(older.conversation_id) == admitted_a.source


@pytest.mark.parametrize("destination", ["direct", "backend", "promotion"])
async def test_order_eviction_restart_preserves_new_admission_and_backend_authority(tmp_path, destination):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    current, frontend = await canonical_input(core, text="Intention initiale")
    original = await core.voice_admission.admit_voice_turn(current)
    previous = current.canonical_turn_id
    for index in range(400 if destination == "direct" else 132):
        pending, _ = await canonical_input(core, current.conversation_id, item=f"pending-{index}", text=f"Incertain {index}",
            previous_turn_id=previous, source=frontend)
        previous = pending.canonical_turn_id
        await core.voice_admission.admit_voice_turn(replace(pending, addressing=AddressingDecision.UNCERTAIN))
    snapshot = await core.state.get_voice_snapshot(current.conversation_id)
    assert all(item.turn_id != current.canonical_turn_id for item in snapshot.turns)
    assert await core.state.get_current_brain_source(current.conversation_id) == original.source
    await core.stop()
    backend = RecordingBackend()
    if destination == "promotion":
        original_run = backend.run_turn
        async def useful(turn, state, emit):
            return replace(await original_run(turn, state, emit), public_summary="Réponse utile actuelle")
        backend.run_turn = useful
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        newest, _ = await canonical_input(core, current.conversation_id, item="newest", text="Intention actuelle",
            previous_turn_id=previous, source=frontend)
        if destination == "promotion":
            newest = replace(newest, addressing=AddressingDecision.UNCERTAIN)
        accepted = await core.voice_admission.admit_voice_turn(newest)
        if destination != "direct":
            await core.brain.submit(BrainTurnInput(conversation_id=newest.conversation_id, text=newest.text,
                correlation_id=accepted.correlation_id, provider_item_id=newest.provider_item_id, addressing=newest.addressing))
            await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
        assert await core.state.get_current_brain_source(newest.conversation_id) == accepted.source
        assert accepted.source.intent_epoch > original.source.intent_epoch
        assert len(backend.calls) == (0 if destination == "direct" else 1)
    finally:
        await core.stop()


@pytest.mark.parametrize("mutation", ["missing", "empty", "extra", "version", "session", "turn", "cycle", "bool_order", "wrong_order", "wrong_parent"])
async def test_claim_refuses_corrupt_or_forged_server_order(admission_stack, mutation):
    import json
    from jarvis.domain.v2 import jsonable
    core, _ = admission_stack
    request, _ = await canonical_input(core)
    accepted = await core.voice_admission.admit_voice_turn(request)
    row = jsonable(await core.state.get_turn(accepted.turn_id))
    order = row["metadata"]["voice_admission_order"]
    if mutation == "missing":
        row["metadata"].pop("voice_admission_order")
    elif mutation == "empty":
        row["metadata"]["voice_admission_order"] = {}
    elif mutation == "extra":
        order["trusted"] = True
    elif mutation == "version":
        order["schema_version"] = True
    elif mutation == "session":
        order["session_id"] = "other-session"
    elif mutation == "turn":
        order["turn_id"] = "other-turn"
    elif mutation == "cycle":
        order["previous_turn_id"] = order["turn_id"]
    elif mutation == "bool_order":
        order["observation_order"] = True
    elif mutation == "wrong_order":
        order["observation_order"] += 1
    else:
        order["previous_turn_id"] = "not-the-server-predecessor"
    raw = json.dumps(row)
    await core.state._run(lambda conn: conn.execute("UPDATE turns SET data=? WHERE id=?", (raw, accepted.turn_id)))
    assert not await core.state.claim_admitted_backend_dispatch(accepted.turn_id)
    assert "backend_dispatch_reserved" not in (await core.state.get_turn(accepted.turn_id)).metadata


@pytest.mark.parametrize("destination", ["direct", "backend", "promotion"])
async def test_explicit_sibling_fork_never_uses_observation_fallback(admission_stack, destination):
    core, backend = admission_stack
    current, frontend = await canonical_input(core, item="current", previous_turn_id="common-root", text="Branche courante")
    original = await core.voice_admission.admit_voice_turn(current)
    sibling, _ = await canonical_input(core, current.conversation_id, item="sibling", previous_turn_id="common-root",
                                       text="Autre branche", source=frontend)
    if destination == "promotion":
        sibling = replace(sibling, addressing=AddressingDecision.UNCERTAIN)
        original_run = backend.run_turn
        async def useful(turn, state, emit):
            return replace(await original_run(turn, state, emit), public_summary="Résultat de l'autre branche")
        backend.run_turn = useful
    admitted = await core.voice_admission.admit_voice_turn(sibling)
    if destination != "direct":
        await core.brain.submit(BrainTurnInput(conversation_id=sibling.conversation_id, text=sibling.text,
            correlation_id=admitted.correlation_id, provider_item_id=sibling.provider_item_id, addressing=sibling.addressing))
        await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
    assert admitted.source.intent_epoch > original.source.intent_epoch
    assert await core.state.get_current_brain_source(current.conversation_id) == original.source


@pytest.mark.parametrize("mutation", ["missing", "invalid_binding", "invalid_order"])
async def test_missing_or_corrupt_current_order_cannot_authorize_replacement(admission_stack, mutation):
    import json
    from jarvis.domain.v2 import jsonable
    core, _ = admission_stack
    current, frontend = await canonical_input(core)
    original = await core.voice_admission.admit_voice_turn(current)
    row = jsonable(await core.state.get_turn(original.turn_id))
    if mutation == "missing":
        row["metadata"].pop("voice_admission_order")
    elif mutation == "invalid_binding":
        row["metadata"]["voice_admission"] = {}
    else:
        row["metadata"]["voice_admission_order"]["observation_order"] = True
    await core.state._run(lambda conn: conn.execute("UPDATE turns SET data=? WHERE id=?", (json.dumps(row), original.turn_id)))
    next_request, _ = await canonical_input(core, current.conversation_id, item="next", source=frontend)
    await core.voice_admission.admit_voice_turn(next_request)
    assert await core.state.get_current_brain_source(current.conversation_id) == original.source


@pytest.mark.parametrize("destination", ["direct", "backend", "promotion"])
async def test_fork_with_evicted_durable_parents_stays_closed_after_restart(tmp_path, destination):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    root, frontend = await canonical_input(core, item="root")
    await core.voice_admission.admit_voice_turn(replace(root, addressing=AddressingDecision.UNCERTAIN))
    for item in ("left", "right"):
        parent, _ = await canonical_input(core, root.conversation_id, item=item, previous_turn_id=root.canonical_turn_id, source=frontend)
        await core.voice_admission.admit_voice_turn(replace(parent, addressing=AddressingDecision.UNCERTAIN))
    current, _ = await canonical_input(core, root.conversation_id, item="current", previous_turn_id="canonical-left", source=frontend)
    original = await core.voice_admission.admit_voice_turn(current)
    previous = current.canonical_turn_id
    for index in range(132):
        pending, _ = await canonical_input(core, root.conversation_id, item=f"pending-{index}", previous_turn_id=previous, source=frontend)
        previous = pending.canonical_turn_id
        await core.voice_admission.admit_voice_turn(replace(pending, addressing=AddressingDecision.UNCERTAIN))
    snapshot = await core.state.get_voice_snapshot(root.conversation_id)
    assert not {"canonical-root", "canonical-left", "canonical-right", "canonical-current"} & {item.turn_id for item in snapshot.turns}
    await core.stop()
    backend = RecordingBackend()
    if destination == "promotion":
        original_run = backend.run_turn
        async def useful(turn, state, emit):
            return replace(await original_run(turn, state, emit), public_summary="Résultat de l'autre branche")
        backend.run_turn = useful
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        candidate, _ = await canonical_input(core, root.conversation_id, item="candidate", previous_turn_id="canonical-right", source=frontend)
        if destination == "promotion":
            candidate = replace(candidate, addressing=AddressingDecision.UNCERTAIN)
        admitted = await core.voice_admission.admit_voice_turn(candidate)
        if destination != "direct":
            await core.brain.submit(BrainTurnInput(conversation_id=candidate.conversation_id, text=candidate.text,
                correlation_id=admitted.correlation_id, provider_item_id=candidate.provider_item_id, addressing=candidate.addressing))
            await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
        assert await core.state.get_current_brain_source(root.conversation_id) == original.source
    finally:
        await core.stop()


@pytest.mark.parametrize("damage", ["missing", "cycle"])
async def test_missing_or_cyclic_evicted_ancestor_never_grants_activation(admission_stack, damage):
    core, _ = admission_stack
    current, frontend = await canonical_input(core)
    original = await core.voice_admission.admit_voice_turn(current)
    previous = current.canonical_turn_id
    first_pending_id = None
    for index in range(132):
        pending, _ = await canonical_input(core, current.conversation_id, item=f"pending-{index}", previous_turn_id=previous, source=frontend)
        previous = pending.canonical_turn_id
        admitted = await core.voice_admission.admit_voice_turn(replace(pending, addressing=AddressingDecision.UNCERTAIN))
        if index == 0:
            first_pending_id = admitted.turn_id
    if damage == "missing":
        await core.state._run(lambda conn: conn.execute("DELETE FROM turns WHERE id=?", (first_pending_id,)))
    else:
        # pending-1 already points to pending-0: this creates a durable cycle
        # outside the current window, without a trivially invalid self edge.
        await core.state._run(lambda conn: conn.execute(
            "UPDATE turns SET data=json_set(data,'$.metadata.voice_admission_order.previous_turn_id',?) WHERE id=?",
            ("canonical-pending-1", first_pending_id)))
    candidate, _ = await canonical_input(core, current.conversation_id, item="newest", previous_turn_id=previous, source=frontend)
    await core.voice_admission.admit_voice_turn(candidate)
    assert await core.state.get_current_brain_source(current.conversation_id) == original.source
