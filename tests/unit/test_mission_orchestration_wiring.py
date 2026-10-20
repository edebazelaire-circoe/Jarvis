"""Câblage hook → fait → relais → route Core → historique des missions → Work State `role_id` (Slice 05).

Handoff jarvis-organic-agent-orchestration. Le vrai hook, le vrai registre local, le vrai `AgentTaskTracker`, le
vrai relais, la vraie route (`MissionProtocolRoutes`), le vrai service sur une base temporaire et le vrai
`WorkStateStore`. Le flux `stream-json` est rejoué à la main sous la forme constatée sur le CLI 2.1.304 (bac à
sable du 2026-10-20) : au niveau 3, `task_started` seul nomme le parent (`parent_task_id`), et la clé de travail
est le `task_id`, pas le `tool_use_id`.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.mission_history import (
    MISSION_HISTORY_CLOSE_FAILED_KIND, MISSION_HISTORY_MISSION_CLOSED_KIND, MissionHistoryService,
)
from jarvis.core.work_state import WorkStateStore
from jarvis.domain.mission_history import DeclarationOutcome as O, MissionOpening
from jarvis.domain.missions import MissionStatus
from jarvis.domain.work_state import WorkObservation, WorkStatus
from jarvis.protocol.mission_routes import MissionProtocolRoutes, decode_declarations
from jarvis.runtime import routing_hook
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.core_forwarder import CoreBatchRejected
from jarvis.runtime.declaration_relay import DeclarationRelay, DeclarationsRejected
from jarvis.runtime.mission_view import CoreMissionView
from jarvis.runtime.work_ingress import TrackerWorkObserver
from tests.fakes.mission_history import SOURCE, at, fact, observation, open_store


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.lines.append((kind, level, dict(data or {})))

    def kinds(self, kind):
        return [data for name, _level, data in self.lines if name == kind]


class Clock:
    def now(self):
        return at(30)


@pytest.fixture
async def core(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    work = WorkStateStore(clock=Clock())
    journal = Journal()
    service = MissionHistoryService(store, work_state=work, diagnostics=journal, clock=Clock(), sweep_interval_s=None)
    app = web.Application()
    fake_core = SimpleNamespace(mission_history=service, work_state=work, _diagnostics=journal)
    app.add_routes(MissionProtocolRoutes(fake_core).routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    yield SimpleNamespace(service=service, store=store, work=work, journal=journal, client=client)
    await client.close()
    await service.stop()
    await state.close()


class HttpTransport:
    """Le transport du relais, branché sur la vraie route par HTTP (sans le middleware de jeton)."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.posted: list[list[dict]] = []
        self.down = False

    async def post(self, items):
        if self.down:
            raise ConnectionError("Core arrêté")
        self.posted.append(items)
        response = await self.client.post("/v1/missions/declarations", json={"declarations": items})
        body = await response.json()
        if response.status == 400:
            raise DeclarationsRejected(body["error"]["message"])
        return body

    async def health(self):
        response = await self.client.get("/v1/missions/health")
        return await response.json()

    async def mission(self, mission_id):
        response = await self.client.get(f"/v1/missions/{mission_id}")
        return await response.json()

    async def for_work(self, source, external):
        response = await self.client.get(f"/v1/missions/work/{source}/{external}")
        return await response.json()

    async def close(self):
        return None


def agent_call(tool_use_id, description, *, parent=None):
    return {"type": "assistant", "parent_tool_use_id": parent, "message": {"content": [
        {"type": "tool_use", "id": tool_use_id, "name": "Agent",
         "input": {"description": description, "prompt": "p", "subagent_type": "general-purpose"}}]}}


def started(task_id, tool_use_id, description, depth, *, parent_task_id=None):
    event = {"type": "system", "subtype": "task_started", "task_id": task_id, "tool_use_id": tool_use_id,
             "description": description, "subagent_type": "general-purpose", "task_type": "local_agent",
             "spawn_depth": depth}
    if parent_task_id:
        event["parent_task_id"] = parent_task_id
    return event


def hook(runtime, tool_use_id, description, *, caller=None):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id, "session_id": "s",
             "tool_input": {"description": description, "prompt": "p", "subagent_type": "general-purpose"}}
    if caller:
        event["agent_id"] = caller
    return routing_hook.run(event, runtime, spawn_guard=True)


async def test_the_whole_chain_records_a_team_and_puts_roles_on_work_state(core, tmp_path):
    runtime = tmp_path / "runtime"
    tracker = AgentTaskTracker(provider=SOURCE)
    relay = DeclarationRelay(runtime_root=runtime, source=SOURCE, transport=HttpTransport(core.client))
    relay.attach(tracker)
    observations: list[WorkObservation] = []
    observer = TrackerWorkObserver(tracker, observations.append, role_of=relay.role_for)
    tracker.subscribe(observer.sync)
    relay.on_joined = observer.sync

    # Niveau 1 : un Developer lancé par le cerveau (Mission Owner de la mission racine).
    hook(runtime, "toolu_A", "[code] [coder] Corriger le bug")
    tracker.observe_claude(agent_call("toolu_A", "[code] [coder] Corriger le bug"))
    tracker.observe_claude(started("taskA", "toolu_A", "[code] [coder] Corriger le bug", 1))
    # Niveau 2 : un QA (membre) et une Direction de recherche qui ouvre une sous-mission.
    hook(runtime, "toolu_Q", "[general] [qa] Relire", caller="taskA")
    tracker.observe_claude(agent_call("toolu_Q", "[general] [qa] Relire", parent="toolu_A"))
    tracker.observe_claude(started("taskQ", "toolu_Q", "[general] [qa] Relire", 2, parent_task_id="taskA"))
    hook(runtime, "toolu_L", "[general] [research-lead] [mission] Comparer", caller="taskA")
    tracker.observe_claude(agent_call("toolu_L", "[general] [research-lead] [mission] Comparer", parent="toolu_A"))
    tracker.observe_claude(started("taskL", "toolu_L", "[general] [research-lead] [mission] Comparer", 2,
                                   parent_task_id="taskA"))
    # Niveau 3 : l'appel du niveau 2 n'apparaît pas dans le flux ; seul `task_started` nomme son parent.
    hook(runtime, "toolu_R", "[general] [research] Chercher", caller="taskL")
    tracker.observe_claude(started("taskR", "toolu_R", "[general] [research] Chercher", 3, parent_task_id="taskL"))

    assert await relay.flush() is True
    for item in observations:
        await core.work.observe(item)

    keys = {task.tool_use_id: task.work_key for task in tracker.tasks()}
    assert keys["toolu_R"] == "taskR"  # la clé de travail n'est pas le tool_use_id : la jointure l'est
    views = {tid: await core.service.instance_for_work(SOURCE, key) for tid, key in keys.items()}
    root, lead = "mis_toolu_A", "mis_toolu_L"
    assert (views["toolu_A"].stored.instance.role_id, views["toolu_A"].stored.instance.mission_id) == ("coder", root)
    assert views["toolu_A"].stored.instance.mission_owner is True
    assert (views["toolu_Q"].stored.instance.mission_id, views["toolu_Q"].stored.instance.mission_owner) == (root, False)
    assert (views["toolu_L"].stored.instance.mission_id, views["toolu_L"].stored.instance.mission_owner) == (lead, True)
    assert views["toolu_R"].stored.instance.mission_id == lead  # membre de la sous-mission de son appelant
    assert views["toolu_R"].stored.instance.parent_instance_id == views["toolu_L"].stored.instance.instance_id
    tree, _ = await core.service.mission_view(root)
    missions = {m.mission_id: m for m in tree.missions}
    assert missions[lead].parent_mission_id == root and missions[lead].root_mission_id == root
    assert missions[root].objective == "Corriger le bug" and missions[lead].objective == "Comparer"
    roles = {item.external_id: item.role_id for item in core.work.current_snapshot().items}
    assert roles == {"toolu_A": "coder", "toolu_Q": "qa", "toolu_L": "research-lead", "taskR": "research"}

    # Rejouer : rien n'est réécrit (doublons), ni dans l'historique ni dans Work State.
    assert relay.join() == 0
    replay = await core.service.record_declaration(fact("toolu_A", role="coder", mission_id=root, owner=True),
                                                   work_source=SOURCE, work_external_id="toolu_A")
    assert replay.outcome in (O.DUPLICATE, O.REFUSED)


async def test_an_unstarted_call_is_never_declared(core, tmp_path):
    runtime = tmp_path / "runtime"
    tracker = AgentTaskTracker(provider=SOURCE)
    transport = HttpTransport(core.client)
    relay = DeclarationRelay(runtime_root=runtime, source=SOURCE, transport=transport)
    relay.attach(tracker)
    hook(runtime, "toolu_X", "[code] [coder] Corriger")
    tracker.observe_claude(agent_call("toolu_X", "[code] [coder] Corriger"))  # appel vu, jamais démarré
    assert await relay.flush() is True
    assert transport.posted == [] and await core.service.instance_for_work(SOURCE, "toolu_X") is None
    tracker.observe_claude(started("taskX", "toolu_X", "[code] [coder] Corriger", 1))
    assert await relay.flush() is True and len(transport.posted) == 1


async def test_core_unreachable_keeps_the_declaration_and_a_new_core_gets_the_live_ones_again(core, tmp_path):
    runtime = tmp_path / "runtime"
    tracker = AgentTaskTracker(provider=SOURCE)
    transport = HttpTransport(core.client)
    relay = DeclarationRelay(runtime_root=runtime, source=SOURCE, transport=transport)
    relay.attach(tracker)
    hook(runtime, "toolu_E", "[éphémère] [general] Lister")
    tracker.observe_claude(started("taskE", "toolu_E", "[éphémère] [general] Lister", 1))
    transport.down = True
    assert await relay.flush() is False and relay.pending_count == 1
    transport.down = False
    assert await relay.flush() is True and relay.pending_count == 0
    assert core.service.health().pending_ephemeral == 1
    # Core redémarre : nouveau `store_id`, mémoire des éphémères vide ; la sonde réarme le renvoi.
    core.work.store_id = "new-store"
    relay._last_probe = -1e9
    assert await relay.flush() is True
    assert len(transport.posted) == 2 and transport.posted[1][0]["fact"]["tool_use_id"] == "toolu_E"


async def test_a_rejected_batch_is_dropped_and_reported_once(core, tmp_path):
    journal = Journal()

    class Refusing(HttpTransport):
        async def post(self, items):
            raise DeclarationsRejected("400 invalid_request")

    runtime = tmp_path / "runtime"
    tracker = AgentTaskTracker(provider=SOURCE)
    relay = DeclarationRelay(runtime_root=runtime, source=SOURCE, transport=Refusing(core.client), journal=journal)
    relay.attach(tracker)
    for index in range(2):
        hook(runtime, f"toolu_{index}", "[code] [coder] X")
        tracker.observe_claude(started(f"task{index}", f"toolu_{index}", "[code] [coder] X", 1))
    assert await relay.flush() is True
    assert relay.rejected_total == 2 and relay.pending_count == 0
    assert len(journal.kinds(DeclarationRelay.REJECTED_KIND)) == 1
    assert issubclass(DeclarationsRejected, CoreBatchRejected)


async def test_an_invalid_ledger_file_is_reported_and_skipped(core, tmp_path):
    journal = Journal()
    runtime = tmp_path / "runtime"
    folder = runtime / "agent-declarations"
    folder.mkdir(parents=True)
    name = f"{int(__import__('time').time() * 1000)}-toolu_bad.json"  # récent : l'élagage ne l'enlève pas
    (folder / name).write_text("{pas du json", encoding="utf-8")
    relay = DeclarationRelay(runtime_root=runtime, source=SOURCE, transport=HttpTransport(core.client), journal=journal)
    assert await relay.flush() is True
    assert await relay.flush() is True
    [report] = journal.kinds(DeclarationRelay.INVALID_KIND)
    assert report["file"] == name and (folder / name).exists()


# ---------------------------------------------------------------- route Core


async def test_the_route_is_strict_and_records_nothing_on_a_bad_item(core):
    good = {"fact": fact("toolu_1").to_payload(), "work_source": SOURCE, "work_external_id": "toolu_1"}
    bad = {**good, "prompt": "fuite"}
    response = await core.client.post("/v1/missions/declarations", json={"declarations": [good, bad]})
    assert response.status == 400 and "declarations[1]" in (await response.json())["error"]["message"]
    assert await core.service.instance_for_work(SOURCE, "toolu_1") is None
    for body in ({}, {"declarations": []}, {"declarations": [good] * 33}, {"declarations": [good], "x": 1}):
        assert (await core.client.post("/v1/missions/declarations", json=body)).status == 400
    response = await core.client.post("/v1/missions/declarations", json={"declarations": [good]})
    body = await response.json()
    assert response.status == 200 and body["results"][0]["outcome"] == "recorded"
    assert body["store_id"] == core.work.store_id
    assert core.journal.kinds("core.missions.declarations")[-1]["outcomes"] == {"recorded": 1}


async def test_read_routes_answer_coded_refusals(core):
    assert (await core.client.get("/v1/missions/health")).status == 200
    health = await (await core.client.get("/v1/missions/health")).json()
    assert health["state"] == "ok" and health["store_id"] == core.work.store_id
    missing = await core.client.get("/v1/missions/mis_nope")
    assert missing.status == 404 and (await missing.json())["error"]["code"] == "mission_not_found"
    unknown = await core.client.get("/v1/missions/work/claude/toolu_nope")
    assert unknown.status == 404 and (await unknown.json())["error"]["code"] == "mission_instance_not_found"
    assert core.journal.kinds("core.missions.route_failed")[-1]["code"] == "mission_instance_not_found"
    assert decode_declarations({"declarations": [{"fact": fact("t").to_payload(), "work_source": SOURCE,
                                                  "work_external_id": "t"}]})[0][3] is None


async def test_the_control_center_view_relays_and_bounds_the_wait(core):
    view = CoreMissionView(HttpTransport(core.client), timeout_s=0.5)
    assert (await view.health())[0] == 200

    class Hanging(HttpTransport):
        async def health(self):
            await asyncio.sleep(5)

    class Down(HttpTransport):
        async def health(self):
            raise ConnectionError("refused")

    journal = Journal()
    status, body = await CoreMissionView(Hanging(core.client), journal=journal, timeout_s=0.05).health()
    assert (status, body["code"], body["ok"]) == (503, "core_unreachable", False) and "0.05" in body["error"]
    status, body = await CoreMissionView(Down(core.client), journal=journal).health()
    assert status == 503 and "ConnectionError" in body["error"]
    assert len(journal.kinds("missions.read_failed")) == 2


# ---------------------------------------------------------------- service : héritage, sous-missions, clôture


async def _owner(service, tool_use_id, *, parent=None, role="coder", label="Objet"):
    return await service.record_declaration(
        fact(tool_use_id, role=role, mission_id=f"mis_{tool_use_id}", owner=True, label=label),
        work_source=SOURCE, work_external_id=tool_use_id, parent_work_external_id=parent,
        mission=MissionOpening(objective=label, parent_from_caller=True), inherit_mission=True)


async def test_members_inherit_and_sub_missions_nest_under_the_caller_mission(core):
    await _owner(core.service, "A")
    member = await core.service.record_declaration(fact("B", role="qa"), work_source=SOURCE, work_external_id="B",
                                                   parent_work_external_id="A", inherit_mission=True)
    assert member.instance.mission_id == "mis_A" and not member.instance.mission_owner
    sub = await _owner(core.service, "C", parent="A", role="research-lead")
    mission = await core.store.get_mission("mis_C")
    assert (mission.parent_mission_id, mission.root_mission_id, sub.instance.mission_id) == ("mis_A", "mis_A", "mis_C")
    deep = await _owner(core.service, "D", parent="C", role="coder")
    assert (await core.store.get_mission("mis_D")).root_mission_id == "mis_A" and deep.outcome is O.RECORDED
    # Sans héritage demandé (Slice 03), un enfant reste sans mission.
    plain = await core.service.record_declaration(fact("E", role="qa"), work_source=SOURCE, work_external_id="E",
                                                  parent_work_external_id="A")
    assert plain.instance.mission_id is None
    assert core.service.mission_ref(SOURCE, "B").mission_id == "mis_A"


async def test_a_mission_closes_with_its_current_owner_and_only_once(core):
    await _owner(core.service, "A")
    await core.service.record_declaration(fact("B", role="qa"), work_source=SOURCE, work_external_id="B",
                                          parent_work_external_id="A", inherit_mission=True)
    await core.work.observe(observation("B", WorkStatus.FAILED, minute=1))
    await core.service.observe_work_item(core.work.current_snapshot().items[0])
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.OPEN  # un membre ne clôt rien
    for status, minute in ((WorkStatus.RUNNING, 1), (WorkStatus.INTERRUPTED, 2)):
        await core.work.observe(observation("A", status, minute=minute))
    item = next(i for i in core.work.current_snapshot().items if i.external_id == "A")
    await core.service.observe_work_item(item)
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.CANCELLED
    await core.service.observe_work_item(item)  # fin rejouée : déjà close, rien ne change, rien n'échoue
    assert len(core.journal.kinds(MISSION_HISTORY_MISSION_CLOSED_KIND)) == 1
    assert core.journal.kinds(MISSION_HISTORY_CLOSE_FAILED_KIND) == []


async def test_an_owner_whose_end_arrived_before_its_declaration_closes_at_once(core):
    await core.work.observe(observation("A", WorkStatus.COMPLETED, minute=1))
    await _owner(core.service, "A")
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.COMPLETED


async def test_after_a_service_restart_the_end_of_an_owner_still_closes_its_mission(core):
    await _owner(core.service, "A")
    fresh = MissionHistoryService(core.store, work_state=core.work, diagnostics=core.journal, clock=Clock(),
                                  sweep_interval_s=None)
    await core.work.observe(observation("A", WorkStatus.COMPLETED, minute=1))
    await fresh.observe_work_item(core.work.current_snapshot().items[0])
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.COMPLETED


async def test_the_periodic_sweep_runs_at_start_and_survives_a_failure(core, monkeypatch):
    calls = []
    service = MissionHistoryService(core.store, work_state=core.work, diagnostics=core.journal, clock=Clock(),
                                    sweep_interval_s=0.01)

    async def sweep():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("balayage cassé")
        return 0

    monkeypatch.setattr(service, "_sweep", sweep)
    await service.start()
    for _ in range(50):
        if len(calls) >= 3:
            break
        await asyncio.sleep(0.01)
    await service.stop()
    assert len(calls) >= 3
    assert core.journal.kinds("mission_history.sweep_failed")[0]["error"] == "RuntimeError"
