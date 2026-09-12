from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_service import (
    BRAIN_SPEECH_REQUESTED,
    BRAIN_STATE_UPDATED,
    BRAIN_TURN_ACCEPTED,
    BRAIN_WORK_COMPLETED,
    BRAIN_INTENT_REVISED,
    BRAIN_WORK_FAILED,
    BRAIN_WORK_PROGRESS,
    BRAIN_WORK_STARTED,
    NO_BACKEND_ERROR,
    BrainOrchestrator,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainRunStatus,
    BrainTurnInput,
    BrainTurnResult,
    ProtocolEnvelope,
    SpeechKind,
    SpeechProvenance,
    SpeechRequest,
    TurnKind,
)

# Clés documentées dans docs/handoff-realtime-brain/docs/05-event-contracts.md.
DOC_PAYLOAD_KEYS = {
    BRAIN_TURN_ACCEPTED: {"turn_id", "provider_item_id", "revision", "interrupted_speech_id"},
    BRAIN_STATE_UPDATED: {"revision", "current_user_intent", "active_work_ids", "unresolved_question_count", "completed_work_count"},
    BRAIN_WORK_STARTED: {"work_id", "job_id", "kind", "public_label"},
    BRAIN_WORK_PROGRESS: {"work_id", "job_id", "phase", "fraction", "public_summary"},
    BRAIN_WORK_COMPLETED: {"work_id", "job_id", "result_ref", "public_summary"},
    BRAIN_WORK_FAILED: {"work_id", "job_id", "error_class", "public_summary"},
    BRAIN_SPEECH_REQUESTED: {"speech_id", "text", "kind", "priority", "work_id", "supersedes_key", "interruptible", "expires_at", "provenance"},
    BRAIN_INTENT_REVISED: {"revision", "previous_revision", "superseded_work_ids", "cancelled_work_ids", "retained_work_ids"},
}


# --- doubles -----------------------------------------------------------------


@dataclass(slots=True)
class RecordingSink:
    """Puits de diagnostic de test."""

    events: list[tuple[str, str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _level, _data in self.events]


@dataclass(slots=True)
class SlowBackend:
    """Backend factice qui ne rend la main que sur ordre du test."""

    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    calls: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.calls.append(turn.correlation_id)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.append(turn.correlation_id)
            raise
        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id="work-1",
                speech=SpeechRequest(
                    conversation_id=turn.conversation_id,
                    text="Trois messages attendent une réponse.",
                    kind=SpeechKind.RESULT,
                    work_id="work-1",
                ),
            )
        )
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="Trois messages attendent une réponse.")


@dataclass(slots=True)
class ScriptedBackend:
    """Backend factice rejouant une séquence d'événements puis une issue."""

    events: tuple[BrainEventKind, ...] = ()
    status: BrainRunStatus = BrainRunStatus.COMPLETED
    error: str | None = None
    calls: list[str] = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.calls.append(turn.correlation_id)
        for kind in self.events:
            speech = None
            if kind is BrainEventKind.SPEECH:
                speech = SpeechRequest(conversation_id=turn.conversation_id, text="Je regarde.", kind=SpeechKind.PROGRESS, work_id="work-1")
            await emit.emit(
                BrainEvent(
                    kind=kind,
                    conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id,
                    work_id="work-1",
                    public_summary="Recherche des messages",
                    speech=speech,
                    error="mail_provider_unavailable" if kind is BrainEventKind.FAILED else None,
                )
            )
        return BrainTurnResult(correlation_id=turn.correlation_id, status=self.status, error=self.error)


@dataclass(slots=True)
class StateCapturingBackend:
    """Backend factice qui retient l'état public reçu à chaque tour."""

    states: list = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.states.append(state)
        return BrainTurnResult(correlation_id=turn.correlation_id)


@dataclass(slots=True)
class MisrouteBackend:
    """Backend factice qui rend un résultat portant une autre corrélation."""

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        return BrainTurnResult(correlation_id="corr-etrangere", public_summary="fait")


@dataclass(slots=True)
class ExplodingBackend:
    """Backend factice qui casse : la panne ne doit pas fuiter en clair."""

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        raise RuntimeError("token sk-secret-123 rejected by provider")


# --- utilitaires -------------------------------------------------------------


async def build_orchestrator(tmp_path, backend=None, diagnostics=None) -> tuple[BrainOrchestrator, ConversationService, CoreEventBus, SQLiteStateRepository, str]:
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    events = CoreEventBus()
    brain = BrainOrchestrator(conversations=conversations, events=events, backend=backend, diagnostics=diagnostics)
    conversation = await conversations.create()
    return brain, conversations, events, state, conversation.id


def drain(queue: asyncio.Queue[ProtocolEnvelope]) -> list[ProtocolEnvelope]:
    collected: list[ProtocolEnvelope] = []
    while True:
        try:
            collected.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return collected


async def wait_idle(brain: BrainOrchestrator) -> None:
    """Attendre que toutes les tâches cerveau soient soldées."""

    async def loop() -> None:
        while brain.active_turn_count:
            await asyncio.sleep(0)

    await asyncio.wait_for(loop(), timeout=5)


# --- acceptation asynchrone --------------------------------------------------


async def test_submit_returns_before_a_slow_backend_completes(tmp_path):
    backend = SlowBackend()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()

    turn = BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul.")
    acceptance = await brain.submit(turn)

    assert acceptance.duplicate is False
    assert acceptance.revision == 1
    assert acceptance.correlation_id == turn.correlation_id
    # L'accusé est rendu alors que le backend n'a même pas encore démarré.
    assert backend.calls == []
    assert brain.active_turn_count == 1

    await asyncio.wait_for(backend.started.wait(), timeout=5)
    assert [e.message_type for e in drain(queue)] == [BRAIN_TURN_ACCEPTED, BRAIN_INTENT_REVISED, BRAIN_STATE_UPDATED]

    backend.release.set()
    await wait_idle(brain)
    await state.close()


async def test_turn_accepted_is_published_before_result_speech(tmp_path):
    backend = SlowBackend()
    backend.release.set()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul."))
    await wait_idle(brain)

    ordered = [e.message_type for e in drain(queue)]
    assert ordered.index(BRAIN_TURN_ACCEPTED) < ordered.index(BRAIN_SPEECH_REQUESTED)
    assert ordered[0] == BRAIN_TURN_ACCEPTED
    await state.close()


async def test_persisted_turn_is_marked_authoritative(tmp_path):
    brain, _conversations, _events, state, conversation_id = await build_orchestrator(tmp_path, ScriptedBackend())
    turn = BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul.", provider_item_id="item_42")
    await brain.submit(turn)
    await wait_idle(brain)

    stored = await state.list_turns(conversation_id)
    assert [t.kind for t in stored] == [TurnKind.USER]
    assert stored[0].content == turn.text
    assert stored[0].correlation_id == turn.correlation_id
    assert stored[0].metadata["authoritative"] is True
    assert stored[0].metadata["provider_item_id"] == "item_42"
    await state.close()


async def test_unknown_conversation_is_refused_before_any_write(tmp_path):
    backend = ScriptedBackend()
    brain, _conversations, _events, state, _conversation_id = await build_orchestrator(tmp_path, backend)

    with pytest.raises(KeyError):
        await brain.submit(BrainTurnInput(conversation_id="conv-inconnue", text="bonjour"))
    assert brain.active_turn_count == 0
    assert backend.calls == []
    await state.close()


# --- déduplication (Décision 24) ---------------------------------------------


async def test_repeated_correlation_id_persists_and_dispatches_once(tmp_path):
    backend = ScriptedBackend()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()

    turn = BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul.")
    first = await brain.submit(turn)
    await wait_idle(brain)
    second = await brain.submit(turn)
    await wait_idle(brain)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.turn_id == first.turn_id
    assert second.revision == first.revision
    assert backend.calls == [turn.correlation_id]
    assert len(await state.list_turns(conversation_id)) == 1
    assert [e.message_type for e in drain(queue)].count(BRAIN_TURN_ACCEPTED) == 1
    await state.close()


async def test_provider_item_id_is_only_a_secondary_dedup_key(tmp_path):
    backend = ScriptedBackend()
    brain, _conversations, _events, state, conversation_id = await build_orchestrator(tmp_path, backend)

    first = await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Paul.", provider_item_id="item_42"))
    # Corrélation différente mais même identifiant fournisseur : c'est le même
    # tour vu deux fois par la surface, il ne doit pas être rejoué.
    second = await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Paul.", provider_item_id="item_42"))
    # Sans identifiant fournisseur, seule la corrélation compte : nouveau tour.
    third = await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Et Marie ?"))
    await wait_idle(brain)

    assert second.duplicate is True and second.turn_id == first.turn_id
    assert third.duplicate is False
    assert len(backend.calls) == 2
    assert len(await state.list_turns(conversation_id)) == 2
    await state.close()


# --- état structuré ----------------------------------------------------------


async def test_state_revisions_are_monotonic_and_carry_no_hidden_reasoning(tmp_path):
    backend = ScriptedBackend(events=(BrainEventKind.ACCEPTED, BrainEventKind.PROGRESS, BrainEventKind.COMPLETED))
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul."))
    await wait_idle(brain)

    published = drain(queue)
    revisions = [e.payload["revision"] for e in published if e.message_type == BRAIN_STATE_UPDATED]
    assert revisions == sorted(set(revisions))
    # Ni la progression (aucun identifiant de travail ne bouge) ni une issue
    # sans résumé public ne consomment de révision : un numéro de révision doit
    # désigner un changement réel, sinon il ne repère plus rien.
    assert revisions == [1, 2, 3]

    final = brain.working_state(conversation_id)
    assert final.active_work_ids == ()
    assert final.completed_work_ids == ("work-1",)
    assert final.current_user_intent == "Regarde les mails de Paul."

    for envelope in published:
        assert set(envelope.payload) <= DOC_PAYLOAD_KEYS[envelope.message_type] | {"conversation_id", "correlation_id", "duplicate", "created_at"}
    await state.close()


async def test_public_result_summary_becomes_a_known_public_fact(tmp_path):
    backend = SlowBackend()
    backend.release.set()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul."))
    await wait_idle(brain)

    final = brain.working_state(conversation_id)
    assert final.known_public_facts == ("Trois messages attendent une réponse.",)
    assert [e.message_type for e in drain(queue)][-1] == BRAIN_STATE_UPDATED
    await state.close()


async def test_a_cold_core_hands_the_brain_a_derived_state_not_an_empty_one(tmp_path):
    """Décision 38 : le premier tour après un redémarrage n'est pas aveugle.

    Un Core froid n'a rien en cache, mais les tours du processus précédent sont
    persistés. Le tour faisant autorité doit donc résoudre son état par la même
    dérivation que `rehydrate()` — celle qui promeut en fait public une parole
    cerveau de genre `result` réellement prononcée.
    """

    backend = StateCapturingBackend()
    _previous, conversations, events, state, conversation_id = await build_orchestrator(tmp_path)
    # Trace laissée par le processus d'avant : le cerveau a dit et l'utilisateur
    # a entendu. C'est tout ce qui survit au redémarrage.
    await conversations.append_turn(
        conversation_id,
        TurnKind.ASSISTANT,
        "Ton vol part à 7 h 40.",
        correlation_id="corr-precedente",
        metadata={"provenance": SpeechProvenance.BRAIN.value, "speech_kind": SpeechKind.RESULT.value},
    )

    # Core redémarre : nouvel orchestrateur, cache d'états vide, même magasin.
    cold = BrainOrchestrator(conversations=conversations, events=events, backend=backend)
    assert cold.working_state(conversation_id).known_public_facts == ()

    await cold.submit(BrainTurnInput(conversation_id=conversation_id, text="Et le retour ?"))
    await wait_idle(cold)

    assert len(backend.states) == 1
    handed = backend.states[0]
    assert handed.known_public_facts == ("Ton vol part à 7 h 40.",)
    assert handed.current_user_intent == "Et le retour ?"
    # La dérivation n'a lieu qu'une fois : le second tour repart du cache.
    await cold.submit(BrainTurnInput(conversation_id=conversation_id, text="Et l'hôtel ?"))
    await wait_idle(cold)
    assert backend.states[1].known_public_facts == ("Ton vol part à 7 h 40.",)
    assert backend.states[1].revision == handed.revision + 1
    await state.close()



async def test_a_cold_state_does_not_resurrect_an_unconfirmed_uncertain_turn(tmp_path):
    """Décision 44 : un tour incertain non confirmé ne revient pas en intention.

    Le tour est persisté — la Décision 06 l'exige, ce qui a été dit a été dit —
    mais rien dans le journal ne montre que le cerveau l'a pris : aucune parole
    ne porte sa corrélation. La reconstruction à froid doit donc s'arrêter à la
    dernière intention réellement autoritaire.
    """

    backend = StateCapturingBackend()
    _previous, conversations, events, state, conversation_id = await build_orchestrator(tmp_path)
    await conversations.append_turn(
        conversation_id,
        TurnKind.USER,
        "Jarvis fais les comptes",
        correlation_id="corr-adressee",
        metadata={"authoritative": True, "final": True, "addressing": "addressed"},
    )
    await conversations.append_turn(
        conversation_id,
        TurnKind.USER,
        "il faudrait vraiment que quelqu un rappelle le plombier demain matin",
        correlation_id="corr-incertaine",
        metadata={"authoritative": True, "final": True, "addressing": "uncertain"},
    )

    cold = BrainOrchestrator(conversations=conversations, events=events, backend=backend)
    assert (await cold.rehydrate(conversation_id))["current_user_intent"] == "Jarvis fais les comptes"
    await state.close()


async def test_a_cold_state_restores_an_uncertain_turn_the_brain_answered(tmp_path):
    """Le même tour, mais le cerveau lui a parlé : il redevient l'intention.

    La parole persistée porte la corrélation du tour incertain. C'est la trace
    durable de la confirmation faite en vol, et elle ne demande aucune écriture
    supplémentaire au moment de la promotion.
    """

    backend = StateCapturingBackend()
    _previous, conversations, events, state, conversation_id = await build_orchestrator(tmp_path)
    await conversations.append_turn(
        conversation_id,
        TurnKind.USER,
        "Jarvis fais les comptes",
        correlation_id="corr-adressee",
        metadata={"authoritative": True, "final": True, "addressing": "addressed"},
    )
    await conversations.append_turn(
        conversation_id,
        TurnKind.USER,
        "il faudrait vraiment que quelqu un rappelle le plombier demain matin",
        correlation_id="corr-incertaine",
        metadata={"authoritative": True, "final": True, "addressing": "uncertain"},
    )
    await conversations.append_turn(
        conversation_id,
        TurnKind.ASSISTANT,
        "J'ai laissé un message au plombier.",
        correlation_id="corr-incertaine",
        metadata={"provenance": SpeechProvenance.BRAIN.value, "speech_kind": SpeechKind.RESULT.value},
    )

    cold = BrainOrchestrator(conversations=conversations, events=events, backend=backend)
    rehydrated = await cold.rehydrate(conversation_id)
    assert rehydrated["current_user_intent"] == "il faudrait vraiment que quelqu un rappelle le plombier demain matin"
    await state.close()


async def test_a_cold_state_ignores_an_error_spoken_on_an_uncertain_turn(tmp_path):
    """Une panne de l'agent ne dit rien de l'adressage : elle ne confirme rien.

    Symétrique de la règle en vol, où `SpeechKind.ERROR` est le seul genre de
    parole exclu de la promotion.
    """

    backend = StateCapturingBackend()
    _previous, conversations, events, state, conversation_id = await build_orchestrator(tmp_path)
    await conversations.append_turn(
        conversation_id,
        TurnKind.USER,
        "Jarvis fais les comptes",
        correlation_id="corr-adressee",
        metadata={"authoritative": True, "final": True, "addressing": "addressed"},
    )
    await conversations.append_turn(
        conversation_id,
        TurnKind.USER,
        "il faudrait vraiment que quelqu un rappelle le plombier demain matin",
        correlation_id="corr-incertaine",
        metadata={"authoritative": True, "final": True, "addressing": "uncertain"},
    )
    await conversations.append_turn(
        conversation_id,
        TurnKind.ASSISTANT,
        "L'agent local n'a pas pu traiter la demande.",
        correlation_id="corr-incertaine",
        metadata={"provenance": SpeechProvenance.BRAIN.value, "speech_kind": SpeechKind.ERROR.value},
    )

    cold = BrainOrchestrator(conversations=conversations, events=events, backend=backend)
    assert (await cold.rehydrate(conversation_id))["current_user_intent"] == "Jarvis fais les comptes"
    await state.close()

async def test_backend_events_map_onto_the_documented_event_types(tmp_path):
    backend = ScriptedBackend(events=(BrainEventKind.ACCEPTED, BrainEventKind.PROGRESS, BrainEventKind.SPEECH, BrainEventKind.COMPLETED))
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()

    turn = BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul.")
    await brain.submit(turn)
    await wait_idle(brain)

    published = drain(queue)
    assert [e.message_type for e in published] == [
        BRAIN_TURN_ACCEPTED,
        BRAIN_INTENT_REVISED,
        BRAIN_STATE_UPDATED,
        BRAIN_WORK_STARTED,
        BRAIN_STATE_UPDATED,
        BRAIN_WORK_PROGRESS,
        BRAIN_SPEECH_REQUESTED,
        BRAIN_WORK_COMPLETED,
        BRAIN_STATE_UPDATED,
    ]
    # Toute publication d'un tour reste rattachable à ce que l'utilisateur a dit.
    assert {e.correlation_id for e in published} == {turn.correlation_id}
    assert {e.conversation_id for e in published} == {conversation_id}

    speech_payload = next(e.payload for e in published if e.message_type == BRAIN_SPEECH_REQUESTED)
    assert DOC_PAYLOAD_KEYS[BRAIN_SPEECH_REQUESTED] <= set(speech_payload)
    assert speech_payload["priority"] == "normal"
    assert speech_payload["provenance"] == "brain.speech"
    assert speech_payload["correlation_id"] == turn.correlation_id
    await state.close()


# --- échecs ------------------------------------------------------------------


async def test_backend_crash_is_published_as_a_class_and_detailed_only_in_diagnostics(tmp_path):
    sink = RecordingSink()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, ExplodingBackend(), diagnostics=sink)
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul."))
    await wait_idle(brain)

    failures = [e for e in drain(queue) if e.message_type == BRAIN_WORK_FAILED]
    assert len(failures) == 1
    assert failures[0].payload["error_class"] == "RuntimeError"
    assert "sk-secret-123" not in str(failures[0].payload)
    assert any("sk-secret-123" in str(data) for _kind, _level, data in sink.events)
    await state.close()


async def test_backend_reported_failure_is_reduced_to_a_stable_token(tmp_path):
    backend = ScriptedBackend(status=BrainRunStatus.FAILED, error="mail_provider_unavailable\nTraceback: ligne 42")
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul."))
    await wait_idle(brain)

    failures = [e for e in drain(queue) if e.message_type == BRAIN_WORK_FAILED]
    assert failures[0].payload["error_class"] == "mail_provider_unavailable"
    assert failures[0].payload["work_id"] is None
    await state.close()


async def test_result_from_another_correlation_is_treated_as_a_contract_breach(tmp_path):
    sink = RecordingSink()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, MisrouteBackend(), diagnostics=sink)
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul."))
    await wait_idle(brain)

    failures = [e for e in drain(queue) if e.message_type == BRAIN_WORK_FAILED]
    assert failures[0].payload["error_class"] == "backend_correlation_mismatch"
    assert "core.brain.backend_contract_violation" in sink.kinds()
    assert brain.working_state(conversation_id).known_public_facts == ()
    await state.close()


async def test_backend_reported_cancellation_publishes_nothing_but_leaves_a_trace(tmp_path):
    backend = ScriptedBackend(status=BrainRunStatus.CANCELLED)
    sink = RecordingSink()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend, diagnostics=sink)
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Laisse tomber."))
    await wait_idle(brain)

    assert [e.message_type for e in drain(queue)] == [BRAIN_TURN_ACCEPTED, BRAIN_INTENT_REVISED, BRAIN_STATE_UPDATED]
    assert "core.brain.turn_cancelled" in sink.kinds()
    await state.close()


# --- arrêt -------------------------------------------------------------------


@pytest.mark.parametrize("failure", ["exception", "failed_result", "wrong_correlation"])
async def test_terminal_turn_failure_settles_only_its_unfinished_backend_work(tmp_path, failure):
    class FailingAfterAcceptance:
        async def run_turn(self, turn, state, emit):
            async def event(kind, work_id):
                await emit.emit(BrainEvent(
                    kind=kind, conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id, work_id=work_id,
                ))

            await event(BrainEventKind.ACCEPTED, "orphan")
            await event(BrainEventKind.ACCEPTED, "finished")
            await event(BrainEventKind.COMPLETED, "finished")
            # Reporting another turn's work does not acquire its ownership.
            await event(BrainEventKind.PROGRESS, "independent")
            if failure == "exception":
                raise RuntimeError("backend disconnected after acceptance")
            if failure == "failed_result":
                return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.FAILED, error="backend_unavailable")
            return BrainTurnResult(correlation_id="wrong-correlation")

    class RecordingJobs:
        def __init__(self):
            self.cancelled = []

        async def cancel_work(self, work_id):
            self.cancelled.append(work_id)
            return ()

    sink = RecordingSink()
    brain, conversations, events, state, conversation_id = await build_orchestrator(tmp_path, FailingAfterAcceptance(), diagnostics=sink)
    jobs = RecordingJobs()
    brain._jobs = jobs
    queue = events.subscribe()
    other = await conversations.create()
    try:
        # Same work id in another conversation, and different work in this one.
        for owner_conversation, work_id in ((conversation_id, "independent"), (other.id, "orphan")):
            await brain._dispatch_backend_event(BrainEvent(
                kind=BrainEventKind.ACCEPTED, conversation_id=owner_conversation,
                correlation_id="other-turn", work_id=work_id,
            ))
        drain(queue)
        turn = BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails.")
        await brain.submit(turn)
        await wait_idle(brain)

        assert brain.working_state(conversation_id).active_work_ids == ("independent",)
        assert brain.working_state(conversation_id).completed_work_ids == ("finished",)
        assert brain.working_state(other.id).active_work_ids == ("orphan",)
        assert jobs.cancelled == []
        published = drain(queue)
        failures = [event for event in published if event.message_type == BRAIN_WORK_FAILED]
        assert [event.payload["work_id"] for event in failures] == ["orphan", None]
        expected_error = {"exception": "RuntimeError", "failed_result": "backend_unavailable", "wrong_correlation": "backend_correlation_mismatch"}[failure]
        assert all(event.payload["error_class"] == expected_error for event in failures)
        assert all(event.correlation_id == turn.correlation_id and event.conversation_id == conversation_id for event in failures)
        assert not any(event.message_type == BRAIN_SPEECH_REQUESTED for event in published)
        states = [event for event in published if event.message_type == BRAIN_STATE_UPDATED]
        assert states[-1].payload["active_work_ids"] == ["independent"]
        assert "core.brain.turn_failed" in sink.kinds() or "core.brain.backend_contract_violation" in sink.kinds()
        assert turn.correlation_id not in brain._work_owners.values()
        # Only the independent completion and the other conversation's two
        # measures remain. The failed work must leave neither timer behind.
        assert brain._latency.pending_count == 3
        await brain._dispatch_backend_event(BrainEvent(
            kind=BrainEventKind.COMPLETED, conversation_id=other.id,
            correlation_id="other-turn", work_id="orphan",
        ))
        other_completions = [data for kind, _level, data in sink.events if kind == "core.brain.latency.work_completed" and data["conversation_id"] == other.id]
        assert len(other_completions) == 1
        assert brain._latency.pending_count == 1
    finally:
        await brain.stop()
        await state.close()


async def test_stop_cancels_in_flight_brain_work_without_publishing_a_failure(tmp_path):
    backend = SlowBackend()
    sink = RecordingSink()
    brain, _conversations, events, state, conversation_id = await build_orchestrator(tmp_path, backend, diagnostics=sink)
    queue = events.subscribe()

    turn = BrainTurnInput(conversation_id=conversation_id, text="Regarde les mails de Paul.")
    await brain.submit(turn)
    await asyncio.wait_for(backend.started.wait(), timeout=5)

    await brain.stop()

    assert brain.active_turn_count == 0
    assert backend.cancelled == [turn.correlation_id]
    assert BRAIN_WORK_FAILED not in [e.message_type for e in drain(queue)]
    assert "core.brain.turn_cancelled" in sink.kinds()
    with pytest.raises(RuntimeError):
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="encore"))
    await state.close()


# --- intégration au composition root -----------------------------------------


async def test_core_starts_headless_and_reports_the_missing_brain_backend(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        assert core.health.ready is True
        queue = core.events.subscribe()
        conversation = await core.conversations.create()
        acceptance = await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, text="Bonjour."))
        assert acceptance.duplicate is False
        await wait_idle(core.brain)

        published = [e for e in drain(queue) if e.message_type.startswith("brain.")]
        assert [e.message_type for e in published] == [BRAIN_TURN_ACCEPTED, BRAIN_INTENT_REVISED, BRAIN_STATE_UPDATED, BRAIN_WORK_FAILED]
        assert published[-1].payload["error_class"] == NO_BACKEND_ERROR
    finally:
        await core.stop()


async def test_core_stop_settles_in_flight_brain_work(tmp_path):
    backend = SlowBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    conversation = await core.conversations.create()
    turn = BrainTurnInput(conversation_id=conversation.id, text="Cherche les mails de Paul.")
    await core.brain.submit(turn)
    await asyncio.wait_for(backend.started.wait(), timeout=5)
    assert core.brain.active_turn_count == 1

    await core.stop()

    assert core.health.status == "stopped"
    assert core.brain.active_turn_count == 0
    assert backend.cancelled == [turn.correlation_id]


async def test_core_injects_its_diagnostic_sink_into_the_event_bus(tmp_path):
    """Décision 25 : l'éviction d'un abonné saturé doit être diagnosticable.

    Le bus savait déjà le signaler, mais le composition root ne lui branchait
    aucun puits : l'éviction restait invisible en production.
    """

    sink = RecordingSink()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=sink)
    saturated = core.events.subscribe(max_queue=1)

    await core.events.publish(ProtocolEnvelope(message_type="brain.state.updated", payload={}, conversation_id="conv-1"))
    await core.events.publish(ProtocolEnvelope(message_type="brain.state.updated", payload={}, conversation_id="conv-1"))

    assert saturated.qsize() == 1
    assert core.events.evicted_total == 1
    assert CoreEventBus.EVICTION_KIND in sink.kinds()
