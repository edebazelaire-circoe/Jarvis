"""La vie d'une séance PRESENTATION dans la ligne de temps canonique (Slice 10).

Handoff `jarvis-presentation-interaction-mode`, décisions P6/P7 et R4. Chaque
cas fait tourner le **vrai** producteur — `SpeechScheduler`, le service
spéculatif, le service d'attention, le coordinateur et sa composition — et un
vrai `ConversationEventForwarder` jamais démarré : `record()` ne fait que
mettre en file, et le test lit exactement ce qui partirait vers Core.

Ce que ce fichier épingle :

- une parole retenue par la politique ferme la demande du cerveau
  (`brain.speech.requested` → `mouth.speech.superseded`), sans orphelin ;
- une préparation est un span `subagent.*` qui ne porte **aucune** parole de
  la salle, pas même celle qu'une exception recopierait ;
- les trois types `system.*` neufs se valident contre leur spécification ;
- un point d'attention vivant est retiré à la fin de la séance ;
- un relais ou un port en panne ne change rien à la voie de préparation.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from jarvis.core.conversation_event_emitter import PRODUCER_BRAIN_SERVICE, build_conversation_event
from jarvis.core.presentation_attention import PresentationAttentionService
from jarvis.core.presentation_speculative import PresentationSpeculativeService
from jarvis.core.presentation_working_set import PresentationWorkingSetStore
from jarvis.domain.ambient_observation import AmbientTrigger, AmbientTriggerKind
from jarvis.domain.conversation_events import (
    ConversationActor,
    ConversationEventType as T,
    ConversationVisibility,
    EventShape,
    decode_conversation_event,
    encode_conversation_event,
    event_shape,
    reconstruct_conversation,
    validate_conversation_event,
)
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_speculative import SpeculativeAdmission
from jarvis.domain.presentation_working_set import (
    ClaimStatus,
    ObservationProvenance,
    PresentationClaim,
    PresentationObservation,
    PresentationSource,
    ResourceKind,
    UtteranceOrigin,
)
from jarvis.domain.v2 import SpeechKind, utc_now
from jarvis.runtime.presentation_runtime import (
    PresentationCoordinator,
    PresentationRefusal,
    PresentationWakeRouter,
)
from jarvis.runtime.presentation_timeline import (
    PREPARATION_SUBAGENT_TYPE,
    PRODUCER_PRESENTATION,
    PresentationTimeline,
)
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.fakes.conversation_events import queued, recording_forwarder
from tests.fakes.speech_context import context
import tests.unit.test_v2_speech_scheduler as scheduler_tests
from tests.unit.test_presentation_attention import _assessment, _evidence
from tests.unit.test_presentation_integration import FakeSimpleWake, composition
from tests.unit.test_presentation_speculative import NeverFinishingRunner, ScriptedRunner
from tests.unit.test_ambient_ingestion_lane import RecordingJournal as LaneJournal
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION,
    FakeCore,
    FakeVoiceSession,
    RecordingJournal,
    speech_envelope,
)

#: Une phrase de la salle, plantée partout où elle pourrait fuir.
PLANTED = "Ducroix a dit que la marge du troisième trimestre est de 31 pour cent"
#: Ce que les trois types `system.*` neufs peuvent porter : la liste blanche
#: existante, réduite à ce que P6 nomme.
SYSTEM_ATTRIBUTES = {"kind", "source", "reason", "revision", "code"}


@pytest.fixture(autouse=True)
def _fresh_speech_origin():
    # Même raison que `test_conversation_event_mouth_producers` : les demandes
    # de `speech_envelope` sont datées d'une origine réancrée par test.
    scheduler_tests.ORIGIN = utc_now()


def _timeline(forwarder=None, *, conversation: str | None = CONVERSATION) -> tuple[PresentationTimeline, object]:
    forwarder = forwarder if forwarder is not None else recording_forwarder()
    return PresentationTimeline(recorder=forwarder, conversation_id=lambda: conversation), forwarder


def _encoded_text(events) -> str:
    return "\n".join(str(encode_conversation_event(event)) for event in events)


def _seed(store: PresentationWorkingSetStore, session: str, *, claims: int = 3) -> None:
    """Des affirmations et deux sources réelles, sous la séance donnée."""

    # L'heure **réelle** : le magasin borne l'âge de ce qu'il garde, et un
    # instant figé dans le passé verrait tout balayé au premier rangement.
    now = utc_now()
    provenance = ObservationProvenance(utterance_id="utt-1", sequence=1, observed_at=now,
                                       origin=UtteranceOrigin.AMBIENT)
    for index in range(1, claims + 1):
        claim = PresentationClaim(
            claim_id=f"claim-{index}", statement=f"la marge du projet {_NAMES[index - 1]} progresse",
            provenance=provenance, first_seen_at=now, last_seen_at=now,
            status=ClaimStatus.ASSERTED, confidence=0.5, topic_id=None,
        )
        assert store.apply(PresentationObservation(f"claim-{index}", session, claim)).applied
    for index in (1, 2):
        source = PresentationSource(
            source_id=f"src-{index}", kind=ResourceKind.WEB_PAGE,
            reference=f"https://exemple.test/{index}", title=f"Source {index}", retrieved_at=now,
        )
        assert store.apply(PresentationObservation(f"src-{index}", session, source)).applied


_NAMES = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet")


class RecordingLifecycle:
    """Le port d'attention, réduit à ce qu'il reçoit."""

    def __init__(self) -> None:
        self.raised: list[tuple[str, str, str]] = []
        self.cleared: list[tuple[str, str, str, str]] = []

    def attention_raised(self, attention_id, *, session_id, category):  # noqa: ANN001
        self.raised.append((attention_id, session_id, category))

    def attention_cleared(self, attention_id, *, session_id, category, reason):  # noqa: ANN001
        self.cleared.append((attention_id, session_id, category, reason))


# ==========================================================================
# 1. Parole retenue : la demande du cerveau est soldée
# ==========================================================================


async def test_withheld_speech_closes_brain_request_in_reconstruction():
    """`brain.speech.requested` → `mouth.speech.superseded`, `reason=presentation_withheld`.

    Sans ce solde, la demande reste orpheline : la ligne de temps dit que le
    cerveau a demandé une parole et rien ne dit ce qu'elle est devenue.
    """

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    forwarder = recording_forwarder()
    scheduler = SpeechScheduler(core=core, conversation_id=CONVERSATION, session=session, journal=journal,
                                reconnect_delay_s=0.0, output_timeout_s=5.0, conversation_events=forwarder)
    scheduler.update_speech_context(context(CONVERSATION))
    # PRESENTATION, et aucun tour adressé : un résultat est retenu (`no_addressed_turn`).
    scheduler.interaction_mode = SimpleNamespace(mode=InteractionMode.PRESENTATION)
    await scheduler.start()
    try:
        envelope = speech_envelope("Voici le bilan détaillé.", kind=SpeechKind.RESULT, speech_id="speech-held")
        await core.publish(envelope)
        await journal.wait_until(lambda: journal.count("voice.presentation.speech_withheld") == 1)
    finally:
        await scheduler.stop()

    assert session.spoken == []
    events = queued(forwarder)
    assert [event.event_type for event in events] == [T.MOUTH_SPEECH_SUPERSEDED]
    [closed] = events
    assert closed.producer == "voice.speech_scheduler"
    assert dict(closed.attributes)["reason"] == "presentation_withheld"
    assert closed.visibility is ConversationVisibility.DIAGNOSTIC
    # Jamais tentée : la fermeture porte le texte retenu, et aucune heure de début.
    assert closed.content == "Voici le bilan détaillé." and closed.started_at is None

    # Le fait de Core, tel que Core l'enregistre (`BrainOrchestrator._emit_speech`).
    request = envelope.payload
    requested = build_conversation_event(
        T.BRAIN_SPEECH_REQUESTED, producer=PRODUCER_BRAIN_SERVICE, conversation_id=CONVERSATION,
        source_ids=("speech-held",), occurred_at=closed.occurred_at,
        correlation_id=request["correlation_id"], speech_id="speech-held", content="Voici le bilan détaillé.",
    )
    assert closed.parent_event_id == requested.event_id, "la fermeture rejoint la demande du cerveau"
    everything = [requested, *events]
    known = {event.event_id for event in everything}
    assert all(event.parent_event_id in (None, *known) for event in everything), "aucun parent orphelin"
    items = reconstruct_conversation(everything)
    [span] = [item for item in items if item.span_id == "speech-held"]
    assert (span.status, span.anomalies) == ("superseded", ())
    assert [item.event_type for item in items] == [T.BRAIN_SPEECH_REQUESTED, T.MOUTH_SPEECH_SUPERSEDED]


# ==========================================================================
# 2. Préparations : des spans de sous-agent, sans parole de la salle
# ==========================================================================


async def test_preparation_jobs_are_subagent_spans_without_room_text():
    """Admise → finie, échouée, retirée : trois spans, l'étiquette des capacités seulement.

    La phrase plantée est le texte du déclencheur **et** le message de
    l'exception de l'exécutant en échec : les deux chemins par lesquels de la
    parole pourrait entrer dans un événement.
    """

    timeline, forwarder = _timeline()

    async def run(runner, utterance: str, *, end: bool = False) -> PresentationSpeculativeService:
        # Une séance par travail : les numéros de travail repartent de zéro à
        # chaque séance, c'est l'identifiant de séance qui les distingue.
        session = f"pres-{utterance}"
        store = PresentationWorkingSetStore()
        assert store.bind_session(session).applied
        service = PresentationSpeculativeService(store=store, runner=runner,
                                                 lifecycle=timeline.for_session(session))
        assert service.bind_session(session) is SpeculativeAdmission.ACCEPTED
        trigger = AmbientTrigger(kind=AmbientTriggerKind.CHECKABLE_CLAIM, utterance_id=utterance,
                                 text=f"{PLANTED} ({utterance})", confidence=0.8)
        assert service.submit_trigger(trigger) is SpeculativeAdmission.ACCEPTED
        if end:
            await asyncio.sleep(0)
            service.end_session()
        await service.drain()
        return service

    await run(ScriptedRunner(), "u-1")
    await run(ScriptedRunner(boom=RuntimeError(PLANTED)), "u-2")
    never = NeverFinishingRunner()
    await run(never, "u-3", end=True)
    assert never.cancelled == 1

    events = queued(forwarder)
    assert PLANTED not in _encoded_text(events) and "Ducroix" not in _encoded_text(events)
    assert [event.event_type for event in events] == [
        T.SUBAGENT_STARTED, T.SUBAGENT_FINISHED,
        T.SUBAGENT_STARTED, T.SUBAGENT_FAILED,
        T.SUBAGENT_STARTED, T.SUBAGENT_STOPPED,
    ]
    for event in events:
        assert event.producer == PRODUCER_PRESENTATION and event.actor is ConversationActor.SUBAGENT
        assert event.conversation_id == CONVERSATION
        attributes = dict(event.attributes)
        assert attributes["subagent_type"] == PREPARATION_SUBAGENT_TYPE and attributes["background"] is True
        assert event.task_id == event.span_id and event.task_id.endswith(f"/{attributes['job_id']}")
        assert event.task_id.startswith("pres-u-") and attributes["job_id"].startswith("prep-")
        if event_shape(event.event_type) is EventShape.SPAN_OPEN:
            assert event.content == "fact_verification+research_search", "l'étiquette des capacités, rien d'autre"
        else:
            assert event.content is None
            assert isinstance(attributes["duration_ms"], int) and attributes["duration_ms"] >= 0
    closes = [dict(event.attributes) for event in events if event_shape(event.event_type) is EventShape.SPAN_CLOSE]
    assert [close["status"] for close in closes] == ["completed", "failed", "retired"]
    assert closes[2]["reason"] == "session_ended"
    statuses = [item.status for item in reconstruct_conversation(events)]
    assert statuses == ["finished", "failed", "stopped"]
    assert all(not item.anomalies for item in reconstruct_conversation(events))


# ==========================================================================
# 3. Les trois types neufs, produits par la vraie composition
# ==========================================================================


async def test_mode_change_and_attention_events_validate_against_specs(tmp_path):
    """Entrée, point levé, sortie (et son retrait), puis un refus d'entrée.

    Chaque événement est réencodé et redécodé par le codec : c'est la
    validation que Core appliquerait à l'ingestion.
    """

    timeline, forwarder = _timeline()
    journal = LaneJournal()
    built, _, _, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=replace(built, timeline=timeline).build, journal=journal, timeline=timeline,
    )
    await coordinator.apply(InteractionMode.PRESENTATION)
    stack = coordinator.stack
    assert stack is not None
    _seed(stack.store, stack.session_id)
    [decision] = stack.attention.raise_from_assessments(
        [_assessment(evidence=(_evidence(),), reason=PLANTED)], job_id="prep-0-1",
        session_id=stack.session_id, may_verify=True)
    assert decision.alerted, decision.code
    await coordinator.apply(InteractionMode.ASSISTANT)
    await coordinator.aclose()

    refused = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal, timeline=timeline,
        precondition=lambda: PresentationRefusal("Pas sur cette architecture.", "duplex_autonomous_output"),
    )
    await refused.apply(InteractionMode.PRESENTATION)
    await refused.aclose()

    events = [event for event in queued(forwarder) if event.actor is ConversationActor.SYSTEM]
    assert [event.event_type for event in events] == [
        T.SYSTEM_MODE_CHANGED, T.SYSTEM_ATTENTION_RAISED, T.SYSTEM_ATTENTION_CLEARED,
        T.SYSTEM_MODE_CHANGED, T.SYSTEM_MODE_CHANGED,
    ]
    for event in events:
        validate_conversation_event(encode_conversation_event(event))
        assert decode_conversation_event(encode_conversation_event(event)) == event
        assert event.producer == PRODUCER_PRESENTATION
        assert event_shape(event.event_type) is EventShape.INSTANT
        assert event.visibility is ConversationVisibility.DIAGNOSTIC
        assert event.content is None
        assert set(dict(event.attributes)) <= SYSTEM_ATTRIBUTES
    entered, raised, cleared, left, refusal = (dict(event.attributes) for event in events)
    assert (entered["kind"], entered["reason"]) == ("presentation", "entered")
    assert (raised["kind"], raised["source"]) == ("contradiction", "fact_check")
    assert (cleared["kind"], cleared["reason"]) == ("contradiction", "session_ended")
    assert (left["kind"], left["reason"], left["code"]) == ("simple", "left", "mode_left_presentation")
    assert (refusal["kind"], refusal["reason"], refusal["code"]) == (
        "simple", "entry_refused", "presentation_architecture_unsupported")
    assert PLANTED not in _encoded_text(queued(forwarder))
    # Une décision par fait : aucune identité partagée.
    assert len({event.event_id for event in events}) == len(events)


# ==========================================================================
# 4. Retrait à la fin de la séance, et à l'éviction
# ==========================================================================


def test_attention_cleared_at_session_end():
    """Chaque point encore vivant est retiré une fois ; un point évincé l'est plus tôt."""

    session = "pres-b"
    store = PresentationWorkingSetStore()
    assert store.bind_session(session).applied
    _seed(store, session, claims=10)
    story = RecordingLifecycle()
    service = PresentationAttentionService(store=store, lifecycle=story)
    for index in range(1, 10):
        [decision] = service.raise_from_assessments(
            [_assessment(claim_id=f"claim-{index}")], job_id=f"prep-0-{index}", session_id=session, may_verify=True)
        assert decision.alerted, decision.code
    assert len(story.raised) == 9

    # Le magasin garde huit points : le neuvième en a poussé un dehors.
    in_store = {item.attention_id for item in store.snapshot.working_set.attention}
    evicted = [entry for entry in story.cleared if entry[3] == "evicted"]
    assert len(evicted) == 1 and evicted[0][0] not in in_store
    assert set(service.live_ids) == in_store

    cleared = service.retire("session_ended")
    assert set(cleared) == in_store
    assert sorted(entry[0] for entry in story.cleared if entry[3] == "session_ended") == sorted(in_store)
    assert all(entry[1] == session and entry[2] == "contradiction" for entry in story.cleared)
    assert service.live_ids == () and service.counters.cleared == 9

    # Une seconde fin ne retire rien de plus.
    assert service.retire("session_ended") == ()
    assert len(story.cleared) == 9


# ==========================================================================
# 5. Un relais en panne ne touche pas la voie
# ==========================================================================


class _BrokenRecorder:
    def record(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError(PLANTED)


class _BrokenLifecycle:
    def preparation_started(self, job_id, *, label):  # noqa: ANN001
        raise RuntimeError("port en panne")

    def preparation_ended(self, job_id, *, outcome, status, reason=None):  # noqa: ANN001
        raise RuntimeError("port en panne")


async def test_recorder_failure_never_breaks_speculative_lane():
    """Relais qui lève, port qui lève : la préparation finit, la place est rendue."""

    journal = RecordingJournal()
    timeline = PresentationTimeline(recorder=_BrokenRecorder(), conversation_id=lambda: CONVERSATION,
                                    journal=journal)
    for lifecycle in (timeline.for_session("pres-c"), _BrokenLifecycle()):
        store = PresentationWorkingSetStore()
        assert store.bind_session("pres-c").applied
        service = PresentationSpeculativeService(store=store, runner=ScriptedRunner(), lifecycle=lifecycle)
        assert service.bind_session("pres-c") is SpeculativeAdmission.ACCEPTED
        trigger = AmbientTrigger(kind=AmbientTriggerKind.CHECKABLE_CLAIM, utterance_id="u-1", text=PLANTED,
                                 confidence=0.8)
        assert service.submit_trigger(trigger) is SpeculativeAdmission.ACCEPTED
        await service.drain()
        assert service.counters.completed == 1 and service.counters.failed == 0
        assert service.in_flight == () and service.free_explicit_slots == service.stats()["pool"]
        if isinstance(lifecycle, _BrokenLifecycle):
            assert service.counters.lifecycle_failures == 2
        else:
            # L'adaptateur avale et compte : le service ne voit rien.
            assert service.counters.lifecycle_failures == 0

    # Une ouverture refusée n'a pas de fermeture : rien n'est inventé.
    assert timeline.counters.failed == 1 and timeline.counters.skipped_unopened == 1
    # Dit une fois, sans le texte de l'exception.
    [line] = journal.of("voice.conversation_events.producer_failed")
    assert line["data"]["exception_type"] == "RuntimeError" and PLANTED not in str(line)

    # Sans conversation Voice vivante, rien n'est enregistré, et cela se compte.
    quiet, forwarder = _timeline(conversation=None)
    quiet.mode_changed("pres-d", kind="presentation", reason="entered")
    assert queued(forwarder) == [] and quiet.counters.skipped_no_conversation == 1
