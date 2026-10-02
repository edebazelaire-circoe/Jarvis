"""Une seule parole : la porte de parole des Boards dans Core (handoff board-session, Slice 04b).

Core complet (`JarvisCoreApplication`), base temporaire, backend cerveau et
hôte des cerveaux simulés. Contrat : `docs/boards.md` › *Switch and speech
authority*. Aucune voix réelle : la « voix » est l'ensemble des
`brain.speech.requested` publiés sur le bus, seul chemin vers Voice.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from jarvis.core.brain_service import BRAIN_NOTICE_DROPPED_KIND, BRAIN_SPEECH_REQUESTED, BRAIN_SPEECH_WITHHELD_KIND
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import (
    BrainEvent, BrainEventKind, BrainTurnInput, BrainTurnResult, SpeechKind, SpeechRequest, utc_now,
)
from jarvis.domain.work_state import WorkObservation, WorkStatus
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID, BoardError, BoardErrorCode, BrainLifecycle
from jarvis.ports.workspace_board import BoardActivation


@dataclass
class Sink:
    lines: list[tuple[str, str, dict]] = field(default_factory=list)

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.lines.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for k, _, data in self.lines if k == kind]


class Host:
    def __init__(self) -> None:
        self.calls = []

    async def activate(self, binding) -> BoardActivation:
        self.calls.append(binding)
        return BoardActivation(agent_cli="claude", agent_session_id=None, previous_lifecycle=BrainLifecycle.SUSPENDED)


class Backend:
    """Répond « réponse: <texte> » ; une conversation dont la porte est fermée attend (travail de fond)."""

    def __init__(self) -> None:
        self.board_host = Host()
        self.gates: dict[str, asyncio.Event] = {}
        self.contexts = []

    async def run_turn(self, turn, state, emit) -> BrainTurnResult:
        gate = self.gates.get(turn.conversation_id)
        if gate is not None:
            await gate.wait()
        text = f"réponse: {turn.text}"
        await emit.emit(BrainEvent(
            kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id, correlation_id=turn.correlation_id,
            speech=SpeechRequest(conversation_id=turn.conversation_id, text=text, kind=SpeechKind.RESULT),
        ))
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=text)

    async def run_turn_with_context(self, turn, context, emit) -> BrainTurnResult:
        self.contexts.append((turn.conversation_id, context))
        return await self.run_turn(turn, context.state, emit)


@pytest.fixture
async def core(tmp_path):
    sink, backend = Sink(), Backend()
    app = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend, diagnostics=sink,
                                work_attention_wake_interval_s=0.01)
    await app.start()
    await asyncio.wait_for(app._host_align_task, timeout=5)
    queue = app.events.subscribe()
    try:
        yield app, backend, sink, queue
    finally:
        app.events.unsubscribe(queue)
        await app.stop()


def spoken(queue: asyncio.Queue) -> list[tuple[str, str]]:
    """Ce que Core a demandé à Voice de dire depuis le dernier appel : (conversation, texte)."""

    said = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.message_type == BRAIN_SPEECH_REQUESTED:
            said.append((event.conversation_id, event.payload["text"]))
    return said


async def settle(app) -> None:
    for _ in range(200):
        if not app.brain.active_turn_count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("brain turns did not settle")


async def ask(app, conversation_id: str, text: str) -> None:
    await app.brain.submit(BrainTurnInput(conversation_id=conversation_id, text=text))


# ------------------------------------------------------------------ une seule parole


async def test_exactly_one_board_speaks(core):
    app, _, sink, queue = core
    a = (await app.sessions.current()).binding
    b_board = await app.boards.create({"title": "Projet B"})
    b = await app.sessions.binding_for(a.jarvis_session_id, b_board.board_id)

    await ask(app, a.conversation_id, "A1")
    await ask(app, b.conversation_id, "B1")
    await settle(app)

    assert spoken(queue) == [(a.conversation_id, "réponse: A1")]
    withheld = sink.of(BRAIN_SPEECH_WITHHELD_KIND)
    assert [(w["board_id"], w["conversation_id"], w["origin"]) for w in withheld] == [
        (b_board.board_id, b.conversation_id, "speech")]
    assert withheld[0]["active_board_id"] == DEFAULT_BOARD_ID
    # Le résultat du Board silencieux reste durable : son cerveau le retrouvera.
    outcomes = await app.outcomes.list(b.conversation_id)
    assert [item["text"] for item in outcomes["outcomes"]] == ["réponse: B1"]


async def test_a_b_a_with_background_work_on_a_that_never_speaks(core):
    app, backend, sink, queue = core
    a = (await app.sessions.current()).binding
    b_board = await app.boards.create({"title": "Projet B"})
    backend.gates[a.conversation_id] = asyncio.Event()

    await ask(app, a.conversation_id, "long travail")          # A travaille, pas encore de réponse
    b = (await app.boards.switch(b_board.board_id)).binding     # B prend la parole
    await ask(app, b.conversation_id, "question B")
    backend.gates[a.conversation_id].set()                      # le travail de A finit pendant B
    await settle(app)

    assert spoken(queue) == [(b.conversation_id, "réponse: question B")]
    assert [w["conversation_id"] for w in sink.of(BRAIN_SPEECH_WITHHELD_KIND)] == [a.conversation_id]

    back = await app.boards.switch(DEFAULT_BOARD_ID)            # retour sur A : même conversation
    assert back.binding.conversation_id == a.conversation_id
    await ask(app, a.conversation_id, "et alors ?")
    await settle(app)
    assert spoken(queue) == [(a.conversation_id, "réponse: et alors ?")]
    # Le résultat de fond de A n'a jamais été dit, mais il est retenu.
    texts = [item["text"] for item in (await app.outcomes.list(a.conversation_id))["outcomes"]]
    assert "réponse: long travail" in texts


# ------------------------------------------------------------------ relais et réveils


async def test_notice_targets_the_active_binding_not_the_last_turn(core):
    app, _, sink, queue = core
    b_board = await app.boards.create({"title": "Projet B"})
    a = (await app.sessions.current()).binding
    b = (await app.boards.switch(b_board.board_id)).binding
    await ask(app, b.conversation_id, "B1")
    await settle(app)
    await ask(app, a.conversation_id, "A tardif")               # dernier tour reçu : A
    await settle(app)
    spoken(queue)

    assert await app.brain.announce_notice("Le sous-agent a fini.")
    assert spoken(queue) == [(b.conversation_id, "Le sous-agent a fini.")]


async def test_an_inactive_notice_is_withheld_and_traced(core):
    app, _, sink, queue = core
    a = (await app.sessions.current()).binding
    b_board = await app.boards.create({"title": "Projet B"})
    await app.boards.switch(b_board.board_id)
    spoken(queue)

    assert not await app.brain.announce_notice("Fini sur A.", conversation_id=a.conversation_id)
    assert spoken(queue) == []
    withheld = sink.of(BRAIN_SPEECH_WITHHELD_KIND)[-1]
    assert (withheld["origin"], withheld["board_id"], withheld["conversation_id"]) == (
        "notice", DEFAULT_BOARD_ID, a.conversation_id)


async def test_selecting_an_outcome_of_an_inactive_board_is_refused(core):
    app, _, sink, _ = core
    a = (await app.sessions.current()).binding
    await ask(app, a.conversation_id, "A1")
    await settle(app)
    outcome = (await app.outcomes.list(a.conversation_id))["outcomes"][0]
    b_board = await app.boards.create({"title": "Projet B"})
    await app.boards.switch(b_board.board_id)

    with pytest.raises(BoardError) as caught:
        await app.brain.select_outcome(a.conversation_id, outcome["id"], "sel-1")
    assert caught.value.code is BoardErrorCode.BRAIN_NOT_FOREGROUND
    assert sink.of(BRAIN_SPEECH_WITHHELD_KIND)[-1]["origin"] == "outcome_selection"


async def _observe(app, external_id: str, status: WorkStatus, board_id: str | None, *, at) -> None:
    await app.work_state.observe(WorkObservation(
        source="claude", external_id=external_id, status=status, observed_at=at, label=external_id,
        error_class="agent_failed" if status is WorkStatus.FAILED else None, board_id=board_id,
    ))


async def test_inactive_board_work_is_withheld_from_context_and_never_wakes(core):
    app, backend, sink, queue = core
    b_board = await app.boards.create({"title": "Projet B"})
    b = (await app.boards.switch(b_board.board_id)).binding
    t0 = utc_now()
    await _observe(app, "task-a", WorkStatus.RUNNING, DEFAULT_BOARD_ID, at=t0)
    await _observe(app, "task-b", WorkStatus.RUNNING, b_board.board_id, at=t0)
    await _observe(app, "task-free", WorkStatus.RUNNING, None, at=t0)
    await _observe(app, "task-a", WorkStatus.FAILED, DEFAULT_BOARD_ID, at=t0 + timedelta(seconds=1))
    await asyncio.sleep(0.1)

    # Un échec sur A (Board de fond) ne réveille pas le cerveau de B.
    assert sink.of("core.brain.woken_by_work") == []
    assert [n.board_id for n in app.work_attention.pending] == [DEFAULT_BOARD_ID]

    await ask(app, b.conversation_id, "où en est mon travail ?")
    await settle(app)
    _, context = backend.contexts[-1]
    listed = sorted(item.external_id for item in context.work.items)
    assert listed == ["task-b", "task-free"]
    assert context.work.attention == ()
    # Retenu, pas consommé : le retour sur A le remettra.
    assert [n.external_id for n in app.work_attention.pending] == ["task-a"]
    assert sink.of("core.brain.work_context")[-1]["other_boards"] == 1

    await _observe(app, "task-b", WorkStatus.FAILED, b_board.board_id, at=t0 + timedelta(seconds=2))
    for _ in range(100):
        if sink.of("core.brain.woken_by_work"):
            break
        await asyncio.sleep(0.01)
    assert [w["conversation_id"] for w in sink.of("core.brain.woken_by_work")] == [b.conversation_id]


async def test_a_wake_with_only_inactive_board_notes_is_withheld(core):
    app, _, sink, _ = core
    b_board = await app.boards.create({"title": "Projet B"})
    await app.boards.switch(b_board.board_id)
    from jarvis.domain.brain_context import WorkAttention

    note = WorkAttention(source="claude", external_id="x", status=WorkStatus.FAILED,
                         previous_status=WorkStatus.RUNNING, revision=1, noticed_at=utc_now(),
                         board_id=DEFAULT_BOARD_ID)
    assert not await app.brain.wake_for_work_attention((note,))
    assert sink.of("core.brain.wake_skipped")[-1]["reason"] == "inactive_board"
    withheld = sink.of(BRAIN_SPEECH_WITHHELD_KIND)[-1]
    assert withheld["origin"] == "work_wake"
    # Tracé au nom du travail (son Board), jamais de la conversation qui a la parole (QA 04b nit).
    assert withheld["board_id"] == DEFAULT_BOARD_ID
    assert withheld["conversation_id"] != withheld["active_conversation_id"]
    assert withheld["conversation_id"] is None


# ------------------------------------------------------------------ contexte du tour


async def test_every_turn_carries_its_board_block(core):
    app, backend, _, _ = core
    a = (await app.sessions.current()).binding
    await app.boards.update(DEFAULT_BOARD_ID, {"context_summary": "Refonte du site.", "task_refs": ["T-1"]})
    await ask(app, a.conversation_id, "on en est où ?")
    await settle(app)
    _, context = backend.contexts[-1]
    assert context.board.board_id == DEFAULT_BOARD_ID
    assert context.board.context_summary == "Refonte du site." and context.board.task_refs == ("T-1",)


async def test_a_job_is_tagged_with_the_board_of_its_conversation(core):
    app, _, _, _ = core
    a = (await app.sessions.current()).binding
    assert await app.sessions.board_of(a.conversation_id) == DEFAULT_BOARD_ID
    from jarvis.domain.v2 import Job

    job = Job(kind="unknown_kind", payload={}, requested_by_conversation_id=a.conversation_id)
    await app.jobs._observe_work(job, WorkStatus.RUNNING)
    item = next(i for i in (await app.work_state.snapshot()).items if i.external_id == job.id)
    assert item.board_id == DEFAULT_BOARD_ID


async def test_a_conversation_bound_to_no_board_is_not_gated(core):
    """Une conversation hors Board (d'avant les Boards, créée hors Session) n'est pas un Board : elle parle."""

    app, _, sink, queue = core
    loose = await app.conversations.create()
    await ask(app, loose.id, "hors Board")
    await settle(app)
    assert spoken(queue) == [(loose.id, "réponse: hors Board")]
    assert sink.of(BRAIN_SPEECH_WITHHELD_KIND) == []


# ------------------------------------------------------------------ seconde porte (QA Slice 04b, B1)
#
# Entrelacement déterministe : la parole de A passe la première porte, se gare
# sur un `await` avant la publication, la bascule vers B valide, puis A repart.
# Contrat : aucune parole de A n'est publiée après la bascule, un
# `core.brain.speech_withheld_inactive_board` (`late: true`) la trace, et
# l'issue durable reste retenue.


class Park:
    """Remplace une coroutine de l'orchestrateur : la première fois, se gare jusqu'à `release`."""

    def __init__(self, obj, name: str) -> None:
        self.obj, self.name, self.original = obj, name, getattr(obj, name)
        self.parked, self.release = asyncio.Event(), asyncio.Event()
        setattr(obj, name, self)

    async def __call__(self, *args, **kwargs):
        if not self.release.is_set():
            self.parked.set()
            await self.release.wait()
        return await self.original(*args, **kwargs)


def _order(queue: asyncio.Queue, a_conversation: str) -> list[tuple[str, str]]:
    from jarvis.core.speech_authority import BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED

    order = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.message_type in (BRAIN_SPEECH_REQUESTED, BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED):
            order.append((event.message_type, "A" if event.conversation_id == a_conversation else "B"))
    return order


async def _switch_while_parked(app, park: Park, pending: asyncio.Future, board_id: str):
    await asyncio.wait_for(park.parked.wait(), 5)
    result = await asyncio.wait_for(app.boards.switch(board_id), 5)
    park.release.set()
    return result, await asyncio.wait_for(pending, 10)


async def test_speech_parked_after_the_gate_is_withheld_when_the_switch_commits(core):
    app, _, sink, queue = core
    a = (await app.sessions.current()).binding
    b_board = await app.boards.create({"title": "Projet B"})
    park = Park(app.brain, "_promote_uncertain_turn")

    asking = asyncio.create_task(ask(app, a.conversation_id, "A1"))
    await _switch_while_parked(app, park, asking, b_board.board_id)
    await settle(app)

    order = _order(queue, a.conversation_id)
    assert (BRAIN_SPEECH_REQUESTED, "A") not in order, order
    withheld = sink.of(BRAIN_SPEECH_WITHHELD_KIND)[-1]
    assert (withheld["origin"], withheld["conversation_id"], withheld["late"]) == ("speech", a.conversation_id, True)
    assert withheld["board_id"] == DEFAULT_BOARD_ID and withheld["active_board_id"] == b_board.board_id
    texts = [item["text"] for item in (await app.outcomes.list(a.conversation_id))["outcomes"]]
    assert texts == ["réponse: A1"]                             # l'issue durable reste retenue


async def test_notice_parked_after_the_gate_is_withheld_when_the_switch_commits(core):
    app, _, sink, queue = core
    a = (await app.sessions.current()).binding
    await ask(app, a.conversation_id, "A1")                     # une intention courante porte le relais
    await settle(app)
    spoken(queue)
    b_board = await app.boards.create({"title": "Projet B"})
    park = Park(app.brain, "_promote_uncertain_turn")

    notice = asyncio.create_task(app.brain.announce_notice("Le sous-agent a fini."))
    _, published = await _switch_while_parked(app, park, notice, b_board.board_id)

    assert published is False
    assert (BRAIN_SPEECH_REQUESTED, "A") not in _order(queue, a.conversation_id)
    withheld = sink.of(BRAIN_SPEECH_WITHHELD_KIND)[-1]
    assert (withheld["origin"], withheld["conversation_id"], withheld["late"]) == ("notice", a.conversation_id, True)
    assert "Le sous-agent a fini." not in app.brain.working_state(a.conversation_id).known_public_facts


async def test_a_notice_withheld_at_the_late_gate_raises_one_alert_not_two(core):
    """Revue mainfix 30/09 (m1) : une retenue de la seconde porte est déjà tracée
    (`speech_withheld_inactive_board`) ; `announce_notice` n'y ajoute pas un
    `notice_dropped`, comme à la première porte — une seule alerte par relais."""

    app, _, sink, queue = core
    a = (await app.sessions.current()).binding
    await ask(app, a.conversation_id, "A1")
    await settle(app)
    spoken(queue)
    b_board = await app.boards.create({"title": "Projet B"})
    park = Park(app.brain, "_promote_uncertain_turn")

    notice = asyncio.create_task(app.brain.announce_notice("Le sous-agent a fini."))
    _, published = await _switch_while_parked(app, park, notice, b_board.board_id)

    assert published is False
    assert [w["late"] for w in sink.of(BRAIN_SPEECH_WITHHELD_KIND) if w["origin"] == "notice"] == [True]
    assert sink.of(BRAIN_NOTICE_DROPPED_KIND) == []


@pytest.mark.parametrize("parked_on, saved", [("context", False), ("save_brain_selection", True)])
async def test_outcome_selection_parked_after_the_gate_is_refused_when_the_switch_commits(core, parked_on, saved):
    app, _, sink, queue = core
    a = (await app.sessions.current()).binding
    await ask(app, a.conversation_id, "A1")
    await settle(app)
    spoken(queue)
    outcome = (await app.outcomes.list(a.conversation_id))["outcomes"][0]
    b_board = await app.boards.create({"title": "Projet B"})
    target = app.brain.outcomes if parked_on == "context" else app.brain.outcomes.repository
    park = Park(target, parked_on)

    selecting = asyncio.ensure_future(app.brain.select_outcome(a.conversation_id, outcome["id"], "sel-1"))
    await asyncio.wait_for(park.parked.wait(), 5)
    await asyncio.wait_for(app.boards.switch(b_board.board_id), 5)
    park.release.set()
    with pytest.raises(BoardError) as caught:
        await asyncio.wait_for(selecting, 10)

    assert caught.value.code is BoardErrorCode.BRAIN_NOT_FOREGROUND
    assert (BRAIN_SPEECH_REQUESTED, "A") not in _order(queue, a.conversation_id)
    withheld = sink.of(BRAIN_SPEECH_WITHHELD_KIND)[-1]
    assert (withheld["origin"], withheld["late"]) == ("outcome_selection", True)
    stored = await app.brain.outcomes.repository.get_brain_selection(a.conversation_id, "sel-1")
    assert (stored is not None) is saved                        # écrite avant le refus : elle reste durable


async def test_a_question_withheld_late_opens_no_question_in_the_working_state(core):
    app, backend, sink, queue = core
    a = (await app.sessions.current()).binding
    b_board = await app.boards.create({"title": "Projet B"})
    original = backend.run_turn

    async def ask_back(turn, state, emit):
        await emit.emit(BrainEvent(
            kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id, correlation_id=turn.correlation_id,
            speech=SpeechRequest(conversation_id=turn.conversation_id, text="Laquelle ?", kind=SpeechKind.QUESTION),
        ))
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="")

    backend.run_turn = ask_back
    park = Park(app.brain, "_promote_uncertain_turn")
    asking = asyncio.create_task(ask(app, a.conversation_id, "ouvre le fichier"))
    await _switch_while_parked(app, park, asking, b_board.board_id)
    await settle(app)
    backend.run_turn = original

    assert (BRAIN_SPEECH_REQUESTED, "A") not in _order(queue, a.conversation_id)
    assert app.brain.working_state(a.conversation_id).unresolved_questions == ()
    assert sink.of(BRAIN_SPEECH_WITHHELD_KIND)[-1]["late"] is True


async def test_a_conversation_bound_to_no_board_is_not_re_gated_before_publication(core):
    """Seconde porte : une conversation hors Board parle même si l'autorité bouge pendant sa parole."""

    app, _, sink, queue = core
    loose = await app.conversations.create()
    b_board = await app.boards.create({"title": "Projet B"})
    park = Park(app.brain, "_promote_uncertain_turn")

    asking = asyncio.create_task(ask(app, loose.id, "hors Board"))
    await _switch_while_parked(app, park, asking, b_board.board_id)
    await settle(app)

    assert (BRAIN_SPEECH_REQUESTED, "A") in _order(queue, loose.id)
    assert sink.of(BRAIN_SPEECH_WITHHELD_KIND) == []


async def test_a_speech_deferred_for_capacity_is_not_reported_as_withheld(core):
    """NIT QA 06/07 : un abandon hors porte n'est pas une retenue de la porte des Boards.

    Depuis la fusion avec les relais typés, `_emit_speech` rend un `_SpeechEmission` dont la
    raison distingue les deux ; aucune trace `speech_withheld` n'est écrite."""

    from jarvis.domain.v2 import SpeechPriority, SpeechProvenance

    app, _, sink, queue = core
    a = (await app.sessions.current()).binding
    text = "\n\n".join(f"Paragraphe {i}." for i in range(40))        # au-delà des 16 morceaux
    result = await app.brain._emit_speech(SpeechRequest(
        conversation_id=a.conversation_id, text=text, kind=SpeechKind.PROGRESS,
        priority=SpeechPriority.NORMAL, provenance=SpeechProvenance.BRAIN))
    assert not result.published and result.reason == "semantic_chunk_capacity"
    assert sink.of("core.brain.speech_deferred") and not sink.of(BRAIN_SPEECH_WITHHELD_KIND)
    assert spoken(queue) == []
