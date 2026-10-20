"""Briques de test de l'historique des missions (Slice 03 organic-agent-orchestration).

Bases temporaires seulement (`tmp_path`) : jamais une base réelle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.adapters.sqlite_mission_history import SQLiteMissionHistoryRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.domain.agent_relations import (
    AgentRelation, AgentRelationKind, HandoffPacket, ParticipantPosition, RelationMessage, RelationMessageType,
    RelationParticipant,
)
from jarvis.domain.mission_history import AgentDeclarationFact
from jarvis.domain.missions import AgentInstance, Mission
from jarvis.domain.subagent_roles import RoleStatus
from jarvis.domain.work_state import WorkObservation, WorkStatus

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
SOURCE = "claude"


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


async def open_store(path: Path) -> tuple[SQLiteStateRepository, SQLiteMissionHistoryRepository]:
    state = SQLiteStateRepository(path)
    await state.initialize()
    return state, SQLiteMissionHistoryRepository(state)


def instance(instance_id: str, *, role: str = "coder", mission: str | None = None, owner: bool = False,
             parent: str | None = None, minute: float = 0, external: str | None = None, label: str = "",
             ephemeral: bool = False) -> AgentInstance:
    return AgentInstance(
        instance_id=instance_id, work_source=SOURCE, work_external_id=external or f"toolu_{instance_id}",
        role_id=role, created_at=at(minute), role_marker=role if role not in ("undeclared",) else None,
        ephemeral=ephemeral, mission_id=mission, mission_owner=owner, parent_instance_id=parent, label=label,
    )


def mission(mission_id: str, owner: str, *, parent: str | None = None, root: str | None = None,
            minute: float = 0) -> Mission:
    return Mission(mission_id=mission_id, objective=f"Objectif {mission_id}", owner_instance_id=owner,
                   created_at=at(minute), parent_mission_id=parent, root_mission_id=root)


def fact(tool_use_id: str, *, role: str = "coder", status: RoleStatus = RoleStatus.DECLARED, ephemeral: bool = False,
         mission_id: str | None = None, owner: bool = False, minute: float = 0, label: str = "Corriger") -> AgentDeclarationFact:
    return AgentDeclarationFact(
        tool_use_id=tool_use_id, declared_at=at(minute), role_id=role, role_status=status,
        role_marker=None if role == "undeclared" else role, ephemeral=ephemeral, profile="code", label=label,
        session_id="sess-1", subagent_type="general-purpose", run_in_background=True, mission_id=mission_id,
        mission_owner=owner,
    )


def observation(external_id: str, status: WorkStatus, *, minute: float = 0, ephemeral: bool = False,
                role_id: str | None = None) -> WorkObservation:
    return WorkObservation(source=SOURCE, external_id=external_id, status=status, observed_at=at(minute),
                           ephemeral=ephemeral, role_id=role_id)


def packet() -> HandoffPacket:
    return HandoffPacket(objective="Finir la correction", completed_work="Cause trouvée, test rouge écrit",
                         recommended_next_action="Écrire le correctif", key_decisions=("garder l'API",),
                         open_points=(), artifact_refs=("art_1",))


def relation(relation_id: str, kind: AgentRelationKind, mission_id: str, pairs: list[tuple[str, ParticipantPosition]],
             *, minute: float = 1, **fields) -> AgentRelation:
    return AgentRelation(relation_id=relation_id, kind=kind, mission_id=mission_id,
                         participants=tuple(RelationParticipant(i, p) for i, p in pairs),
                         purpose=f"But de {relation_id}", created_at=at(minute), **fields)


def message(message_id: str, relation_id: str, author: str, *, minute: float = 2, text: str = "Proposition claire",
            kind: RelationMessageType = RelationMessageType.PROPOSAL, reply_to: str | None = None) -> RelationMessage:
    return RelationMessage(message_id=message_id, relation_id=relation_id, author_instance_id=author, type=kind,
                           text=text, created_at=at(minute), reply_to_message_id=reply_to)
