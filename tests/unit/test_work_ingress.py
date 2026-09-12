"""Relais des sous-tâches Claude vers l'état de travail Core (handoff work-state, tâche 11).

Côté Control Center : `AgentTaskTracker` → `TrackerWorkObserver` →
`WorkIngressForwarder`. Ce qui doit tenir :

- une tâche Claude = un seul travail Core, malgré le passage du
  `tool_use_id` au `task_id` et les fusions ;
- l'arrêt ou la mort du processus Claude interrompt ses sous-tâches côté Core ;
- rien du flux brut (prompt, trace, `subagent_type`, `tool_use_id`) ne part ;
- ni un observateur défaillant ni un Core injoignable ne rendent le brain sourd :
  `offer()` n'attend jamais, la file est bornée, l'envoi reprend seul.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from jarvis.core.work_state import PRODUCER_RESTARTED, WorkStateStore
from jarvis.domain.work_state import OBSERVATION_WIRE_KEYS, WorkObservation, WorkObservationBatch, WorkStatus
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.codex_local import CodexLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.work_ingress import (
    MERGED,
    PROCESS_STOPPED,
    TrackerWorkObserver,
    WorkIngressForwarder,
    WorkIngressRejected,
    task_status,
)

SESSION = "ac329510-db70-42d4-84ac-5fddd9b11c0d"
T0 = 1_789_047_300.0


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ------------------------------------------------------------------ événements


def agent_call(tool_use_id: str, description: str, *, parent: str | None = None, model: str | None = None) -> dict:
    payload: dict[str, Any] = {"description": description, "prompt": "Rends le réglage persistant.", "run_in_background": True}
    if model:
        payload["model"] = model
    return {
        "type": "assistant", "parent_tool_use_id": parent, "session_id": SESSION,
        "message": {"model": "claude-opus-5", "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent", "input": payload},
        ]},
    }


def task_started(task_id: str, tool_use_id: str | None, description: str) -> dict:
    event = {
        "type": "system", "subtype": "task_started", "task_id": task_id, "description": description,
        "is_backgrounded": True, "task_type": "local_agent", "subagent_type": "general-purpose",
        "prompt": "Rends le réglage persistant.", "session_id": SESSION,
    }
    if tool_use_id is not None:
        event["tool_use_id"] = tool_use_id
    return event


def progress(task_id: str, tool_use_id: str, activity: str, *, tokens: int, tool_uses: int) -> dict:
    return {
        "type": "system", "subtype": "task_progress", "task_id": task_id, "tool_use_id": tool_use_id,
        "description": activity, "usage": {"total_tokens": tokens, "tool_uses": tool_uses}, "session_id": SESSION,
    }


def notification(task_id: str, tool_use_id: str, status: str, summary: str = "") -> dict:
    return {
        "type": "system", "subtype": "task_notification", "task_id": task_id, "tool_use_id": tool_use_id,
        "status": status, "summary": summary, "session_id": SESSION,
    }


def async_launched(tool_use_id: str, agent_id: str) -> dict:
    return {
        "type": "user", "session_id": SESSION,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": [{"type": "text", "text": "Async agent launched."}]},
        ]},
        "tool_use_result": {"isAsync": True, "status": "async_launched", "agentId": agent_id, "resolvedModel": "claude-opus-5[1m]"},
    }


RESULT = {"type": "result", "subtype": "success", "result": "C'est lancé.", "session_id": SESSION}


# ---------------------------------------------------------------------- outils


class Collector:
    def __init__(self) -> None:
        self.observations: list[WorkObservation] = []

    def __call__(self, observation: WorkObservation) -> None:
        self.observations.append(observation)

    def keys(self) -> set[str]:
        return {observation.external_id for observation in self.observations}

    def last(self, key: str) -> WorkObservation:
        return [observation for observation in self.observations if observation.external_id == key][-1]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def agent(tmp_path, clock) -> ClaudeLocalAgent:
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    agent.subtasks.clock = clock
    return agent


@pytest.fixture
def collected(agent) -> Collector:
    collector = Collector()
    observer = TrackerWorkObserver(agent.subtasks, collector)
    agent.subtasks.subscribe(observer.sync)
    return collector


def feed(agent: ClaudeLocalAgent, *events: dict) -> None:
    for event in events:
        agent._record(event)


async def applied(observations: list[WorkObservation]) -> WorkStateStore:
    store = WorkStateStore()
    for observation in observations:
        await store.apply(observation)
    return store


class FakeRunningProcess:
    pid = 4242

    def __init__(self) -> None:
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


# ================================================================ projection


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("running", (WorkStatus.RUNNING, None)),
        ("queued", (WorkStatus.PENDING, None)),
        ("completed", (WorkStatus.COMPLETED, None)),
        ("failed", (WorkStatus.FAILED, None)),
        ("killed", (WorkStatus.CANCELLED, "killed")),
        ("stopped", (WorkStatus.CANCELLED, "stopped")),
        ("interrupted", (WorkStatus.INTERRUPTED, PROCESS_STOPPED)),
        ("exploded", (WorkStatus.FAILED, "unknown_status")),
    ],
)
def test_claude_statuses_map_to_the_normalized_contract(raw, expected):
    assert task_status(raw) == expected


async def test_one_claude_task_is_one_core_item_despite_its_id_switch(agent, clock, collected):
    feed(agent, agent_call("toolu_01FEy", "Persist voice arch setting", model="sonnet"))
    clock.advance(1.5)
    feed(agent, task_started("a6151a92", "toolu_01FEy", "Persist voice arch setting"))
    clock.advance(2)
    feed(agent, progress("a6151a92", "toolu_01FEy", "Read · app.py", tokens=1200, tool_uses=3))
    assert agent.tasks_snapshot()["tasks"][0]["id"] == "a6151a92"  # l'identifiant public a changé

    assert collected.keys() == {"toolu_01FEy"}  # Core, lui, n'en voit qu'un
    last = collected.last("toolu_01FEy")
    assert last.status is WorkStatus.RUNNING and last.kind == "agent"
    assert last.label == "Persist voice arch setting" and last.activity == "Read · app.py"
    assert last.tokens == 1200 and last.tool_uses == 3 and last.model == "sonnet" and last.background is True
    store = await applied(collected.observations)
    assert len((await store.snapshot()).items) == 1


async def test_a_completed_task_is_observed_completed_with_its_summary(agent, clock, collected):
    feed(agent, agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"))
    clock.advance(30)
    feed(agent, notification("a1", "toolu_A", "completed", "Réglage rendu persistant, tests verts."))

    store = await applied(collected.observations)
    [item] = (await store.snapshot()).items
    assert item.status is WorkStatus.COMPLETED
    assert item.summary == "Réglage rendu persistant, tests verts."
    assert (item.ended_at - item.started_at).total_seconds() == pytest.approx(30)


def test_an_unchanged_tracker_emits_nothing_more(agent, collected):
    feed(agent, agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"))
    before = len(collected.observations)

    feed(agent, {"type": "system", "subtype": "init", "model": "claude-opus-5"}, {"type": "stderr", "text": "bruit"})

    assert len(collected.observations) == before


def test_no_raw_provider_field_leaves_the_runtime(agent, collected):
    feed(
        agent,
        agent_call("toolu_A", "Persist"),
        task_started("a1", "toolu_A", "Persist"),
        progress("a1", "toolu_A", "Read · app.py", tokens=10, tool_uses=1),
        notification("a1", "toolu_A", "completed", "Fait."),
    )

    for observation in collected.observations:
        payload = observation.to_payload()
        assert set(payload) == OBSERVATION_WIRE_KEYS
        text = json.dumps(payload, ensure_ascii=False)
        assert "Rends le réglage persistant" not in text  # le prompt
        assert "general-purpose" not in text  # subagent_type
        assert "toolu_A" == payload["external_id"] or "toolu_A" not in text


async def test_a_nested_agent_names_its_parent_by_stable_key(agent, collected):
    feed(agent, agent_call("toolu_P", "Parent"), task_started("p1", "toolu_P", "Parent"))
    feed(agent, agent_call("toolu_C", "Enfant", parent="toolu_P"))

    assert collected.last("toolu_C").parent_external_id == "toolu_P"


async def test_a_merge_after_publication_closes_the_duplicate(agent, clock, collected):
    feed(agent, task_started("a1", None, "Meeting Planner"))  # connu par son task_id seul
    clock.advance(1)
    feed(agent, agent_call("toolu_A", "Meeting Planner"))  # connu par son tool_use_id seul
    assert collected.keys() == {"a1", "toolu_A"}  # deux travaux publiés, rien ne les relie encore

    feed(agent, async_launched("toolu_A", "a1"))

    assert len(agent.tasks_snapshot()["tasks"]) == 1
    closed = collected.last("toolu_A")
    assert closed.status is WorkStatus.CANCELLED and closed.error_class == MERGED
    store = await applied(collected.observations)
    active = [item for item in (await store.snapshot()).items if not item.status.is_terminal]
    assert [item.external_id for item in active] == ["a1"]  # la plus ancienne garde son identité


async def test_a_full_resend_still_closes_a_duplicate_merged_meanwhile(agent):
    """NB3 : vider la mémoire d'envoi ne doit pas perdre une clôture due."""

    collector = Collector()
    observer = TrackerWorkObserver(agent.subtasks, collector)
    feed(agent, task_started("a1", None, "Meeting Planner"), agent_call("toolu_A", "Meeting Planner"))
    observer.sync()  # les deux travaux sont publiés
    feed(agent, async_launched("toolu_A", "a1"))  # fusion : « toolu_A » est retirée

    observer.resync()  # Core a redémarré pile à cet instant

    closed = collector.last("toolu_A")
    assert closed.status is WorkStatus.CANCELLED and closed.error_class == MERGED
    store = await applied(collector.observations)
    active = [item for item in (await store.snapshot()).items if not item.status.is_terminal]
    assert [item.external_id for item in active] == ["a1"]


# ============================================================ arrêt du processus


async def test_stopping_the_claude_process_interrupts_its_subtasks_in_core(agent, collected):
    agent.process = FakeRunningProcess()
    feed(
        agent,
        agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"),
        agent_call("toolu_B", "Tests"), task_started("b1", "toolu_B", "Tests"),
        notification("b1", "toolu_B", "completed", "Verts."),
    )

    await agent.stop()

    store = await applied(collected.observations)
    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert items["toolu_A"].status is WorkStatus.INTERRUPTED and items["toolu_A"].error_class == PROCESS_STOPPED
    assert items["toolu_B"].status is WorkStatus.COMPLETED


class _ExitingProcess:
    pid = 31337

    def __init__(self, events: list[dict]) -> None:
        self._lines = [json.dumps(event).encode("utf-8") + b"\n" for event in events]
        self.stdout = self
        self.returncode: int | None = None

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    async def wait(self) -> int:
        self.returncode = 1
        return 1


async def test_a_claude_process_that_dies_leaves_nothing_running_in_core(agent, collected):
    agent.process = _ExitingProcess([agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist")])

    await agent._read_stdout()

    store = await applied(collected.observations)
    [item] = (await store.snapshot()).items
    assert item.status is WorkStatus.INTERRUPTED


async def test_a_restarted_claude_process_interrupts_the_previous_one_subtasks(agent, collected):
    feed(agent, agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"))

    agent.subtasks.process_started()  # sans arrêt constaté : le processus précédent a disparu

    store = await applied(collected.observations)
    [item] = (await store.snapshot()).items
    assert item.status is WorkStatus.INTERRUPTED and item.error_class == PROCESS_STOPPED


# ====================================================== le brain ne devient pas sourd


class _QueuedStream:
    def __init__(self) -> None:
        self._lines: asyncio.Queue[bytes] = asyncio.Queue()

    def push(self, *events: dict) -> None:
        for event in events:
            self._lines.put_nowait(json.dumps(event).encode("utf-8") + b"\n")

    async def readline(self) -> bytes:
        return await self._lines.get()


class _Stdin:
    def write(self, data: bytes) -> None:
        del data

    async def drain(self) -> None:
        return None


class _TalkingProcess(FakeRunningProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stdin = _Stdin()
        self.stdout = _QueuedStream()


async def test_a_failing_work_observer_never_deafens_the_brain(agent, tmp_path):
    def broken() -> None:
        raise RuntimeError("Core ingress bug")

    agent.subtasks.subscribe(broken)
    process = _TalkingProcess()
    agent.process = process
    reader = asyncio.create_task(agent._read_stdout())
    pending = asyncio.create_task(agent.ask("Quelle heure est-il ?", timeout_s=5))
    while agent._pending_result is None:
        await asyncio.sleep(0)
    process.stdout.push(agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"), RESULT)

    answer = await asyncio.wait_for(pending, timeout=2)

    assert answer["ok"] is True and answer["text"] == "C'est lancé."
    assert not reader.done()
    assert agent.tasks_snapshot()["tasks"][0]["id"] == "a1"  # le suivi continue
    failures = [item for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=500) if item["kind"] == "agent.work_state_failed"]
    assert len(failures) == 1 and failures[0]["data"]["exception_type"] == "RuntimeError"
    reader.cancel()
    await asyncio.gather(reader, return_exceptions=True)


async def test_a_hanging_core_never_blocks_the_stream_reader(agent):
    class HangingTransport:
        async def post(self, batch: WorkObservationBatch) -> dict:
            await asyncio.Event().wait()
            return {}

        async def close(self) -> None:
            return None

    forwarder = WorkIngressForwarder(source="claude", transport=HangingTransport(), flush_interval_s=0, close_timeout_s=0.05)
    observer = TrackerWorkObserver(agent.subtasks, forwarder.offer)
    agent.subtasks.subscribe(observer.sync)
    forwarder.start()
    feed(agent, agent_call("toolu_first", "Première"))
    await asyncio.sleep(0.01)  # le premier lot part, et reste pendu

    for index in range(400):
        feed(agent, agent_call(f"toolu_{index}", f"Tâche {index}"))

    assert len(agent.tasks_snapshot()["tasks"]) == 401  # le suivi a tout vu, sans attendre Core
    assert forwarder.pending_count == forwarder.max_pending and forwarder.dropped_total > 0
    await asyncio.wait_for(forwarder.aclose(), timeout=5)


# ================================================================ file d'envoi


class FakeTransport:
    def __init__(self, *, store_id: str = "core-1") -> None:
        self.batches: list[WorkObservationBatch] = []
        self.store_id = store_id
        self.failures: list[Exception] = []
        self.closed = False

    async def post(self, batch: WorkObservationBatch) -> dict:
        if self.failures:
            raise self.failures.pop(0)
        self.batches.append(batch)
        return {"store_id": self.store_id, "revision": len(self.batches), "outcomes": {}, "interrupted": 0}

    async def close(self) -> None:
        self.closed = True

    def sent(self) -> list[WorkObservation]:
        return [observation for batch in self.batches for observation in batch.observations]


def observation(key: str, status: WorkStatus = WorkStatus.RUNNING, t: float = 0.0, **fields) -> WorkObservation:
    from datetime import datetime, timedelta, timezone

    return WorkObservation(
        source="claude", external_id=key, status=status,
        observed_at=datetime(2026, 9, 11, tzinfo=timezone.utc) + timedelta(seconds=t), **fields,
    )


async def test_pending_observations_coalesce_per_task_and_keep_the_latest():
    transport = FakeTransport()
    forwarder = WorkIngressForwarder(source="claude", transport=transport)

    forwarder.offer(observation("a1", activity="Read"))
    forwarder.offer(observation("a1", t=1, activity="Edit"))
    forwarder.offer(observation("a2"))
    assert await forwarder.flush() is True

    assert [(item.external_id, item.activity) for item in transport.sent()] == [("a1", "Edit"), ("a2", "")]
    assert transport.batches[0].producer_id == forwarder.producer_id


async def test_a_pending_end_is_never_overwritten_by_progress():
    transport = FakeTransport()
    forwarder = WorkIngressForwarder(source="claude", transport=transport)

    forwarder.offer(observation("a1", WorkStatus.COMPLETED, t=2))
    forwarder.offer(observation("a1", t=3, activity="tardif"))
    await forwarder.flush()

    assert [item.status for item in transport.sent()] == [WorkStatus.COMPLETED]


async def test_overflow_drops_the_oldest_and_triggers_a_full_resync():
    transport = FakeTransport()
    forwarder = WorkIngressForwarder(source="claude", transport=transport, max_pending=3)
    resyncs: list[int] = []
    forwarder.on_resync = lambda: resyncs.append(1)
    await forwarder.flush()  # rien à envoyer

    for index in range(5):
        forwarder.offer(observation(f"a{index}"))

    assert forwarder.pending_count == 3 and forwarder.dropped_total == 2
    await forwarder.flush()
    assert [item.external_id for item in transport.sent()] == ["a2", "a3", "a4"]
    assert resyncs == [1]  # premier contact et pertes : l'état complet repart


async def test_core_unavailable_keeps_everything_and_reports_once(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    transport = FakeTransport()
    transport.failures = [ConnectionError("refused"), ConnectionError("refused")]
    forwarder = WorkIngressForwarder(source="claude", transport=transport, journal=RuntimeJournal(tmp_path))
    forwarder.offer(observation("a1", activity="Read"))

    assert await forwarder.flush() is False
    forwarder.offer(observation("a1", t=1, activity="Edit"))  # plus récente que celle remise en file
    assert await forwarder.flush() is False
    assert forwarder.pending_count == 1

    assert await forwarder.flush() is True
    assert [item.activity for item in transport.sent()] == ["Edit"]
    kinds = [item["kind"] for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=100)]
    assert kinds.count("work.ingress_unavailable") == 1 and kinds.count("work.ingress_restored") == 1


async def test_a_new_core_instance_triggers_a_full_resync():
    transport = FakeTransport(store_id="core-1")
    forwarder = WorkIngressForwarder(source="claude", transport=transport)
    resyncs: list[str] = []
    forwarder.on_resync = lambda: resyncs.append(transport.store_id)

    forwarder.offer(observation("a1"))
    await forwarder.flush()
    forwarder.offer(observation("a1", t=1, activity="Edit"))
    await forwarder.flush()
    transport.store_id = "core-2"  # Core a redémarré, magasin vide
    forwarder.offer(observation("a1", t=2, activity="Bash"))
    await forwarder.flush()

    assert resyncs == ["core-1", "core-2"]


async def test_a_rejected_batch_is_dropped_and_arms_a_full_resend():
    """B4 : sans renvoi, une tâche finie resterait « en cours » dans Core."""

    transport = FakeTransport()
    forwarder = WorkIngressForwarder(source="claude", transport=transport)
    resyncs: list[int] = []
    forwarder.offer(observation("a1"))
    await forwarder.flush()  # premier contact : le `store_id` est appris
    forwarder.on_resync = lambda: resyncs.append(1)

    transport.failures = [WorkIngressRejected("400")]
    forwarder.offer(observation("a2"))
    assert await forwarder.flush() is True
    assert forwarder.rejected_total == 1 and forwarder.pending_count == 0
    assert resyncs == []  # rien n'a encore été accusé depuis le refus

    forwarder.offer(observation("a3"))
    await forwarder.flush()

    assert resyncs == [1]  # le premier accusé qui suit déclenche l'état complet


async def test_a_core_that_refuses_every_batch_is_journaled_once(tmp_path):
    """NB6 : `RuntimeJournal.emit` écrit sur disque depuis la boucle d'envoi."""

    from jarvis.runtime.journal import RuntimeJournal

    transport = FakeTransport()
    transport.failures = [WorkIngressRejected("400") for _ in range(4)]
    forwarder = WorkIngressForwarder(source="claude", transport=transport, journal=RuntimeJournal(tmp_path))
    for index in range(4):
        forwarder.offer(observation(f"a{index}"))
        await forwarder.flush()

    assert forwarder.rejected_total == 4
    kinds = [item["kind"] for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=100)]
    assert kinds.count("work.ingress_rejected") == 1

    # Un lot accepté referme la série : un refus plus tard est consigné de nouveau.
    forwarder.offer(observation("b0"))
    await forwarder.flush()
    transport.failures = [WorkIngressRejected("400")]
    forwarder.offer(observation("b1"))
    await forwarder.flush()

    kinds = [item["kind"] for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=100)]
    assert kinds.count("work.ingress_rejected") == 2


async def test_the_send_loop_retries_on_its_own_until_core_answers():
    transport = FakeTransport()
    transport.failures = [ConnectionError("refused"), RuntimeError("boom")]
    forwarder = WorkIngressForwarder(source="claude", transport=transport, flush_interval_s=0, retry_min_s=0.01, retry_max_s=0.02)
    forwarder.start()
    forwarder.offer(observation("a1"))

    async def delivered() -> None:
        while not transport.batches:
            await asyncio.sleep(0.005)

    await asyncio.wait_for(delivered(), timeout=2)
    await forwarder.aclose()
    assert transport.closed is True


async def test_closing_flushes_the_last_observations():
    transport = FakeTransport()
    forwarder = WorkIngressForwarder(source="claude", transport=transport, flush_interval_s=10)
    forwarder.start()
    forwarder.offer(observation("a1", WorkStatus.INTERRUPTED, error_class=PROCESS_STOPPED))

    await forwarder.aclose()

    assert [item.status for item in transport.sent()] == [WorkStatus.INTERRUPTED]


async def until(condition, *, timeout: float = 2.0) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout=timeout)


def wired(agent: ClaudeLocalAgent, transport, **options) -> WorkIngressForwarder:
    forwarder = WorkIngressForwarder(source="claude", transport=transport, flush_interval_s=0, **options)
    observer = TrackerWorkObserver(agent.subtasks, forwarder.offer)
    agent.subtasks.subscribe(observer.sync)
    forwarder.on_resync = observer.resync
    return forwarder


async def test_an_idle_forwarder_lets_a_restarted_core_relearn_silent_work(agent):
    # Une commande de fond silencieuse : plus aucun événement du flux après son lancement.
    transport = FakeCoreTransport(WorkStateStore())
    forwarder = wired(agent, transport, resync_interval_s=0.01)
    feed(agent, agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"))
    forwarder.start()
    first = transport.store
    await until(lambda: first.revision == 1)

    # Au repos, les sondes sont des doublons : ni révision, ni événement.
    await until(lambda: first.outcome_totals.get("duplicate", 0) >= 3)
    assert first.revision == 1

    transport.store = WorkStateStore()  # Core redémarre : magasin vide, nouveau `store_id`
    await until(lambda: len(transport.store.current_snapshot().items) == 1)
    [item] = transport.store.current_snapshot().items
    assert item.external_id == "toolu_A" and item.status is WorkStatus.RUNNING
    await forwarder.aclose()


async def test_an_idle_forwarder_with_nothing_to_report_sends_nothing(agent):
    transport = FakeTransport()
    forwarder = wired(agent, transport, resync_interval_s=0.01)
    forwarder.start()

    await asyncio.sleep(0.1)

    assert transport.batches == []
    await forwarder.aclose()


async def test_a_resync_failing_at_every_probe_is_reported_once(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    forwarder = WorkIngressForwarder(
        source="claude", transport=FakeTransport(), journal=RuntimeJournal(tmp_path), flush_interval_s=0, resync_interval_s=0.01,
    )
    attempts: list[int] = []

    def broken() -> None:
        attempts.append(1)
        raise ValueError("external_id exceeds 128 characters")

    forwarder.on_resync = broken
    forwarder.start()
    await until(lambda: len(attempts) >= 5)
    await forwarder.aclose()

    kinds = [item["kind"] for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=100)]
    assert kinds.count("work.ingress_resync_failed") == 1


def test_an_observation_from_another_source_is_refused():
    forwarder = WorkIngressForwarder(source="claude", transport=FakeTransport())

    with pytest.raises(ValueError):
        forwarder.offer(WorkObservation(source="codex", external_id="x", status=WorkStatus.RUNNING, observed_at=observation("x").observed_at))


# ============================================================ Control Center


async def test_the_control_center_relays_claude_subtasks_without_changing_its_api(tmp_path):
    transport = FakeTransport()
    forwarder = WorkIngressForwarder(source="claude", transport=transport)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, work_ingress=forwarder)
    agent = control.agent
    assert isinstance(agent, ClaudeLocalAgent)

    feed(agent, agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"))
    await forwarder.flush()

    assert {item.external_id for item in transport.sent()} == {"toolu_A"}
    tasks = agent.tasks_snapshot()["tasks"]
    assert tasks[0]["id"] == "a1" and "prompt" in tasks[0]  # `/api/agent/tasks` inchangé


def test_codex_gets_no_invented_subtask_relay(tmp_path):
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"agent_cli": "codex"}), encoding="utf-8")
    forwarder = WorkIngressForwarder(source="claude", transport=FakeTransport())

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, work_ingress=forwarder)

    assert isinstance(control.agent, CodexLocalAgent)
    assert forwarder.on_resync is None


async def test_core_interrupts_a_previous_control_center_instance():
    store = WorkStateStore()
    first = FakeCoreTransport(store)
    old = WorkIngressForwarder(source="claude", transport=first)
    old.offer(observation("toolu_A", activity="Read"))
    await old.flush()

    new = WorkIngressForwarder(source="claude", transport=FakeCoreTransport(store))
    new.offer(observation("toolu_B", t=10))
    await new.flush()

    items = {item.external_id: item for item in (await store.snapshot()).items}
    assert items["toolu_A"].status is WorkStatus.INTERRUPTED and items["toolu_A"].error_class == PRODUCER_RESTARTED
    assert items["toolu_B"].status is WorkStatus.RUNNING


class FakeCoreTransport:
    """Transport en mémoire, par le même fil qu'en production (lot → payload → lot)."""

    def __init__(self, store: WorkStateStore) -> None:
        self.store = store

    async def post(self, batch: WorkObservationBatch) -> dict:
        result = await self.store.ingest(WorkObservationBatch.from_payload(json.loads(json.dumps(batch.to_payload()))))
        return result.to_payload()

    async def close(self) -> None:
        return None


def test_a_standalone_tracker_notifies_its_listeners_after_process_changes(clock):
    tracker = AgentTaskTracker(provider="claude", clock=clock)
    calls: list[int] = []
    tracker.subscribe(lambda: calls.append(1))

    tracker.process_started()
    tracker.observe_claude(agent_call("toolu_A", "Persist"))
    tracker.process_stopped()

    assert len(calls) == 3
