"""Rework QA de la Slice 03 (organic-agent-orchestration) : ouverture de mission par l'API publique du service
(B1), bornes mémoire (M16, M17, M23), rejeu tardif d'une éphémère oubliée (M10), transfert vers un autre que le
successeur (M18), mission close gelée par la table (M03), diagnostics (N2, N3, N4a).

Bases temporaires seulement ; Work State est le vrai `WorkStateStore`, en mémoire.
"""

from __future__ import annotations

import sqlite3

import pytest

from jarvis.core import mission_history as mission_history_module
from jarvis.core.mission_history import (
    MISSION_HISTORY_DEGRADED_KIND, MISSION_HISTORY_DISCARDED_FORGOTTEN_KIND, MISSION_HISTORY_PENDING_DROPPED_KIND,
    MISSION_HISTORY_RECOVERED_KIND, MISSION_HISTORY_UNSAVED_REFUSED_KIND, MissionHistoryService,
)
from jarvis.core.work_state import WorkStateStore
from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.mission_history import AGENT_DECLARED_KIND, MissionOpening
from jarvis.domain.mission_history import DeclarationOutcome as O
from jarvis.domain.missions import MissionError, MissionStatus
from jarvis.domain.work_state import WorkStatus
from jarvis.ports.mission_history import MissionHistoryUnavailable
from tests.fakes.mission_history import SOURCE, at, fact, instance, mission, observation, open_store, packet, relation
from tests.unit.test_mission_history_service import Clock, Flaky, Journal


async def _declare(service, tool_use_id, **fields):
    return await service.record_declaration(fact(tool_use_id, **fields), work_source=SOURCE, work_external_id=tool_use_id)


@pytest.fixture
async def public(tmp_path):
    """Le service tel que Core le construit (`v2_app`) : aucun générateur d'id injecté."""

    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    work = WorkStateStore(clock=Clock())
    journal = Journal()
    service = MissionHistoryService(store, work_state=work, diagnostics=journal, clock=Clock())
    yield service, store, work, journal
    await state.close()


@pytest.fixture
async def store(tmp_path):
    state, repository = await open_store(tmp_path / "jarvis.sqlite3")
    yield repository
    await state.close()


# ------------------------------------------------------------------ B1 : ouverture de mission


async def test_a_root_and_a_sub_mission_open_through_the_public_api(public):
    service, store, _work, _journal = public
    root = await service.record_declaration(
        fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE, work_external_id="toolu_own",
        mission=MissionOpening(objective="Corriger la facturation"))
    assert root.outcome is O.RECORDED and root.instance.instance_id.startswith("ainst_")
    opened = await store.get_mission("m1")
    assert (opened.owner_instance_id, opened.root_mission_id, opened.objective) == (
        root.instance.instance_id, "m1", "Corriger la facturation")
    assert opened.created_at == fact("toolu_own").declared_at

    sub = await service.record_declaration(
        fact("toolu_sub", mission_id="m1.tests", owner=True, minute=1), work_source=SOURCE,
        work_external_id="toolu_sub", parent_work_external_id="toolu_own",
        mission=MissionOpening(objective="Écrire les tests", parent_mission_id="m1"))
    assert sub.outcome is O.RECORDED and sub.instance.parent_instance_id == root.instance.instance_id
    child = await store.get_mission("m1.tests")
    assert (child.owner_instance_id, child.parent_mission_id, child.root_mission_id) == (
        sub.instance.instance_id, "m1", "m1")
    assert [m.mission_id for m in (await store.mission_tree("m1")).missions] == ["m1", "m1.tests"]
    # Un membre (pas propriétaire) se rattache à la sous-mission sans rien ouvrir.
    assert (await _declare(service, "toolu_dev", mission_id="m1.tests", minute=2)).outcome is O.RECORDED
    # Rejeu de l'ouverture (redémarrage du producteur) : un doublon, la mission n'est pas rouverte.
    replay = await service.record_declaration(
        fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE, work_external_id="toolu_own",
        mission=MissionOpening(objective="Corriger la facturation"))
    assert replay.outcome is O.DUPLICATE and replay.instance.instance_id == root.instance.instance_id


async def test_a_full_mission_value_gets_its_owner_and_root_from_core(public):
    service, store, _work, _journal = public
    result = await service.record_declaration(
        fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE, work_external_id="toolu_own",
        mission=mission("m1", "a-guess-the-caller-cannot-know"))
    assert result.outcome is O.RECORDED
    assert (await store.get_mission("m1")).owner_instance_id == result.instance.instance_id


@pytest.mark.parametrize("fields, opening, code", [
    ({}, MissionOpening(objective="x"), "ownership_invalid"),  # pas Mission Owner
    ({"mission_id": "m2", "owner": True}, MissionOpening(objective="x", parent_mission_id="ghost"),
     "mission_parent_missing"),
    ({"mission_id": "m2", "owner": True}, MissionOpening(objective="  "), "mission_invalid"),
])
async def test_a_mission_opening_is_refused_with_its_reason(public, fields, opening, code):
    service, store, _work, _journal = public
    result = await service.record_declaration(fact("toolu_x", **fields), work_source=SOURCE,
                                              work_external_id="toolu_x", mission=opening)
    assert result.outcome is O.REFUSED and result.code == code
    assert await store.find_instance(SOURCE, "toolu_x") is None


# ------------------------------------------------------------------ M18, M03 : magasin


async def test_transfer_to_someone_else_than_the_handoff_successor_is_refused(store):
    await store.record_instance(instance("own", mission="m1", owner=True), mission=mission("m1", "own"))
    await store.record_instance(instance("succ", mission="m1", owner=True, minute=2))
    await store.record_instance(instance("other", mission="m1", owner=True, minute=2))
    await store.create_relation(relation("h1", K.HANDOFF, "m1", [("own", P.PREDECESSOR), ("succ", P.SUCCESSOR)],
                                         minute=3, handoff=packet()))
    with pytest.raises(MissionError) as caught:
        await store.transfer_ownership("m1", "other", handoff_relation_id="h1", at=at(4))
    assert caught.value.code == "ownership_invalid"
    assert (await store.get_mission("m1")).owner_instance_id == "own"
    assert [c.owner_instance_id for c in await store.ownership("m1")] == ["own"]


async def test_a_closed_mission_row_is_frozen_by_the_table(store):
    await store.record_instance(instance("own", mission="m1", owner=True), mission=mission("m1", "own"))
    await store.record_instance(instance("succ", mission="m1", owner=True, minute=2))
    await store.create_relation(relation("h1", K.HANDOFF, "m1", [("own", P.PREDECESSOR), ("succ", P.SUCCESSOR)],
                                         minute=3, handoff=packet()))
    closed = await store.close_mission("m1", MissionStatus.COMPLETED, at(5))

    def poke(sql):
        def run(conn):
            conn.execute(sql)
        return run

    for sql in ("UPDATE missions SET data=data WHERE mission_id='m1'",
                "UPDATE missions SET owner_instance_id='succ' WHERE mission_id='m1'",
                "UPDATE missions SET status='open', closed_at=NULL WHERE mission_id='m1'"):
        with pytest.raises(sqlite3.IntegrityError, match="frozen"):
            await store._state.run_serialized(poke(sql))
    # Comportement : la mission close ne change plus de propriétaire et ne se reclôt pas autrement.
    with pytest.raises(MissionError) as caught:
        await store.transfer_ownership("m1", "succ", handoff_relation_id="h1", at=at(6))
    assert caught.value.code == "mission_closed"
    with pytest.raises(MissionError) as caught:
        await store.close_mission("m1", MissionStatus.FAILED, at(6))
    assert caught.value.code == "mission_closed"
    assert await store.get_mission("m1") == closed


# ------------------------------------------------------------------ M16, M17, M23 : bornes mémoire


async def test_the_oldest_pending_ephemeral_is_evicted_and_reported(public, monkeypatch):
    service, store, work, journal = public
    monkeypatch.setattr(mission_history_module, "MAX_PENDING_EPHEMERAL", 2)
    for name in ("toolu_a", "toolu_b", "toolu_c"):
        await _declare(service, name, ephemeral=True)
    assert service.health().pending_ephemeral == 2
    [(level, data)] = journal.kinds(MISSION_HISTORY_PENDING_DROPPED_KIND)
    assert level == "warning" and data["work_external_id"] == "toolu_a" and data["max_pending"] == 2
    # L'évincée échoue ensuite : plus suivie, rien n'est retenu ; la suivante l'est.
    await work.apply(observation("toolu_a", WorkStatus.FAILED, minute=1))
    await work.apply(observation("toolu_b", WorkStatus.FAILED, minute=1))
    for item in work.current_snapshot().items:
        await service.observe_work_item(item)
    assert await store.find_instance(SOURCE, "toolu_a") is None
    assert (await store.find_instance(SOURCE, "toolu_b")).ephemeral_lowered


async def test_the_oldest_discarded_key_is_forgotten_and_reported(public, monkeypatch):
    service, store, work, journal = public
    monkeypatch.setattr(mission_history_module, "MAX_DISCARDED_KEYS", 2)
    for minute, name in enumerate(("toolu_a", "toolu_b", "toolu_c")):
        await _declare(service, name, ephemeral=True)
        await work.apply(observation(name, WorkStatus.COMPLETED, minute=minute))
        item = next(i for i in work.current_snapshot().items if i.external_id == name)
        assert (await service.observe_work_item(item)).outcome is O.EPHEMERAL_DISCARDED
    [(level, data)] = journal.kinds(MISSION_HISTORY_DISCARDED_FORGOTTEN_KIND)
    assert level == "warning" and data["work_external_id"] == "toolu_a" and data["max_discarded"] == 2
    assert [key[1] for key in service._discarded] == ["toolu_b", "toolu_c"]
    # L'oubliée rejouée suit de nouveau le statut vivant (réussie) : écartée, toujours sans ligne durable.
    assert (await _declare(service, "toolu_a", ephemeral=True)).outcome is O.EPHEMERAL_DISCARDED
    assert (await store.counts())["agent_instances"] == 0


async def test_the_oldest_unsaved_write_is_dropped_and_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(mission_history_module, "MAX_UNSAVED", 2)
    state, inner = await open_store(tmp_path / "jarvis.sqlite3")
    store = Flaky(inner)
    work = WorkStateStore(clock=Clock())
    journal = Journal()
    service = MissionHistoryService(store, work_state=work, diagnostics=journal, clock=Clock())
    try:
        for name in ("toolu_a", "toolu_b", "toolu_c"):
            await _declare(service, name, ephemeral=True)
            await work.apply(observation(name, WorkStatus.FAILED, minute=1))
        store.down = True
        for name in ("toolu_a", "toolu_b", "toolu_c"):
            item = next(i for i in work.current_snapshot().items if i.external_id == name)
            assert (await service.observe_work_item(item)).outcome is O.DEGRADED
        dropped = [data for level, data in journal.kinds(MISSION_HISTORY_PENDING_DROPPED_KIND) if level == "error"]
        assert [data["work_external_id"] for data in dropped] == ["toolu_a"] and dropped[0]["max_unsaved"] == 2
        store.down = False
        assert await service.sweep() == 2
        assert await inner.find_instance(SOURCE, "toolu_a") is None
        for name in ("toolu_b", "toolu_c"):
            assert (await inner.find_instance(SOURCE, name)).ephemeral_lowered
        [(_level, data)] = journal.kinds(MISSION_HISTORY_RECOVERED_KIND)
        # Exact (N3) : compté après le retrait de l'écriture rejouée qui a rétabli le magasin.
        assert data["unsaved"] == 1
    finally:
        await state.close()


# ------------------------------------------------------------------ M10


async def test_a_late_replay_of_a_succeeded_ephemeral_that_work_state_forgot_stays_discarded(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    work = WorkStateStore(clock=Clock(), max_items=1)
    service = MissionHistoryService(store, work_state=work, clock=Clock())
    try:
        await _declare(service, "toolu_e", ephemeral=True)
        await work.apply(observation("toolu_e", WorkStatus.COMPLETED, minute=1))
        await service.observe_work_item(work.current_snapshot().items[0])
        await work.apply(observation("toolu_other", WorkStatus.RUNNING, minute=2))  # élague toolu_e
        assert [item.external_id for item in work.current_snapshot().items] == ["toolu_other"]
        assert (await _declare(service, "toolu_e", ephemeral=True)).outcome is O.EPHEMERAL_DISCARDED
        assert service.health().pending_ephemeral == 0
        assert (await store.counts())["agent_instances"] == 0
    finally:
        await state.close()


# ------------------------------------------------------------------ N2, N3, N4a : diagnostics


async def test_an_unsaved_write_refused_at_replay_is_reported(tmp_path):
    state, inner = await open_store(tmp_path / "jarvis.sqlite3")
    store = Flaky(inner)
    journal = Journal()
    service = MissionHistoryService(store, work_state=WorkStateStore(clock=Clock()), diagnostics=journal,
                                    clock=Clock())
    try:
        store.down = True
        # Mission jamais ouverte : l'écriture mise en attente pendant la panne sera refusée au rejeu.
        assert (await service._persist((SOURCE, "toolu_1"), instance("i1", external="toolu_1", mission="m-late"),
                                       None, False, None)).outcome is O.DEGRADED
        store.down = False
        assert await service.sweep() == 1
        [(level, data)] = journal.kinds(MISSION_HISTORY_UNSAVED_REFUSED_KIND)
        assert level == "error" and data["code"] == "mission_unknown" and data["work_external_id"] == "toolu_1"
        assert not service._unsaved and not service.degraded
    finally:
        await state.close()


async def test_the_degraded_diagnostic_names_the_real_operation(tmp_path, monkeypatch):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    journal = Journal()
    service = MissionHistoryService(store, work_state=WorkStateStore(clock=Clock()), diagnostics=journal,
                                    clock=Clock())
    real = store._state.run_serialized
    calls = {"n": 0}

    async def lock_writes(fn):
        calls["n"] += 1
        if calls["n"] > 1:  # find_instance passe, record_instance bute sur le verrou
            raise sqlite3.OperationalError("database is locked")
        return await real(fn)

    try:
        monkeypatch.setattr(store._state, "run_serialized", lock_writes)
        result = await _declare(service, "toolu_1")
        assert result.outcome is O.DEGRADED
        assert "record_instance failed" in result.message and "_transaction" not in result.message
        [(_level, data)] = journal.kinds(MISSION_HISTORY_DEGRADED_KIND)
        assert data["operation"] == "record_instance" and "record_instance failed" in data["detail"]
    finally:
        monkeypatch.setattr(store._state, "run_serialized", real)
        await state.close()


async def test_an_ephemeral_retained_by_observation_is_announced_like_a_declaration(public):
    service, _store, work, journal = public
    await _declare(service, "toolu_e", ephemeral=True)
    await work.apply(observation("toolu_e", WorkStatus.FAILED, minute=1))
    await service.observe_work_item(work.current_snapshot().items[0])
    announced = [data for _level, data in journal.kinds(AGENT_DECLARED_KIND)]
    assert [data["outcome"] for data in announced] == ["ephemeral_pending", "ephemeral_retained"]
    assert announced[-1]["instance_id"] is not None


# ------------------------------------------------------------------ revérification QA : N1 à N4


class Selective(Flaky):
    """Le magasin réel, qui refuse seulement les opérations nommées tant que `down` est vrai."""

    def __init__(self, inner, failing: set[str]) -> None:
        super().__init__(inner)
        self.failing = failing

    def __getattr__(self, name):
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        async def call(*args, **kwargs):
            if self.down and name in self.failing:
                raise MissionHistoryUnavailable(name, "OSError: disk I/O error")
            return await attribute(*args, **kwargs)

        return call


async def _down_world(tmp_path, failing=None):
    state, inner = await open_store(tmp_path / "jarvis.sqlite3")
    store = Flaky(inner) if failing is None else Selective(inner, failing)
    journal = Journal()
    service = MissionHistoryService(store, work_state=WorkStateStore(clock=Clock()), diagnostics=journal,
                                    clock=Clock())
    return state, inner, store, service, journal


async def test_a_declaration_made_during_a_total_outage_is_replayed_and_becomes_durable(tmp_path):
    state, inner, store, service, journal = await _down_world(tmp_path)
    try:
        store.down = True  # lectures ET écritures refusées
        result = await _declare(service, "toolu_1")
        assert result.outcome is O.DEGRADED and len(service._unsaved) == 1
        store.down = False
        assert await service.sweep() == 1
        stored = await inner.find_instance(SOURCE, "toolu_1")
        assert stored is not None and stored.declaration == fact("toolu_1")
        assert not service._unsaved and not service.degraded
        [(_level, data)] = journal.kinds(MISSION_HISTORY_RECOVERED_KIND)
        assert data["unsaved"] == 0
        assert [d["outcome"] for _l, d in journal.kinds(AGENT_DECLARED_KIND)] == ["recorded"]
    finally:
        await state.close()


async def test_a_mission_opening_made_during_a_total_outage_is_replayed_with_its_owner(tmp_path):
    state, inner, store, service, _journal = await _down_world(tmp_path)
    try:
        store.down = True
        result = await service.record_declaration(
            fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE, work_external_id="toolu_own",
            mission=MissionOpening(objective="Objectif"))
        assert result.outcome is O.DEGRADED
        store.down = False
        assert await service.sweep() == 1
        owner = await inner.find_instance(SOURCE, "toolu_own")
        assert (await inner.get_mission("m1")).owner_instance_id == owner.instance.instance_id
        assert not service._unsaved
    finally:
        await state.close()


async def test_a_sub_mission_whose_parent_read_fails_is_replayed(tmp_path):
    state, inner, store, service, _journal = await _down_world(tmp_path, failing={"get_mission"})
    try:
        await service.record_declaration(fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE,
                                         work_external_id="toolu_own", mission=MissionOpening(objective="Racine"))
        store.down = True
        result = await service.record_declaration(
            fact("toolu_sub", mission_id="m1.a", owner=True, minute=1), work_source=SOURCE,
            work_external_id="toolu_sub", mission=MissionOpening(objective="Sous", parent_mission_id="m1"))
        assert result.outcome is O.DEGRADED and len(service._unsaved) == 1
        store.down = False
        assert await service.sweep() == 1
        assert (await inner.get_mission("m1.a")).root_mission_id == "m1"
        assert not service._unsaved
    finally:
        await state.close()


async def test_a_sub_mission_under_a_closed_parent_is_refused(public):
    service, store, _work, _journal = public
    await service.record_declaration(fact("toolu_own", mission_id="m1", owner=True), work_source=SOURCE,
                                     work_external_id="toolu_own", mission=MissionOpening(objective="Racine"))
    await service.close_mission("m1", MissionStatus.COMPLETED)
    result = await service.record_declaration(
        fact("toolu_sub", mission_id="m1.a", owner=True, minute=1), work_source=SOURCE, work_external_id="toolu_sub",
        mission=MissionOpening(objective="Sous", parent_mission_id="m1"))
    assert result.outcome is O.REFUSED and result.code == "mission_closed"
    assert await store.get_mission("m1.a") is None and await store.find_instance(SOURCE, "toolu_sub") is None
    # Même règle au magasin, défense en profondeur.
    with pytest.raises(MissionError) as caught:
        await store.record_instance(instance("sub", mission="m1.b", owner=True, minute=2),
                                    mission=mission("m1.b", "sub", parent="m1", root="m1", minute=2))
    assert caught.value.code == "mission_closed"


async def test_an_ephemeral_non_owner_declaration_cannot_carry_a_mission_opening(public):
    service, store, _work, _journal = public
    result = await service.record_declaration(fact("toolu_e", ephemeral=True), work_source=SOURCE,
                                              work_external_id="toolu_e", mission=MissionOpening(objective="x"))
    assert result.outcome is O.REFUSED and result.code == "ownership_invalid"
    assert service.health().pending_ephemeral == 0
    assert (await store.counts())["missions"] == 0


async def test_a_sub_sub_mission_takes_the_root_of_its_grandparent(public):
    service, store, _work, _journal = public
    for minute, (mission_id, parent) in enumerate((("m1", None), ("m1.a", "m1"), ("m1.a.b", "m1.a"))):
        result = await service.record_declaration(
            fact(f"toolu_{mission_id}", mission_id=mission_id, owner=True, minute=minute), work_source=SOURCE,
            work_external_id=f"toolu_{mission_id}",
            mission=MissionOpening(objective=f"Objectif {mission_id}", parent_mission_id=parent))
        assert result.outcome is O.RECORDED, result
    deepest = await store.get_mission("m1.a.b")
    assert (deepest.parent_mission_id, deepest.root_mission_id) == ("m1.a", "m1")
    assert [m.mission_id for m in (await store.mission_tree("m1.a.b")).missions] == ["m1", "m1.a", "m1.a.b"]
