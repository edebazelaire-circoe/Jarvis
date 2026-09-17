"""Le cerveau et l'UI lisent le même état de travail (handoff work-state, tâche 12).

Chaîne réelle : `POST /v1/work/observations` → `WorkStateStore` →
`GET /v1/work/snapshot` (ce que lira l'UI) d'un côté, tour cerveau soumis par
`POST /v1/conversations/{id}/brain-turns` → `BrainOrchestrator` → backend
déclarant `run_turn_with_context` de l'autre. Même `store_id`, même révision.
Un échec observé ensuite est retenu par la politique de Core, qui **réveille**
le cerveau : Core lui ouvre un tour portant ce changement, sans prononcer lui-même
la moindre parole (Décision D17).
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field

import pytest

from jarvis.core.brain_context import ATTENTION_QUEUE_SIZE, WORK_ATTENTION_KIND
from jarvis.core.brain_service import BRAIN_SPEECH_REQUESTED, BRAIN_WOKEN_KIND
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.work_state import CORE_WORK_UPDATED
from jarvis.domain.brain_context import BrainContext
from jarvis.domain.v2 import BrainTurnInput, BrainTurnResult, ProtocolEnvelope
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer

TOKEN = "b" * 48


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(slots=True)
class RecordingSink:
    events: list[tuple[str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, dict(data or {})))


@dataclass(slots=True)
class ContextBackend:
    contexts: list[BrainContext] = field(default_factory=list)
    arrived: asyncio.Queue = field(default_factory=asyncio.Queue)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:  # pragma: no cover
        raise AssertionError("Core must prefer run_turn_with_context")

    async def run_turn_with_context(self, turn: BrainTurnInput, context: BrainContext, emit) -> BrainTurnResult:
        self.contexts.append(context)
        self.arrived.put_nowait(context)
        return BrainTurnResult(correlation_id=turn.correlation_id)


@pytest.fixture
async def core_stack(tmp_path):
    port = free_port()
    backend = ContextBackend()
    diagnostics = RecordingSink()
    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=backend, diagnostics=diagnostics)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, client, backend, diagnostics
    finally:
        await client.close()
        await server.stop()
        await core.stop()


def batch(external_id: str, status: str, observed_at: str, **fields) -> dict:
    observation = {"source": "claude", "external_id": external_id, "status": status, "observed_at": observed_at, **fields}
    return {"source": "claude", "producer_id": "cc-1", "observations": [observation]}


async def test_the_brain_and_the_ui_read_the_same_work_state(core_stack):
    core, client, backend, diagnostics = core_stack
    watcher = core.events.subscribe(max_queue=512)
    conversation = await client.create_conversation()

    await client.ingest_work_observations(
        batch("toolu_A", "running", "2026-09-11T15:00:00+00:00", label="Analyse du dépôt", activity="Lecture de x.py", model="claude-sonnet")
    )
    await client.ingest_work_observations(batch("toolu_B", "running", "2026-09-11T15:00:05+00:00", label="Recherche web"))
    await client.submit_brain_turn(conversation["id"], content="Où en sont mes tâches ?", correlation_id="corr-1")
    first = await asyncio.wait_for(backend.arrived.get(), timeout=5)
    snapshot = await client.work_snapshot()

    assert (first.work.store_id, first.work.revision) == (snapshot["store_id"], snapshot["revision"])
    assert [entry.external_id for entry in first.work.items] == [item["external_id"] for item in snapshot["items"]]
    assert first.work.items[0].activity == "Lecture de x.py" and first.work.items[0].model == "claude-sonnet"

    # Échec inattendu d'une sous-tâche active, hors de tout tour. La politique
    # le relève et **réveille** le cerveau : sans ce réveil, l'échec n'aurait
    # été appris qu'au prochain tour de l'utilisateur — donc jamais s'il se
    # taisait, et la tâche mourait sans un mot.
    await client.ingest_work_observations(batch("toolu_B", "failed", "2026-09-11T15:01:00+00:00", error_class="timeout"))
    wake = await asyncio.wait_for(backend.arrived.get(), timeout=5)

    assert [data["external_id"] for kind, data in diagnostics.events if kind == WORK_ATTENTION_KIND] == ["toolu_B"]
    assert [data["notes"] for kind, data in diagnostics.events if kind == BRAIN_WOKEN_KIND] == [1]
    # Le tour de réveil porte le changement, et vient de Core, pas de la voix.
    assert [(note.external_id, note.status.value, note.error_class) for note in wake.work.attention] == [("toolu_B", "failed", "timeout")]
    assert wake.state.conversation_id == conversation["id"]
    # Core n'a toujours prononcé aucune parole de lui-même (Décision D17) :
    # c'est le cerveau qui parlera, sur le tour qu'on vient de lui ouvrir.
    published = []
    while not watcher.empty():
        published.append(watcher.get_nowait().message_type)
    assert BRAIN_SPEECH_REQUESTED not in published and CORE_WORK_UPDATED in published
    # Remis une fois, consommé : le tour suivant ne réannonce pas le même échec.
    assert core.work_attention.pending == ()

    await client.submit_brain_turn(conversation["id"], content="Et la recherche ?", correlation_id="corr-2")
    second = await asyncio.wait_for(backend.arrived.get(), timeout=5)
    snapshot = await client.work_snapshot()

    assert second.work.revision == snapshot["revision"]
    assert second.work.attention == ()


async def test_a_burst_of_core_events_never_ends_work_attention(core_stack):
    """NB4 : rien ne réabonne la politique ; une éviction l'éteindrait à vie."""

    core, client, _backend, _diagnostics = core_stack
    # `publish` ne rend jamais la main : la file de la politique déborde vraiment.
    for index in range(ATTENTION_QUEUE_SIZE + 20):
        await core.events.publish(ProtocolEnvelope(message_type="schedule.checked", payload={"index": index}))
    assert core.events.dropped_total >= 20

    await client.ingest_work_observations(batch("toolu_C", "running", "2026-09-11T15:02:00+00:00", label="Tests"))
    await client.ingest_work_observations(batch("toolu_C", "failed", "2026-09-11T15:03:00+00:00", error_class="boom"))
    for _ in range(200):
        if core.work_attention.pending:
            break
        await asyncio.sleep(0.01)

    assert [note.external_id for note in core.work_attention.pending] == ["toolu_C"]
