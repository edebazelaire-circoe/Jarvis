"""Port du magasin durable de l'historique des missions (handoff organic-agent-orchestration, Slice 03).

Tables `missions`, `agent_instances`, `mission_owners`, `agent_relations`,
`agent_relation_participants`, `agent_handoff_packets`,
`agent_relation_messages` : étape v10 de `sqlite_state`, connexion partagée
(adaptateur `sqlite_mission_history`). Les valeurs et les règles sont celles de
`jarvis.domain.missions`, `jarvis.domain.agent_relations` et
`jarvis.domain.mission_history` ; un refus de règle lève l'erreur codée du
domaine (`MissionError`, `RelationError`, `MissionHistoryError`), jamais une
erreur de stockage. Contrat : `docs/mission-history.md`.

Aucune méthode n'écrit ni ne lit un statut d'exécution : il vit dans Work State.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from jarvis.domain.agent_relations import AgentRelation, RelationMessage, RelationOutcome
from jarvis.domain.mission_history import AgentDeclarationFact, MissionTree, OwnershipChange, StoredInstance
from jarvis.domain.missions import AgentInstance, Mission, MissionStatus
from jarvis.ports.workspace_board import BoardStoreError, BoardStoreUnavailable


class MissionHistoryStoreError(BoardStoreError):
    """Ligne illisible ou qui contredit ses colonnes clés ; jamais réparée (historique canonique)."""

    code = "mission_history_unreadable"


class MissionHistoryUnavailable(BoardStoreUnavailable):
    """SQLite a refusé l'opération (verrou, E/S) ; la cause SQLite reste dans le message."""

    code = "mission_history_failed"

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(operation, reason)
        self.args = (f"mission history {operation} failed: {reason}",)
        self.table = "mission_history"


class MissionHistoryRepository(Protocol):
    async def record_instance(
        self, instance: AgentInstance, *, declaration: AgentDeclarationFact | None = None,
        ephemeral_lowered: bool = False, mission: Mission | None = None,
    ) -> tuple[StoredInstance, bool]:
        """Retenir `instance` (jamais éphémère) ; rend l'instance retenue et `True` si elle est neuve.

        Même identité de travail déjà retenue : `missions.reconcile_instance` (identique ou `immutable_field`,
        seul un libellé vide s'enrichit), l'id déjà attribué fait foi. `mission` : la mission que cette
        instance ouvre et possède, insérée dans la même transaction. Sinon la mission nommée doit exister
        (`mission_unknown`) ; un parent inconnu est refusé (`mission_parent_missing`).
        """
        ...

    async def get_instance(self, instance_id: str) -> StoredInstance | None: ...

    async def find_instance(self, work_source: str, work_external_id: str) -> StoredInstance | None: ...

    async def recent_instances(self, *, limit: int = 50) -> tuple[StoredInstance, ...]:
        """Les dernières instances retenues, de la plus récente à la plus ancienne."""
        ...

    # Pas d'`open_mission` isolé : une mission n'existe qu'avec son propriétaire (`Mission.owner_instance_id`
    # requis), qui la nomme comme sa mission ; les deux naissent ensemble (`record_instance(..., mission=)`).

    async def close_mission(self, mission_id: str, status: MissionStatus, at: datetime) -> Mission: ...

    async def transfer_ownership(self, mission_id: str, successor_instance_id: str, *, handoff_relation_id: str,
                                 at: datetime) -> Mission:
        """Changer de propriétaire par le relais `handoff_relation_id` (nature `handoff`, de la mission, non
        retiré, du propriétaire courant vers `successor_instance_id`) ; la mission et le changement sont
        écrits dans la même transaction."""
        ...

    async def get_mission(self, mission_id: str) -> Mission | None: ...

    async def list_missions(self, *, open_only: bool = False, limit: int = 50) -> tuple[Mission, ...]: ...

    async def open_missions_after(self, after: tuple[datetime, str] | None, *, limit: int) -> tuple[Mission, ...]:
        """Missions ouvertes après le curseur `(created_at, mission_id)`, dans l'ordre croissant (balayage tournant)."""
        ...

    async def mission_tree(self, root_mission_id: str) -> MissionTree | None: ...

    async def ownership(self, mission_id: str) -> tuple[OwnershipChange, ...]: ...

    async def create_relation(self, relation: AgentRelation) -> AgentRelation:
        """Relation, participants et paquet de relais en **une** transaction, après
        `check_relation_participants(..., missions=, relations=)` et `check_handoff_chain`."""
        ...

    async def close_relation(
        self, relation_id: str, outcome: RelationOutcome, at: datetime, *, summary: str = "",
        winner_instance_id: str | None = None, closed_by: str | None = None,
    ) -> AgentRelation: ...

    async def get_relation(self, relation_id: str) -> AgentRelation | None: ...

    async def record_handoff(
        self, instance: AgentInstance, *, declaration: AgentDeclarationFact | None, relation: AgentRelation,
        at: datetime, summary: str,
    ) -> tuple[StoredInstance, AgentRelation, Mission]:
        """Slice 06 : le successeur d'un relais, sa relation (paquet), le transfert de propriété et la clôture
        `transferred` en **une** transaction : tout ou rien."""
        ...

    async def relations_of_instance(self, instance_id: str, *, limit: int = 16) -> tuple[AgentRelation, ...]:
        """Les relations où figure l'instance, les plus récentes d'abord (Slice 06, résumés du cerveau)."""
        ...

    async def append_message(self, message: RelationMessage) -> int:
        """Poster sur le fil de la relation (`check_message`) ; rend le rang d'acceptation (ordre du fil)."""
        ...

    async def thread(self, relation_id: str, *, after: int = 0, limit: int = 100
                     ) -> tuple[tuple[int, RelationMessage], ...]:
        """Messages acceptés après le rang `after`, dans l'ordre d'acceptation."""
        ...

    async def counts(self) -> dict[str, int]:
        """Nombre de lignes par table (journal du démarrage)."""
        ...


__all__: Sequence[str] = (
    "MissionHistoryRepository", "MissionHistoryStoreError", "MissionHistoryUnavailable",
)
