"""Missions, sous-missions et instances d'agent : le contrat sémantique (Slice 01).

Ces contrats disent **qui fait quoi pour quelle mission** ; ils ne disent jamais
où en est l'exécution. Le statut vivant d'un agent reste celui de Core Work
State (`jarvis/domain/work_state.py`, D16) : une instance s'y rattache par son
identité de travail `(source, external_id)`, sans recopier de statut.

- `Mission` : un objectif dont quelqu'un répond. Identité stable, mission parente
  facultative (sous-mission, D04), racine, objectif borné, dossier de mission
  partagé référencé par chemin (`subagent_roles.MISSION_PATH_HINT`, pas un second
  support de prose), propriétaire courant. Son cycle de vie
  (`open` -> `completed | cancelled | failed`) est celui de l'objectif, pas
  celui des agents qui y travaillent.
- `AgentInstance` : une instance d'agent. `role_id`, `ephemeral`, `mission_id`,
  `mission_owner` et `parent_instance_id` sont posés une fois et ne changent
  plus (D01, D14 : changer de rôle ou de contexte = une nouvelle instance).
  Mission Owner est un **statut d'instance**, pas un rôle (D03) : il exige un
  rôle capable (`can_own_mission`).
- `reconcile_instance` : une seconde déclaration de la même instance doit être
  identique, sinon `immutable_field` ; rien n'est réécrit.
- `transfer_ownership` : un changement de propriétaire n'existe que par un
  passage de relais explicite, vers une instance qui porte ce statut.
- `check_mission_tree` : un ensemble de missions et d'instances est cohérent,
  sans cycle ni parent manquant, à toute profondeur bornée.
- Éphémère : drapeau déclaré (marqueur `[éphémère]`, `agent_markers`), jamais
  déduit d'une durée. Une instance éphémère ne porte pas de mission ;
  `retained_in_history` dit si elle doit survivre dans l'historique : elle le
  doit dès que son travail finit autrement que bien (même règle que
  `work_state.EPHEMERAL_WORK_STATUSES`).

Contrat : `docs/subagent-roles.md`. Module pur, sans E/S. La persistance relève
de la Slice 03, le lancement des Slices 05 à 07.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import re
from typing import Any

from jarvis.domain._checks import (
    check_aware, check_id, check_text, check_token, parse_dt, parse_enum, preview, recode, strict_keys,
)
from jarvis.domain.agent_markers import AgentDeclaration
from jarvis.domain.subagent_roles import (
    MISSION_DIR, MISSION_FILE, RESERVED_ROLE_IDS, UNDECLARED_ROLE_ID, _MARKER as _ROLE_ID, role_by_id,
)
from jarvis.domain.work_state import EPHEMERAL_WORK_STATUSES, MAX_LABEL_CHARS, MAX_SOURCE_CHARS, WorkStatus, clip_text

MAX_OBJECTIVE_CHARS = 1_000
MAX_DOSSIER_PATH_CHARS = 200
#: Profondeur maximale d'une chaîne de sous-missions (et d'instances) : au-delà, c'est un défaut, pas une mission.
MAX_MISSION_DEPTH = 16
#: `origin_kind` : nature de la demande d'origine quand elle est connue (`code`, `research`, `design`...).
MAX_ORIGIN_KIND_CHARS = 32

#: Un marqueur de rôle tel qu'écrit : un mot de la grammaire de tête (`agent_markers.WORD_PATTERN`) en minuscules.
_ROLE_MARKER = re.compile(r"[a-z_-]{2,24}\Z")

#: `missions/<sujet-court>-<AAAAMMJJ>/mission.md`, relatif au dossier mémoire du Board.
_DOSSIER = re.compile(
    rf"{re.escape(MISSION_DIR)}/(?P<slug>[^/\\\s.][^/\\]*-\d{{8}})/{re.escape(MISSION_FILE)}\Z"
)


class MissionError(ValueError):
    """Contrat de mission refusé, avec un code stable (`mission_invalid`, `immutable_field`, `mission_cycle`...)."""

    def __init__(self, message: str, *, code: str = "mission_invalid", field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _fail(message: str) -> MissionError:
    return MissionError(message)


def _check(name: str, check: Any, *args: Any, **kwargs: Any) -> None:
    """Les contrôles partagés lèvent `TypeError`/`ValueError` : ici, tout refus est une `MissionError`."""

    recode(lambda message: MissionError(message, field=name), check, name, *args, **kwargs)


def check_dossier_path(path: object) -> None:
    """Un chemin de dossier de mission relatif, de la forme `subagent_roles.MISSION_PATH_HINT`."""

    _check("dossier_path", check_text, path, MAX_DOSSIER_PATH_CHARS)
    if not _DOSSIER.fullmatch(str(path)) or ".." in str(path).split("/"):
        raise MissionError(
            f"dossier_path must look like {MISSION_DIR}/<sujet>-<AAAAMMJJ>/{MISSION_FILE}, got {preview(path)}",
            field="dossier_path",
        )


class MissionStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_closed(self) -> bool:
        return self is not MissionStatus.OPEN


@dataclass(frozen=True, slots=True)
class Mission:
    """Un objectif dont une instance répond. `root_mission_id == mission_id` si et seulement si pas de parent."""

    mission_id: str
    objective: str
    owner_instance_id: str
    created_at: datetime
    parent_mission_id: str | None = None
    root_mission_id: str | None = None
    dossier_path: str | None = None
    origin_kind: str | None = None
    status: MissionStatus = MissionStatus.OPEN
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.root_mission_id is None:
            # Une mission racine est sa propre racine : la valeur se déduit, elle ne se devine pas.
            if self.parent_mission_id is not None:
                raise MissionError("a sub-mission must name its root_mission_id", field="root_mission_id")
            object.__setattr__(self, "root_mission_id", self.mission_id)
        _check("mission_id", check_id, self.mission_id, required=True)
        _check("owner_instance_id", check_id, self.owner_instance_id, required=True)
        _check("parent_mission_id", check_id, self.parent_mission_id, required=False)
        _check("root_mission_id", check_id, self.root_mission_id, required=True)
        _check("objective", check_text, self.objective, MAX_OBJECTIVE_CHARS, single_line=False)
        if not self.objective.strip():
            raise MissionError("objective is required", field="objective")
        if self.parent_mission_id == self.mission_id:
            raise MissionError("a mission cannot be its own parent", code="mission_cycle", field="parent_mission_id")
        if (self.parent_mission_id is None) != (self.root_mission_id == self.mission_id):
            raise MissionError("root_mission_id is the mission itself exactly when it has no parent",
                               field="root_mission_id")
        if self.dossier_path is not None:
            check_dossier_path(self.dossier_path)
        if self.origin_kind is not None:
            _check("origin_kind", check_token, self.origin_kind, MAX_ORIGIN_KIND_CHARS, required=True)
        check_aware(_fail, "created_at", self.created_at)
        if not isinstance(self.status, MissionStatus):
            raise MissionError("status must be a MissionStatus", field="status")
        if self.status.is_closed != (self.closed_at is not None):
            raise MissionError("closed_at is set exactly when the mission is closed", field="closed_at")
        check_aware(_fail, "closed_at", self.closed_at, required=False)
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise MissionError("closed_at cannot precede created_at", field="closed_at")

    @property
    def is_root(self) -> bool:
        return self.parent_mission_id is None

    def close(self, status: MissionStatus, at: datetime) -> Mission:
        """Clore une mission ouverte. Une mission close ne se rouvre pas et ne se reclôt pas autrement."""

        if not isinstance(status, MissionStatus) or not status.is_closed:
            raise MissionError("close needs completed, cancelled or failed", field="status")
        if self.status.is_closed:
            if self.status is status and self.closed_at == at:
                return self
            raise MissionError(f"mission {self.mission_id} is already {self.status.value}", code="mission_closed")
        return replace(self, status=status, closed_at=at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "objective": self.objective,
            "owner_instance_id": self.owner_instance_id,
            "created_at": self.created_at.isoformat(),
            "parent_mission_id": self.parent_mission_id,
            "root_mission_id": self.root_mission_id,
            "dossier_path": self.dossier_path,
            "origin_kind": self.origin_kind,
            "status": self.status.value,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Mission:
        data = strict_keys(_fail, "mission", payload, _MISSION_KEYS, required=_MISSION_REQUIRED)
        return cls(
            mission_id=data["mission_id"],
            objective=data["objective"],
            owner_instance_id=data["owner_instance_id"],
            created_at=parse_dt(_fail, "created_at", data["created_at"]),
            parent_mission_id=data.get("parent_mission_id"),
            root_mission_id=data.get("root_mission_id"),
            dossier_path=data.get("dossier_path"),
            origin_kind=data.get("origin_kind"),
            status=parse_enum(_fail, "status", data.get("status", "open"), MissionStatus),
            closed_at=parse_dt(_fail, "closed_at", data.get("closed_at"), required=False),
        )


_MISSION_KEYS = frozenset({
    "mission_id", "objective", "owner_instance_id", "created_at", "parent_mission_id", "root_mission_id",
    "dossier_path", "origin_kind", "status", "closed_at",
})
_MISSION_REQUIRED = frozenset({"mission_id", "objective", "owner_instance_id", "created_at"})


@dataclass(frozen=True, slots=True)
class AgentInstance:
    """Une instance d'agent, telle que la mission la connaît. Aucun statut d'exécution ici (D16).

    - `work_source` / `work_external_id` : son identité Work State (`WorkItem`), la clé de jointure stable
      (`AgentTask.work_key` côté Claude, le `tool_use_id` initial) ;
    - `role_id` : id canonique (`subagent_roles.resolve_role`), ou `undeclared` sans marqueur. Un id que le
      registre ne connaît plus reste tel quel : l'affichage dégrade (`role_known`), rien n'est réécrit ;
    - `role_marker` : le marqueur tel qu'écrit (`reviewer` pour `qa`), provenance seulement ;
    - `ephemeral` : déclaré, jamais déduit ; `mission_owner` : statut, pas rôle.
    """

    instance_id: str
    work_source: str
    work_external_id: str
    role_id: str
    created_at: datetime
    role_marker: str | None = None
    ephemeral: bool = False
    mission_id: str | None = None
    mission_owner: bool = False
    parent_instance_id: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        _check("instance_id", check_id, self.instance_id, required=True)
        _check("work_source", check_token, self.work_source, MAX_SOURCE_CHARS, required=True)
        _check("work_external_id", check_id, self.work_external_id, required=True)
        if not isinstance(self.role_id, str) or not _ROLE_ID.fullmatch(self.role_id):
            raise MissionError(f"role_id must be an explicit role id, got {preview(self.role_id)}", field="role_id")
        if self.role_marker is not None and (not isinstance(self.role_marker, str)
                                             or not _ROLE_MARKER.fullmatch(self.role_marker)):
            raise MissionError(f"role_marker must be a role marker, got {preview(self.role_marker)}",
                               field="role_marker")
        check_aware(_fail, "created_at", self.created_at)
        for name in ("ephemeral", "mission_owner"):
            if not isinstance(getattr(self, name), bool):
                raise MissionError(f"{name} must be a boolean", field=name)
        _check("mission_id", check_id, self.mission_id, required=False)
        _check("parent_instance_id", check_id, self.parent_instance_id, required=False)
        _check("label", check_text, self.label, MAX_LABEL_CHARS)
        if self.parent_instance_id == self.instance_id:
            raise MissionError("an agent instance cannot be its own parent", code="mission_cycle",
                               field="parent_instance_id")
        if self.mission_owner:
            if self.mission_id is None:
                raise MissionError("a mission owner must name its mission", field="mission_id")
            if self.ephemeral:
                # D08 : une éphémère ne laisse pas d'historique ; la mission qu'elle porterait y resterait orpheline.
                raise MissionError("an ephemeral instance cannot own a mission", code="ephemeral_mission_owner",
                                   field="mission_owner")
            role = role_by_id(self.role_id)
            if role is None or not role.can_own_mission:
                raise MissionError(f"role {self.role_id!r} cannot own a mission", code="role_cannot_own_mission",
                                   field="mission_owner")

    @property
    def work_identity(self) -> tuple[str, str]:
        return self.work_source, self.work_external_id

    @property
    def role_known(self) -> bool:
        """Faux pour un rôle non déclaré ou que le registre ne connaît pas : l'UI le montre comme tel."""

        return self.role_id not in RESERVED_ROLE_IDS and role_by_id(self.role_id) is not None

    def to_payload(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "work_source": self.work_source,
            "work_external_id": self.work_external_id,
            "role_id": self.role_id,
            "created_at": self.created_at.isoformat(),
            "role_marker": self.role_marker,
            "ephemeral": self.ephemeral,
            "mission_id": self.mission_id,
            "mission_owner": self.mission_owner,
            "parent_instance_id": self.parent_instance_id,
            "label": self.label,
        }

    @classmethod
    def from_payload(cls, payload: object) -> AgentInstance:
        data = strict_keys(_fail, "agent instance", payload, _INSTANCE_KEYS, required=_INSTANCE_REQUIRED)
        return cls(
            instance_id=data["instance_id"],
            work_source=data["work_source"],
            work_external_id=data["work_external_id"],
            role_id=data["role_id"],
            created_at=parse_dt(_fail, "created_at", data["created_at"]),
            role_marker=data.get("role_marker"),
            ephemeral=data.get("ephemeral", False),
            mission_id=data.get("mission_id"),
            mission_owner=data.get("mission_owner", False),
            parent_instance_id=data.get("parent_instance_id"),
            label=data.get("label") or "",
        )


_INSTANCE_KEYS = frozenset({
    "instance_id", "work_source", "work_external_id", "role_id", "created_at", "role_marker", "ephemeral",
    "mission_id", "mission_owner", "parent_instance_id", "label",
})
_INSTANCE_REQUIRED = frozenset({"instance_id", "work_source", "work_external_id", "role_id", "created_at"})

#: Champs posés une fois pour toutes : une seconde déclaration qui en change un est refusée.
IMMUTABLE_INSTANCE_FIELDS = (
    "work_source", "work_external_id", "role_id", "role_marker", "ephemeral", "mission_id", "mission_owner",
    "parent_instance_id",
)


def reconcile_instance(current: AgentInstance, incoming: AgentInstance) -> AgentInstance:
    """La même instance déclarée deux fois (rejeu, redémarrage) : identique ou refusée, jamais réécrite.

    Seul `label` peut s'enrichir (libellé vide d'abord, puis connu). `created_at` garde la première valeur.
    """

    if incoming.instance_id != current.instance_id:
        raise MissionError("reconcile needs the same instance_id", field="instance_id")
    for name in IMMUTABLE_INSTANCE_FIELDS:
        if getattr(current, name) != getattr(incoming, name):
            raise MissionError(
                f"agent instance {current.instance_id}: {name} is immutable "
                f"({preview(getattr(current, name))} -> {preview(getattr(incoming, name))}); "
                "a different role or assignment is a new instance",
                code="immutable_field", field=name,
            )
    if not current.label and incoming.label:
        return replace(current, label=incoming.label)
    return current


def transfer_ownership(mission: Mission, successor: AgentInstance, *, handoff_ref: str) -> Mission:
    """Passer la mission à `successor` par un relais explicite (`handoff_ref` : id du relais, Slice 02).

    Le successeur doit être une autre instance, Mission Owner de cette mission. Une mission close ne change
    plus de propriétaire.
    """

    _check("handoff_ref", check_id, handoff_ref, required=True)
    if mission.status.is_closed:
        raise MissionError(f"mission {mission.mission_id} is closed", code="mission_closed")
    if successor.instance_id == mission.owner_instance_id:
        raise MissionError("the successor is already the owner", field="owner_instance_id")
    if not successor.mission_owner or successor.mission_id != mission.mission_id:
        raise MissionError("the successor must be a mission owner of this mission", code="ownership_invalid",
                           field="owner_instance_id")
    return replace(mission, owner_instance_id=successor.instance_id)


def retained_in_history(instance: AgentInstance, status: WorkStatus) -> bool:
    """Une instance doit-elle rester dans l'historique, vu son statut Work State ?

    Une instance ordinaire, toujours. Une éphémère, seulement si son travail a fini autrement que bien
    (échec, arrêt, interruption, blocage) : elle redevient alors ordinaire, comme dans `work_state`.
    """

    return not instance.ephemeral or status not in EPHEMERAL_WORK_STATUSES


def _walk(start: str | None, parent_of: Mapping[str, str | None], kind: str) -> list[str]:
    chain: list[str] = []
    seen: set[str] = set()
    current = start
    while current is not None:
        if current in seen:
            raise MissionError(f"{kind} cycle through {current}", code="mission_cycle")
        if len(chain) >= MAX_MISSION_DEPTH:
            raise MissionError(f"{kind} chain deeper than {MAX_MISSION_DEPTH}", code="mission_too_deep")
        seen.add(current)
        chain.append(current)
        if current not in parent_of:
            raise MissionError(f"{kind} {current} is missing", code="mission_parent_missing")
        current = parent_of[current]
    return chain


def check_mission_tree(missions: Iterable[Mission], instances: Iterable[AgentInstance]) -> None:
    """Un ensemble complet de missions et d'instances est cohérent.

    - ids uniques ; chaque parent (mission ou instance) existe ; aucune boucle ; profondeur bornée ;
    - la racine déclarée d'une sous-mission est la racine réelle de sa chaîne ;
    - le propriétaire de chaque mission est une instance Mission Owner de cette mission ;
    - chaque instance rattachée à une mission la trouve dans l'ensemble.
    """

    by_mission: dict[str, Mission] = {}
    for mission in missions:
        if mission.mission_id in by_mission:
            raise MissionError(f"mission {mission.mission_id} is listed twice", field="mission_id")
        by_mission[mission.mission_id] = mission
    by_instance: dict[str, AgentInstance] = {}
    for instance in instances:
        if instance.instance_id in by_instance:
            raise MissionError(f"agent instance {instance.instance_id} is listed twice", field="instance_id")
        by_instance[instance.instance_id] = instance

    mission_parents = {key: value.parent_mission_id for key, value in by_mission.items()}
    for mission in by_mission.values():
        chain = _walk(mission.mission_id, mission_parents, "mission")
        if chain[-1] != mission.root_mission_id:
            raise MissionError(f"mission {mission.mission_id} declares root {mission.root_mission_id}, "
                               f"its chain ends at {chain[-1]}", field="root_mission_id")
        owner = by_instance.get(mission.owner_instance_id)
        if owner is None or not owner.mission_owner or owner.mission_id != mission.mission_id:
            raise MissionError(f"mission {mission.mission_id}: owner {mission.owner_instance_id} is not one of its "
                               "mission owner instances", code="ownership_invalid", field="owner_instance_id")

    instance_parents = {key: value.parent_instance_id for key, value in by_instance.items()}
    for instance in by_instance.values():
        _walk(instance.instance_id, instance_parents, "agent instance")
        if instance.mission_id is not None and instance.mission_id not in by_mission:
            raise MissionError(f"agent instance {instance.instance_id}: mission {instance.mission_id} is missing",
                               code="mission_parent_missing", field="mission_id")


def instance_from_declaration(
    declaration: AgentDeclaration, *, instance_id: str, work_source: str, work_external_id: str, created_at: datetime,
    mission_id: str | None = None, mission_owner: bool = False, parent_instance_id: str | None = None,
) -> AgentInstance:
    """L'instance que décrit une `agent_markers.AgentDeclaration`, rôle et éphémère tels que déclarés.

    Un rôle inconnu garde l'id réservé `unknown` et son marqueur ; aucun rôle n'est déduit du libellé.
    """

    role = declaration.role
    return AgentInstance(
        instance_id=instance_id,
        work_source=work_source,
        work_external_id=work_external_id,
        role_id=role.role_id,
        role_marker=role.marker if role.role_id != UNDECLARED_ROLE_ID else None,
        created_at=created_at,
        ephemeral=declaration.ephemeral,
        mission_id=mission_id,
        mission_owner=mission_owner,
        parent_instance_id=parent_instance_id,
        label=clip_text(declaration.label, MAX_LABEL_CHARS) if declaration.label else "",
    )
