from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from jarvis.core.v2_services import CoreEventBus
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.runtime.journal import RuntimeJournal


@dataclass(slots=True)
class RecordingSink:
    """Puits de diagnostic de test : capture les événements structurés."""

    events: list[tuple[str, str, str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, message, level, dict(data or {})))


@dataclass(slots=True)
class BrokenSink:
    """Puits de diagnostic défaillant : simule un journal indisponible."""

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        raise OSError("journal indisponible")


def envelope(message_type: str = "brain.progress") -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type=message_type, payload={"step": 1}, conversation_id="conv-1")


async def test_saturated_subscriber_is_evicted_and_reported():
    sink = RecordingSink()
    bus = CoreEventBus(diagnostics=sink)
    queue = bus.subscribe(max_queue=1)

    await bus.publish(envelope())  # remplit la file
    await bus.publish(envelope("brain.final"))  # sature -> éviction

    assert bus.subscriber_count == 0
    assert bus.evicted_total == 1
    assert queue.qsize() == 1  # le bus reste borné, rien n'a été mis en attente

    assert len(sink.events) == 1
    kind, _message, level, data = sink.events[0]
    assert kind == CoreEventBus.EVICTION_KIND
    assert level == "warning"
    assert data["message_type"] == "brain.final"
    assert data["conversation_id"] == "conv-1"
    assert data["queue_maxsize"] == 1
    assert data["remaining_subscribers"] == 0
    assert data["evicted_total"] == 1
    assert data["correlation_id"]


async def test_healthy_subscriber_survives_a_neighbour_eviction():
    sink = RecordingSink()
    bus = CoreEventBus(diagnostics=sink)
    small = bus.subscribe(max_queue=1)
    large = bus.subscribe(max_queue=8)

    await bus.publish(envelope())
    await bus.publish(envelope("brain.final"))

    assert small.qsize() == 1
    assert large.qsize() == 2
    assert bus.subscriber_count == 1
    assert len(sink.events) == 1


async def test_default_sink_is_inert_for_existing_callers():
    """Les appelants historiques instancient `CoreEventBus()` sans argument."""
    bus = CoreEventBus()
    queue = bus.subscribe(max_queue=1)

    await bus.publish(envelope())
    await bus.publish(envelope())

    assert bus.subscriber_count == 0
    assert bus.evicted_total == 1
    assert queue.qsize() == 1


async def test_failing_sink_does_not_break_event_delivery():
    bus = CoreEventBus(diagnostics=BrokenSink())
    saturated = bus.subscribe(max_queue=1)
    healthy = bus.subscribe(max_queue=8)

    await bus.publish(envelope())
    await bus.publish(envelope())

    assert saturated.qsize() == 1
    assert healthy.qsize() == 2
    assert bus.evicted_total == 1


async def test_the_requested_bound_is_enforced_not_merely_stored():
    """Ce que ce test prouve : la file s'arrête à la taille demandée, sous pression.

    La version précédente se contentait de `queue.maxsize == 4`, ce qui prouve
    que l'argument est bien transmis à `asyncio.Queue` — pas que le bus reste
    borné. On remplit donc la file jusqu'à son bord, puis on la déborde : la
    taille ne dépasse jamais 4, et le débordement est traité par l'éviction,
    jamais par une mise en attente qui ferait grossir la file.
    """

    bus = CoreEventBus()
    queue = bus.subscribe(max_queue=4)
    assert isinstance(queue, asyncio.Queue)
    assert queue.maxsize == 4

    for _ in range(4):
        await bus.publish(envelope())
    assert queue.qsize() == 4
    assert bus.subscriber_count == 1
    assert bus.evicted_total == 0

    await bus.publish(envelope("brain.final"))
    assert queue.qsize() == 4
    assert bus.subscriber_count == 0
    assert bus.evicted_total == 1


async def test_a_lossy_subscriber_loses_the_oldest_event_but_never_its_subscription():
    """NB4 : l'abonné permanent de Core survit à une rafale, borné comme les autres."""

    sink = RecordingSink()
    bus = CoreEventBus(diagnostics=sink)
    queue = bus.subscribe(max_queue=2, lossy=True)

    await bus.publish(envelope("first"))
    await bus.publish(envelope("second"))
    await bus.publish(envelope("third"))
    await bus.publish(envelope("fourth"))

    assert bus.subscriber_count == 1 and bus.evicted_total == 0
    assert queue.qsize() == 2 and bus.dropped_total == 2
    assert [queue.get_nowait().message_type for _ in range(2)] == ["third", "fourth"]
    kinds = [kind for kind, _message, _level, _data in sink.events]
    assert kinds == [CoreEventBus.DROP_KIND, CoreEventBus.DROP_KIND]  # une fois par type
    assert sink.events[0][3] == {"message_type": "third", "queue_maxsize": 2, "dropped_total": 1}


async def test_an_unsubscribed_lossy_queue_is_forgotten_by_both_registers():
    bus = CoreEventBus()
    queue = bus.subscribe(max_queue=1, lossy=True)

    bus.unsubscribe(queue)
    await bus.publish(envelope())

    assert bus.subscriber_count == 0 and bus.dropped_total == 0 and queue.qsize() == 0


async def test_the_attention_policy_keeps_its_subscription_through_a_burst():
    """Le branchement réel : Core abonne la politique d'attention en mode tolérant."""

    from jarvis.core.brain_context import ATTENTION_QUEUE_SIZE

    bus = CoreEventBus()
    queue = bus.subscribe(max_queue=ATTENTION_QUEUE_SIZE, lossy=True)

    for _ in range(ATTENTION_QUEUE_SIZE + 10):
        await bus.publish(envelope("core.work.updated"))

    assert bus.subscriber_count == 1 and bus.evicted_total == 0
    assert queue.qsize() == ATTENTION_QUEUE_SIZE and bus.dropped_total == 10


async def test_runtime_journal_satisfies_the_diagnostic_sink(tmp_path):
    """Le branchement réel se fait au composition root, sans adaptateur."""
    journal = RuntimeJournal(tmp_path)
    bus = CoreEventBus(diagnostics=journal)
    bus.subscribe(max_queue=1)

    await bus.publish(envelope())
    await bus.publish(envelope())

    entries = [json.loads(line) for line in journal.trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    evictions = [entry for entry in entries if entry["kind"] == CoreEventBus.EVICTION_KIND]
    assert len(evictions) == 1
    assert evictions[0]["level"] == "warning"
    assert evictions[0]["data"]["message_type"] == "brain.progress"
