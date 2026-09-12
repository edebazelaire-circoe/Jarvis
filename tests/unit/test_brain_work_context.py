"""Le cerveau voit le travail en cours tenu par Core (handoff work-state, tâche 12).

Trois moitiés :

- **contexte** : à chaque tour, Core lit son `WorkStateStore` — la source de
  `GET /v1/work/snapshot` — et remet au backend un `BrainWorkContext` borné
  (actifs d'abord, terminés récents ensuite), par la capacité optionnelle
  `run_turn_with_context` ; un backend qui ne la déclare pas garde `run_turn` ;
- **politique** : un travail actif qui échoue, s'interrompt ou se bloque est
  retenu pour le prochain tour et signalé au diagnostic, jamais prononcé ; un
  réveil éventuel est borné ;
- **consigne** : le Control Center rend ce contexte en quelques lignes, ce qui
  permet de répondre à « où en sont mes tâches ? » sans lire son propre suivi.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import web

from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_context import (
    BRAIN_WORK_CONTEXT_FAILED_KIND,
    BRAIN_WORK_CONTEXT_KIND,
    WORK_ATTENTION_KIND,
    WORK_ATTENTION_WAKE_FAILED_KIND,
    BrainContextBuilder,
    WorkAttentionPolicy,
)
from jarvis.core.brain_service import BRAIN_INTENT_REVISED, BRAIN_SPEECH_REQUESTED, BrainOrchestrator
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.core.work_state import CORE_WORK_UPDATED, WorkStateStore
from jarvis.domain.brain_context import (
    MAX_BRAIN_LABEL_CHARS,
    MAX_BRAIN_WORK_ACTIVE,
    MAX_BRAIN_WORK_ATTENTION,
    MAX_BRAIN_WORK_CONTEXT_CHARS,
    MAX_BRAIN_WORK_FINISHED,
    BrainContext,
    BrainWorkContext,
    BrainWorkEntry,
    WorkAttention,
    build_brain_work_context,
    needs_attention,
)
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainTurnInput,
    BrainTurnResult,
    BrainWorkingState,
    ProtocolEnvelope,
)
from jarvis.domain.work_state import WorkLink, WorkObservation, WorkStatus
from jarvis.ports.v2 import ContextAwareBrainBackend, supports_brain_context
from jarvis.runtime.control_center import build_agent_brief
from jarvis.runtime.work_brief import BRIEF_WORK_SOURCE_NOTE, MAX_BRIEF_WORK_LINES, render_work_brief

T0 = datetime(2026, 9, 11, 15, 0, tzinfo=timezone.utc)
REASONING_MARKERS = ("thought", "reason", "scratchpad", "chain_of", "cot", "internal_monologue", "deliberation")


# --- doubles -----------------------------------------------------------------


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


@dataclass(slots=True)
class RecordingSink:
    events: list[tuple[str, str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for recorded, _level, data in self.events if recorded == kind]


@dataclass(slots=True)
class ContextBackend:
    """Backend qui déclare la capacité et retient ce que Core lui remet."""

    contexts: list[BrainContext] = field(default_factory=list)
    legacy_calls: int = 0
    seen: asyncio.Event = field(default_factory=asyncio.Event)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.legacy_calls += 1
        return BrainTurnResult(correlation_id=turn.correlation_id)

    async def run_turn_with_context(self, turn: BrainTurnInput, context: BrainContext, emit) -> BrainTurnResult:
        self.contexts.append(context)
        self.seen.set()
        return BrainTurnResult(correlation_id=turn.correlation_id)


@dataclass(slots=True)
class LegacyBackend:
    """Backend d'avant la tâche 12 : `run_turn` seulement."""

    states: list[BrainWorkingState] = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.states.append(state)
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="Fait.")


class BrokenReader:
    async def snapshot(self):
        raise RuntimeError("store unavailable")


def obs(external_id: str, status: WorkStatus, at_s: float = 0, **fields) -> WorkObservation:
    return WorkObservation(
        source=fields.pop("source", "claude"),
        external_id=external_id,
        status=status,
        observed_at=T0 + timedelta(seconds=at_s),
        **fields,
    )


def drain(queue: asyncio.Queue[ProtocolEnvelope]) -> list[ProtocolEnvelope]:
    collected: list[ProtocolEnvelope] = []
    while True:
        try:
            collected.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return collected


async def settle(rounds: int = 20) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def wait_idle(brain: BrainOrchestrator) -> None:
    async def loop() -> None:
        while brain.active_turn_count:
            await asyncio.sleep(0)

    await asyncio.wait_for(loop(), timeout=5)


@dataclass(slots=True)
class Stack:
    brain: BrainOrchestrator
    events: CoreEventBus
    store: WorkStateStore
    policy: WorkAttentionPolicy
    builder: BrainContextBuilder
    diagnostics: RecordingSink
    clock: FixedClock
    conversation_id: str
    policy_task: asyncio.Task
    repository: SQLiteStateRepository

    async def close(self) -> None:
        try:
            self.policy_task.cancel()
            await asyncio.gather(self.policy_task, return_exceptions=True)
            await self.policy.stop()
        finally:
            try:
                await self.brain.stop()
            finally:
                await self.repository.close()


async def build_stack(tmp_path, backend, *, reader=None, jobs=None) -> Stack:
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    events = CoreEventBus()
    diagnostics = RecordingSink()
    clock = FixedClock(T0 + timedelta(minutes=5))
    store = WorkStateStore(events=events, diagnostics=diagnostics, clock=clock)
    policy = WorkAttentionPolicy(diagnostics=diagnostics, clock=clock)
    builder = BrainContextBuilder(reader=reader or store, store_id=store.store_id, attention=policy, diagnostics=diagnostics, clock=clock)
    brain = BrainOrchestrator(conversations=conversations, events=events, backend=backend, diagnostics=diagnostics, work_context=builder, jobs=jobs)
    conversation = await conversations.create()
    policy_task = asyncio.create_task(policy.run(events.subscribe(max_queue=512)))
    return Stack(brain, events, store, policy, builder, diagnostics, clock, conversation.id, policy_task, state)


def turn(conversation_id: str, text: str = "Où en sont mes tâches ?", correlation_id: str = "corr-1") -> BrainTurnInput:
    return BrainTurnInput(conversation_id=conversation_id, text=text, correlation_id=correlation_id)


# ===========================================================================
# Contexte borné
# ===========================================================================


async def test_active_work_comes_first_with_its_public_details():
    store = WorkStateStore(clock=FixedClock(T0))
    await store.apply(obs("done", WorkStatus.RUNNING, 0, label="Résumé des mails"))
    await store.apply(obs("done", WorkStatus.COMPLETED, 60, summary="3 mails importants."))
    await store.apply(obs("run", WorkStatus.RUNNING, 8, label="Analyse du dépôt", activity="Lecture de brain_service.py", model="claude-sonnet", progress_fraction=0.4))
    await store.apply(obs("wait", WorkStatus.RUNNING, 30, label="Choix du format"))
    await store.apply(obs("wait", WorkStatus.BLOCKED, 40))
    await store.apply(obs("boom", WorkStatus.RUNNING, 10, label="Recherche web"))
    await store.apply(obs("boom", WorkStatus.FAILED, 120, error_class="timeout"))

    context = build_brain_work_context(await store.snapshot(), now=T0 + timedelta(seconds=200), store_id=store.store_id)

    assert [entry.external_id for entry in context.items] == ["wait", "run", "boom", "done"]
    assert (context.active_total, context.finished_total, context.revision) == (2, 2, store.revision)
    running = context.items[1]
    assert (running.status, running.label, running.activity, running.model) == (
        WorkStatus.RUNNING, "Analyse du dépôt", "Lecture de brain_service.py", "claude-sonnet",
    )
    assert running.elapsed_s == 192 and running.ended_at is None and running.progress_fraction == 0.4
    failed = context.items[2]
    assert failed.error_class == "timeout" and failed.elapsed_s == 110 and failed.ended_ago_s == 80
    assert context.items[3].summary == "3 mails importants."


async def test_the_context_is_bounded_in_items_and_characters():
    store = WorkStateStore(clock=FixedClock(T0))
    for index in range(40):
        await store.apply(obs(f"old-{index}", WorkStatus.RUNNING, index, label="x" * 160))
        await store.apply(obs(f"old-{index}", WorkStatus.FAILED, 100 + index, summary="détail " * 140, error_class="boom"))
    for index in range(24):
        await store.apply(obs(f"live-{index}", WorkStatus.RUNNING, 200 + index, label="é" * 160, activity="a" * 160, summary="s" * 1000))

    context = build_brain_work_context(await store.snapshot(), now=T0 + timedelta(hours=1))
    payload = context.to_payload()

    assert (context.active_total, context.finished_total) == (24, 40)
    assert context.listed_active <= MAX_BRAIN_WORK_ACTIVE
    assert len(context.items) - context.listed_active <= MAX_BRAIN_WORK_FINISHED
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) <= MAX_BRAIN_WORK_CONTEXT_CHARS
    assert all(len(entry.label) <= MAX_BRAIN_LABEL_CHARS and entry.label.endswith("…") for entry in context.items)
    # Les actifs passent avant les terminés quand le budget manque.
    assert context.items and not context.items[0].status.is_terminal

    tight = build_brain_work_context(await store.snapshot(), now=T0 + timedelta(hours=1), max_chars=1500)
    assert len(json.dumps(tight.to_payload(), ensure_ascii=False, separators=(",", ":"))) <= 1500
    assert tight.active_total == 24 and len(tight.items) < len(context.items)


async def test_twelve_modest_active_entries_all_fit_in_the_budget():
    """La borne d'items est atteignable : ce n'est pas le budget qui coupe à 6."""

    store = WorkStateStore(clock=FixedClock(T0))
    for index in range(MAX_BRAIN_WORK_ACTIVE + 4):
        await store.apply(obs(f"live-{index}", WorkStatus.RUNNING, index, label=f"Tâche {index}", activity="Read · app.py"))

    context = build_brain_work_context(await store.snapshot(), now=T0 + timedelta(minutes=1))

    assert context.listed_active == MAX_BRAIN_WORK_ACTIVE and context.active_total == MAX_BRAIN_WORK_ACTIVE + 4
    assert len(json.dumps(context.to_payload(), ensure_ascii=False, separators=(",", ":"))) <= MAX_BRAIN_WORK_CONTEXT_CHARS


async def test_attention_notes_survive_a_full_budget_and_only_delivered_ones_are_consumed():
    """B1 : le poste chargé est justement celui où un échec doit passer."""

    events = CoreEventBus()
    queue = events.subscribe(max_queue=512)
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    for index in range(MAX_BRAIN_WORK_ACTIVE):
        await store.apply(obs(f"live-{index}", WorkStatus.RUNNING, index, label="é" * 160, activity="a" * 160, summary="s" * 400))
    for index in range(3):
        await store.apply(obs(f"boom-{index}", WorkStatus.RUNNING, 50 + index, label="B" * 160))
        await store.apply(obs(f"boom-{index}", WorkStatus.FAILED, 60 + index, error_class="timeout"))
    policy = WorkAttentionPolicy(clock=FixedClock(T0))
    for envelope in drain(queue):
        policy.consider(envelope)
    assert len(policy.pending) == 3

    context = build_brain_work_context(await store.snapshot(), now=T0 + timedelta(minutes=5), attention=policy.pending)

    assert [note.external_id for note in context.attention] == ["boom-0", "boom-1", "boom-2"]
    assert len(json.dumps(context.to_payload(), ensure_ascii=False, separators=(",", ":"))) <= MAX_BRAIN_WORK_CONTEXT_CHARS
    # Le budget est bien saturé : c'est la liste des actifs qui est coupée.
    assert 0 < context.listed_active < MAX_BRAIN_WORK_ACTIVE
    assert policy.take_delivered(context.attention) == 3 and policy.pending == ()


async def test_a_note_that_did_not_fit_is_not_erased():
    """Consommer, c'est avoir remis : une note coupée attend le tour suivant."""

    events = CoreEventBus()
    queue = events.subscribe(max_queue=512)
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    for index in range(4):
        await store.apply(obs(f"boom-{index}", WorkStatus.RUNNING, index, label="B" * 120))
        await store.apply(obs(f"boom-{index}", WorkStatus.FAILED, 10 + index, error_class="timeout"))
    policy = WorkAttentionPolicy(clock=FixedClock(T0))
    for envelope in drain(queue):
        policy.consider(envelope)

    context = build_brain_work_context(await store.snapshot(), now=T0 + timedelta(minutes=5), attention=policy.pending, max_chars=1200)
    consumed = policy.take_delivered(context.attention)

    delivered = {note.external_id for note in context.attention}
    assert 0 < len(delivered) < 4
    assert consumed == len(delivered)
    # Les plus récentes partent d'abord ; les plus anciennes restent en attente.
    assert [note.external_id for note in policy.pending] == [key for key in ("boom-0", "boom-1", "boom-2", "boom-3") if key not in delivered]


async def test_the_wire_form_carries_declared_public_fields_only():
    store = WorkStateStore(clock=FixedClock(T0))
    await store.apply(obs("run", WorkStatus.RUNNING, 0, label="Tâche", link=WorkLink(work_id="work-7", correlation_id="corr-7")))
    context = build_brain_work_context(await store.snapshot(), now=T0)
    [entry] = context.to_payload()["items"]

    assert set(entry) == {
        "source", "external_id", "status", "label", "activity", "summary", "model", "started_at", "ended_at",
        "elapsed_s", "ended_ago_s", "error_class", "work_id", "parent_external_id", "progress_fraction", "background",
    }
    assert entry["work_id"] == "work-7"
    assert set(context.to_payload()) == {"revision", "store_id", "generated_at", "active_total", "finished_total", "items", "attention"}
    for contract in (BrainWorkEntry, WorkAttention, BrainWorkContext, BrainContext):
        for name in (f.name for f in dataclasses.fields(contract)):
            assert not any(marker in name.lower() for marker in REASONING_MARKERS), f"{contract.__name__}.{name}"


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (WorkStatus.RUNNING, WorkStatus.FAILED, True),
        (WorkStatus.RUNNING, WorkStatus.INTERRUPTED, True),
        (WorkStatus.PENDING, WorkStatus.BLOCKED, True),
        (WorkStatus.BLOCKED, WorkStatus.FAILED, True),
        (None, WorkStatus.FAILED, False),
        (WorkStatus.BLOCKED, WorkStatus.BLOCKED, False),
        (WorkStatus.RUNNING, WorkStatus.RUNNING, False),
        (WorkStatus.RUNNING, WorkStatus.COMPLETED, False),
        (WorkStatus.RUNNING, WorkStatus.CANCELLED, False),
        (WorkStatus.COMPLETED, WorkStatus.FAILED, False),
    ],
)
def test_only_an_active_work_that_fails_stops_or_blocks_needs_attention(previous, current, expected):
    assert needs_attention(previous, current) is expected


# ===========================================================================
# Politique d'événements
# ===========================================================================


async def test_a_failure_of_active_work_is_retained_for_the_brain_and_never_spoken():
    events = CoreEventBus()
    diagnostics = RecordingSink()
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    policy = WorkAttentionPolicy(diagnostics=diagnostics, clock=FixedClock(T0))
    watcher = events.subscribe()
    task = asyncio.create_task(policy.run(events.subscribe()))
    try:
        await store.apply(obs("boom", WorkStatus.RUNNING, 0, label="Recherche web"))
        await store.apply(obs("boom", WorkStatus.FAILED, 30, error_class="timeout"))
        await settle()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    [note] = policy.pending
    assert (note.external_id, note.status, note.previous_status, note.error_class, note.label) == (
        "boom", WorkStatus.FAILED, WorkStatus.RUNNING, "timeout", "Recherche web",
    )
    assert note.revision == store.revision
    [diag] = diagnostics.of(WORK_ATTENTION_KIND)
    assert diag["status"] == "failed" and diag["previous_status"] == "running" and diag["wake"] is False
    # Scalaires seulement : pas de libellé ni de résumé dans la trace.
    assert "label" not in diag and "summary" not in diag
    # D17 : un changement d'état n'est pas une parole.
    assert {envelope.message_type for envelope in drain(watcher)} == {CORE_WORK_UPDATED}


async def test_progress_completion_cancellation_and_replayed_endings_are_not_retained():
    events = CoreEventBus()
    diagnostics = RecordingSink()
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    policy = WorkAttentionPolicy(diagnostics=diagnostics)
    queue = events.subscribe()

    await store.apply(obs("a", WorkStatus.RUNNING, 0, activity="Lecture"))
    await store.apply(obs("a", WorkStatus.RUNNING, 1, activity="Écriture"))
    await store.apply(obs("a", WorkStatus.COMPLETED, 2))
    await store.apply(obs("b", WorkStatus.RUNNING, 0))
    await store.apply(obs("b", WorkStatus.CANCELLED, 3, error_class="killed"))
    # Renvoi après un redémarrage de Core : l'élément naît déjà en échec.
    await store.apply(obs("c", WorkStatus.FAILED, 4, error_class="boom"))
    for envelope in drain(queue):
        assert policy.consider(envelope) is None

    assert policy.pending == () and diagnostics.of(WORK_ATTENTION_KIND) == []


async def test_retained_changes_are_bounded_and_one_per_work():
    events = CoreEventBus()
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    policy = WorkAttentionPolicy()
    queue = events.subscribe(max_queue=512)

    await store.apply(obs("hold", WorkStatus.RUNNING, 0))
    await store.apply(obs("hold", WorkStatus.BLOCKED, 1))
    await store.apply(obs("hold", WorkStatus.RUNNING, 2))
    await store.apply(obs("hold", WorkStatus.BLOCKED, 3))
    for index in range(12):
        await store.apply(obs(f"w{index}", WorkStatus.RUNNING, 10 + index))
        await store.apply(obs(f"w{index}", WorkStatus.INTERRUPTED, 30 + index, error_class="process_stopped"))
    for envelope in drain(queue):
        policy.consider(envelope)

    pending = policy.pending
    assert len(pending) == MAX_BRAIN_WORK_ATTENTION
    assert [note.external_id for note in pending] == [f"w{index}" for index in range(4, 12)]
    assert policy.noticed_total == 14
    assert policy.take_pending() == pending and policy.pending == ()


async def test_a_wake_is_rate_limited_does_not_consume_and_does_not_speak():
    events = CoreEventBus()
    diagnostics = RecordingSink()
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    monotonic = FakeMonotonic()
    woken: list[tuple[WorkAttention, ...]] = []

    async def wake(notes):
        woken.append(notes)

    policy = WorkAttentionPolicy(diagnostics=diagnostics, wake=wake, wake_interval_s=60.0, monotonic=monotonic)
    watcher = events.subscribe()
    queue = events.subscribe()

    async def fail(external_id: str, at_s: float) -> None:
        await store.apply(obs(external_id, WorkStatus.RUNNING, at_s))
        await store.apply(obs(external_id, WorkStatus.FAILED, at_s + 1, error_class="boom"))
        for envelope in drain(queue):
            policy.consider(envelope)
        await settle()

    await fail("a", 0)
    monotonic.value += 10
    await fail("b", 10)
    monotonic.value += 60
    await fail("c", 80)

    assert [[note.external_id for note in notes] for notes in woken] == [["a"], ["a", "b", "c"]]
    assert [data["wake"] for data in diagnostics.of(WORK_ATTENTION_KIND)] == [True, False, True]
    assert [note.external_id for note in policy.pending] == ["a", "b", "c"]
    assert policy.wake_total == 2
    assert {envelope.message_type for envelope in drain(watcher)} == {CORE_WORK_UPDATED}
    await policy.stop()


async def test_a_failing_wake_is_reported_once_and_the_policy_keeps_going():
    events = CoreEventBus()
    diagnostics = RecordingSink()
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    monotonic = FakeMonotonic()

    async def wake(notes):
        raise RuntimeError("brain down")

    policy = WorkAttentionPolicy(diagnostics=diagnostics, wake=wake, wake_interval_s=0.0, monotonic=monotonic)
    queue = events.subscribe()
    for name in ("a", "b"):
        await store.apply(obs(name, WorkStatus.RUNNING, 0))
        await store.apply(obs(name, WorkStatus.FAILED, 1, error_class="boom"))
        for envelope in drain(queue):
            policy.consider(envelope)
        await settle()

    assert [data["error"] for data in diagnostics.of(WORK_ATTENTION_WAKE_FAILED_KIND)] == ["RuntimeError"]
    assert len(policy.pending) == 2 and policy.wake_total == 2


async def test_attention_diagnostics_are_rate_limited_and_count_what_they_drop():
    events = CoreEventBus()
    diagnostics = RecordingSink()
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    monotonic = FakeMonotonic()
    policy = WorkAttentionPolicy(diagnostics=diagnostics, diagnostics_per_minute=2, monotonic=monotonic)
    queue = events.subscribe(max_queue=512)

    async def interrupt(names) -> None:
        for name in names:
            await store.apply(obs(name, WorkStatus.RUNNING, 0))
            await store.apply(obs(name, WorkStatus.INTERRUPTED, 1, error_class="process_stopped"))
        for envelope in drain(queue):
            policy.consider(envelope)

    await interrupt(["a", "b", "c", "d", "e"])
    monotonic.value += 61
    await interrupt(["f"])

    recorded = diagnostics.of(WORK_ATTENTION_KIND)
    assert [data["external_id"] for data in recorded] == ["a", "b", "f"]
    assert recorded[-1]["suppressed"] == 3


# ===========================================================================
# Tours cerveau
# ===========================================================================


async def test_a_context_aware_backend_receives_the_current_work_on_every_turn(tmp_path):
    backend = ContextBackend()
    stack = await build_stack(tmp_path, backend)
    try:
        await stack.store.apply(obs("toolu_A", WorkStatus.RUNNING, 0, label="Analyse du dépôt", activity="Lecture de x.py", model="claude-sonnet"))
        await stack.brain.submit(turn(stack.conversation_id))
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    [context] = backend.contexts
    assert backend.legacy_calls == 0
    assert context.state.conversation_id == stack.conversation_id
    work = context.work
    assert (work.store_id, work.revision) == (stack.store.store_id, stack.store.revision)
    [entry] = work.items
    assert (entry.label, entry.activity, entry.model, entry.status) == ("Analyse du dépôt", "Lecture de x.py", "claude-sonnet", WorkStatus.RUNNING)
    assert entry.elapsed_s == 300
    [diag] = stack.diagnostics.of(BRAIN_WORK_CONTEXT_KIND)
    assert diag["correlation_id"] == "corr-1" and diag["revision"] == stack.store.revision and diag["listed"] == 1


async def test_an_unexpected_failure_reaches_the_next_turn_once(tmp_path):
    backend = ContextBackend()
    stack = await build_stack(tmp_path, backend)
    try:
        await stack.store.apply(obs("boom", WorkStatus.RUNNING, 0, label="Recherche web"))
        await stack.store.apply(obs("boom", WorkStatus.FAILED, 30, error_class="timeout"))
        await settle()
        await stack.brain.submit(turn(stack.conversation_id, correlation_id="corr-1"))
        await wait_idle(stack.brain)
        await stack.brain.submit(turn(stack.conversation_id, "Et maintenant ?", correlation_id="corr-2"))
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    first, second = (context.work for context in backend.contexts)
    assert [(note.external_id, note.status) for note in first.attention] == [("boom", WorkStatus.FAILED)]
    assert second.attention == ()
    # L'échec reste un fait du travail, visible à chaque tour.
    assert [(entry.external_id, entry.status) for entry in second.items] == [("boom", WorkStatus.FAILED)]


async def test_a_busy_workstation_still_tells_the_brain_what_failed(tmp_path):
    """B1 : douze gros travaux actifs ne doivent pas effacer trois échecs."""

    backend = ContextBackend()
    stack = await build_stack(tmp_path, backend)
    try:
        for index in range(MAX_BRAIN_WORK_ACTIVE):
            await stack.store.apply(obs(f"live-{index}", WorkStatus.RUNNING, index, label="é" * 160, activity="a" * 160, summary="s" * 400))
        for index in range(3):
            await stack.store.apply(obs(f"boom-{index}", WorkStatus.RUNNING, 50 + index, label="B" * 160))
            await stack.store.apply(obs(f"boom-{index}", WorkStatus.FAILED, 60 + index, error_class="timeout"))
        await settle()
        await stack.brain.submit(turn(stack.conversation_id))
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    [context] = backend.contexts
    assert [note.external_id for note in context.work.attention] == ["boom-0", "boom-1", "boom-2"]
    assert context.work.listed_active < MAX_BRAIN_WORK_ACTIVE  # le budget a bien coupé les actifs
    assert stack.policy.pending == ()  # remis, donc consommés
    [diag] = stack.diagnostics.of(BRAIN_WORK_CONTEXT_KIND)
    assert diag["attention"] == 3


async def test_a_change_noticed_since_the_context_was_built_stays_pending():
    """Consommer se fait par note remise, jamais par vidage aveugle."""

    events = CoreEventBus()
    queue = events.subscribe(max_queue=512)
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    policy = WorkAttentionPolicy(clock=FixedClock(T0))

    await store.apply(obs("hold", WorkStatus.RUNNING, 0))
    await store.apply(obs("hold", WorkStatus.BLOCKED, 1))
    for envelope in drain(queue):
        policy.consider(envelope)
    delivered = policy.pending

    await store.apply(obs("hold", WorkStatus.RUNNING, 2))
    await store.apply(obs("hold", WorkStatus.BLOCKED, 3))
    for envelope in drain(queue):
        policy.consider(envelope)

    assert policy.take_delivered(delivered) == 0
    assert [note.revision for note in policy.pending] == [store.revision]


async def test_a_backend_without_the_capability_still_gets_run_turn(tmp_path):
    backend = LegacyBackend()
    stack = await build_stack(tmp_path, backend)
    assert not supports_brain_context(backend)
    try:
        await stack.store.apply(obs("boom", WorkStatus.RUNNING, 0))
        await stack.store.apply(obs("boom", WorkStatus.FAILED, 1, error_class="timeout"))
        await settle()
        await stack.brain.submit(turn(stack.conversation_id))
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    [state] = backend.states
    assert isinstance(state, BrainWorkingState)
    assert "Fait." in stack.brain.working_state(stack.conversation_id).known_public_facts
    # Rien n'a été lu pour lui : le changement attend un backend qui le transmette.
    assert len(stack.policy.pending) == 1
    assert stack.diagnostics.of(BRAIN_WORK_CONTEXT_KIND) == []


async def test_an_unreadable_work_state_sends_the_turn_without_work(tmp_path):
    backend = ContextBackend()
    stack = await build_stack(tmp_path, backend, reader=BrokenReader())
    try:
        await stack.brain.submit(turn(stack.conversation_id, correlation_id="corr-1"))
        await wait_idle(stack.brain)
        await stack.brain.submit(turn(stack.conversation_id, correlation_id="corr-2"))
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    assert [context.work for context in backend.contexts] == [None, None]
    assert [data["error"] for data in stack.diagnostics.of(BRAIN_WORK_CONTEXT_FAILED_KIND)] == ["RuntimeError"]


@dataclass(slots=True)
class HoldingBackend:
    """Ouvre `work-1`, attend, puis se solde : du travail cerveau reste actif."""

    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def run_turn_with_context(self, turn: BrainTurnInput, context: BrainContext, emit) -> BrainTurnResult:
        await emit.emit(BrainEvent(kind=BrainEventKind.ACCEPTED, conversation_id=turn.conversation_id, correlation_id=turn.correlation_id, work_id="work-1"))
        self.started.set()
        await self.release.wait()
        return BrainTurnResult(correlation_id=turn.correlation_id)

    async def run_turn(self, turn, state, emit):  # pragma: no cover - jamais appelé
        raise AssertionError("the capability must be preferred")


@dataclass(slots=True)
class RecordingCanceller:
    cancelled: list[str] = field(default_factory=list)

    async def cancel_work(self, work_id: str):
        self.cancelled.append(work_id)
        return ()


async def test_a_linked_work_failure_never_cancels_nor_revises_brain_work(tmp_path):
    """Annulation et supersession restent des décisions explicites du cerveau."""

    backend = HoldingBackend()
    canceller = RecordingCanceller()
    stack = await build_stack(tmp_path, backend, jobs=canceller)
    watcher = stack.events.subscribe(max_queue=512)
    try:
        await stack.brain.submit(turn(stack.conversation_id))
        await asyncio.wait_for(backend.started.wait(), timeout=5)
        await settle()
        before = stack.brain.working_state(stack.conversation_id)
        drain(watcher)

        await stack.store.apply(obs("job-1", WorkStatus.RUNNING, 0, source="job", link=WorkLink(work_id="work-1")))
        await stack.store.apply(obs("job-1", WorkStatus.FAILED, 5, source="job", error_class="boom"))
        await settle()
        after = stack.brain.working_state(stack.conversation_id)
        published = {envelope.message_type for envelope in drain(watcher)}

        backend.release.set()
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    assert [note.work_id for note in stack.policy.pending] == ["work-1"]
    assert after == before and after.active_work_ids == ("work-1",)
    assert canceller.cancelled == []
    assert published == {CORE_WORK_UPDATED}
    assert BRAIN_INTENT_REVISED not in published and BRAIN_SPEECH_REQUESTED not in published


# ===========================================================================
# Transport et consigne
# ===========================================================================


async def a_work_context() -> BrainWorkContext:
    events = CoreEventBus()
    queue = events.subscribe()
    store = WorkStateStore(events=events, clock=FixedClock(T0))
    await store.apply(obs("toolu_A", WorkStatus.RUNNING, 8, label="Analyse du dépôt", activity="Lecture de brain_service.py", model="claude-sonnet"))
    await store.apply(obs("toolu_B", WorkStatus.RUNNING, 10, label="Recherche web"))
    await store.apply(obs("toolu_B", WorkStatus.FAILED, 80, error_class="timeout"))
    policy = WorkAttentionPolicy()
    for envelope in drain(queue):
        policy.consider(envelope)
    return build_brain_work_context(await store.snapshot(), now=T0 + timedelta(seconds=200), store_id=store.store_id, attention=policy.take_pending())


async def serve_agent(seen: dict) -> tuple[ControlCenterBrainBackend, web.AppRunner]:
    async def handler(request: web.Request) -> web.Response:
        seen.update(await request.json())
        return web.json_response({"ok": True, "text": "fait"})

    app = web.Application()
    app.add_routes([web.post("/api/agent/ask", handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return ControlCenterBrainBackend(base_url=f"http://127.0.0.1:{port}", timeout_s=5), runner


class NullSink:
    async def emit(self, event: BrainEvent) -> None:
        return None


def test_the_context_capability_matches_its_production_adapter():
    """Même preuve structurelle que pour `BrainBackend` : le port et l'adaptateur réel."""

    assert [name for name in vars(ContextAwareBrainBackend) if not name.startswith("_")] == ["run_turn_with_context"]
    assert inspect.signature(ControlCenterBrainBackend.run_turn_with_context) == inspect.signature(
        ContextAwareBrainBackend.run_turn_with_context
    )


async def test_the_control_center_backend_carries_the_work_with_the_turn():
    work = await a_work_context()
    state = BrainWorkingState(conversation_id="conv-1", revision=3)
    seen_with: dict = {}
    seen_without: dict = {}
    backend, runner = await serve_agent(seen_with)
    try:
        assert supports_brain_context(backend)
        await backend.run_turn_with_context(turn("conv-1"), BrainContext(state=state, work=work), NullSink())
    finally:
        await backend.close()
        await runner.cleanup()
    backend, runner = await serve_agent(seen_without)
    try:
        await backend.run_turn_with_context(turn("conv-1"), BrainContext(state=state), NullSink())
    finally:
        await backend.close()
        await runner.cleanup()

    assert seen_with["context"]["work"] == work.to_payload()
    assert seen_with["context"]["state"] == state.to_rehydration_payload()
    assert set(seen_without["context"]) == {"addressing", "state"}


async def test_the_brief_lets_the_agent_answer_where_its_tasks_are():
    work = await a_work_context()
    brief = build_agent_brief(
        {"addressing": "addressed", "state": {"current_user_intent": "Où en sont mes tâches ?"}, "work": work.to_payload()},
        "Où en sont mes tâches ?",
    )

    assert "Tâches suivies par Core : 1 en cours, 1 terminée(s) récemment." in brief
    assert "- en cours depuis 3 min 12 s : « Analyse du dépôt » — activité : Lecture de brain_service.py — modèle : claude-sonnet" in brief
    assert "- échouée il y a 2 min (durée 1 min 10 s) : « Recherche web » — erreur : timeout" in brief
    assert "Nouveau depuis ton dernier tour : « Recherche web » échouée (timeout)." in brief
    assert BRIEF_WORK_SOURCE_NOTE in brief
    assert brief.index(BRIEF_WORK_SOURCE_NOTE) < brief.index("[Demande]")
    # Identifiants et horodatages restent dans la charge utile, pas dans la consigne.
    for leaked in ("toolu_A", work.store_id, "2026-09-11"):
        assert leaked not in brief


def test_a_brief_without_work_is_unchanged_and_an_empty_one_says_so():
    without = build_agent_brief({"addressing": "addressed"}, "Salut")
    empty = build_agent_brief({"addressing": "addressed", "work": {"revision": 0, "items": [], "attention": []}}, "Salut")

    assert "Tâches suivies par Core" not in without
    assert "Tâches suivies par Core : aucune." in empty


def test_a_hostile_work_payload_renders_a_bounded_brief():
    item = {"status": "running", "label": "L" * 5000, "activity": "a\nb" * 2000, "elapsed_s": "beaucoup", "progress_fraction": 7}
    lines = render_work_brief({"active_total": 10**9, "items": [item] * 500, "attention": [{"label": "x" * 5000}] * 500})

    assert len(lines) <= MAX_BRIEF_WORK_LINES + 4
    assert all(len(line) <= 2500 for line in lines)
    assert render_work_brief("pas un objet") == [] and render_work_brief(None) == []
