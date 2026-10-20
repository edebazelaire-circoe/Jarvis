"""Service Core de l'historique des missions : déclarations, éphémères, réconciliation avec Work State,
redémarrage et fournisseur dégradé (Slice 03 organic-agent-orchestration).

Bases temporaires seulement ; Work State est le vrai `WorkStateStore`, en mémoire.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.mission_history import (
    MISSION_HISTORY_DECLARATION_REFUSED_KIND, MISSION_HISTORY_DEGRADED_KIND, MISSION_HISTORY_EPHEMERAL_DISCARDED_KIND,
    MISSION_HISTORY_READY_KIND, MISSION_HISTORY_RECOVERED_KIND, MISSION_HISTORY_ROLE_MISMATCH_KIND,
    MissionHistoryService,
)
from jarvis.core.v2_services import CoreEventBus
from jarvis.core.work_state import WorkStateStore
from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.agent_relations import RelationError
from jarvis.domain.mission_history import AGENT_DECLARED_KIND, DeclarationOutcome as O
from jarvis.domain.subagent_roles import RoleStatus
from jarvis.domain.work_state import WorkStatus
from jarvis.ports.mission_history import MissionHistoryUnavailable
from tests.fakes.mission_history import SOURCE, at, fact, mission, observation, open_store, relation


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.lines.append((kind, level, dict(data or {})))

    def kinds(self, kind: str) -> list[tuple[str, dict]]:
        return [(level, data) for name, level, data in self.lines if name == kind]


class Clock:
    def now(self):
        return at(30)


class Flaky:
    """Le vrai magasin, qui refuse tant que `down` est vrai (verrou, disque plein...)."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.down = False

    def __getattr__(self, name):
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        async def call(*args, **kwargs):
            if self.down:
                raise MissionHistoryUnavailable(name, "OperationalError: database is locked")
            return await attribute(*args, **kwargs)

        return call


@pytest.fixture
async def world(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    work = WorkStateStore(clock=Clock())
    journal = Journal()
    ids = iter(f"inst{i}" for i in range(1, 100))
    service = MissionHistoryService(store, work_state=work, diagnostics=journal, clock=Clock(),
                                    instance_ids=lambda: next(ids))
    yield service, store, work, journal
    await service.stop()
    await state.close()


async def _declare(service, tool_use_id, **fields):
    return await service.record_declaration(fact(tool_use_id, **fields), work_source=SOURCE, work_external_id=tool_use_id)


# ------------------------------------------------------------------ déclarations ordinaires


async def test_a_declaration_is_recorded_once_and_logged(world):
    service, store, _work, journal = world
    result = await _declare(service, "toolu_1")
    assert result.outcome is O.RECORDED and result.instance.instance_id == "inst1"
    [(level, data)] = journal.kinds(AGENT_DECLARED_KIND)
    assert level == "info" and data["role_id"] == "coder" and data["role_status"] == "declared"
    assert (await _declare(service, "toolu_1")).outcome is O.DUPLICATE
    assert (await store.counts())["agent_instances"] == 1


async def test_a_replayed_declaration_cannot_rewrite_the_role(world):
    service, store, _work, journal = world
    await _declare(service, "toolu_1")
    result = await _declare(service, "toolu_1", role="research")
    assert result.outcome is O.REFUSED and result.code == "immutable_field"
    [(level, data)] = journal.kinds(MISSION_HISTORY_DECLARATION_REFUSED_KIND)
    assert level == "warning" and data["code"] == "immutable_field"
    assert (await store.find_instance(SOURCE, "toolu_1")).instance.role_id == "coder"


async def test_an_unknown_role_is_kept_as_unknown_never_guessed(world):
    service, store, _work, _journal = world
    result = await _declare(service, "toolu_1", role="unknown", status=RoleStatus.UNKNOWN)
    assert result.outcome is O.RECORDED
    stored = await store.find_instance(SOURCE, "toolu_1")
    assert stored.instance.role_id == "unknown" and not stored.instance.role_known


async def test_a_mission_owner_opens_its_mission_and_an_unknown_mission_is_refused(world):
    service, store, _work, _journal = world
    result = await service.record_declaration(
        fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE, work_external_id="toolu_own",
        mission=mission("m1", "inst1"))
    assert result.outcome is O.RECORDED and (await store.get_mission("m1")).owner_instance_id == "inst1"
    refused = await _declare(service, "toolu_x", mission_id="m404")
    assert refused.outcome is O.REFUSED and refused.code == "mission_unknown"
    # Une éphémère ne possède pas de mission (D08).
    refused = await _declare(service, "toolu_e", ephemeral=True, mission_id="m1", owner=True)
    assert refused.outcome is O.REFUSED and refused.code == "ephemeral_mission_owner"


async def test_the_parent_comes_from_the_work_identity_never_from_a_label(world):
    service, store, _work, _journal = world
    await _declare(service, "toolu_parent")
    child = await service.record_declaration(fact("toolu_child"), work_source=SOURCE, work_external_id="toolu_child",
                                             parent_work_external_id="toolu_parent")
    assert child.instance.parent_instance_id == "inst1"
    orphan = await service.record_declaration(fact("toolu_orphan"), work_source=SOURCE,
                                              work_external_id="toolu_orphan", parent_work_external_id="toolu_unknown")
    assert orphan.outcome is O.RECORDED and orphan.instance.parent_instance_id is None


# ------------------------------------------------------------------ éphémères (D08)


async def test_a_completed_ephemeral_leaves_no_durable_row_and_cannot_be_resurrected(world):
    service, store, work, journal = world
    assert (await _declare(service, "toolu_e", ephemeral=True)).outcome is O.EPHEMERAL_PENDING
    assert (await store.counts())["agent_instances"] == 0  # jamais tant qu'elle est éphémère
    await work.apply(observation("toolu_e", WorkStatus.RUNNING, minute=1, ephemeral=True))
    assert await service.observe_work_item(work.current_snapshot().items[0]) is None
    await work.apply(observation("toolu_e", WorkStatus.COMPLETED, minute=2, ephemeral=True))
    result = await service.observe_work_item(work.current_snapshot().items[0])
    assert result.outcome is O.EPHEMERAL_DISCARDED
    assert journal.kinds(MISSION_HISTORY_EPHEMERAL_DISCARDED_KIND)
    # Rejeu tardif de la déclaration, puis de l'observation : toujours rien de durable.
    assert (await _declare(service, "toolu_e", ephemeral=True)).outcome is O.EPHEMERAL_DISCARDED
    assert await service.observe_work_item(work.current_snapshot().items[0]) is None
    assert (await store.counts())["agent_instances"] == 0
    assert service.health().pending_ephemeral == 0


async def test_a_failed_ephemeral_loses_its_flag_and_is_retained(world):
    service, store, work, _journal = world
    await _declare(service, "toolu_e", ephemeral=True)
    await work.apply(observation("toolu_e", WorkStatus.FAILED, minute=1))
    result = await service.observe_work_item(work.current_snapshot().items[0])
    assert result.outcome is O.EPHEMERAL_RETAINED
    stored = await store.find_instance(SOURCE, "toolu_e")
    assert stored.ephemeral_lowered and not stored.instance.ephemeral and stored.declaration.ephemeral
    # La même déclaration rejouée (Core redémarré, producteur qui renvoie) : un doublon, pas un refus.
    assert (await _declare(service, "toolu_e", ephemeral=True)).outcome is O.DUPLICATE


@pytest.mark.parametrize("status, outcome", [
    (WorkStatus.COMPLETED, O.EPHEMERAL_DISCARDED),
    (WorkStatus.INTERRUPTED, O.EPHEMERAL_RETAINED),
    (WorkStatus.BLOCKED, O.EPHEMERAL_RETAINED),
    (WorkStatus.RUNNING, O.EPHEMERAL_PENDING),
])
async def test_a_late_ephemeral_declaration_follows_the_live_status(world, status, outcome):
    service, store, work, _journal = world
    if status is WorkStatus.BLOCKED:
        await work.apply(observation("toolu_e", WorkStatus.RUNNING, minute=0))
    await work.apply(observation("toolu_e", status, minute=1))
    assert (await _declare(service, "toolu_e", ephemeral=True)).outcome is outcome
    retained = (await store.counts())["agent_instances"]
    assert retained == (1 if outcome is O.EPHEMERAL_RETAINED else 0)


async def test_a_pending_ephemeral_is_never_a_relation_participant(world):
    service, _store, _work, _journal = world
    await service.record_declaration(fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE,
                                     work_external_id="toolu_own", mission=mission("m1", "inst1"))
    pending = await _declare(service, "toolu_e", ephemeral=True)
    with pytest.raises(RelationError) as caught:
        await service.create_relation(relation("c1", K.COMMUNICATION, "m1", [
            ("inst1", P.MEMBER), (pending.instance.instance_id, P.MEMBER)]))
    assert caught.value.code == "relation_participant_missing"


async def test_the_bus_drives_the_ephemeral_rule(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    bus = CoreEventBus()
    work = WorkStateStore(events=bus, clock=Clock())
    journal = Journal()
    service = MissionHistoryService(store, work_state=work, events=bus, diagnostics=journal, clock=Clock())
    try:
        await service.start()
        assert journal.kinds(MISSION_HISTORY_READY_KIND)[0][1]["agent_instances"] == 0
        await _declare(service, "toolu_e", ephemeral=True)
        await work.apply(observation("toolu_e", WorkStatus.FAILED, minute=1))
        for _ in range(200):
            if await store.find_instance(SOURCE, "toolu_e") is not None:
                break
            await asyncio.sleep(0.005)
        assert (await store.find_instance(SOURCE, "toolu_e")).ephemeral_lowered
    finally:
        await service.stop()
        await state.close()


async def test_a_lost_bus_event_is_caught_up_by_the_sweep(world):
    service, store, work, _journal = world
    await _declare(service, "toolu_e", ephemeral=True)
    await work.apply(observation("toolu_e", WorkStatus.CANCELLED, minute=1))  # aucun abonné : l'événement est perdu
    assert await service.sweep() == 1
    assert (await store.find_instance(SOURCE, "toolu_e")).ephemeral_lowered


# ------------------------------------------------------------------ réconciliation et redémarrage


async def test_history_survives_a_core_restart_and_live_status_comes_from_work_state_only(tmp_path):
    path = tmp_path / "jarvis.sqlite3"
    state, store = await open_store(path)
    work = WorkStateStore(clock=Clock())
    service = MissionHistoryService(store, work_state=work, clock=Clock())
    await _declare(service, "toolu_1")
    await work.apply(observation("toolu_1", WorkStatus.RUNNING, minute=1, role_id="coder"))
    assert (await service.instance_for_work(SOURCE, "toolu_1")).work_status is WorkStatus.RUNNING
    await state.close()

    # Core redémarre : Work State repart vide, l'historique est intact.
    state, store = await open_store(path)
    work = WorkStateStore(clock=Clock())
    service = MissionHistoryService(store, work_state=work, clock=Clock())
    try:
        view = await service.instance_for_work(SOURCE, "toolu_1")
        assert view.stored.instance.role_id == "coder" and view.work_status is None  # inconnu, jamais deviné
        # Le producteur rejoue : la déclaration est un doublon, l'observation rend le statut vivant.
        assert (await _declare(service, "toolu_1")).outcome is O.DUPLICATE
        assert (await _declare(service, "toolu_1", role="research")).outcome is O.REFUSED
        await work.apply(observation("toolu_1", WorkStatus.COMPLETED, minute=2, role_id="coder"))
        view = await service.instance_for_work(SOURCE, "toolu_1")
        assert view.work_status is WorkStatus.COMPLETED and view.stored.instance.role_id == "coder"
    finally:
        await state.close()


async def test_a_role_contradiction_between_work_state_and_history_is_reported_and_nothing_is_rewritten(world):
    service, store, work, journal = world
    await _declare(service, "toolu_1")
    await work.apply(observation("toolu_1", WorkStatus.RUNNING, minute=1, role_id="research"))
    await service.observe_work_item(work.current_snapshot().items[0])
    [(level, data)] = journal.kinds(MISSION_HISTORY_ROLE_MISMATCH_KIND)
    assert level == "warning" and data["history_role_id"] == "coder" and data["work_role_id"] == "research"
    assert (await store.find_instance(SOURCE, "toolu_1")).instance.role_id == "coder"
    assert work.current_snapshot().items[0].role_id == "research"


async def test_mission_view_joins_live_status_per_instance(world):
    service, _store, work, _journal = world
    await service.record_declaration(fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE,
                                     work_external_id="toolu_own", mission=mission("m1", "inst1"))
    await _declare(service, "toolu_dev", mission_id="m1")
    await work.apply(observation("toolu_dev", WorkStatus.RUNNING, minute=1))
    tree, views = await service.mission_view("m1")
    assert [m.mission_id for m in tree.missions] == ["m1"]
    assert {view.stored.instance.work_external_id: view.work_status for view in views} == {
        "toolu_own": None, "toolu_dev": WorkStatus.RUNNING}
    payload = views[0].to_payload()
    assert "work_status" in payload and "status" not in payload


# ------------------------------------------------------------------ fournisseur dégradé


async def test_a_store_outage_degrades_history_but_never_live_work(tmp_path):
    state, inner = await open_store(tmp_path / "jarvis.sqlite3")
    store = Flaky(inner)
    work = WorkStateStore(clock=Clock())
    journal = Journal()
    service = MissionHistoryService(store, work_state=work, diagnostics=journal, clock=Clock())
    try:
        store.down = True
        result = await _declare(service, "toolu_1")
        assert result.outcome is O.DEGRADED and result.code == "mission_history_failed"
        health = service.health().to_payload()
        assert health["state"] == "degraded" and "database is locked" in health["reason"]
        [(level, data)] = journal.kinds(MISSION_HISTORY_DEGRADED_KIND)
        assert level == "error" and data["operation"] == "find_instance"
        # Le travail vivant continue : Work State ingère comme avant.
        assert await work.apply(observation("toolu_1", WorkStatus.RUNNING, minute=1)) == "created"
        await service.sweep()  # toujours indisponible : rien de perdu, rien de levé
        assert service.degraded
        with pytest.raises(MissionHistoryUnavailable):
            await service.create_relation(relation("c1", K.COMMUNICATION, "m1", [("a", P.MEMBER), ("b", P.MEMBER)]))

        store.down = False
        assert (await _declare(service, "toolu_2")).outcome is O.RECORDED
        assert not service.degraded
        [(_level, data)] = journal.kinds(MISSION_HISTORY_RECOVERED_KIND)
        assert data["failed_writes"] >= 2
    finally:
        await state.close()


async def test_an_unsaved_write_is_replayed_once_the_store_is_back(tmp_path):
    state, inner = await open_store(tmp_path / "jarvis.sqlite3")
    store = Flaky(inner)
    work = WorkStateStore(clock=Clock())
    service = MissionHistoryService(store, work_state=work, clock=Clock())
    try:
        await _declare(service, "toolu_e", ephemeral=True)
        await work.apply(observation("toolu_e", WorkStatus.FAILED, minute=1))
        store.down = True
        assert (await service.observe_work_item(work.current_snapshot().items[0])).outcome is O.DEGRADED
        store.down = False
        assert await service.sweep() == 1
        assert (await inner.find_instance(SOURCE, "toolu_e")).ephemeral_lowered
        assert not service.degraded
    finally:
        await state.close()
