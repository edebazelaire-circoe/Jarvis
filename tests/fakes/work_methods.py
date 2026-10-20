"""Historique de missions closes pour les tests des candidats de Work Method (Slice 12).

Écrit par l'adaptateur réel dans une base temporaire (`tmp_path`) : jamais une base réelle.
"""

from __future__ import annotations

from jarvis.domain.agent_relations import AgentRelationKind as K, ParticipantPosition as P, RelationOutcome as O
from jarvis.domain.mission_history import AgentDeclarationFact
from jarvis.domain.missions import MissionStatus
from jarvis.domain.subagent_roles import RoleStatus
from tests.fakes.mission_history import at, instance, mission, relation


def declared(inst, method=None, chosen=False):
    return AgentDeclarationFact(tool_use_id=inst.work_external_id, declared_at=inst.created_at, role_id=inst.role_id,
                                role_status=RoleStatus.DECLARED, role_marker=inst.role_id, label="Tâche",
                                mission_id=inst.mission_id, mission_owner=inst.mission_owner, work_method=method,
                                work_method_chosen=chosen)


async def record_mission(store, mid: str, *, minute: float, qa: O | None = O.APPROVED,
                         status: MissionStatus = MissionStatus.COMPLETED, method: str | None = "deep-research@1"):
    """Une vraie mission close dans l'historique : propriétaire research-lead, deux chercheurs, un relecteur QA."""

    owner = instance(f"o{mid}", role="research-lead", mission=mid, owner=True, minute=minute)
    await store.record_instance(owner, declaration=declared(owner, method), mission=mission(mid, owner.instance_id,
                                                                                         minute=minute))
    members = []
    for name, role in ((f"a{mid}", "web-research"), (f"b{mid}", "web-research"), (f"q{mid}", "qa")):
        member = instance(name, role=role, mission=mid, parent=owner.instance_id, minute=minute)
        await store.record_instance(member, declaration=declared(member))
        members.append(member.instance_id)
    a, b, q = members
    await store.create_relation(relation(f"rd{mid}", K.DELEGATION, mid, [(owner.instance_id, P.DELEGATOR),
                                                                          (a, P.DELEGATEE)], minute=minute + 1))
    await store.close_relation(f"rd{mid}", O.RETURNED, at(minute + 2))
    await store.create_relation(relation(f"rv{mid}", K.ADVERSARY, mid, [(a, P.PRODUCER), (b, P.PRODUCER)],
                                         minute=minute + 1))
    await store.close_relation(f"rv{mid}", O.SYNTHESIS, at(minute + 3), closed_by=owner.instance_id)
    if qa is not None:
        await store.create_relation(relation(f"rq{mid}", K.QA, mid, [(q, P.REVIEWER), (a, P.REVIEWED)],
                                             minute=minute + 1))
        await store.close_relation(f"rq{mid}", qa, at(minute + 4), closed_by=q)
    await store.close_mission(mid, status, at(minute + 5))
