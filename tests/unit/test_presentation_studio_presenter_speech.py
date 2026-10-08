"""The Jarvis presenter over the REAL speech path (jarvis-interactive-presentation-studio, Slice 14).

Real: `BrainOrchestrator.announce_notice` (Core), its bus, the Conversation Event emitter, the Voice `SpeechScheduler` with its real
`PresentationSpeechGate` and `InteractionModeObserver`, the playback service and the interaction mode service. Doubles: the voice
surface (`FakeVoiceSession`, which only records what it was asked to say) and the Voice->Core event transport (a recorder that hands
the scheduler's conversation events to Core's emitter, as the forwarder and the ingestion route do).

What this proves that the fake speech stack cannot: the scripted line goes through the one existing speech path and is admitted in
ASSISTANT mode (the mode a Jarvis run switches to), the very same line is withheld in PRESENTATION mode (so the role needs the mode switch),
and the withholding is a visible failure, not a silent hang. NOT proven here: audible output (needs the Human, see OPERATIONS).
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.conversation_event_emitter import ConversationEventEmitter, build_conversation_event
from jarvis.core.presentation_studio_events import StudioPresenterEvents
from jarvis.core.presentation_studio_presenter import PresentationStudioPresenter, SPEECH_NOT_STARTED
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_studio_roles import SCORE_LINE_KIND
from jarvis.domain.v2 import BrainTurnInput, PlaybackCursor, ProtocolEnvelope, SpeechKind
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver
from jarvis.runtime.presentation_speech_gate import SPEECH_WITHHELD
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.fakes.conversation_events import open_store
from tests.fakes.presentation_studio_presenter import SECRET, TEXT_A, advance, lines_content, set_ms
from tests.unit.test_brain_delegation import ScriptedBackend, _idle, _orchestrator
from tests.unit.test_presentation_studio_playback_service import Rig, applied
from tests.unit.test_v2_speech_scheduler import FakeCore, FakeVoiceSession, RecordingJournal, finish_speech, wait_for
import tests.unit.test_v2_speech_scheduler as scheduler_tests


@pytest.fixture(autouse=True)
def _fresh_speech_origin():
    from jarvis.domain.v2 import utc_now
    scheduler_tests.ORIGIN = utc_now()


class VoiceToCore:
    """What the Voice process's forwarder and Core's ingestion route do: a scheduler's event becomes a Core event."""

    def __init__(self, emitter: ConversationEventEmitter) -> None:
        self.emitter, self.sent = emitter, []

    def record(self, event_type, *, producer, conversation_id, source_ids, occurred_at, **fields):
        event = build_conversation_event(event_type, producer=producer, conversation_id=conversation_id, source_ids=source_ids,
                                         occurred_at=occurred_at, **fields)
        self.sent.append(event)
        self.emitter.emit(event)
        return event.event_id

    def derive_event_id(self, event_type, **kwargs):
        return self.emitter.derive_event_id(event_type, **kwargs)


class CoreOfTheBrain(FakeCore):
    """The Voice process's view of Core: a bus (fed from the real brain's) and the real `speech_context` of the brain."""

    def __init__(self, brain) -> None:
        super().__init__()
        self.brain = brain

    async def speech_context(self, conversation_id: str):
        return await self.brain.speech_context(conversation_id)


class World:
    """Core (brain, emitter, playback) and Voice (scheduler, gate, mode observer) wired like the product, minus the transports."""


async def build(tmp_path, *, core_mode: InteractionMode, voice_mode: InteractionMode | None = None):
    for name in ("events", "brain", "rig"):
        (tmp_path / name).mkdir()
    world = World()
    world.state_repo, store = await open_store(tmp_path / "events" / "events.sqlite3")
    world.emitter = ConversationEventEmitter(store, batch_linger_s=0.0)
    world.brain, world.bus, world.brain_state, world.conversation_id, world.brain_sink = await _orchestrator(
        tmp_path / "brain", ScriptedBackend(), conversation_events=world.emitter)
    world.rig = await Rig(tmp_path / "rig").open(content=lines_content(), mode=core_mode)
    set_ms(world.rig, 1_000_000)
    world.presenter = PresentationStudioPresenter(
        world.rig.service, world.brain, events=StudioPresenterEvents(world.rig.conversation, lambda: "conv-1"),
        diagnostics=world.rig.env.sink, monotonic=world.rig.mono, gap_ms=0, run_loop=False)
    world.emitter.add_listener(world.presenter.on_event)
    # Voice side: the scheduler learns the current intention and the speech requests from Core's own bus, as in the product
    world.observer = InteractionModeObserver()
    world.observer.adopt({"mode": (voice_mode or core_mode).value, "revision": world.rig.mode.revision, "epoch": "epoch-1"})
    world.core, world.session, world.journal = CoreOfTheBrain(world.brain), FakeVoiceSession(), RecordingJournal()
    world.scheduler = SpeechScheduler(
        core=world.core, conversation_id=world.conversation_id, session=world.session, journal=world.journal,
        reconnect_delay_s=0.0, output_timeout_s=5.0, interaction_mode=world.observer, reflex_delay_s=0.0,
        conversation_events=VoiceToCore(world.emitter))
    world.queue = world.bus.subscribe()
    await world.scheduler.start()

    async def forward() -> None:
        while True:
            envelope = await world.queue.get()
            await world.core.publish(envelope)

    world.forwarder = asyncio.create_task(forward())
    await world.brain.submit(BrainTurnInput(conversation_id=world.conversation_id, text="Prepare la presentation."))
    await _idle(world.brain)
    await wait_for(lambda: world.scheduler._current_source is not None)
    return world


async def close(world: World) -> None:
    world.forwarder.cancel()
    await asyncio.gather(world.forwarder, return_exceptions=True)
    await world.scheduler.stop()
    await world.emitter.stop()
    await world.rig.close()
    await world.state_repo.close()


def forward_mode_change(world: World) -> None:
    """The `interaction.mode.changed` Core published on its bus reaches the Voice observer (hot switch, D15)."""

    for message_type, payload in world.rig.bus.messages:
        if message_type == "interaction.mode.changed":
            world.observer.observe(ProtocolEnvelope(message_type=message_type, payload=payload))


async def test_the_line_goes_through_the_one_speech_path_and_is_admitted_in_assistant_mode(tmp_path):
    world = await build(tmp_path, core_mode=InteractionMode.PRESENTATION)
    try:
        assert world.observer.mode is InteractionMode.PRESENTATION
        state = applied(await world.rig.service.start(world.rig.start_body("jarvis_presenter")))
        forward_mode_change(world)
        assert world.rig.mode.mode is InteractionMode.ASSISTANT and world.observer.mode is InteractionMode.ASSISTANT
        await world.presenter.pump()
        await wait_for(lambda: len(world.session.spoken) == 1)
        [request] = world.session.spoken
        assert request.text == TEXT_A and request.kind is SpeechKind.PROGRESS is SCORE_LINE_KIND
        assert request.supersedes_key == f"presentation_studio:{state['run_id']}" and request.expires_at is not None
        assert request.provenance.value == "brain.speech" and request.work_id is None
        # the facts the existing stack records come back as the line's progress
        await wait_for(lambda: any(e.event_type.value == "mouth.speech.started" for e in world.scheduler.conversation_events.sent))
        await world.presenter.pump()
        assert world.presenter.view()["line"] == "playing" and world.rig.service.where()["speaking"] == "jarvis"
        await finish_speech(world.scheduler, world.session)
        await wait_for(lambda: any(e.event_type.value == "mouth.speech.completed" for e in world.scheduler.conversation_events.sent))
        await world.presenter.pump()
        assert world.rig.service.where()["position"]["index"] == 2 and len(world.session.spoken) == 1
        assert world.journal.count(SPEECH_WITHHELD) == 0
    finally:
        await close(world)


async def test_the_same_line_is_withheld_in_presentation_mode_and_the_run_says_so_instead_of_hanging(tmp_path):
    """Why the role needs the mode switch: the gate withholds an unaddressed line in PRESENTATION. Core cannot see that, so the
    only honest outcome is the bounded wait ending in a visible `speech_not_started`."""

    world = await build(tmp_path, core_mode=InteractionMode.ASSISTANT, voice_mode=InteractionMode.PRESENTATION)
    try:
        applied(await world.rig.service.start(world.rig.start_body("jarvis_presenter")))   # Core is in ASSISTANT: no switch
        await world.presenter.pump()
        await wait_for(lambda: world.journal.count(SPEECH_WITHHELD) >= 1)
        assert world.session.spoken == []                                                  # nothing was said
        advance(world.rig, 10_001)
        await world.presenter.pump()
        state = world.rig.service.where()
        # the Voice process records the withheld line as dropped (`speech_obsolete`) or, with no fact at all, the bounded wait ends
        # (`speech_not_started`): either way the run is paused with a stated reason
        assert state["phase"] == "paused" and set(state["problems"]) & {"speech_obsolete", SPEECH_NOT_STARTED}
        assert TEXT_A not in repr(world.journal.events)                                    # the withholding trace carries no text
        # the user (or the mode switch catching up) fixes it: the explicit retry is admitted
        world.observer.adopt({"mode": "assistant", "revision": 99, "epoch": "epoch-1"})
        applied(await world.rig.run("resume"))
        await world.presenter.pump()
        await wait_for(lambda: len(world.session.spoken) == 1)
        assert world.session.spoken[0].text == TEXT_A
    finally:
        await close(world)


async def test_a_barge_in_cut_by_the_real_scheduler_pauses_the_run_and_it_waits_for_the_users_continue(tmp_path):
    world = await build(tmp_path, core_mode=InteractionMode.ASSISTANT)
    try:
        applied(await world.rig.service.start(world.rig.start_body("jarvis_presenter")))
        await world.presenter.pump()
        await wait_for(lambda: len(world.session.spoken) == 1)
        speech_id = world.session.spoken[0].id
        world.scheduler.note_interruption(PlaybackCursor(speech_id=speech_id, played_ms=900))
        await finish_speech(world.scheduler, world.session, status="cancelled")
        await wait_for(lambda: any(e.event_type.value == "mouth.speech.interrupted" for e in world.scheduler.conversation_events.sent))
        await world.presenter.pump()
        assert world.rig.service.where()["phase"] == "paused" and world.presenter.view()["interrupted"] is True
        for _ in range(3):
            advance(world.rig, 30_000)
            await world.presenter.pump()
        assert world.rig.service.where()["phase"] == "paused" and len(world.session.spoken) == 1      # never alone
        # the user's turn is answered (a new intention in Core releases the floor), then the explicit continue
        await world.brain.submit(BrainTurnInput(conversation_id=world.conversation_id, text="Une question en passant."))
        await _idle(world.brain)
        applied(await world.rig.run("resume"))
        await world.presenter.pump()
        await wait_for(lambda: len(world.session.spoken) == 2)
        assert world.session.spoken[1].text == TEXT_A                                                   # from its start, once
    finally:
        await close(world)


async def test_no_text_of_the_script_reaches_the_presenters_logs_or_events_on_the_real_path(tmp_path):
    world = await build(tmp_path, core_mode=InteractionMode.ASSISTANT)
    try:
        applied(await world.rig.service.start(world.rig.start_body("jarvis_presenter")))
        await world.presenter.pump()
        await wait_for(lambda: len(world.session.spoken) == 1)
        await finish_speech(world.scheduler, world.session)
        await wait_for(lambda: any(e.event_type.value == "mouth.speech.completed" for e in world.scheduler.conversation_events.sent))
        await world.presenter.pump()
        everything = repr(world.rig.env.sink.rows) + repr(world.rig.conversation.recorded) + repr(world.rig.service.where())
        assert SECRET not in everything
    finally:
        await close(world)
