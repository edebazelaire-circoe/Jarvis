"""Independent adversarial review of the Task10 Core voice-admission seam."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.brain_outcomes import stable_identity
from jarvis.domain.v2 import AddressingDecision, BrainTurnInput, TurnKind
from jarvis.domain.voice_admission import BRAIN_SOURCE_CHANGED, VOICE_TURN_ADMITTED
from tests.unit.test_voice_turn_admission import RecordingBackend, canonical_input


@pytest.fixture
async def review_core(tmp_path):
    backend = RecordingBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        yield core, backend
    finally:
        await core.stop()


async def test_first_late_admission_of_older_canonical_a_cannot_replace_b(review_core):
    core, backend = review_core
    older, frontend = await canonical_input(core, text="Ancienne intention")
    newer, _ = await canonical_input(
        core,
        older.conversation_id,
        item="b",
        text="Intention actuelle",
        source=frontend,
    )

    admitted_b = await core.voice_admission.admit_voice_turn(newer)
    await core.brain._ensure_state(older.conversation_id)
    admitted_a = await core.voice_admission.admit_voice_turn(older)

    assert admitted_a.source.intent_epoch > admitted_b.source.intent_epoch
    context = await core.brain.speech_context(older.conversation_id)
    assert context["current_speech_source"] == admitted_b.source.to_payload()
    assert core.brain._states[older.conversation_id].current_user_intent == newer.text
    assert backend.calls == []


async def test_retry_after_source_event_publication_failure_replays_current_context(review_core):
    core, _ = review_core
    request, _ = await canonical_input(core)
    original_publish = core.events.publish
    delivered = []
    failed = False

    async def fail_source_event_once(event):
        nonlocal failed
        if event.message_type == BRAIN_SOURCE_CHANGED and not failed:
            failed = True
            raise OSError("controlled source event publication failure")
        delivered.append(event)
        await original_publish(event)

    core.events.publish = fail_source_event_once
    with pytest.raises(OSError, match="publication failure"):
        await core.voice_admission.admit_voice_turn(request)
    assert await core.state.get_current_brain_source(request.conversation_id) is not None

    await core.voice_admission.admit_voice_turn(request)

    source_events = [event for event in delivered if event.message_type == BRAIN_SOURCE_CHANGED]
    assert len(source_events) == 1
    assert source_events[0].payload == await core.brain.speech_context(request.conversation_id)
    assert [event.message_type for event in delivered].count(VOICE_TURN_ADMITTED) == 2


async def test_dispatch_marker_cannot_be_forged_on_generic_user_history(review_core):
    core, _ = review_core
    conversation = await core.conversations.create()
    forged = await core.conversations.append_turn(
        conversation.id,
        TurnKind.USER,
        "Legacy user input",
        correlation_id="legacy-correlation",
        metadata={"voice_admission": {}},
    )

    assert not await core.state.claim_admitted_backend_dispatch(forged.id)
    assert (await core.state.get_turn(forged.id)).metadata == {"voice_admission": {}}


async def test_checkpoint_failure_publishes_nothing_and_retry_recovers(review_core):
    core, _ = review_core
    request, _ = await canonical_input(core)
    queue = core.events.subscribe()
    original_save = core.state.save_voice_snapshot
    failed = False

    async def fail_once(snapshot):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("controlled checkpoint failure")
        await original_save(snapshot)

    core.state.save_voice_snapshot = fail_once
    with pytest.raises(OSError, match="checkpoint failure"):
        await core.voice_admission.admit_voice_turn(request)
    assert queue.empty()
    assert await core.conversations.list_turns(request.conversation_id) == ()

    accepted = await core.voice_admission.admit_voice_turn(request)
    assert not accepted.duplicate
    assert (await queue.get()).message_type == VOICE_TURN_ADMITTED
    assert (await queue.get()).message_type == BRAIN_SOURCE_CHANGED
    assert queue.empty()
    core.events.unsubscribe(queue)


@pytest.mark.parametrize("failure_step", ["turn", "conversation", "archive", "source", "activation"])
async def test_each_durable_admission_step_is_retryable_after_restart(tmp_path, failure_step):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    request, _ = await canonical_input(core)
    queue = core.events.subscribe()

    if failure_step == "turn":
        target, name = core.state, "save_turn"
    elif failure_step == "conversation":
        target, name = core.state, "save_conversation"
    elif failure_step == "archive":
        target, name = core.history, "append"
    elif failure_step == "source":
        target, name = core.state, "allocate_brain_source"
    else:
        target, name = core.state, "activate_brain_source"
    original = getattr(target, name)
    failed = False

    async def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError(f"controlled {failure_step} interruption")
        return await original(*args, **kwargs)

    setattr(target, name, fail_once)
    try:
        with pytest.raises(OSError, match=failure_step):
            await core.voice_admission.admit_voice_turn(request)
        assert queue.empty()
    finally:
        core.events.unsubscribe(queue)
        await core.stop()

    restarted = JarvisCoreApplication(data_root=tmp_path)
    await restarted.start()
    try:
        accepted = await restarted.voice_admission.admit_voice_turn(request)
        retry = await restarted.voice_admission.admit_voice_turn(request)
        assert retry == replace(accepted, duplicate=True)
        assert await restarted.state.get_current_brain_source(request.conversation_id) == accepted.source
        assert len(await restarted.conversations.list_turns(request.conversation_id)) == 1
        assert len(await restarted.history.read(conversation_id=request.conversation_id)) == 1
    finally:
        await restarted.stop()


async def test_cancellation_before_activation_is_retryable_without_dispatch(review_core):
    core, backend = review_core
    request, _ = await canonical_input(core)
    original_activate = core.state.activate_brain_source
    entered = asyncio.Event()
    release = asyncio.Event()

    async def held_activate(conversation_id, source):
        entered.set()
        await release.wait()
        return await original_activate(conversation_id, source)

    core.state.activate_brain_source = held_activate
    admission = asyncio.create_task(core.voice_admission.admit_voice_turn(request))
    await asyncio.wait_for(entered.wait(), 1)
    admission.cancel()
    with pytest.raises(asyncio.CancelledError):
        await admission
    assert await core.state.get_current_brain_source(request.conversation_id) is None
    assert await core.state.get_brain_source(
        request.conversation_id,
        "voice-source-" + stable_identity(request.conversation_id, request.session_id, request.canonical_turn_id),
    ) is not None

    core.state.activate_brain_source = original_activate
    accepted = await core.voice_admission.admit_voice_turn(request)
    assert accepted.duplicate
    assert await core.state.get_current_brain_source(request.conversation_id) == accepted.source
    assert backend.calls == [] and core.brain.active_turn_count == 0


async def test_cancelled_claim_waiter_does_not_reserve_then_two_connections_converge(review_core):
    core, _ = review_core
    request, _ = await canonical_input(core)
    accepted = await core.voice_admission.admit_voice_turn(request)

    await core.state._lock.acquire()
    blocked = asyncio.create_task(core.state.claim_admitted_backend_dispatch(accepted.turn_id))
    await asyncio.sleep(0)
    blocked.cancel()
    with pytest.raises(asyncio.CancelledError):
        await blocked
    core.state._lock.release()

    second = SQLiteStateRepository(core.state.path)
    await second.initialize()
    try:
        claims = await asyncio.wait_for(
            asyncio.gather(
                core.state.claim_admitted_backend_dispatch(accepted.turn_id),
                second.claim_admitted_backend_dispatch(accepted.turn_id),
            ),
            3,
        )
    finally:
        await second.close()
    assert sum(claims) == 1


async def test_assistant_and_actual_legacy_turns_cannot_claim_direct_dispatch(review_core):
    core, backend = review_core
    conversation = await core.conversations.create()
    assistant = await core.conversations.append_turn(
        conversation.id,
        TurnKind.ASSISTANT,
        "Assistant",
        correlation_id="assistant-correlation",
        metadata={"voice_admission": {"schema_version": 1}},
    )
    assert not await core.state.claim_admitted_backend_dispatch(assistant.id)

    legacy = BrainTurnInput(
        conversation_id=conversation.id,
        text="Legacy",
        correlation_id="legacy-submit",
    )
    accepted = await core.brain.submit(legacy)
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
    assert len(backend.calls) == 1
    assert "voice_admission" not in (await core.state.get_turn(accepted.turn_id)).metadata
    assert not await core.state.claim_admitted_backend_dispatch(accepted.turn_id)


async def test_uncertain_admission_and_backend_submit_never_preempt_current_source(review_core):
    core, backend = review_core
    addressed, frontend = await canonical_input(core, text="Intention courante")
    current = await core.voice_admission.admit_voice_turn(addressed)
    uncertain, _ = await canonical_input(
        core,
        addressed.conversation_id,
        item="uncertain",
        text="Conversation ambiante possible",
        source=frontend,
    )
    uncertain = replace(uncertain, addressing=AddressingDecision.UNCERTAIN)
    admitted = await core.voice_admission.admit_voice_turn(uncertain)
    assert await core.state.get_current_brain_source(addressed.conversation_id) == current.source

    await core.brain.submit(
        BrainTurnInput(
            conversation_id=uncertain.conversation_id,
            text=uncertain.text,
            correlation_id=admitted.correlation_id,
            addressing=AddressingDecision.UNCERTAIN,
            provider_item_id=uncertain.provider_item_id,
        )
    )
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values())), 3)
    assert await core.state.get_current_brain_source(addressed.conversation_id) == current.source
    assert len(backend.calls) == 1


async def test_stopping_refuses_new_admission_without_mutation(review_core):
    core, backend = review_core
    request, _ = await canonical_input(core)
    await core.brain.stop()

    with pytest.raises(RuntimeError, match="stopping"):
        await core.voice_admission.admit_voice_turn(request)

    assert await core.conversations.list_turns(request.conversation_id) == ()
    assert await core.state.get_current_brain_source(request.conversation_id) is None
    assert backend.calls == []


async def test_new_addressed_turn_advances_after_old_current_canonical_order_is_evicted(review_core):
    core, backend = review_core
    current_request, frontend = await canonical_input(core, item="current", text="Intention initiale")
    current = await core.voice_admission.admit_voice_turn(current_request)
    previous = current_request.canonical_turn_id
    latest = None

    # A long run of admitted uncertain turns legitimately leaves the addressed
    # source unchanged while bounded canonical turn-order evidence is pruned.
    for index in range(132):
        latest, _ = await canonical_input(
            core,
            current_request.conversation_id,
            item=f"pending-{index}",
            text=f"Énoncé incertain {index}",
            source=frontend,
            previous_turn_id=previous,
        )
        previous = latest.canonical_turn_id
        await core.voice_admission.admit_voice_turn(replace(latest, addressing=AddressingDecision.UNCERTAIN))

    newest, _ = await canonical_input(
        core,
        current_request.conversation_id,
        item="newest",
        text="Nouvelle intention adressée",
        source=frontend,
        previous_turn_id=previous,
    )
    accepted = await core.voice_admission.admit_voice_turn(newest)

    assert accepted.source.intent_epoch > current.source.intent_epoch
    assert await core.state.get_current_brain_source(newest.conversation_id) == accepted.source
    assert backend.calls == []
