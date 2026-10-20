"""Historique durable des missions : contrat de déclaration et lecture jointe au Work State (Slice 03).

L'historique de mission retient **qui a fait quoi pour quelle mission** —
missions, instances d'agent à rôle figé, changements de propriétaire, relations
typées, messages de relation et paquets de relais — au-delà de la vie de Core
Work State. Il ne retient **aucun statut d'exécution** : le statut vivant d'une
instance se lit dans Work State par son identité de travail
`(work_source, work_external_id)` (D16, D18). Les valeurs sont celles de
`jarvis.domain.missions` et `jarvis.domain.agent_relations` ; ce module ajoute :

- `AgentDeclarationFact` : la déclaration d'un sous-agent telle que Core
  l'accepte. Source : le hook `PreToolUse` (arbitrage D25, audit §8 N5), avant
  le lancement, à partir de `agent_markers.declaration_from_hook_event`. Le
  hook est court et hors réseau : il écrit ce fait borné, le Control Center le
  rattache à l'observation de la tâche (même `tool_use_id`) et le remet à Core
  (câblage : Slice 05). Le parsing `stream-json` du suivi des tâches reste un
  affichage de diagnostic et n'alimente jamais l'historique ;
- `DeclarationOutcome` : ce que Core a fait d'une déclaration ;
- `live_status` / `InstanceView` : la lecture jointe, où le statut vient du
  seul Work State (`None` quand Work State ne connaît pas ou plus ce travail :
  redémarrage, élagage — jamais déduit de l'historique).

Règle éphémère (D08) : aucune ligne durable n'est écrite pour une instance
tant qu'elle est éphémère. Une fin anormale rabaisse le drapeau
(`missions.retained_in_history`, même règle que
`work_state.EPHEMERAL_WORK_STATUSES`) : l'instance redevient ordinaire et peut
alors être retenue, avec la trace `ephemeral_lowered`. Les spans `subagent.*`
de Conversation Events sont un registre de diagnostic, pas un nœud
d'historique : ils n'alimentent jamais ce module.

Contrat : `docs/mission-history.md`. Module pur, sans E/S.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.domain._checks import (
    ROLE_ID, TOKEN, check_aware, check_id, check_text, check_token, parse_dt, parse_enum, preview, recode, strict_keys,
)
from jarvis.domain.agent_markers import AgentDeclaration, declaration_from_hook_event
from jarvis.domain.agent_relations import AgentRelation
from jarvis.domain.missions import AgentInstance, Mission
from jarvis.domain.subagent_roles import RoleResolution, RoleStatus
from jarvis.domain.work_state import MAX_LABEL_CHARS, WorkItem, WorkSnapshot, WorkStatus, clip_text

#: Version du contrat de déclaration. Un fait d'une autre version est refusé, jamais deviné.
DECLARATION_CONTRACT_VERSION = 1
#: Nom de l'événement de journal d'une déclaration acceptée (diagnostic Core ; le hook l'écrira aussi, Slice 05).
AGENT_DECLARED_KIND = "agent.declared"
MAX_PROFILE_CHARS = 32
MAX_SUBAGENT_TYPE_CHARS = 64
#: Bornes de lecture d'un arbre de mission : au-delà, la lecture le dit (`truncated`) au lieu de tout charger.
MAX_TREE_MISSIONS = 256
MAX_TREE_INSTANCES = 1_024
MAX_TREE_RELATIONS = 1_024
#: Messages retenus par relation. Une borne de stockage, pas un protocole (D12) : au-delà, refus explicite.
MAX_MESSAGES_PER_RELATION = 1_000
MAX_THREAD_PAGE = 200


class MissionHistoryError(ValueError):
    """Fait de déclaration ou demande d'historique refusé, avec un code stable et le champ en cause."""

    def __init__(self, message: str, *, code: str = "mission_history_invalid", field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _fail(message: str) -> MissionHistoryError:
    return MissionHistoryError(message)


def _check(name: str, check: Any, *args: Any, **kwargs: Any) -> None:
    recode(lambda message: MissionHistoryError(message, field=name), check, name, *args, **kwargs)


# ------------------------------------------------------------------ déclaration


@dataclass(frozen=True, slots=True)
class AgentDeclarationFact:
    """Une déclaration de sous-agent, bornée et sans contenu : ni prompt, ni trace, ni raisonnement.

    - `tool_use_id` : clé de jointure avec la tâche suivie (son `work_key` initial) ; requis ;
    - `role_id` / `role_marker` / `role_status` : la résolution canonique (`subagent_roles.resolve_role`) ;
      un rôle inconnu garde l'id réservé `unknown` et son marqueur, l'affichage dégrade, rien n'est deviné ;
    - `ephemeral` : le marqueur `[éphémère]` tel que lu, jamais déduit d'une durée ;
    - `session_id`, `caller_agent_id` (appel imbriqué), `subagent_type`, `run_in_background` : ceux de
      l'événement du hook ; `mission_id` / `mission_owner` : annoncés par l'appelant (Slice 05) ;
    - `handoff_id` (Slice 06) : le relais préparé que ce successeur reprend (`[relais]`) ; il exige
      `mission_owner` et la mission reprise. Absent de la charge utile quand il est vide : un fait ordinaire
      garde exactement sa forme d'avant ;
    - `declared_at` : l'horloge du hook ; `contract_version` : `DECLARATION_CONTRACT_VERSION`.
    """

    tool_use_id: str
    declared_at: datetime
    role_id: str
    role_status: RoleStatus
    role_marker: str | None = None
    ephemeral: bool = False
    profile: str = ""
    label: str = ""
    session_id: str | None = None
    caller_agent_id: str | None = None
    subagent_type: str | None = None
    run_in_background: bool | None = None
    mission_id: str | None = None
    mission_owner: bool = False
    handoff_id: str | None = None
    contract_version: int = DECLARATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != DECLARATION_CONTRACT_VERSION or isinstance(self.contract_version, bool):
            raise MissionHistoryError(
                f"declaration contract version {preview(self.contract_version)} is not supported "
                f"(expected {DECLARATION_CONTRACT_VERSION})", code="declaration_version", field="contract_version",
            )
        _check("tool_use_id", check_id, self.tool_use_id, required=True)
        check_aware(_fail, "declared_at", self.declared_at)
        if not isinstance(self.role_id, str) or not ROLE_ID.fullmatch(self.role_id):
            raise MissionHistoryError(f"role_id must be a canonical role id, got {preview(self.role_id)}",
                                      field="role_id")
        if not isinstance(self.role_status, RoleStatus):
            raise MissionHistoryError("role_status must be a RoleStatus", field="role_status")
        if self.role_marker is not None:
            _check("role_marker", check_text, self.role_marker, 24)
        for name in ("ephemeral", "mission_owner"):
            if not isinstance(getattr(self, name), bool):
                raise MissionHistoryError(f"{name} must be a boolean", field=name)
        if self.run_in_background is not None and not isinstance(self.run_in_background, bool):
            raise MissionHistoryError("run_in_background must be a boolean or None", field="run_in_background")
        _check("profile", check_token, self.profile, MAX_PROFILE_CHARS, required=False)
        _check("label", check_text, self.label, MAX_LABEL_CHARS)
        for name in ("session_id", "caller_agent_id", "mission_id", "handoff_id"):
            _check(name, check_id, getattr(self, name), required=False)
        if self.subagent_type is not None:
            _check("subagent_type", check_token, self.subagent_type, MAX_SUBAGENT_TYPE_CHARS, required=True)
        if self.mission_owner and self.mission_id is None:
            raise MissionHistoryError("a mission owner declaration names its mission", field="mission_id")
        if self.handoff_id is not None and (not self.mission_owner or self.ephemeral):
            raise MissionHistoryError("a handoff successor is a non-ephemeral mission owner of the handed-off mission",
                                      field="handoff_id")

    def to_payload(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "tool_use_id": self.tool_use_id,
            "declared_at": self.declared_at.isoformat(),
            "role_id": self.role_id,
            "role_status": self.role_status.value,
            "role_marker": self.role_marker,
            "ephemeral": self.ephemeral,
            "profile": self.profile,
            "label": self.label,
            "session_id": self.session_id,
            "caller_agent_id": self.caller_agent_id,
            "subagent_type": self.subagent_type,
            "run_in_background": self.run_in_background,
            "mission_id": self.mission_id,
            "mission_owner": self.mission_owner,
            **({"handoff_id": self.handoff_id} if self.handoff_id is not None else {}),
        }

    @classmethod
    def from_payload(cls, payload: object) -> AgentDeclarationFact:
        """Décodage strict : une clé inconnue (prompt, trace...) trahit un producteur défectueux, refusée."""

        data = strict_keys(_fail, "agent declaration", payload, _FACT_KEYS, required=_FACT_REQUIRED)
        return cls(
            contract_version=data["contract_version"],
            tool_use_id=data["tool_use_id"],
            declared_at=parse_dt(_fail, "declared_at", data["declared_at"]),
            role_id=data["role_id"],
            role_status=parse_enum(_fail, "role_status", data["role_status"], RoleStatus),
            role_marker=data.get("role_marker"),
            ephemeral=data.get("ephemeral", False),
            profile=data.get("profile") or "",
            label=data.get("label") or "",
            session_id=data.get("session_id"),
            caller_agent_id=data.get("caller_agent_id"),
            subagent_type=data.get("subagent_type"),
            run_in_background=data.get("run_in_background"),
            mission_id=data.get("mission_id"),
            mission_owner=data.get("mission_owner", False),
            handoff_id=data.get("handoff_id"),
        )

    def declaration(self) -> AgentDeclaration:
        """La `agent_markers.AgentDeclaration` équivalente (pour `missions.instance_from_declaration`)."""

        return AgentDeclaration(
            profile=self.profile, role=RoleResolution(self.role_id, self.role_marker, self.role_status),
            ephemeral=self.ephemeral, label=self.label, tool_use_id=self.tool_use_id,
            caller_agent_id=self.caller_agent_id,
        )


_FACT_KEYS = frozenset({
    "contract_version", "tool_use_id", "declared_at", "role_id", "role_status", "role_marker", "ephemeral",
    "profile", "label", "session_id", "caller_agent_id", "subagent_type", "run_in_background", "mission_id",
    "mission_owner", "handoff_id",
})
_FACT_REQUIRED = frozenset({"contract_version", "tool_use_id", "declared_at", "role_id", "role_status"})


def fact_from_hook_event(
    event: Mapping[str, Any], *, declared_at: datetime, mission_id: str | None = None, mission_owner: bool = False,
    handoff_id: str | None = None,
) -> AgentDeclarationFact:
    """Le fait qu'un hook `PreToolUse` produit pour un appel `Agent` (lecture : `agent_markers`).

    Seuls des champs nommés sont lus ; `prompt` et le reste de `tool_input` ne sortent jamais. Un événement
    sans `tool_use_id` ne peut pas être rattaché à une tâche : refusé (`declaration_unjoinable`).
    """

    declaration = declaration_from_hook_event(event)
    if declaration.tool_use_id is None:
        raise MissionHistoryError("a hook event without tool_use_id cannot be joined to its task",
                                  code="declaration_unjoinable", field="tool_use_id")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), Mapping) else {}
    session_id = event.get("session_id")
    subagent_type = tool_input.get("subagent_type")
    background = tool_input.get("run_in_background")
    role = declaration.role
    return AgentDeclarationFact(
        tool_use_id=declaration.tool_use_id,
        declared_at=declared_at,
        role_id=role.role_id,
        role_status=role.status,
        role_marker=role.marker,
        ephemeral=declaration.ephemeral,
        profile=declaration.profile,
        label=clip_text(declaration.label, MAX_LABEL_CHARS) if declaration.label else "",
        # Un identifiant hors contrat (vide, blancs de bord) n'est pas recopié : il ne servirait à aucune jointure.
        session_id=session_id if isinstance(session_id, str) and session_id and session_id == session_id.strip()
        else None,
        caller_agent_id=declaration.caller_agent_id,
        subagent_type=subagent_type if isinstance(subagent_type, str) and len(subagent_type) <= MAX_SUBAGENT_TYPE_CHARS
        and TOKEN.fullmatch(subagent_type) else None,
        run_in_background=background if isinstance(background, bool) else None,
        mission_id=mission_id,
        mission_owner=mission_owner,
        handoff_id=handoff_id,
    )


@dataclass(frozen=True, slots=True)
class MissionOpening:
    """La mission qu'une déclaration de Mission Owner ouvre, telle que l'appelant la connaît.

    L'id est celui du fait (`AgentDeclarationFact.mission_id`) ; le propriétaire (l'instance que Core crée pour
    cette déclaration), la racine (celle du parent, ou la mission elle-même) et la date (`declared_at`) sont
    posés par Core : l'appelant ne peut pas connaître l'id d'une instance qui n'existe pas encore. Les champs
    sont validés à la construction de la `missions.Mission`.
    """

    objective: str
    parent_mission_id: str | None = None
    dossier_path: str | None = None
    origin_kind: str | None = None
    #: Slice 05 : sans `parent_mission_id`, la mission parente est celle de l'instance appelante (résolue par Core
    #: depuis `parent_work_external_id`) ; sans appelant retenu ou sans mission chez lui, la mission est racine.
    parent_from_caller: bool = False

    def mission(self, *, mission_id: str, owner_instance_id: str, created_at: datetime,
                root_mission_id: str | None) -> Mission:
        return Mission(mission_id=mission_id, objective=self.objective, owner_instance_id=owner_instance_id,
                       created_at=created_at, parent_mission_id=self.parent_mission_id,
                       root_mission_id=root_mission_id, dossier_path=self.dossier_path, origin_kind=self.origin_kind)


class DeclarationOutcome(StrEnum):
    """Ce que Core a fait d'une déclaration (rendu à l'appelant, compté, jamais un statut d'exécution)."""

    #: Nouvelle instance durable.
    RECORDED = "recorded"
    #: Même instance déjà retenue, identique (rejeu, redémarrage) : rien n'est réécrit.
    DUPLICATE = "duplicate"
    #: Éphémère : gardée en mémoire seulement, en attendant l'issue de son travail.
    EPHEMERAL_PENDING = "ephemeral_pending"
    #: Éphémère dont le travail a bien fini : aucune trace durable, et un rejeu tardif ne la ressuscite pas.
    EPHEMERAL_DISCARDED = "ephemeral_discarded"
    #: Éphémère dont le travail a fini autrement que bien : drapeau rabaissé, instance retenue.
    EPHEMERAL_RETAINED = "ephemeral_retained"
    #: Refusée par un contrat (rôle réécrit, mission inconnue...) : `code` dit pourquoi.
    REFUSED = "refused"
    #: Magasin indisponible : le travail vivant continue, l'historique est marqué dégradé.
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class DeclarationResult:
    outcome: DeclarationOutcome
    instance: AgentInstance | None = None
    code: str | None = None
    message: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "instance_id": self.instance.instance_id if self.instance else None,
            "code": self.code,
            "message": self.message,
        }


# ------------------------------------------------------------------ lecture


@dataclass(frozen=True, slots=True)
class StoredInstance:
    """Une instance telle que l'historique la retient : le contrat, plus sa provenance."""

    instance: AgentInstance
    #: Vrai si l'instance était déclarée éphémère et a été retenue après une fin anormale.
    ephemeral_lowered: bool = False
    declaration: AgentDeclarationFact | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.instance.to_payload(),
            "ephemeral_lowered": self.ephemeral_lowered,
            "role_known": self.instance.role_known,
            "declaration": self.declaration.to_payload() if self.declaration else None,
        }


@dataclass(frozen=True, slots=True)
class OwnershipChange:
    """Un propriétaire de mission, dans l'ordre : le premier à l'ouverture, les suivants par relais explicite."""

    mission_id: str
    owner_instance_id: str
    at: datetime
    handoff_relation_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "owner_instance_id": self.owner_instance_id,
                "at": self.at.isoformat(), "handoff_relation_id": self.handoff_relation_id}


@dataclass(frozen=True, slots=True)
class MissionTree:
    """Une mission racine et tout ce qui s'y rattache. `truncated` : une borne de lecture a été atteinte."""

    root_mission_id: str
    missions: tuple[Mission, ...]
    instances: tuple[StoredInstance, ...]
    relations: tuple[AgentRelation, ...]
    ownership: tuple[OwnershipChange, ...] = ()
    truncated: bool = False


def live_status(instance: AgentInstance, snapshot: WorkSnapshot | Mapping[tuple[str, str], WorkItem]) -> WorkStatus | None:
    """Le statut vivant d'une instance, lu dans Work State seul ; `None` si Work State ne connaît pas ce travail.

    `None` ne veut dire ni « fini » ni « échoué » : après un redémarrage ou un élagage, l'historique ne sait
    pas, et ne devine pas.
    """

    items = snapshot if isinstance(snapshot, Mapping) else {item.key: item for item in snapshot.items}
    item = items.get(instance.work_identity)
    return item.status if item is not None else None


@dataclass(frozen=True, slots=True)
class InstanceView:
    """Instance durable + statut vivant de Work State (ou `None`). Rien d'autre n'est joint."""

    stored: StoredInstance
    work_status: WorkStatus | None = None

    def to_payload(self) -> dict[str, Any]:
        return {**self.stored.to_payload(), "work_status": self.work_status.value if self.work_status else None}


def join_live(instances: Iterable[StoredInstance], snapshot: WorkSnapshot) -> tuple[InstanceView, ...]:
    items = {item.key: item for item in snapshot.items}
    return tuple(InstanceView(stored, live_status(stored.instance, items)) for stored in instances)


@dataclass(slots=True)
class HistoryHealth:
    """État du fournisseur d'historique, lisible par l'UI et le diagnostic. `degraded` n'arrête rien."""

    degraded: bool = False
    since: datetime | None = None
    reason: str = ""
    failed_writes: int = 0
    pending_ephemeral: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "state": "degraded" if self.degraded else "ok",
            "since": self.since.isoformat() if self.since else None,
            "reason": self.reason,
            "failed_writes": self.failed_writes,
            "pending_ephemeral": self.pending_ephemeral,
            "outcomes": dict(sorted(self.outcomes.items())),
        }
