"""Clôture d'un doublon fusionné et règle éphémère de l'historique des missions (Slice 03, reprise S8 QA).

Le relais du Control Center retire la clé d'une tâche fusionnée par `cancelled` / `merged`, sans drapeau
éphémère (`jarvis/runtime/work_ingress.py`). Ce n'est pas une fin du travail : une éphémère en attente est
écartée sans trace (`ephemeral_discarded`), comme après une réussite, sa clé est retenue contre le rejeu, et
rien n'est écrit en base. Une vraie fin anormale garde la règle : drapeau rabaissé, instance retenue.
"""

from __future__ import annotations

import pytest

from jarvis.core.mission_history import MissionHistoryService
from jarvis.core.work_state import WorkStateStore
from jarvis.domain.mission_history import DeclarationOutcome as O
from jarvis.domain.missions import discarded_without_trace, retained_in_history
from jarvis.domain.work_state import MERGED_CLOSURE, WorkObservation, WorkStatus, is_merged_closure
from jarvis.runtime.work_ingress import MERGED
from tests.fakes.mission_history import SOURCE, at, fact, instance, open_store
from tests.unit.test_relations_runtime_service import Clock


@pytest.fixture
async def history(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    clock = Clock()
    work = WorkStateStore(clock=clock)
    service = MissionHistoryService(store, work_state=work, clock=clock, sweep_interval_s=None)
    yield service, store, work
    await service.stop()
    await state.close()


async def observe(service, work, key, status, *, minute, ephemeral=False, error_class=None):
    await work.observe(WorkObservation(source=SOURCE, external_id=key, status=status, observed_at=at(minute),
                                       kind="agent", ephemeral=ephemeral, error_class=error_class))
    item = next(i for i in work.current_snapshot().items if i.external_id == key)
    return item, await service.observe_work_item(item)


def test_one_merged_closure_value_is_shared_by_relay_history_and_scene():
    from jarvis.core import scene_projector

    assert MERGED == MERGED_CLOSURE == scene_projector.MERGED_CLOSURE == "merged"
    assert is_merged_closure(WorkStatus.CANCELLED, "merged")
    assert not is_merged_closure(WorkStatus.CANCELLED, "killed") and not is_merged_closure(WorkStatus.FAILED, "merged")
    ephemeral = instance("ainst_E", ephemeral=True)
    assert not retained_in_history(ephemeral, WorkStatus.CANCELLED, MERGED_CLOSURE)
    assert retained_in_history(ephemeral, WorkStatus.CANCELLED, "killed")  # un vrai arrêt reste retenu
    assert retained_in_history(instance("ainst_O"), WorkStatus.CANCELLED, MERGED_CLOSURE)  # ordinaire : toujours
    assert discarded_without_trace(WorkStatus.COMPLETED) and discarded_without_trace(WorkStatus.CANCELLED, "merged")
    assert not discarded_without_trace(WorkStatus.CANCELLED, "stopped")


async def test_a_merged_closure_of_a_pending_ephemeral_discards_it_without_trace(history):
    service, store, work = history
    declared = await service.record_declaration(fact("E", ephemeral=True), work_source=SOURCE, work_external_id="E")
    assert declared.outcome is O.EPHEMERAL_PENDING
    _item, result = await observe(service, work, "E", WorkStatus.RUNNING, minute=0.1, ephemeral=True)
    assert result is None
    item, result = await observe(service, work, "E", WorkStatus.CANCELLED, minute=0.3, error_class=MERGED)
    assert item.ephemeral is False  # Work State rabaisse le drapeau ; l'historique ne s'en sert pas ici
    assert result is not None and result.outcome is O.EPHEMERAL_DISCARDED
    assert await store.find_instance(SOURCE, "E") is None
    # Rejeu tardif de la déclaration : la clé écartée ne ressuscite pas.
    replay = await service.record_declaration(fact("E", ephemeral=True), work_source=SOURCE, work_external_id="E")
    assert replay.outcome is O.EPHEMERAL_DISCARDED
    assert await store.find_instance(SOURCE, "E") is None


async def test_a_declaration_arriving_after_the_merged_closure_is_discarded_too(history):
    service, store, work = history
    await observe(service, work, "L", WorkStatus.RUNNING, minute=0.1, ephemeral=True)
    await observe(service, work, "L", WorkStatus.CANCELLED, minute=0.3, error_class=MERGED)
    late = await service.record_declaration(fact("L", ephemeral=True), work_source=SOURCE, work_external_id="L")
    assert late.outcome is O.EPHEMERAL_DISCARDED
    assert await store.find_instance(SOURCE, "L") is None


async def test_a_real_abnormal_end_still_retains_the_ephemeral(history):
    service, store, work = history
    await service.record_declaration(fact("S", ephemeral=True), work_source=SOURCE, work_external_id="S")
    await observe(service, work, "S", WorkStatus.RUNNING, minute=0.1, ephemeral=True)
    _item, result = await observe(service, work, "S", WorkStatus.CANCELLED, minute=0.3, error_class="stopped")
    assert result is not None and result.outcome is O.EPHEMERAL_RETAINED
    stored = await store.find_instance(SOURCE, "S")
    assert stored is not None and stored.ephemeral_lowered


async def test_a_replayed_declaration_after_eviction_is_discarded_by_the_retained_key(tmp_path):
    """N2 : Work State a élagué l'éphémère close par fusion ; seule la clé retenue empêche le rejeu de la ressusciter."""

    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    clock = Clock()
    work = WorkStateStore(clock=clock, max_items=1)
    service = MissionHistoryService(store, work_state=work, clock=clock, sweep_interval_s=None)
    try:
        await service.record_declaration(fact("E", ephemeral=True), work_source=SOURCE, work_external_id="E")
        await observe(service, work, "E", WorkStatus.RUNNING, minute=0.1, ephemeral=True)
        await observe(service, work, "E", WorkStatus.CANCELLED, minute=0.3, error_class=MERGED)
        await observe(service, work, "X", WorkStatus.RUNNING, minute=0.4)  # au-delà de la borne : E est élaguée
        assert [item.external_id for item in work.current_snapshot().items] == ["X"]
        assert (SOURCE, "E") in service._discarded
        replay = await service.record_declaration(fact("E", ephemeral=True), work_source=SOURCE, work_external_id="E")
        assert replay.outcome is O.EPHEMERAL_DISCARDED
        assert await store.find_instance(SOURCE, "E") is None
        # Témoin : une clé jamais écartée, sans élément de Work State, attend son issue.
        other = await service.record_declaration(fact("N", ephemeral=True), work_source=SOURCE, work_external_id="N")
        assert other.outcome is O.EPHEMERAL_PENDING
    finally:
        await service.stop()
        await state.close()
