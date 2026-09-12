"""Magasin Core de l'état de travail (handoff work-state, tâche 11).

Ce qui doit tenir :

- Core est l'autorité : révision globale strictement croissante, un
  événement `core.work.updated` par changement et aucun pour un doublon ;
- un progrès en retard ne rouvre jamais un travail fini, même élagué ;
- la rétention est bornée, sans jamais sacrifier un travail actif ;
- une nouvelle instance de producteur interrompt les travaux de l'ancienne,
  et d'elle seule ; seul le revendicateur courant rouvre un travail que Core
  avait ainsi interrompu, jamais un producteur par ce qu'il écrit sur le fil ;
- le lot du fil est strict : un champ brut de fournisseur est refusé ;
- `JobService` est un observateur comme un autre, et son repli `job:<id>`
  n'est jamais un rattachement cerveau.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_context import WorkAttentionPolicy
from jarvis.core.v2_services import JOB_WORK_SOURCE, JOB_WORK_STATE_FAILED_KIND, CoreEventBus, JobService
from jarvis.core.work_state import (
    CAPACITY_OUTCOME,
    CORE_WORK_UPDATED,
    EVICTED_OUTCOME,
    MAX_EVICTED_KEYS,
    MAX_PRODUCERS,
    PRODUCER_RESTARTED,
    WORK_OBSERVATION_CONFLICT_KIND,
    WORK_OBSERVATION_IGNORED_KIND,
    WORK_PRODUCER_FORGOTTEN_KIND,
    WorkStateStore,
)
from jarvis.domain.v2 import Job, JobProgress, JobStatus, ProtocolEnvelope, utc_now
from jarvis.domain.work_state import (
    MAX_OBSERVATION_BATCH,
    MAX_WORK_ITEMS,
    OBSERVATION_WIRE_KEYS,
    WorkItem,
    WorkLink,
    WorkObservation,
    WorkObservationBatch,
    WorkStatus,
)
from jarvis.ports.work_state import WorkObservationSink, WorkStateReader

T0 = datetime(2026, 9, 11, 15, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def obs(external_id: str = "a1", status: WorkStatus = WorkStatus.RUNNING, t: float = 0.0, **fields) -> WorkObservation:
    fields.setdefault("source", "claude")
    return WorkObservation(external_id=external_id, status=status, observed_at=at(t), **fields)


@dataclass(slots=True)
class RecordingSink:
    events: list[tuple[str, str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for event_kind, _level, data in self.events if event_kind == kind]


def drain(queue: asyncio.Queue[ProtocolEnvelope]) -> list[ProtocolEnvelope]:
    collected = []
    while not queue.empty():
        collected.append(queue.get_nowait())
    return [event for event in collected if event.message_type == CORE_WORK_UPDATED]


@pytest.fixture
def bus() -> CoreEventBus:
    return CoreEventBus()


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def store(bus, sink) -> WorkStateStore:
    return WorkStateStore(events=bus, diagnostics=sink)


class CoreClock:
    """Horloge de Core, posée sur la même ligne de temps que les observations.

    Ce que Core date lui-même (l'instant d'une interruption) devient alors
    comparable à `at(...)`, comme sur une machine où le producteur et Core
    lisent la même horloge murale.
    """

    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:  # pragma: no cover - jamais attendu ici
        await asyncio.sleep(0)


@pytest.fixture
def core_clock() -> CoreClock:
    return CoreClock(at(2))


@pytest.fixture
def dated_store(bus, sink, core_clock) -> WorkStateStore:
    return WorkStateStore(events=bus, diagnostics=sink, clock=core_clock)


def test_the_store_implements_both_work_state_ports(store):
    sink: WorkObservationSink = store
    reader: WorkStateReader = store
    assert inspect.iscoroutinefunction(sink.observe) and inspect.iscoroutinefunction(reader.snapshot)


# ------------------------------------------------------------ révision, doublons


async def test_a_first_observation_creates_the_item_and_publishes_it(store, bus):
    queue = bus.subscribe()

    outcome = await store.apply(obs(label="Persist voice arch setting", activity="Read · app.py"))

    assert outcome == "created"
    snapshot = await store.snapshot()
    assert snapshot.revision == 1
    assert [item.external_id for item in snapshot.items] == ["a1"]
    [event] = drain(queue)
    assert event.payload["revision"] == 1
    assert event.payload["previous_status"] is None
    assert event.payload["store_id"] == store.store_id
    assert event.payload["item"] == snapshot.items[0].to_payload()


async def test_a_duplicate_observation_changes_nothing_and_publishes_nothing(store, bus):
    await store.apply(obs(activity="Read · app.py"))
    queue = bus.subscribe()

    outcome = await store.apply(obs(activity="Read · app.py", t=5))

    assert outcome == "duplicate"
    assert store.revision == 1
    assert drain(queue) == []
    assert store.outcome_totals == {"created": 1, "duplicate": 1}


async def test_an_ingested_batch_replayed_twice_is_idempotent(store):
    batch = WorkObservationBatch(
        source="claude",
        producer_id="cc-1",
        observations=(obs("a1", t=0), obs("a2", t=1), obs("a1", WorkStatus.COMPLETED, t=2, summary="Fait.")),
    )

    first = await store.ingest(batch)
    second = await store.ingest(batch)

    assert first.revision == 3 and dict(first.outcomes) == {"created": 2, "updated": 1}
    # Rejoué, le progrès de a1 bute sur sa fin : rien ne bouge, pas même la révision.
    assert second.revision == 3 and dict(second.outcomes) == {"duplicate": 2, "terminal": 1}
    assert second.store_id == store.store_id


async def test_revisions_advance_by_exactly_one_per_change(store, bus):
    queue = bus.subscribe()
    sequence = [
        obs("a1", t=0),
        obs("a1", t=1, activity="Read · app.py"),
        obs("a1", t=1, activity="Read · app.py"),  # doublon
        obs("a2", t=2),
        obs("a1", t=0.5, activity="ancien"),  # en retard
        obs("a1", WorkStatus.COMPLETED, t=3),
        obs("a1", WorkStatus.RUNNING, t=4),  # ne rouvre pas
        obs("a2", WorkStatus.FAILED, t=5),
    ]
    for observation in sequence:
        await store.apply(observation)

    revisions = [event.payload["revision"] for event in drain(queue)]
    assert revisions == [1, 2, 3, 4, 5]
    snapshot = await store.snapshot()
    assert snapshot.revision == revisions[-1]
    assert all(item.revision <= snapshot.revision for item in snapshot.items)


async def test_a_terminal_transition_carries_its_previous_status(store, bus):
    await store.apply(obs("a1", t=0))
    queue = bus.subscribe()

    await store.apply(obs("a1", WorkStatus.FAILED, t=1))

    [event] = drain(queue)
    assert event.payload["previous_status"] == "running"
    assert event.payload["item"]["status"] == "failed"


# ------------------------------------------------------------------ désordre


async def test_late_progress_never_reopens_a_completed_item(store, sink):
    await store.apply(obs("a1", t=0))
    await store.apply(obs("a1", WorkStatus.COMPLETED, t=10, summary="Fait."))

    stale = await store.apply(obs("a1", t=5, activity="Read · app.py"))
    later = await store.apply(obs("a1", t=20, activity="Edit · app.py"))

    assert stale == "terminal" and later == "terminal"
    [item] = (await store.snapshot()).items
    assert item.status is WorkStatus.COMPLETED and item.activity == "" and item.summary == "Fait."
    assert store.revision == 2
    # Refus d'un état terminal : signalé une fois par élément, pas à chaque progrès.
    assert [data["outcome"] for data in sink.of(WORK_OBSERVATION_IGNORED_KIND)] == ["terminal"]


async def test_late_progress_on_an_active_item_is_ignored_as_stale(store, sink):
    await store.apply(obs("a1", t=10, activity="Edit · app.py"))

    outcome = await store.apply(obs("a1", t=5, activity="Read · app.py"))

    assert outcome == "stale"
    assert (await store.snapshot()).items[0].activity == "Edit · app.py"
    assert sink.of(WORK_OBSERVATION_IGNORED_KIND) == []  # lot ordinaire d'un flux rejoué


async def test_a_late_terminal_observation_still_ends_the_item(store):
    await store.apply(obs("a1", t=10, activity="Edit · app.py"))

    outcome = await store.apply(obs("a1", WorkStatus.COMPLETED, t=5))

    assert outcome == "updated"
    [item] = (await store.snapshot()).items
    assert item.status is WorkStatus.COMPLETED


async def test_a_contradictory_link_keeps_the_first_and_is_reported(store, sink):
    await store.apply(obs("a1", t=0, link=WorkLink(work_id="work-1")))

    await store.apply(obs("a1", t=1, activity="Read · app.py", link=WorkLink(work_id="work-2")))

    [item] = (await store.snapshot()).items
    assert item.link.work_id == "work-1"
    assert sink.of(WORK_OBSERVATION_CONFLICT_KIND) == [{"source": "claude", "external_id": "a1", "fields": ["work_id"]}]


# ----------------------------------------------------------------- rétention


async def test_the_oldest_finished_item_is_evicted_first(bus, sink):
    store = WorkStateStore(events=bus, diagnostics=sink, max_items=3)
    await store.apply(obs("old", WorkStatus.COMPLETED, t=1))
    await store.apply(obs("recent", WorkStatus.COMPLETED, t=2))
    await store.apply(obs("active", t=0))

    await store.apply(obs("new", t=3))

    keys = [item.external_id for item in (await store.snapshot()).items]
    assert sorted(keys) == ["active", "new", "recent"]


async def test_active_items_are_never_evicted_and_overflow_is_refused(bus, sink):
    store = WorkStateStore(events=bus, diagnostics=sink, max_items=2)
    await store.apply(obs("a1", t=0))
    await store.apply(obs("a2", t=1))

    outcome = await store.apply(obs("a3", WorkStatus.COMPLETED, t=2))

    assert outcome == CAPACITY_OUTCOME
    assert sorted(item.external_id for item in (await store.snapshot()).items) == ["a1", "a2"]
    assert store.revision == 2
    assert sink.of(WORK_OBSERVATION_IGNORED_KIND)[0]["outcome"] == CAPACITY_OUTCOME


async def test_an_evicted_item_is_not_resurrected_by_a_late_replay(bus, sink):
    store = WorkStateStore(events=bus, diagnostics=sink, max_items=1)
    await store.apply(obs("done", WorkStatus.COMPLETED, t=0))
    await store.apply(obs("next", t=1))  # élague « done »

    outcome = await store.apply(obs("done", WorkStatus.COMPLETED, t=0))

    assert outcome == EVICTED_OUTCOME
    assert [item.external_id for item in (await store.snapshot()).items] == ["next"]


async def test_a_full_resend_never_resurrects_what_a_producer_can_still_hold(store):
    """La mémoire d'élagage couvre tout ce qu'un renvoi complet peut rejouer."""

    for index in range(MAX_EVICTED_KEYS // 2):
        await store.apply(obs(f"t{index}", WorkStatus.COMPLETED, t=index))
    replayed = [await store.apply(obs(f"t{index}", WorkStatus.COMPLETED, t=index)) for index in range(64)]

    assert set(replayed) == {EVICTED_OUTCOME}
    assert store.outcome_totals[EVICTED_OUTCOME] == 64


async def test_beyond_the_eviction_memory_a_late_replay_recreates_the_work(store):
    """Borne assumée : au-delà de `MAX_EVICTED_KEYS`, la clé est oubliée."""

    await store.apply(obs("first", WorkStatus.COMPLETED, t=0))
    # Les 64 premières créations remplissent le magasin : rien n'est élagué.
    for index in range(MAX_WORK_ITEMS + MAX_EVICTED_KEYS + 1):
        await store.apply(obs(f"t{index}", WorkStatus.COMPLETED, t=index + 1))

    assert await store.apply(obs("first", WorkStatus.COMPLETED, t=0)) == "created"


async def test_the_snapshot_never_exceeds_its_bound_under_a_long_stream(store):
    for index in range(500):
        await store.apply(obs(f"t{index}", t=index))
        await store.apply(obs(f"t{index}", WorkStatus.COMPLETED, t=index + 0.5))

    snapshot = await store.snapshot()
    assert len(snapshot.items) == 64
    assert snapshot.items[0].external_id == "t499"  # les plus récents restent


async def test_snapshot_lists_active_items_first(store):
    await store.apply(obs("done", WorkStatus.COMPLETED, t=0))
    await store.apply(obs("late", t=2))
    await store.apply(obs("early", t=1))

    assert [item.external_id for item in (await store.snapshot()).items] == ["early", "late", "done"]


# ------------------------------------------------------ disparition de l'hôte


async def test_a_new_producer_instance_interrupts_the_previous_one_active_work(store, sink):
    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0), obs("a2", WorkStatus.COMPLETED, t=1))))
    await store.ingest(WorkObservationBatch("job", "core", (obs("j1", t=0, source="job"),)))

    result = await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("b1", t=5),)))

    assert result.interrupted == 1
    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert items["a1"].status is WorkStatus.INTERRUPTED and items["a1"].error_class == PRODUCER_RESTARTED
    assert items["a2"].status is WorkStatus.COMPLETED  # une fin reste une fin
    assert items["j1"].status is WorkStatus.RUNNING  # une autre source n'est pas touchée
    assert items["b1"].status is WorkStatus.RUNNING
    assert sink.of("core.work.producer_restarted") == [{"source": "claude", "interrupted": 1}]


async def test_a_new_producer_never_kills_the_work_its_own_batch_reports(store):
    """B2 : deux Control Centers sur un Core faisaient battre le `producer_id`."""

    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0, activity="Read"), obs("a2", t=1))))

    result = await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("a1", t=5, activity="Edit"),)))

    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert result.interrupted == 1  # a2, dont le nouveau producteur ne parle pas
    assert items["a1"].status is WorkStatus.RUNNING and items["a1"].activity == "Edit"
    assert items["a2"].status is WorkStatus.INTERRUPTED


async def test_a_producer_that_takes_back_the_hand_reopens_the_work_it_still_runs(dated_store, bus):
    """B2 : `producer_restarted` n'est pas une fin, c'est une supposition révisable."""

    store = dated_store
    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0, label="Analyse"),)))
    await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("b1", t=1),)))
    assert (await store.snapshot()).items[0].external_id == "b1"
    queue = bus.subscribe()

    outcome = await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("a1", t=10, activity="Edit"),)))

    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert dict(outcome.outcomes) == {"updated": 1} and outcome.interrupted == 0
    assert items["a1"].status is WorkStatus.RUNNING and items["a1"].error_class is None
    assert items["a1"].ended_at is None and items["a1"].label == "Analyse" and items["a1"].activity == "Edit"
    [event] = drain(queue)
    assert event.payload["previous_status"] == "interrupted" and event.payload["item"]["status"] == "running"


async def test_a_genuinely_abandoned_item_stays_interrupted(store):
    """L'acceptation tâche 11 tient : ce dont personne ne reparle reste interrompu."""

    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0),)))
    await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("b1", t=1),)))

    for index in range(3):
        await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("b1", t=2 + index, activity=f"étape {index}"),)))

    [item] = [item for item in (await store.snapshot()).items if item.external_id == "a1"]
    assert item.status is WorkStatus.INTERRUPTED and item.error_class == PRODUCER_RESTARTED


async def test_only_a_producer_restart_reopens_a_terminal_item(store):
    """Aucune autre fin ne se rouvre : l'exception est étroite."""

    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0),)))
    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", WorkStatus.INTERRUPTED, t=1, error_class="process_stopped"),)))
    await store.apply(obs("a2", t=0))
    await store.apply(obs("a2", WorkStatus.COMPLETED, t=1))

    assert await store.apply(obs("a1", t=5)) == "terminal"
    assert await store.apply(obs("a2", t=5)) == "terminal"
    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert items["a1"].status is WorkStatus.INTERRUPTED and items["a2"].status is WorkStatus.COMPLETED


async def test_two_control_centers_taking_turns_do_not_thrash(bus, sink, core_clock):
    """R1 : deux instances qui alternent leurs lots ne se relancent pas sans fin.

    Chaque revendication n'emporte que le travail de l'instance remplacée, et
    seul le revendicateur courant rouvre : la reprise de main coûte une
    interruption par élément, puis l'état ne bouge plus. Avant ce correctif,
    chaque lot rouvrait ce que l'autre venait d'interrompre — 54 révisions et
    26 notes d'attention pour ces mêmes 14 lots.
    """

    store = WorkStateStore(events=bus, diagnostics=sink, clock=core_clock)
    queue = bus.subscribe()
    revisions = []
    for index in range(7):
        core_clock.current = at(index * 10 + 9)
        await store.ingest(
            WorkObservationBatch(
                "claude", "cc-1", (obs("a1", t=index * 10, activity=f"A{index}"), obs("a2", t=index * 10, activity=f"A{index}"))
            )
        )
        core_clock.current = at(index * 10 + 9.5)
        await store.ingest(
            WorkObservationBatch(
                "claude",
                "cc-2",
                (obs("b1", t=index * 10 + 5, activity=f"B{index}"), obs("b2", t=index * 10 + 5, activity=f"B{index}")),
            )
        )
        revisions.append(store.revision)

    # 4 créations puis 4 interruptions : le premier échange de mains les pose,
    # les cinq suivants ne changent plus rien.
    assert revisions == [6, 8, 8, 8, 8, 8, 8]
    policy = WorkAttentionPolicy()
    notes = [note for event in drain(queue) if (note := policy.consider(event)) is not None]
    assert len(notes) == 4  # une par élément, jamais renouvelée
    items = {item.external_id: item for item in (await store.snapshot()).items}
    # Le prix de cette borne, documenté tel quel dans `docs/ARCHITECTURE.md` :
    # au repos, plus rien ne bascule, mais *tout* finit interrompu — la dernière
    # instance à parler s'est fait reprendre ses éléments par l'autre.
    assert {item.status for item in items.values()} == {WorkStatus.INTERRUPTED}
    assert {item.error_class for item in items.values()} == {PRODUCER_RESTARTED}


async def test_forgetting_a_producer_claim_at_the_bound_is_reported_not_silent(bus, sink):
    """R3 : au-delà de `MAX_PRODUCERS`, la reprise de main se désarme — visiblement.

    La borne fait échouer dans le bon sens (aucun travail n'est tué à tort),
    mais elle coûte la garantie de la tâche 11 pour la source oubliée : la
    prochaine instance n'y trouve plus de revendicateur et n'interrompt rien.
    Ce test épingle les deux moitiés : l'oubli est signalé, et il a bien cette
    conséquence.
    """

    store = WorkStateStore(events=bus, diagnostics=sink)
    for index in range(MAX_PRODUCERS):
        await store.ingest(WorkObservationBatch(f"s{index}", "cc-1", (obs("a1", t=0, source=f"s{index}"),)))
    assert sink.of(WORK_PRODUCER_FORGOTTEN_KIND) == []

    # Une source de plus : la revendication la plus ancienne (`s0`) sort.
    await store.ingest(WorkObservationBatch("s99", "cc-1", (obs("a1", t=0, source="s99"),)))
    assert sink.of(WORK_PRODUCER_FORGOTTEN_KIND) == [{"source": "s0", "max_producers": MAX_PRODUCERS}]

    # Et sur `s0`, une nouvelle instance n'interrompt plus rien : l'élément de
    # l'instance remplacée reste actif jusqu'au redémarrage de Core.
    result = await store.ingest(WorkObservationBatch("s0", "cc-2", (obs("a2", t=1, source="s0"),)))
    items = {item.external_id: item for item in (await store.snapshot()).items if item.source == "s0"}
    assert result.interrupted == 0
    assert items["a1"].status is WorkStatus.RUNNING


async def test_a_producer_cannot_reopen_its_own_terminal_item_by_claiming_a_restart(dated_store):
    """R1 : `error_class` est du contenu de producteur, jamais une autorisation."""

    store = dated_store
    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0),)))
    await store.ingest(
        WorkObservationBatch(
            "claude", "cc-1", (obs("a1", WorkStatus.INTERRUPTED, t=1, error_class=PRODUCER_RESTARTED),)
        )
    )

    result = await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=2, activity="Edit"),)))

    [item] = [item for item in (await store.snapshot()).items if item.external_id == "a1"]
    assert dict(result.outcomes) == {"terminal": 1}
    assert item.status is WorkStatus.INTERRUPTED and item.activity == ""


async def test_an_observation_older_than_the_core_interruption_does_not_reopen(dated_store, core_clock):
    """R1 : un constat en retard reste en retard, même chez le revendicateur."""

    store = dated_store
    core_clock.current = at(11)
    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=5),)))
    await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("b1", t=11),)))

    result = await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("a1", t=5, activity="ancien"),)))

    [item] = [item for item in (await store.snapshot()).items if item.external_id == "a1"]
    assert dict(result.outcomes) == {"stale": 1}
    assert item.status is WorkStatus.INTERRUPTED and item.activity == ""


async def test_a_producer_restart_only_interrupts_what_core_attributes_to_it(store):
    """R1 : l'instance remplacée n'emporte que ses propres éléments."""

    await store.apply(obs("core-side", t=0))  # observé par Core même : aucun producteur
    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0),)))

    result = await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("b1", t=1),)))

    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert result.interrupted == 1
    assert items["a1"].status is WorkStatus.INTERRUPTED
    assert items["core-side"].status is WorkStatus.RUNNING


async def test_the_producer_attribution_never_reaches_a_payload(store, bus):
    """R1 : l'attribution est privée à Core — ni le bus ni l'instantané ne la portent."""

    producers = ("control-center-instance-one", "control-center-instance-two")
    queue = bus.subscribe()
    await store.ingest(WorkObservationBatch("claude", producers[0], (obs("a1", t=0),)))
    await store.ingest(WorkObservationBatch("claude", producers[1], (obs("b1", t=1),)))

    payloads = [event.payload for event in drain(queue)]
    keys = {key for payload in payloads for key in payload} | {key for payload in payloads for key in payload["item"]}
    assert not any(key.startswith(("producer", "owner")) for key in keys)
    rendered = repr(payloads) + repr((await store.snapshot()).to_payload())
    assert all(producer not in rendered for producer in producers)


async def test_a_terminal_observation_never_reopens_an_interrupted_item(store):
    """Une fin arrivée après coup reste refusée : la première fin fait foi."""

    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0),)))
    await store.ingest(WorkObservationBatch("claude", "cc-2", (obs("b1", t=1),)))

    assert await store.apply(obs("a1", WorkStatus.COMPLETED, t=10)) == "terminal"
    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert items["a1"].status is WorkStatus.INTERRUPTED


async def test_the_same_producer_is_not_interrupted_by_its_own_batches(store):
    await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a1", t=0),)))

    result = await store.ingest(WorkObservationBatch("claude", "cc-1", (obs("a2", t=1),)))

    assert result.interrupted == 0
    assert all(item.status is WorkStatus.RUNNING for item in (await store.snapshot()).items)


async def test_the_bus_carries_only_the_normalized_public_item(store, bus):
    queue = bus.subscribe()

    await store.apply(obs("a1", t=0, label="Persist", model="claude-opus-5", tokens=12, tool_uses=3))

    [event] = drain(queue)
    assert set(event.payload) == {"store_id", "revision", "previous_status", "item"}
    assert set(event.payload["item"]) == set(WorkItem.from_observation(obs("a1"), revision=1).to_payload())
    assert not {"prompt", "raw", "subagent_type", "tool_use_id", "trace"} & set(event.payload["item"])


async def test_voice_ignores_work_updates_they_are_not_speech(store, bus):
    """D17 : un changement d'état n'est pas une prise de parole, ni une activité utile."""

    from jarvis.runtime.speech_scheduler import SpeechScheduler

    class NoSession:
        def __getattr__(self, name):  # noqa: ANN001, ANN204
            raise AssertionError(f"la surface ne doit pas être sollicitée ({name})")

    activity: list[int] = []
    scheduler = SpeechScheduler(core=None, conversation_id="conv-1", session=NoSession(), on_brain_activity=lambda: activity.append(1))
    queue = bus.subscribe()
    await store.apply(obs("a1", t=0))
    await store.apply(obs("a1", WorkStatus.FAILED, t=1))

    for event in drain(queue):
        await scheduler.handle_core_event(event)

    assert activity == [] and scheduler.pending_count == 0


# ----------------------------------------------------------------- fil strict


def batch_payload(**overrides) -> dict:
    payload = WorkObservationBatch("claude", "cc-1", (obs("a1", t=0, label="Persist"),)).to_payload()
    payload.update(overrides)
    return payload


def test_the_wire_keys_are_exactly_those_of_an_observation_payload():
    assert OBSERVATION_WIRE_KEYS == set(obs().to_payload())


def test_a_batch_round_trips_through_the_wire():
    batch = WorkObservationBatch("claude", "cc-1", (obs("a1", t=0, label="Persist", started_at=at(-1)),))

    assert WorkObservationBatch.from_payload(batch.to_payload()) == batch


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda payload: payload.update(trace=[{"raw": {}}]), "unknown fields"),
        (lambda payload: payload["observations"][0].update(prompt="Rends le réglage persistant."), "unknown fields"),
        (lambda payload: payload["observations"][0].update(raw={"type": "system"}), "unknown fields"),
        (lambda payload: payload["observations"][0].update(subagent_type="general-purpose"), "unknown fields"),
        (lambda payload: payload.update(observations=[]), "between 1 and"),
        (lambda payload: payload.update(observations=payload["observations"] * (MAX_OBSERVATION_BATCH + 1)), "between 1 and"),
        (lambda payload: payload["observations"][0].update(status="exploded"), r"observations\[0\]"),
        (lambda payload: payload["observations"][0].update(source="codex"), "batch source"),
        (lambda payload: payload.update(producer_id=""), "producer_id"),
        (lambda payload: payload["observations"][0].update(label="x" * 500), r"observations\[0\]"),
    ],
)
def test_the_batch_wire_form_is_strict(mutate, message):
    payload = batch_payload()
    mutate(payload)

    with pytest.raises((TypeError, ValueError), match=message):
        WorkObservationBatch.from_payload(payload)


# ------------------------------------------------------------- JobService


@dataclass(slots=True)
class ScriptedWorker:
    steps: tuple[JobProgress, ...] = ()
    error: Exception | None = None

    async def execute_with_progress(self, job: Job, progress) -> dict[str, object]:
        for step in self.steps:
            await progress.emit(job.id, step)
        if self.error is not None:
            raise self.error
        return {"ok": True}

    async def cancel(self, job_id: str) -> None:
        del job_id


class BrokenSink:
    async def observe(self, observation: WorkObservation) -> None:
        raise RuntimeError("magasin en panne")


async def run_job(tmp_path, worker, *, work_state, diagnostics=None, **submit):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    jobs = JobService(state, CoreEventBus(), {"mail_search": worker}, diagnostics=diagnostics, work_state=work_state, progress_min_interval_s=0)
    job = await jobs.submit(Job(kind="mail_search", payload={}), **submit)
    await asyncio.wait_for(asyncio.gather(*jobs._running.values(), return_exceptions=True), timeout=5)
    stored = [item for item in await state.list_jobs() if item.id == job.id][0]
    await state.close()
    return job, stored


async def test_a_job_is_observed_from_start_to_completion_with_its_explicit_link(tmp_path, store):
    worker = ScriptedWorker(steps=(JobProgress(phase="scan", fraction=0.5, public_summary="Analyse des mails"),))

    job, _ = await run_job(tmp_path, worker, work_state=store, work_id="work-7", correlation_id="turn-7")

    [item] = (await store.snapshot()).items
    assert item.key == (JOB_WORK_SOURCE, job.id)
    assert item.status is WorkStatus.COMPLETED and item.kind == "job" and item.label == "mail_search"
    assert item.link == WorkLink(work_id="work-7", correlation_id="turn-7")
    assert item.progress_fraction == 0.5
    assert store.outcome_totals == {"created": 1, "updated": 2}  # running, progrès, fin


async def test_a_job_without_an_explicit_work_id_is_never_linked_to_the_brain(tmp_path, store):
    await run_job(tmp_path, ScriptedWorker(), work_state=store)

    [item] = (await store.snapshot()).items
    assert item.link == WorkLink()  # pas de `job:<id>`, pas de corrélation inventée


async def test_a_failing_job_is_observed_failed_with_its_error_class(tmp_path, store):
    await run_job(tmp_path, ScriptedWorker(error=TimeoutError("boîte mail muette")), work_state=store)

    [item] = (await store.snapshot()).items
    assert item.status is WorkStatus.FAILED and item.error_class == "TimeoutError"


class ÉchecMessagerie(RuntimeError):
    """Nom de classe Python valide, mais pas un jeton du contrat."""


async def test_a_job_failing_with_a_non_ascii_exception_name_still_ends_failed(tmp_path, store):
    # Régression : l'`error_class` refusée faisait perdre l'observation
    # d'échec, et le travail restait « en cours » pour toujours.
    await run_job(tmp_path, ScriptedWorker(error=ÉchecMessagerie("boîte pleine")), work_state=store)

    [item] = (await store.snapshot()).items
    assert item.status is WorkStatus.FAILED and item.error_class == "error"


async def test_a_broken_work_state_never_fails_a_job(tmp_path, sink):
    job, stored = await run_job(tmp_path, ScriptedWorker(), work_state=BrokenSink(), diagnostics=sink)

    assert stored.status is JobStatus.COMPLETED
    assert {data["status"] for data in sink.of(JOB_WORK_STATE_FAILED_KIND)} == {"running", "completed"}
    assert all(data["job_id"] == job.id for data in sink.of(JOB_WORK_STATE_FAILED_KIND))


async def test_a_job_running_at_core_restart_is_observed_interrupted(tmp_path, store):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    started = utc_now() - timedelta(minutes=5)
    job = replace(Job(kind="mail_search", payload={}), status=JobStatus.RUNNING, started_at=started)
    await state.save_job(job)

    await JobService(state, CoreEventBus(), {}, work_state=store).recover()
    await state.close()

    [item] = (await store.snapshot()).items
    assert item.key == (JOB_WORK_SOURCE, job.id)
    assert item.status is WorkStatus.INTERRUPTED and item.error_class == "core_restarted"
    assert item.started_at == started
