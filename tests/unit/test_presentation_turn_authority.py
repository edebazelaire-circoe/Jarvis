"""Slice 04 — l'autorité d'un tour en PRESENTATION est structurelle (P2, P3, P10, P11, P12).

Tant qu'une séance PRESENTATION vit, une phrase complète n'atteint le cerveau,
l'admission directe ou `on_addressed` que dans une fenêtre d'adresse explicite
armée (servie une seule fois) ou quand elle commence par le vocatif « Jarvis ».
Tout le reste est la salle : aucun tour, aucun texte au journal.

Ce que cette suite prouve, et comment :

- le vrai `RealtimeConversationBridge`, le vrai `PresentationAddressedTurnService`
  et, là où l'ordre compte, le vrai `SpeechScheduler`. Seuls Core, la session du
  fournisseur et l'audio sont des doubles ;
- la règle tient **sans** le texte du brief (HD3) : on le vide, rien ne change ;
- SIMPLE est identique octet pour octet : sans séance, les mêmes appels et les
  mêmes lignes de journal que sans le câblage ;
- Duplex (GPT-Live) refuse PRESENTATION avant tout micro, une fois (P11) ;
- la voie directe décide avant l'admission et ouvre après, sous l'identité que
  Core rend (P12) — c'est ce qui garde la clarification audible.

Aucun micro, aucun réseau, aucun modèle.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from jarvis.audio import input_ownership
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_addressed_turn import (
    WINDOW_REFUSAL_CODES,
    AddressedTurnAction,
    TurnAuthority,
    authority_after_open,
    decide_turn_authority,
    is_vocative_address,
)
from jarvis.domain.presentation_policy import PresentationSituation
from jarvis.domain.v2 import AddressingDecision, ProtocolEnvelope, SpeechKind, VoiceLifecycleState
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.realtime_audio import RealtimeConversationBridge
from tests.unit.test_presentation_addressed_turn import (
    S10Clock,
    build_service,
    build_store,
    trigger,
)
from tests.unit.test_v2_brain_migration import BrainCoreDouble, QueueSession, RecordingJournal, SilentAudio

CONVERSATION = "conv-1"
ROOM = "on passe au slide suivant ?"
NOW = 100.0


@pytest.fixture(autouse=True)
def clean_input_registry():
    """Le compte de propriétaires d'entrée est un état de **processus**."""

    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


# ==========================================================================
# Doubles et fabriques
# ==========================================================================


class Calls:
    """Ce que la surface a reçu : adressé, ambiant, muet."""

    def __init__(self) -> None:
        self.addressed = 0
        self.ambient = 0
        self.mute = 0


class CountingTurns:
    """Le vrai service, dont on compte les ouvertures et l'ordre."""

    def __init__(self, service, order: list[str] | None = None) -> None:  # noqa: ANN001
        self.service = service
        self.order = order if order is not None else []
        self.opened: list[str] = []

    def window_live(self) -> bool:
        return self.service.window_live()

    def open(self, text, *, correlation_id, spoken_at_s=None):  # noqa: ANN001
        self.opened.append(correlation_id)
        self.order.append("open")
        return self.service.open(text, correlation_id=correlation_id, spoken_at_s=spoken_at_s)

    def __getattr__(self, name):  # noqa: ANN001
        return getattr(self.service, name)


class OrderedCore(BrainCoreDouble):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self.order = order

    async def submit_brain_turn(self, conversation_id, **kwargs):  # noqa: ANN001, ANN003
        self.order.append("submit")
        return await super().submit_brain_turn(conversation_id, **kwargs)


def live_service(journal=None, *, clock=None):  # noqa: ANN001
    """Un service de tour adressé sur une séance liée, et son horloge."""

    clock = clock or S10Clock()
    return build_service(build_store(), clock=clock, journal=journal), clock


def arm(service, clock, *, sequence: int = 0) -> None:  # noqa: ANN001
    result = service.arm(trigger(clock, sequence=sequence))
    assert result.applied, result.code
    clock.advance(0.002)


_ABSENT = object()


def make_bridge(
    *, turns=_ABSENT, engaged: bool = True, journal=None, core=None, session=None,  # noqa: ANN001
    direct: bool = False, on_addressed_turn=None, on_conversation=None,  # noqa: ANN001
):
    calls = Calls()

    def addressed() -> None:
        calls.addressed += 1

    def ambient() -> None:
        calls.ambient += 1

    def mute() -> None:
        calls.mute += 1

    extra = {} if turns is _ABSENT else {"presentation_turns": turns if callable(turns) else (lambda: turns)}
    core = core or BrainCoreDouble()
    bridge = RealtimeConversationBridge(
        core=core, session=session or QueueSession(), conversation_id=CONVERSATION, audio=SilentAudio(),
        on_addressed=addressed, on_ambient=ambient, on_mute=mute, continuous=True, auto_turn=True,
        journal=journal if journal is not None else RecordingJournal(), clock=lambda: NOW,
        direct_conversation=direct, on_addressed_turn=on_addressed_turn, on_conversation=on_conversation,
        **extra,
    )
    bridge._last_engaged = NOW if engaged else -1e9
    return bridge, core, calls


async def say(bridge, text: str, item_id: str = "item-1") -> bool:  # noqa: ANN001
    return await bridge._handle_transcript(ProtocolEnvelope("realtime.transcript", {"text": text, "item_id": item_id}))


# ==========================================================================
# Le prédicat pur
# ==========================================================================


def test_the_pure_authority_rule() -> None:
    assert decide_turn_authority(window_live=True, vocative=False) is TurnAuthority.EXPLICIT_ADDRESS
    assert decide_turn_authority(window_live=True, vocative=True) is TurnAuthority.EXPLICIT_ADDRESS
    assert decide_turn_authority(window_live=False, vocative=True) is TurnAuthority.VOCATIVE_ADDRESS
    assert decide_turn_authority(window_live=False, vocative=False) is TurnAuthority.AMBIENT
    assert is_vocative_address("  JARVIS,   montre la courbe")
    assert not is_vocative_address("comme Jarvis l'a montré hier")
    assert not is_vocative_address(None)
    for code in WINDOW_REFUSAL_CODES:
        assert authority_after_open(code, applied=False, vocative=False) is TurnAuthority.AMBIENT
        assert authority_after_open(code, applied=False, vocative=True) is TurnAuthority.VOCATIVE_ADDRESS
    assert authority_after_open("addressed_snapshot_unreadable", applied=False, vocative=False).admits_turn
    assert authority_after_open("addressed_turn_opened", applied=True, vocative=False) is TurnAuthority.EXPLICIT_ADDRESS


# ==========================================================================
# P2 — la salle ne devient pas un tour
# ==========================================================================


async def test_room_speech_without_window_never_reaches_the_brain() -> None:
    """Engagé, une question courte : la forme dirait ADDRESSED. La séance dit non."""

    service, _ = live_service()
    bridge, core, calls = make_bridge(turns=service, engaged=True)
    assert bridge.classifier.classify(ROOM, active=True, engaged=True) is AddressingDecision.ADDRESSED

    await say(bridge, ROOM)

    assert core.brain_turns == []
    assert calls.addressed == 0
    assert calls.ambient == 1


async def test_uncertain_room_speech_is_not_routed_in_presentation() -> None:
    """Décision 44 envoie le doute au cerveau — sauf pendant une séance."""

    text = "le chiffre d'affaires du trimestre a beaucoup progressé grâce aux nouveaux clients en europe"
    baseline, baseline_core, _ = make_bridge(engaged=False)
    assert baseline.classifier.classify(text, active=True, engaged=False) is AddressingDecision.UNCERTAIN
    await say(baseline, text)
    assert [turn["addressing"] for turn in baseline_core.brain_turns] == ["uncertain"]

    service, _ = live_service()
    bridge, core, calls = make_bridge(turns=service, engaged=False)
    await say(bridge, text)

    assert core.brain_turns == []
    assert calls.addressed == 0


async def test_armed_window_admits_exactly_one_turn() -> None:
    service, clock = live_service()
    arm(service, clock)
    bridge, core, calls = make_bridge(turns=service, engaged=False)

    await say(bridge, "montre la courbe des ventes", "item-1")
    await say(bridge, "et les marges du trimestre", "item-2")

    assert [turn["content"] for turn in core.brain_turns] == ["montre la courbe des ventes"]
    assert core.brain_turns[0]["addressing"] == "addressed"
    assert calls.addressed == 1
    assert not service.window_live()


async def test_vocative_prefix_is_explicit_address_without_window() -> None:
    service, _ = live_service()
    bridge, core, calls = make_bridge(turns=service, engaged=False)

    await say(bridge, "Jarvis, quel est le total ?")

    assert [turn["content"] for turn in core.brain_turns] == ["Jarvis, quel est le total ?"]
    assert calls.addressed == 1


async def test_third_person_mention_is_not_address() -> None:
    text = "comme Jarvis l'a montré hier"
    service, _ = live_service()
    bridge, core, calls = make_bridge(turns=service, engaged=True)
    assert bridge.classifier.classify(text, active=True, engaged=True) is AddressingDecision.ADDRESSED

    await say(bridge, text)

    assert core.brain_turns == []
    assert calls.addressed == 0


async def test_jarvis_mute_still_mutes_in_presentation() -> None:
    """Le vocatif garde « Jarvis mute » vivant, et une fenêtre armée n'est pas mangée."""

    service, clock = live_service()
    arm(service, clock)
    bridge, core, calls = make_bridge(turns=service, engaged=False)

    assert await say(bridge, "Jarvis, mute.") is True

    assert calls.mute == 1
    assert core.brain_turns == []
    assert service.window_live(), "la commande ne consomme pas la fenêtre"


async def test_an_expired_window_does_not_authorize_room_speech() -> None:
    service, clock = live_service()
    arm(service, clock)
    clock.advance(60.0)
    bridge, core, calls = make_bridge(turns=service, engaged=True)

    await say(bridge, ROOM)

    assert core.brain_turns == [] and calls.addressed == 0


async def test_guard_holds_with_presentation_brief_blanked(monkeypatch) -> None:
    """HD3 : la frontière est dans le code, pas dans le texte donné au modèle."""

    import jarvis.runtime.control_center as control_center

    monkeypatch.setattr(control_center, "BRIEF_PRESENTATION_MODE", "")
    service, _ = live_service()
    bridge, core, calls = make_bridge(turns=service, engaged=True)

    await say(bridge, ROOM)
    await say(bridge, "comme Jarvis l'a montré hier", "item-2")

    assert core.brain_turns == [] and calls.addressed == 0


# ==========================================================================
# P3 — ouvert avant d'être soumis, jamais rouvert
# ==========================================================================


async def test_addressed_turn_opened_before_submission_and_not_reopened() -> None:
    from tests.unit.test_presentation_integration import _scheduler

    journal = RecordingJournal()
    order: list[str] = []
    service, clock = live_service(journal)
    turns = CountingTurns(service, order)
    arm(service, clock)
    scheduler = _scheduler(turns, journal=journal)
    real_note = scheduler.note_addressed_turn

    def note(text, **kwargs):  # noqa: ANN001, ANN003
        order.append("note")
        return real_note(text, **kwargs)

    bridge, core, _ = make_bridge(turns=turns, engaged=False, journal=journal,
                                  core=OrderedCore(order), on_addressed_turn=note)
    await say(bridge, "montre la courbe des ventes")
    await asyncio.sleep(0)

    assert order == ["open", "submit", "note"]
    assert turns.opened == [core.brain_turns[0]["correlation_id"]] == ["realtime:conv-1:item-1"]
    kinds = [event["kind"] for event in journal.events]
    assert kinds.index("presentation.addressed.opened") < kinds.index("voice.brain_turn_submitted")
    assert service.counters.opened == 1


async def test_a_vocative_without_window_is_authorized_without_a_plan() -> None:
    """Le refus de fenêtre est tracé, le tour part, l'ordonnanceur ne rouvre pas."""

    service, _ = live_service()
    turns = CountingTurns(service)
    received: list[dict[str, object]] = []

    def note(text, **kwargs):  # noqa: ANN001, ANN003
        received.append(kwargs)

    bridge, core, _ = make_bridge(turns=turns, engaged=False, on_addressed_turn=note)
    await say(bridge, "Jarvis, quel est le total ?")

    assert len(core.brain_turns) == 1
    assert len(turns.opened) == 1
    assert received[0]["plan"] is None and received[0]["turns"] is turns


# ==========================================================================
# P10 — la salle ne laisse pas de texte
# ==========================================================================


async def test_ambient_segment_text_never_reaches_trace(tmp_path) -> None:
    planted = "PHRASE-PLANTEE-salle-4291 le budget marketing"
    journal = RuntimeJournal(tmp_path)
    service, _ = live_service(journal)
    bridge, core, _ = make_bridge(turns=service, engaged=True, journal=journal)

    await say(bridge, planted)

    trace = journal.trace_path.read_text(encoding="utf-8")
    assert planted not in trace and "PLANTEE" not in trace
    lines = [json.loads(line) for line in trace.splitlines()]
    [transcript] = [line for line in lines if line["kind"] == "voice.transcript"]
    assert transcript["data"] == {"addressing": "ambient", "chars": len(planted)}
    assert core.brain_turns == []


# ==========================================================================
# D14 — SIMPLE identique, et la sortie de séance le rend
# ==========================================================================


SIMPLE_CASES = [
    ("Jarvis, quel temps fait-il ?", False),
    ("quel est le total ?", True),
    (ROOM, False),
    ("le chiffre d'affaires du trimestre a beaucoup progressé grâce aux nouveaux clients en europe", True),
    ("comme Jarvis l'a montré hier", True),
    ("Jarvis mute", True),
    ("", True),
]


async def _simple_run(text: str, engaged: bool, turns) -> tuple:  # noqa: ANN001
    journal = RecordingJournal()
    bridge, core, calls = make_bridge(turns=turns, engaged=engaged, journal=journal)
    result = await say(bridge, text)
    # Une mesure de latence porte une durée réelle : seule sa présence se compare.
    lines = [(event["kind"],) if str(event["kind"]).startswith("voice.latency.")
             else (event["kind"], event["message"], event["data"])
             for event in journal.events]
    return result, core.brain_turns, (calls.addressed, calls.ambient, calls.mute), lines


@pytest.mark.parametrize("text, engaged", SIMPLE_CASES)
async def test_simple_routing_unchanged(text, engaged) -> None:
    """Sans séance — pas de lecteur, ou un lecteur qui rend `None` (SIMPLE) — rien ne bouge."""

    reference = await _simple_run(text, engaged, _ABSENT)
    assert await _simple_run(text, engaged, None) == reference
    assert await _simple_run(text, engaged, lambda: None) == reference


async def test_mode_exit_restores_simple_routing() -> None:
    service, _ = live_service()
    live = {"turns": service}
    bridge, core, calls = make_bridge(turns=lambda: live["turns"], engaged=True)

    await say(bridge, "quel est le total ?", "item-1")
    assert core.brain_turns == []

    live["turns"] = None  # la séance est retirée : `PresentationCoordinator.turns` rend `None`
    await say(bridge, "quel est le total ?", "item-2")

    assert [turn["content"] for turn in core.brain_turns] == ["quel est le total ?"]
    assert calls.addressed == 1


# ==========================================================================
# P12 — la voie directe décide avant l'admission
# ==========================================================================


class CountingDirectSession(QueueSession):
    def __init__(self) -> None:
        super().__init__()
        self.admitted: list[str] = []

    async def admit_conversation(self, core, conversation_id, item_id, *, addressing):  # noqa: ANN001
        self.admitted.append(item_id)
        return SimpleNamespace(source=SimpleNamespace(correlation_id=f"voice-source-{item_id}"))


async def test_direct_architectures_apply_the_same_guard() -> None:
    service, clock = live_service()
    session = CountingDirectSession()
    requested: list[object] = []
    bridge, _, calls = make_bridge(turns=service, engaged=True, session=session, direct=True,
                                   on_conversation=lambda **kwargs: requested.append(kwargs))

    await say(bridge, ROOM, "item-1")
    await say(bridge, "comme Jarvis l'a montré hier", "item-2")
    assert session.admitted == [] and requested == [] and calls.addressed == 0

    arm(service, clock)
    await say(bridge, "montre la courbe des ventes", "item-3")
    await say(bridge, "Jarvis, quel est le total ?", "item-4")
    assert session.admitted == ["item-3", "item-4"]
    assert len(requested) == 2 and calls.addressed == 2


async def test_clarify_still_speaks_on_a_direct_architecture() -> None:
    """P12 : le tour s'ouvre sous l'identité que Core rend, donc la question n'est pas périmée."""

    from jarvis.runtime.speech_scheduler import SpeechScheduler
    from tests.fakes.speech_context import context
    from tests.integration.test_front_brain_composition_review import (
        CoreBoundary,
        DirectSessionBoundary,
    )
    from tests.integration.test_front_brain_composition_review import source as direct_source
    from tests.unit.test_presentation_integration import _queued
    from tests.unit.test_v2_speech_scheduler import wait_for

    class ClarifyingTurns:
        def __init__(self) -> None:
            self.opened: list[str] = []
            self.concluded: list[str] = []

        def window_live(self) -> bool:
            return True

        def open(self, text, *, correlation_id):  # noqa: ANN001
            self.opened.append(correlation_id)
            plan = SimpleNamespace(correlation_id=correlation_id,
                                   situation=PresentationSituation.VISUAL_COMMAND)
            return SimpleNamespace(applied=True, plan=plan, code="addressed_turn_opened")

        async def deliver(self, plan):  # noqa: ANN001
            return SimpleNamespace(action=AddressedTurnAction.CLARIFY, delivered=True,
                                   code="addressed_clarification", resource_id="",
                                   speaks=True, speech_kind=SpeechKind.QUESTION)

        def note_visible_reaction(self, correlation_id) -> None:  # noqa: ANN001
            return None

        def note_audible_reaction(self, correlation_id) -> None:  # noqa: ANN001
            return None

        def conclude(self, correlation_id) -> None:  # noqa: ANN001
            self.concluded.append(correlation_id)

    observer = InteractionModeObserver()
    observer.adopt({"mode": InteractionMode.PRESENTATION.value, "revision": 1, "epoch": "life-1"})
    core, current = CoreBoundary(), direct_source()
    session = DirectSessionBoundary(current)
    turns = ClarifyingTurns()
    scheduler = SpeechScheduler(core=core, conversation_id=CONVERSATION, session=session,
                                reconnect_delay_s=.01, output_timeout_s=.1, interaction_mode=observer,
                                presentation_turns=lambda: turns)
    scheduler.update_speech_context(context(CONVERSATION))
    bridge = RealtimeConversationBridge(
        core=core, session=session, conversation_id=CONVERSATION, audio=SimpleNamespace(),
        on_addressed=lambda: None, on_mute=lambda: None, continuous=True, direct_conversation=True,
        on_conversation=scheduler.request_conversation, on_addressed_turn=scheduler.note_addressed_turn,
        output_admission=scheduler.output_admission, presentation_turns=lambda: turns,
    )
    await scheduler.start()
    try:
        await wait_for(lambda: scheduler.presentation_snapshot()["source_complete"])
        await bridge._handle_transcript(ProtocolEnvelope(
            "realtime.transcript", {"item_id": "input", "text": "montre-moi ça"}))
        await wait_for(lambda: _queued(scheduler))

        assert turns.opened == [current.correlation_id], "ouvert une fois, sous l'identité de Core"
        [question] = _queued(scheduler)
        assert question.kind is SpeechKind.QUESTION
        assert question.correlation_id == current.correlation_id
    finally:
        await scheduler.stop()


# ==========================================================================
# La touche pendant une session ACTIVE arme une fenêtre (P2a)
# ==========================================================================


class LaneStub:
    """La lane d'adresse explicite vue de l'aiguillage : des déclencheurs typés."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[object] = asyncio.Queue()

    async def triggers(self):
        while True:
            yield await self.queue.get()

    async def suspend(self) -> None: ...

    async def suspend_for_active_session(self) -> None: ...

    async def resume(self) -> None: ...


async def test_manual_key_during_active_session_arms_a_window(monkeypatch) -> None:
    """L'appui pendant une session ACTIVE arme la fenêtre **et** garde la session.

    Avant : l'aiguillage armait bien, puis Voice coupait la session (« la touche
    veut dire stop ») — la phrase annoncée par l'appui n'arrivait jamais.
    """

    import jarvis.runtime.realtime_audio as realtime_audio
    from jarvis.domain.explicit_address import ExplicitAddressSource, ExplicitAddressTrigger
    from jarvis.runtime.presentation_runtime import PresentationWakeRouter
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
    from jarvis.v2_config import VoiceArchitecture
    from tests.unit.test_v2_continuous_live import (
        ContinuousSession,
        FakeAudio,
        FakeCore,
        FakeWakeWord,
    )
    from tests.unit.test_v2_continuous_live import RecordingJournal as LiveJournal

    FakeAudio.instances.clear()
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    service = build_service(build_store(), clock=time.monotonic)
    lane = LaneStub()
    stack = SimpleNamespace(started=True, stopped=False, audio=SimpleNamespace(lane=lane), turns=service)
    simple = FakeWakeWord()
    router = PresentationWakeRouter(simple=simple)
    coordinator = SimpleNamespace(turns=service, audio=None, observe_mode=lambda mode: None)

    async def aclose(reason: str = "") -> None:
        return None

    coordinator.aclose = aclose
    session, journal, core = ContinuousSession(), LiveJournal(), FakeCore()

    async def factory(context):  # noqa: ANN001
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=router, core=core, realtime_factory=factory, journal=journal,
        auto_turn=True, voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN, presentation=coordinator,
    )
    run_task = asyncio.create_task(runtime.run())
    try:
        await simple.queue.put("f9")
        await journal.wait_until(lambda: journal.count("audio.start") == 1)
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE

        router.adopt(stack)
        await lane.queue.put(ExplicitAddressTrigger.admitted(
            ExplicitAddressSource.MANUAL_KEY, "f9", sequence=0, clock=time.monotonic))
        await journal.wait_until(lambda: journal.count("voice.presentation_address_key") == 1)

        assert router.armed == 1 and service.window_live()
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
        assert session.closed is False and journal.count("voice.manual_cancel") == 0

        await session.push("realtime.transcript", text="montre la courbe des ventes", item_id="item-1")
        await journal.wait_until(lambda: len(core.brain_turns) == 1)
        assert core.brain_turns[0]["content"] == "montre la courbe des ventes"
        assert not service.window_live(), "la fenêtre a servi son tour"
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


# ==========================================================================
# P11 — Duplex refuse PRESENTATION, une fois, sans micro
# ==========================================================================


async def test_duplex_architecture_refuses_presentation_visibly_once() -> None:
    from jarvis.domain.voice_architecture import VoiceArchitectureId
    from jarvis.runtime.presentation_runtime import (
        DUPLEX_REFUSAL_MESSAGE,
        PresentationCoordinator,
        PresentationWakeRouter,
        presentation_architecture_refusal,
    )
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
    from tests.unit.test_interaction_mode_follower import (
        FakeCore,
        FakeSignals,
        IdleWake,
        mode_changed,
        settle,
        stop,
        until,
    )
    from tests.unit.test_interaction_mode_follower import RecordingJournal as FollowerJournal

    journal, signals = FollowerJournal(), FakeSignals()
    builds: list[str] = []

    def build(session_id: str):  # noqa: ANN202
        builds.append(session_id)
        raise AssertionError("la séance (et son hub micro) ne doit jamais être construite")

    holder: dict[str, object] = {}
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=IdleWake(), journal=journal),
        build=build, journal=journal, signals=signals,
        precondition=lambda: presentation_architecture_refusal(holder["voice"]),
    )
    core = FakeCore()

    async def factory(context):  # noqa: ANN001
        raise AssertionError("aucune session temps réel n'est ouverte dans ce test")

    runtime = PersistentVoiceRuntime(
        wakeword=coordinator.router, core=core, realtime_factory=factory, auto_turn=True,
        conversation_architecture=VoiceArchitectureId.DUPLEX, presentation=coordinator,
    )
    holder["voice"] = runtime
    assert runtime.continuous, "Duplex est continu : la seule raison du refus est sa sortie autonome"
    task = asyncio.create_task(runtime.run())
    try:
        await until(lambda: core.listening == 1 and core.snapshot_reads == 1)
        core.publish(mode_changed("presentation", 1))
        await until(lambda: coordinator.entry_failures == 1)
        core.publish(mode_changed("presentation", 1))
        await settle()

        assert [message for message in signals.alerts if message] == [DUPLEX_REFUSAL_MESSAGE]
        refused = [entry for entry in journal.entries
                   if entry["data"].get("code") == "presentation_architecture_unsupported"]  # type: ignore[union-attr]
        assert [entry["kind"] for entry in refused] == ["presentation.runtime.entry_refused"]
        assert refused[0]["data"]["reason"] == "duplex_autonomous_output"  # type: ignore[index]
        assert refused[0]["level"] == "error"
        assert builds == [], "aucun hub construit, donc aucun micro ouvert"
        assert input_ownership.open_input_stream_count() == 0
        assert coordinator.turns is None
    finally:
        await stop(runtime, task)


# ==========================================================================
# Rework de la QA critique de la Slice 04 (F1, F2, F3, F4)
# ==========================================================================

#: Une corrélation réelle de la voie cerveau : `realtime:<uuid4>:item_<21>`, 72 caractères.
REAL_CONVERSATION = "fb1d4135-5e13-4a6f-bd34-95d18e1c2e12"
REAL_ITEM = "item_EOfhmg0qDMAExIjvXgr4z"
REAL_CORRELATION = f"realtime:{REAL_CONVERSATION}:{REAL_ITEM}"


async def test_f1_a_real_brain_correlation_stays_whole_and_clarify_is_spoken() -> None:
    """F1 : la corrélation du plan n'est plus coupée à 64, donc la clarification n'est pas « périmée »."""

    from tests.unit.test_presentation_addressed_turn import resource, say as say_room, topic
    from tests.unit.test_presentation_integration import _queued, _scheduler
    from tests.unit.test_v2_speech_scheduler import wait_for

    assert len(REAL_CORRELATION) == 72
    journal = RecordingJournal()
    store = build_store()
    say_room(store, 1, "compare les deux scenarios")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-scenario-a", locator="scene:obj-a")
    resource(store, "u-001", resource_id="r-scenario-b", locator="scene:obj-b")
    clock = S10Clock()
    service = build_service(store, clock=clock, journal=journal)
    arm(service, clock)
    turns = CountingTurns(service)
    plans: list[object] = []
    scheduler = _scheduler(service, journal=journal, correlation=REAL_CORRELATION)

    def note(text, **kwargs):  # noqa: ANN001, ANN003
        plans.append(kwargs.get("plan"))
        return scheduler.note_addressed_turn(text, **kwargs)

    bridge = RealtimeConversationBridge(
        core=BrainCoreDouble(), session=QueueSession(), conversation_id=REAL_CONVERSATION, audio=SilentAudio(),
        on_addressed=lambda: None, on_ambient=lambda: None, on_mute=lambda: None, continuous=True,
        auto_turn=True, journal=journal, clock=lambda: NOW, on_addressed_turn=note,
        presentation_turns=lambda: turns,
    )
    bridge._last_engaged = NOW
    await say(bridge, "montre-moi ça", REAL_ITEM)
    await wait_for(lambda: _queued(scheduler))

    [plan] = plans
    assert plan.action is AddressedTurnAction.CLARIFY
    assert plan.correlation_id == REAL_CORRELATION, "entière : c'est l'identité que Core rend"
    [question] = _queued(scheduler)
    assert question.kind is SpeechKind.QUESTION
    assert question.correlation_id == REAL_CORRELATION
    assert not [event for event in journal.events
                if event["data"].get("code") == "presentation_clarification_stale_turn"]
    # La trace, elle, reste bornée.
    [opened] = journal.of("presentation.addressed.opened")
    assert len(opened["data"]["correlation_id"]) == 64


async def test_f2_a_window_expiring_before_open_leaves_no_text_in_the_trace(tmp_path) -> None:
    """F2 : la fenêtre vue vivante expire avant `open()` ; la phrase ne touche pas `trace.jsonl`."""

    planted = "PHRASE-RACE-4291 budget secret"
    journal = RuntimeJournal(tmp_path)
    service, clock = live_service(journal)
    arm(service, clock)
    clock.advance(60.0)

    class StaleProbe(CountingTurns):
        def window_live(self) -> bool:
            return True  # le pré-contrôle l'a vue vivante

    bridge, core, calls = make_bridge(turns=StaleProbe(service), engaged=True, journal=journal)
    await say(bridge, planted)

    trace = journal.trace_path.read_text(encoding="utf-8")
    assert core.brain_turns == [] and calls.addressed == 0
    assert planted not in trace and "budget secret" not in trace
    kinds = [json.loads(line)["kind"] for line in trace.splitlines()]
    assert "voice.transcript_dropped" in kinds and "voice.transcript" not in kinds


async def test_f2_an_authorized_turn_still_says_its_text_after_the_open() -> None:
    """Le chemin attendu garde sa ligne `voice.transcript`, écrite après l'ouverture."""

    journal = RecordingJournal()
    service, clock = live_service(journal)
    arm(service, clock)
    bridge, core, _ = make_bridge(turns=service, engaged=False, journal=journal)
    await say(bridge, "montre la courbe des ventes")

    kinds = [event["kind"] for event in journal.events]
    assert kinds.index("presentation.addressed.opened") < kinds.index("voice.transcript")
    [line] = journal.of("voice.transcript")
    assert line["message"] == "montre la courbe des ventes"
    assert line["data"]["authority"] == TurnAuthority.EXPLICIT_ADDRESS.value
    assert len(core.brain_turns) == 1


async def test_f4_an_open_that_raises_uses_the_window_up() -> None:
    """F4 : `open()` lève ; la phrase passe sans plan, et la suivante, sans réarmement, est la salle."""

    service, clock = live_service()
    arm(service, clock)

    class Raising(CountingTurns):
        def open(self, text, *, correlation_id, spoken_at_s=None):  # noqa: ANN001
            raise RuntimeError("open broke")

    bridge, core, calls = make_bridge(turns=Raising(service), engaged=False)
    await say(bridge, "montre la courbe", "item-1")
    assert not service.window_live(), "la fenêtre a servi cette phrase, même ratée"
    await say(bridge, "le budget marketing a doublé cette année selon le rapport", "item-2")

    assert [turn["content"] for turn in core.brain_turns] == ["montre la courbe"]
    assert calls.ambient == 1


async def test_f3_an_unreadable_session_hears_the_vocative_only() -> None:
    """F3 : le lecteur de séance lève ; la salle ne passe pas, le vocatif si, et l'erreur est dite."""

    def reader():  # noqa: ANN202
        raise RuntimeError("boom")

    journal = RecordingJournal()
    bridge, core, calls = make_bridge(turns=reader, engaged=True, journal=journal)
    assert bridge.classifier.classify(ROOM, active=True, engaged=True) is AddressingDecision.ADDRESSED

    await say(bridge, ROOM, "item-1")
    assert core.brain_turns == [] and calls.addressed == 0

    await say(bridge, "Jarvis, quel est le total ?", "item-2")
    assert [turn["content"] for turn in core.brain_turns] == ["Jarvis, quel est le total ?"]
    errors = [event for event in journal.events if event["data"].get("code") == "presentation_turn_unreadable"]
    assert len(errors) == 2 and all(event["level"] == "error" for event in errors)
