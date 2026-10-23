"""Graphe d'architecture : types, compatibilité des ports, refus codés (contrat : docs/architecture-graph.md).

Module pur : aucune lecture de réglage, de fichier ni d'environnement. La projection du runtime vivant
(`jarvis/runtime/architecture_graph.py`) construit ces objets ; l'interface ne reçoit que leur `to_dict()`.

Le graphe ne porte aucun état propre : chaque liaison nomme le réglage runtime qui la porte (`binding`).
La disposition des nœuds (positions) vit à part (`LayoutDocument`) et n'entre jamais dans la révision
de la topologie.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import math
import re

SCHEMA_VERSION = 1
LAYOUT_SCHEMA_VERSION = 1


class NodeKind(StrEnum):
    BRAIN = "brain"
    ENDPOINT = "endpoint"
    POOL = "pool"


class NodeState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SHADOW = "shadow"
    UNAVAILABLE = "unavailable"


class PortDirection(StrEnum):
    IN = "in"
    OUT = "out"


class Channel(StrEnum):
    AUDIO = "audio"
    REQUEST = "request"
    RESPONSE = "response"
    TOOL_CALL = "tool_call"
    EVENT = "event"
    SPEECH = "speech"


class Mutability(StrEnum):
    REQUIRED_LOCKED = "required_locked"
    TOGGLEABLE = "toggleable"
    CREATABLE_REMOVABLE = "creatable_removable"
    GOVERNED = "governed"


class Applies(StrEnum):
    """Quand une écriture devient effective. `voice_restart` est un ajout au contrat initial (doc 11) :
    la surface vocale relit sa configuration à son démarrage, et le Control Center lui demande de se
    relancer (bascule `voice_switch`) ; ce n'est ni « en direct » ni « au prochain tour »."""

    LIVE = "live"
    NEXT_TURN = "next_turn"
    VOICE_RESTART = "voice_restart"
    CORE_RESTART = "core_restart"


# Codes stables des refus et statut HTTP associé (doc 11 ; `connection_unbindable` et
# `connection_not_removable` sont des ajouts, `architecture_request_invalid` couvre un corps mal formé).
REVISION_STALE = "architecture_revision_stale"
CONNECTION_LOCKED = "connection_locked"
CONNECTION_INCOMPATIBLE = "connection_incompatible"
CONNECTION_UNKNOWN = "connection_unknown"
CONNECTION_GOVERNED = "connection_governed"
CONNECTION_UNBINDABLE = "connection_unbindable"
CONNECTION_NOT_REMOVABLE = "connection_not_removable"
APPLY_FAILED = "architecture_apply_failed"
REQUEST_INVALID = "architecture_request_invalid"
LAYOUT_REVISION_STALE = "layout_revision_stale"
LAYOUT_INVALID = "layout_invalid"
LAYOUT_WRITE_FAILED = "layout_write_failed"

ERROR_STATUS: Mapping[str, int] = {
    REVISION_STALE: 409, LAYOUT_REVISION_STALE: 409,
    CONNECTION_LOCKED: 423,
    CONNECTION_INCOMPATIBLE: 422, CONNECTION_UNKNOWN: 422, CONNECTION_GOVERNED: 422,
    CONNECTION_UNBINDABLE: 422, CONNECTION_NOT_REMOVABLE: 422,
    REQUEST_INVALID: 400, LAYOUT_INVALID: 400,
    APPLY_FAILED: 500, LAYOUT_WRITE_FAILED: 500,
}


class ArchitectureGraphError(Exception):
    """Refus d'une écriture du graphe : code stable, raison en français, statut HTTP."""

    def __init__(self, code: str, reason: str) -> None:
        if code not in ERROR_STATUS:
            raise ValueError(f"unknown architecture graph error code {code!r}")
        super().__init__(reason)
        self.code, self.reason, self.status = code, reason, ERROR_STATUS[code]


@dataclass(frozen=True, slots=True)
class Port:
    id: str
    direction: PortDirection
    channel: Channel
    #: Famille de compatibilité : deux ports ne se relient que dans la même famille.
    family: str
    label: str = ""

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"id": self.id, "direction": self.direction.value,
                                   "channel": self.channel.value, "family": self.family}
        if self.label:
            data["label"] = self.label
        return data


@dataclass(frozen=True, slots=True)
class Activation:
    mutable: bool
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"mutable": self.mutable, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: NodeKind
    label: str
    state: NodeState
    ports: tuple[Port, ...]
    activation: Activation
    state_reason: str = ""
    brain_type: str | None = None
    endpoint_type: str | None = None
    process: str | None = None
    system: bool = True
    configurable: bool = False
    #: Détails propres au nœud, en lecture seule (p. ex. mode du Tool Brain et sa provenance).
    details: Mapping[str, object] = field(default_factory=dict)

    def port(self, port_id: str) -> Port | None:
        return next((port for port in self.ports if port.id == port_id), None)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"id": self.id, "kind": self.kind.value, "label": self.label}
        if self.brain_type is not None:
            data["brain_type"] = self.brain_type
        if self.endpoint_type is not None:
            data["endpoint_type"] = self.endpoint_type
        data.update({"process": self.process, "system": self.system, "state": self.state.value,
                     "state_reason": self.state_reason, "activation": self.activation.to_dict(),
                     "configurable": self.configurable, "ports": [port.to_dict() for port in self.ports]})
        if self.details:
            data["details"] = dict(self.details)
        return data


@dataclass(frozen=True, slots=True)
class PortRef:
    node: str
    port: str

    def to_dict(self) -> dict[str, str]:
        return {"node": self.node, "port": self.port}


@dataclass(frozen=True, slots=True)
class Pending:
    """Valeur persistée qui attend un redémarrage ; `enabled` de la liaison reste celui du runtime vivant."""

    enabled: bool
    applies: Applies

    def to_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled, "applies": self.applies.value}


@dataclass(frozen=True, slots=True)
class GovernedBy:
    kind: str
    node: str
    field: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "node": self.node, "field": self.field}


def connection_id(source: PortRef, target: PortRef) -> str:
    return f"{source.node}.{source.port}->{target.node}.{target.port}"


@dataclass(frozen=True, slots=True)
class Connection:
    source: PortRef
    target: PortRef
    channel: Channel
    purpose: str
    enabled: bool
    mutability: Mutability
    #: Identité du réglage runtime qui porte la liaison ; jamais un état d'interface.
    binding: str
    #: `None` seulement pour une liaison `governed` : c'est le champ gouvernant qui déclare son effet.
    applies: Applies | None
    locked_reason: str = ""
    impact_when_disabled: str = ""
    pending: Pending | None = None
    governed_by: GovernedBy | None = None

    @property
    def id(self) -> str:
        return connection_id(self.source, self.target)

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "source": self.source.to_dict(), "target": self.target.to_dict(),
                "channel": self.channel.value, "purpose": self.purpose, "enabled": self.enabled,
                "mutability": self.mutability.value, "locked_reason": self.locked_reason,
                "impact_when_disabled": self.impact_when_disabled,
                "applies": self.applies.value if self.applies is not None else None,
                "pending": self.pending.to_dict() if self.pending else None,
                "governed_by": self.governed_by.to_dict() if self.governed_by else None,
                "binding": self.binding}


@dataclass(frozen=True, slots=True)
class VoiceArchitectureRef:
    id: str
    label: str
    settings_target: str = "architecture_compat"
    source: str = "settings"

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "settings_target": self.settings_target, "source": self.source}


@dataclass(frozen=True, slots=True)
class ArchitectureSnapshot:
    revision: str
    voice_architecture: VoiceArchitectureRef
    nodes: tuple[Node, ...]
    connections: tuple[Connection, ...]

    def node(self, node_id: str) -> Node | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def connection(self, conn_id: str) -> Connection | None:
        return next((conn for conn in self.connections if conn.id == conn_id), None)

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, "revision": self.revision,
                "voice_architecture": self.voice_architecture.to_dict(),
                "nodes": [node.to_dict() for node in self.nodes],
                "connections": [conn.to_dict() for conn in self.connections]}


def port_incompatibility(source: Port | None, target: Port | None) -> str | None:
    """Raison (français) pour laquelle `source -> target` est impossible, ou `None` si compatible."""

    if source is None or target is None:
        return "Port inconnu sur ce nœud."
    if source.direction is not PortDirection.OUT:
        return f"Le port « {source.id} » est une entrée : une liaison part d'une sortie."
    if target.direction is not PortDirection.IN:
        return f"Le port « {target.id} » est une sortie : une liaison arrive sur une entrée."
    if source.channel is not target.channel:
        return f"Canaux différents : {source.channel.value} vers {target.channel.value}."
    if source.family != target.family:
        return f"Familles incompatibles : {source.family} vers {target.family}."
    return None


def validate_snapshot(snapshot: ArchitectureSnapshot) -> None:
    """Garde de construction : un snapshot incohérent est un défaut de la projection, jamais servi."""

    ids = [node.id for node in snapshot.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate node id in architecture snapshot")
    for node in snapshot.nodes:
        port_ids = [port.id for port in node.ports]
        if len(port_ids) != len(set(port_ids)):
            raise ValueError(f"duplicate port id on node {node.id}")
    seen: set[str] = set()
    for conn in snapshot.connections:
        if conn.id in seen:
            raise ValueError(f"duplicate connection {conn.id}")
        seen.add(conn.id)
        source, target = snapshot.node(conn.source.node), snapshot.node(conn.target.node)
        if source is None or target is None:
            raise ValueError(f"connection {conn.id} references an absent node")
        problem = port_incompatibility(source.port(conn.source.port), target.port(conn.target.port))
        if problem:
            raise ValueError(f"connection {conn.id} is incompatible: {problem}")
        if source.port(conn.source.port).channel is not conn.channel:  # type: ignore[union-attr]
            raise ValueError(f"connection {conn.id} channel differs from its ports")
        if (conn.mutability is Mutability.GOVERNED) != (conn.governed_by is not None):
            raise ValueError(f"connection {conn.id}: governed_by is set exactly for governed links")
        if conn.mutability is Mutability.REQUIRED_LOCKED and not conn.locked_reason:
            raise ValueError(f"connection {conn.id}: a locked link must say why")
        if not conn.binding:
            raise ValueError(f"connection {conn.id} has no runtime binding")


def topology_revision(inputs: Mapping[str, object]) -> str:
    """Révision opaque `t-<empreinte>` des réglages persistés qui portent la topologie.

    Calculée et non comptée : toute écriture d'un de ces réglages, par le graphe ou par une autre page
    (Avancé, `/api/settings`), périme la révision. L'état vivant (battement de Voice) n'y entre pas,
    pour qu'un battement manqué ne refuse pas une écriture.
    """

    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return "t-" + digest[:16]


# ------------------------------------------------------------------ disposition (interface seule)

_NODE_ID = re.compile(r"\A[a-z][a-z0-9_.-]{0,63}\Z")
MAX_LAYOUT_NODES = 64
MAX_COORDINATE = 100_000.0


@dataclass(frozen=True, slots=True)
class LayoutDocument:
    revision: int
    positions: Mapping[str, Mapping[str, float]]

    @property
    def revision_token(self) -> str:
        return f"l-{self.revision}"

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": LAYOUT_SCHEMA_VERSION, "revision": self.revision_token,
                "positions": {key: dict(value) for key, value in self.positions.items()}}


def parse_layout_revision(raw: object) -> int:
    if isinstance(raw, str) and raw.startswith("l-") and raw[2:].isdigit():
        return int(raw[2:])
    raise ArchitectureGraphError(LAYOUT_INVALID, "Révision de disposition illisible : attendu « l-<n> ».")


def validate_positions(raw: object) -> dict[str, dict[str, float]]:
    """Positions `{node_id: {x, y}}` bornées. Les ids ne sont pas confrontés au graphe : une disposition
    peut garder la place d'un nœud absent dans l'architecture courante (Luna hors Front Brain)."""

    if not isinstance(raw, dict):
        raise ArchitectureGraphError(LAYOUT_INVALID, "Les positions doivent être un objet {nœud: {x, y}}.")
    if len(raw) > MAX_LAYOUT_NODES:
        raise ArchitectureGraphError(LAYOUT_INVALID, f"Au plus {MAX_LAYOUT_NODES} nœuds dans une disposition.")
    result: dict[str, dict[str, float]] = {}
    for node_id, point in raw.items():
        if not isinstance(node_id, str) or not _NODE_ID.match(node_id):
            raise ArchitectureGraphError(LAYOUT_INVALID, f"Identifiant de nœud invalide : {node_id!r}.")
        if not isinstance(point, dict) or set(point) != {"x", "y"}:
            raise ArchitectureGraphError(LAYOUT_INVALID, f"Position de « {node_id} » : attendu {{x, y}}.")
        coords: dict[str, float] = {}
        for axis in ("x", "y"):
            value = point[axis]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or abs(value) > MAX_COORDINATE):
                raise ArchitectureGraphError(LAYOUT_INVALID, f"Coordonnée {axis} de « {node_id} » invalide.")
            coords[axis] = float(value)
        result[node_id] = coords
    return result
