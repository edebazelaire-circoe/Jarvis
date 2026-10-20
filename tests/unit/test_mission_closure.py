"""Clôture d'une mission : propriétaire courant terminé ET équipe terminée (Slice 05, reprise QA M2, D18).

Base temporaire, vrai `WorkStateStore`, vrai service. Repris des sondes de la QA (`qa05/test_qa05_semantics.py`).
"""

from __future__ import annotations

from jarvis.core.mission_history import (
    MISSION_HISTORY_CLOSE_DEFERRED_KIND, MISSION_HISTORY_MEMBER_AFTER_CLOSE_KIND, MISSION_HISTORY_MISSION_CLOSED_KIND,
    MISSION_HISTORY_PARENT_CLOSED_KIND,
)
from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.mission_history import DeclarationOutcome as O
from jarvis.domain.missions import MissionStatus
from jarvis.domain.work_state import WorkStatus
from tests.fakes.mission_history import SOURCE, fact, observation, packet, relation
from tests.unit.test_mission_orchestration_wiring import _owner, core  # noqa: F401 - fixture réutilisée


async def _run(core, key, minute):
    await core.work.observe(observation(key, WorkStatus.RUNNING, minute=minute))


async def _end(core, key, status, minute):
    await core.work.observe(observation(key, WorkStatus.RUNNING, minute=minute - 0.5))
    await core.work.observe(observation(key, status, minute=minute))
    item = next(i for i in core.work.current_snapshot().items if i.external_id == key)
    await core.service.observe_work_item(item)


async def _member(core, key, parent, role="qa"):
    return await core.service.record_declaration(fact(key, role=role), work_source=SOURCE, work_external_id=key,
                                                 parent_work_external_id=parent, inherit_mission=True)


async def _status(core, mission_id):
    return (await core.store.get_mission(mission_id)).status


async def test_the_owner_end_is_deferred_while_a_member_still_runs(core):
    await _owner(core.service, "A")
    await _run(core, "B", 0.2)
    assert (await _member(core, "B", "A")).outcome is O.RECORDED
    await _end(core, "A", WorkStatus.COMPLETED, 1)
    assert await _status(core, "mis_A") is MissionStatus.OPEN
    assert core.journal.kinds(MISSION_HISTORY_CLOSE_DEFERRED_KIND)[0]["alive_members"] == 1
    await _end(core, "B", WorkStatus.FAILED, 2)  # la fin du dernier membre libère la mission
    assert await _status(core, "mis_A") is MissionStatus.COMPLETED  # l'issue suit le propriétaire


async def test_an_open_sub_mission_defers_its_parent_until_it_closes(core):
    await _owner(core.service, "A")
    await _run(core, "S", 0.2)
    await _owner(core.service, "S", parent="A", role="research-lead")
    await _run(core, "R", 0.3)
    await _member(core, "R", "S", role="research")
    await _end(core, "A", WorkStatus.COMPLETED, 1)
    await _end(core, "S", WorkStatus.COMPLETED, 1.5)
    assert (await _status(core, "mis_A"), await _status(core, "mis_S")) == (MissionStatus.OPEN, MissionStatus.OPEN)
    await _end(core, "R", WorkStatus.COMPLETED, 2)
    assert (await _status(core, "mis_S"), await _status(core, "mis_A")) == (
        MissionStatus.COMPLETED, MissionStatus.COMPLETED)


async def test_an_interrupted_owner_does_not_close_a_mission_whose_team_runs(core):
    await _owner(core.service, "A")
    await _run(core, "B", 0.2)
    await _member(core, "B", "A")
    await _end(core, "A", WorkStatus.INTERRUPTED, 1)
    assert await _status(core, "mis_A") is MissionStatus.OPEN
    await _end(core, "B", WorkStatus.COMPLETED, 2)
    assert await _status(core, "mis_A") is MissionStatus.CANCELLED


async def test_the_sweep_closes_a_mission_whose_end_event_was_lost(core):
    await _owner(core.service, "A")
    await _run(core, "B", 0.2)
    await _member(core, "B", "A")
    for key, minute in (("A", 1), ("B", 2)):  # fins observées par Work State, jamais remises au service
        await core.work.observe(observation(key, WorkStatus.RUNNING, minute=minute - 0.5))
        await core.work.observe(observation(key, WorkStatus.COMPLETED, minute=minute))
    assert await _status(core, "mis_A") is MissionStatus.OPEN
    await core.service.sweep()
    assert await _status(core, "mis_A") is MissionStatus.COMPLETED


async def test_an_owner_unknown_to_work_state_leaves_the_mission_open(core):
    await _owner(core.service, "A")
    await core.service.sweep()  # aucune fin vue, rien dans Work State : rien n'est deviné
    assert await _status(core, "mis_A") is MissionStatus.OPEN


async def test_a_late_sub_mission_under_a_closed_mission_is_recorded_without_mission(core):
    await _owner(core.service, "A")
    await _run(core, "B", 0.2)
    await _member(core, "B", "A")
    await _end(core, "B", WorkStatus.COMPLETED, 0.8)
    await _end(core, "A", WorkStatus.COMPLETED, 1)
    assert await _status(core, "mis_A") is MissionStatus.COMPLETED
    late = await _owner(core.service, "S", parent="B", role="research-lead")
    assert late.outcome is O.RECORDED  # D18 : aucune perte d'historique
    assert (late.instance.mission_id, late.instance.mission_owner) == (None, False)
    assert await core.store.get_mission("mis_S") is None
    [diagnostic] = core.journal.kinds(MISSION_HISTORY_PARENT_CLOSED_KIND)
    assert diagnostic["code"] == "mission_parent_closed" and diagnostic["parent_mission_id"] == "mis_A"
    # Le rejeu de la même déclaration est un doublon, pas un refus.
    assert (await _owner(core.service, "S", parent="B", role="research-lead")).outcome is O.DUPLICATE


async def test_a_late_member_of_a_closed_mission_is_recorded_with_a_diagnostic(core):
    await _owner(core.service, "A")
    await _end(core, "A", WorkStatus.COMPLETED, 1)
    late = await _member(core, "L", "A", role="research")
    assert late.outcome is O.RECORDED and late.instance.mission_id == "mis_A"
    [diagnostic] = core.journal.kinds(MISSION_HISTORY_MEMBER_AFTER_CLOSE_KIND)
    assert diagnostic["mission_id"] == "mis_A" and diagnostic["mission_status"] == "completed"


async def test_after_a_transfer_only_the_current_owner_closes_the_mission(core):
    # Mutant M11 de la QA : une clôture qui ne vérifie pas le propriétaire COURANT survivait.
    await _owner(core.service, "A")
    successor = await core.service.record_declaration(fact("C", role="coder", mission_id="mis_A", owner=True),
                                                      work_source=SOURCE, work_external_id="C")
    old, new = (await core.store.find_instance(SOURCE, "A")).instance, successor.instance
    await core.store.create_relation(relation("h1", K.HANDOFF, "mis_A", [(old.instance_id, P.PREDECESSOR),
                                                                         (new.instance_id, P.SUCCESSOR)],
                                              minute=3, handoff=packet()))
    await core.service.transfer_ownership("mis_A", new.instance_id, handoff_relation_id="h1")
    # Le successeur n'est pas encore dans Work State : seule la fin retenue du propriétaire COURANT compterait.
    await _end(core, "A", WorkStatus.COMPLETED, 4)
    assert await _status(core, "mis_A") is MissionStatus.OPEN  # le prédécesseur n'est plus le propriétaire
    await core.service.sweep()
    assert await _status(core, "mis_A") is MissionStatus.OPEN
    await _end(core, "C", WorkStatus.FAILED, 5)
    assert await _status(core, "mis_A") is MissionStatus.FAILED
    assert len(core.journal.kinds(MISSION_HISTORY_MISSION_CLOSED_KIND)) == 1
