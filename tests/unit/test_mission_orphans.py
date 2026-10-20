"""Missions orphelines et balayage tournant (Slice 05, revérification QA) ; repli sur la fin retenue (mutant N10).

Rien n'est deviné : une mission dont ni le propriétaire ni aucun membre n'est connu de Work State reste ouverte ;
sa vue dit `live_unknown` après le délai de grâce. Bases temporaires seulement.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jarvis.core.mission_history import (
    MAX_SWEPT_MISSIONS, MISSION_HISTORY_ORPHANED_KIND, ORPHAN_GRACE_S, MissionHistoryService,
)
from jarvis.core.work_state import WorkStateStore
from jarvis.domain.mission_history import MissionOpening
from jarvis.domain.missions import MissionStatus
from jarvis.domain.work_state import WorkSnapshot, WorkStatus
from jarvis.protocol.mission_routes import MissionProtocolRoutes
from tests.fakes.mission_history import SOURCE, at, fact, observation, open_store
from tests.unit.test_mission_orchestration_wiring import Journal


class MovingClock:
    def __init__(self) -> None:
        self.value = at(30)

    def now(self):
        return self.value


async def _world(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    clock = MovingClock()
    work = WorkStateStore(clock=clock)
    journal = Journal()
    service = MissionHistoryService(store, work_state=work, diagnostics=journal, clock=clock, sweep_interval_s=None)
    return state, store, work, journal, service, clock


async def _open(service, key, *, minute=0.0, parent=None, role="coder"):
    return await service.record_declaration(
        fact(key, role=role, mission_id=f"mis_{key}", owner=True, label="Objet", minute=minute),
        work_source=SOURCE, work_external_id=key, parent_work_external_id=parent,
        mission=MissionOpening(objective="Objet", parent_from_caller=True), inherit_mission=True)


async def test_the_rotating_sweep_reaches_an_old_mission_behind_70_orphans(tmp_path):
    state, store, work, _journal, service, _clock = await _world(tmp_path)
    try:
        await _open(service, "AOLD", minute=0)
        for key, status, minute in (("AOLD", WorkStatus.RUNNING, 0.5), ("AOLD", WorkStatus.COMPLETED, 1)):
            await work.observe(observation(key, status, minute=minute))  # fin vue par Work State, perdue par le bus
        for index in range(70):  # 70 missions plus récentes, propriétaires inconnus de Work State
            await _open(service, f"O{index:02d}", minute=2 + index / 100)
        # Et une mission plus récente que toutes, fin perdue aussi : ni l'ordre décroissant ni l'ordre croissant
        # sans curseur n'atteignent les deux.
        await _open(service, "ANEW", minute=5)
        for key, status, minute in (("ANEW", WorkStatus.RUNNING, 5.5), ("ANEW", WorkStatus.COMPLETED, 6)):
            await work.observe(observation(key, status, minute=minute))
        passes = 0
        while passes < 4 and MissionStatus.OPEN in {(await store.get_mission(m)).status for m in ("mis_AOLD", "mis_ANEW")}:
            await service.sweep()
            passes += 1
        assert (await store.get_mission("mis_AOLD")).status is MissionStatus.COMPLETED
        assert (await store.get_mission("mis_ANEW")).status is MissionStatus.COMPLETED
        assert passes <= -(-72 // MAX_SWEPT_MISSIONS)  # au plus ⌈ouvertes / 64⌉ passes
        # Aucune orpheline n'est close d'office : aucune issue inventée.
        assert len(await store.list_missions(open_only=True, limit=100)) == 70
    finally:
        await service.stop()
        await state.close()


async def test_live_unknown_is_derived_after_the_grace_delay_and_reported_once(tmp_path):
    state, store, work, journal, service, clock = await _world(tmp_path)
    try:
        await _open(service, "A", minute=0)
        tree = await store.mission_tree("mis_A")
        assert service.live_unknown(tree) == frozenset()  # Core vient de naître : délai de grâce
        clock.value = clock.value + timedelta(seconds=ORPHAN_GRACE_S + 1)
        assert service.live_unknown(tree) == {"mis_A"}
        await service.sweep()
        await service.sweep()
        assert len(journal.kinds(MISSION_HISTORY_ORPHANED_KIND)) == 1
        assert (await store.get_mission("mis_A")).status is MissionStatus.OPEN  # pas persisté, pas clos
        # Dès que Work State connaît le propriétaire, l'état n'est plus inconnu.
        await work.observe(observation("A", WorkStatus.RUNNING, minute=40))
        assert service.live_unknown(tree) == frozenset()
        # La route de lecture l'expose par mission.
        app = web.Application()
        app.add_routes(MissionProtocolRoutes(SimpleNamespace(mission_history=service, work_state=work,
                                                             _diagnostics=journal)).routes())
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            body = await (await client.get("/v1/missions/mis_A")).json()
            assert body["missions"][0]["live_unknown"] is False
            fresh = WorkStateStore(clock=clock)
            service._work_state = fresh  # redémarrage simulé : Work State vide
            body = await (await client.get("/v1/missions/mis_A")).json()
            assert body["missions"][0]["live_unknown"] is True and body["missions"][0]["status"] == "open"
        finally:
            await client.close()
    finally:
        await service.stop()
        await state.close()


async def test_a_young_mission_is_never_live_unknown(tmp_path):
    state, store, _work, _journal, service, clock = await _world(tmp_path)
    try:
        clock.value = clock.value + timedelta(seconds=ORPHAN_GRACE_S + 1)  # Core vieux...
        await _open(service, "N", minute=(clock.value - at(0)).total_seconds() / 60)  # ...mission neuve
        assert service.live_unknown(await store.mission_tree("mis_N")) == frozenset()
    finally:
        await service.stop()
        await state.close()


class Pruned:
    """Le Work State réel, dont le propriétaire a été élagué (borne de 64 éléments) avant la fin de l'équipe."""

    def __init__(self, inner, hidden: str) -> None:
        self.inner, self.hidden = inner, hidden

    def current_snapshot(self):
        snapshot = self.inner.current_snapshot()
        return WorkSnapshot(revision=snapshot.revision, updated_at=snapshot.updated_at,
                            items=tuple(item for item in snapshot.items if item.external_id != self.hidden))


async def test_the_retained_owner_end_closes_the_mission_once_the_owner_was_pruned(tmp_path):
    # Mutant N10 : sans le repli sur la fin retenue (`_owner_ended`), la mission restait ouverte pour toujours.
    state, store, work, _journal, service, _clock = await _world(tmp_path)
    try:
        await _open(service, "A")
        await work.observe(observation("B", WorkStatus.RUNNING, minute=0.2))
        await service.record_declaration(fact("B", role="qa"), work_source=SOURCE, work_external_id="B",
                                         parent_work_external_id="A", inherit_mission=True)
        for status, minute in ((WorkStatus.RUNNING, 0.5), (WorkStatus.FAILED, 1)):
            await work.observe(observation("A", status, minute=minute))
        await service.observe_work_item(next(i for i in work.current_snapshot().items if i.external_id == "A"))
        assert (await store.get_mission("mis_A")).status is MissionStatus.OPEN  # l'équipe travaille
        service._work_state = Pruned(work, "A")  # le propriétaire sort de Work State
        await work.observe(observation("B", WorkStatus.COMPLETED, minute=2))
        await service.observe_work_item(next(i for i in work.current_snapshot().items if i.external_id == "B"))
        assert (await store.get_mission("mis_A")).status is MissionStatus.FAILED  # l'issue retenue du propriétaire
    finally:
        await service.stop()
        await state.close()
