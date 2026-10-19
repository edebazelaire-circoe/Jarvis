"""Relations typées entre instances d'agent, messages de relation et paquet de relais (Slice 02).

Une relation dit **quel lien de travail deux agents ou plus ont réellement noué
pour une mission** ; elle ne dit jamais où en est l'exécution (Core Work State,
D16) ni comment la relation doit se dérouler (D12 : sémantique, pas protocole).

- `AgentRelationKind` : les cinq natures fermées de D09 — `delegation`,
  `communication`, `adversary`, `qa`, `handoff`. C'est la source canonique du
  vocabulaire ; `work_methods.USEFUL_RELATION_KINDS` l'importe.
- `AgentRelation` : identité, nature, mission, participants positionnés,
  objet borné, cycle de vie `open -> closed` (une fois), champs propres à une
  nature validés pour elle seule (`sub_mission_id` de la délégation,
  `target_refs` de la QA, `handoff` du relais, `winner_instance_id` d'une
  confrontation close). Aucun compteur ni ordre de tours n'est représentable.
- Positions : `delegator -> delegatee` (dirigé), `member` (au moins deux,
  communication), `producer` (au moins deux pairs symétriques, Adversary,
  D10), `reviewer -> reviewed` (dirigé, QA, D11), `predecessor -> successor`
  (dirigé, relais, D14). Adversary et QA ne partagent aucune position.
- `RelationMessage` : un message délibéré et borné posté sur le tableau de la
  relation (le tableau *est* le fil de la relation, identifié par son
  `relation_id` ; ce n'est pas un Board d'espace de travail).
- `HandoffPacket` : le paquet de transfert complet, porté par la relation de
  relais elle-même : un relais sans paquet complet n'existe pas.
- Frontière de confidentialité (D13) : aucun champ de raisonnement, de prompt
  ou de charge brute du fournisseur ; une clé privée à n'importe quelle
  profondeur d'une charge reçue est refusée (`relation_private_content`, même
  liste que Conversation Events), un texte qui est un blob JSON brut ou porte
  une balise de raisonnement aussi.
- `check_relation_participants` et `check_handoff_chain` : cohérence avec les
  instances (`missions.AgentInstance`) — participants connus, jamais
  éphémères (D08), relecteur de rôle QA, producteurs qui ne sont pas des
  relecteurs, successeur neuf et jamais réutilisé.

Contrat : `docs/agent-relations.md`. Module pur, sans E/S. Il n'importe ni
`missions` ni `subagent_roles` (qui importent `work_methods`, qui importe ce
module) : les instances sont lues par leurs attributs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import json
import re
from typing import TYPE_CHECKING, Any

from jarvis.domain._checks import (
    check_aware, check_id, check_text, parse_dt, parse_enum, preview, recode, strict_keys,
)
from jarvis.domain.conversation_events import is_forbidden_key

if TYPE_CHECKING:  # lecture par attributs seulement, pour ne pas créer de cycle d'import
    from jarvis.domain.missions import AgentInstance, Mission

MAX_PURPOSE_CHARS = 300
MAX_OUTCOME_SUMMARY_CHARS = 1_000
MAX_MESSAGE_CHARS = 4_000
MAX_PACKET_TEXT_CHARS = 2_000
MAX_PACKET_ITEM_CHARS = 300
MAX_PACKET_ITEMS = 16
MAX_REFS = 16
#: Une confrontation ou un fil de coordination reste lisible : au-delà, c'est une équipe, pas une relation.
MAX_PARTICIPANTS = 12
#: Profondeur maximale d'une charge reçue avant décodage (participants, paquet : deux niveaux suffisent).
MAX_PAYLOAD_DEPTH = 6


class RelationError(ValueError):
    """Relation, message ou paquet refusé, avec un code stable et le champ en cause."""

    def __init__(self, message: str, *, code: str = "relation_invalid", field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _fail(message: str) -> RelationError:
    return RelationError(message)


def _check(name: str, check: Any, *args: Any, **kwargs: Any) -> None:
    recode(lambda message: RelationError(message, field=name), check, name, *args, **kwargs)


# ------------------------------------------------------------------ vocabulaire


class AgentRelationKind(StrEnum):
    """Les cinq natures de D09. Fermé : une nature n'est jamais déduite d'un libellé."""

    DELEGATION = "delegation"
    COMMUNICATION = "communication"
    ADVERSARY = "adversary"
    QA = "qa"
    HANDOFF = "handoff"


#: Le vocabulaire en chaînes, dans l'ordre de D09 (réutilisé par `work_methods`).
RELATION_KINDS: tuple[str, ...] = tuple(kind.value for kind in AgentRelationKind)


class ParticipantPosition(StrEnum):
    DELEGATOR = "delegator"
    DELEGATEE = "delegatee"
    MEMBER = "member"
    PRODUCER = "producer"
    REVIEWER = "reviewer"
    REVIEWED = "reviewed"
    PREDECESSOR = "predecessor"
    SUCCESSOR = "successor"


@dataclass(frozen=True, slots=True)
class _Shape:
    """Forme d'une nature : positions exactes (dirigée) ou une position partagée par au moins deux pairs."""

    directed: tuple[ParticipantPosition, ParticipantPosition] | None = None
    peer: ParticipantPosition | None = None


_SHAPES: Mapping[AgentRelationKind, _Shape] = {
    AgentRelationKind.DELEGATION: _Shape(directed=(ParticipantPosition.DELEGATOR, ParticipantPosition.DELEGATEE)),
    AgentRelationKind.COMMUNICATION: _Shape(peer=ParticipantPosition.MEMBER),
    AgentRelationKind.ADVERSARY: _Shape(peer=ParticipantPosition.PRODUCER),
    AgentRelationKind.QA: _Shape(directed=(ParticipantPosition.REVIEWER, ParticipantPosition.REVIEWED)),
    AgentRelationKind.HANDOFF: _Shape(directed=(ParticipantPosition.PREDECESSOR, ParticipantPosition.SUCCESSOR)),
}


def is_directed(kind: AgentRelationKind) -> bool:
    """Vrai pour une relation à sens (délégation, QA, relais) ; faux pour une relation entre pairs."""

    return _SHAPES[kind].directed is not None


class RelationStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class RelationOutcome(StrEnum):
    """Comment une relation s'est close. `withdrawn` : retirée par qui l'a nouée, valable pour toute nature."""

    WITHDRAWN = "withdrawn"
    RETURNED = "returned"
    ENDED = "ended"
    WINNER = "winner"
    SYNTHESIS = "synthesis"
    UNRESOLVED = "unresolved"
    ESCALATED = "escalated"
    APPROVED = "approved"
    FINDINGS = "findings"
    CORRECTION_REQUESTED = "correction_requested"
    REJECTED = "rejected"
    TRANSFERRED = "transferred"


#: Issues permises par nature (sens, pas protocole : aucune n'exige un nombre de tours).
OUTCOMES_BY_KIND: Mapping[AgentRelationKind, frozenset[RelationOutcome]] = {
    AgentRelationKind.DELEGATION: frozenset({RelationOutcome.RETURNED, RelationOutcome.WITHDRAWN}),
    AgentRelationKind.COMMUNICATION: frozenset({RelationOutcome.ENDED, RelationOutcome.WITHDRAWN}),
    AgentRelationKind.ADVERSARY: frozenset({
        RelationOutcome.WINNER, RelationOutcome.SYNTHESIS, RelationOutcome.UNRESOLVED, RelationOutcome.ESCALATED,
        RelationOutcome.WITHDRAWN,
    }),
    AgentRelationKind.QA: frozenset({
        RelationOutcome.APPROVED, RelationOutcome.FINDINGS, RelationOutcome.CORRECTION_REQUESTED,
        RelationOutcome.REJECTED, RelationOutcome.WITHDRAWN,
    }),
    AgentRelationKind.HANDOFF: frozenset({RelationOutcome.TRANSFERRED, RelationOutcome.WITHDRAWN}),
}


class RelationMessageType(StrEnum):
    MESSAGE = "message"
    PROPOSAL = "proposal"
    CRITIQUE = "critique"
    QUESTION = "question"
    DECISION = "decision"
    RESULT_SUMMARY = "result_summary"
    HANDOFF_NOTE = "handoff_note"


#: Rôles dont une instance peut relire en QA (D11 ; l'alias `reviewer` se résout en `qa`). Ids du registre
#: `subagent_roles`, que ce module ne peut pas importer : l'égalité est vérifiée par un test.
QA_REVIEWER_ROLE_IDS = frozenset({"qa"})

#: Clés refusées nommément : une relation a une sémantique, pas un protocole (D12) ni un plan (D15).
FORBIDDEN_PROTOCOL_KEYS = frozenset({
    "round", "rounds", "round_count", "max_rounds", "turns", "max_turns", "phase", "phases", "protocol", "steps",
    "sequence", "order", "schedule", "plan", "workflow",
})


# ------------------------------------------------------------------ confidentialité

#: Balises de raisonnement privé : jamais recopiées sur un tableau (D13).
_PRIVATE_TAG = re.compile(
    r"<\s*/?\s*(?:antml:)?(?:thinking|reasoning|scratchpad|chain[ _-]?of[ _-]?thought|redacted_thinking)\b",
    re.IGNORECASE,
)


def scan_private_keys(payload: object, path: str = "payload", depth: int = 0) -> None:
    """Refuser une clé privée ou brute (raisonnement, prompt, jeton, arguments...) à toute profondeur.

    Même règle que Conversation Events (`conversation_events.is_forbidden_key`) ; le message nomme le chemin,
    jamais la valeur.
    """

    if depth > MAX_PAYLOAD_DEPTH:
        raise RelationError(f"{path}: nesting exceeds {MAX_PAYLOAD_DEPTH} levels", field=path)
    if isinstance(payload, (bytes, bytearray, memoryview)):
        raise RelationError(f"{path}: raw bytes are not collaboration content", code="relation_raw_payload",
                            field=path)
    if isinstance(payload, Mapping):
        for key, item in payload.items():
            name = f"{path}.{str(key)[:40]}"
            if not isinstance(key, str):
                raise RelationError(f"{path}: object keys must be strings", field=path)
            if is_forbidden_key(key):
                raise RelationError(f"{name}: private or raw provider data is never collaboration content",
                                    code="relation_private_content", field=name)
            scan_private_keys(item, name, depth + 1)
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            scan_private_keys(item, f"{path}[{index}]", depth + 1)


def check_collaboration_text(name: str, value: object, limit: int, *, required: bool = True) -> None:
    """Un texte durable de collaboration : borné, délibéré, jamais un raisonnement privé ni une charge brute."""

    _check(name, check_text, value, limit, single_line=False)
    text = str(value)
    if required and not text.strip():
        raise RelationError(f"{name} is required", field=name)
    if _PRIVATE_TAG.search(text):
        raise RelationError(f"{name} holds a private reasoning tag", code="relation_private_content", field=name)
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            decoded = json.loads(stripped)
        except RecursionError:
            # Des milliers de crochets imbriqués : une charge, pas une phrase.
            raise RelationError(f"{name} is a raw nested payload", code="relation_raw_payload", field=name) from None
        except ValueError:
            return
        if isinstance(decoded, (dict, list)):
            raise RelationError(f"{name} is a raw JSON payload, not an explicit message", code="relation_raw_payload",
                                field=name)


def _check_refs(name: str, refs: object) -> None:
    if not isinstance(refs, tuple) or len(refs) > MAX_REFS:
        raise RelationError(f"{name} must be a tuple of at most {MAX_REFS} references", field=name)
    for ref in refs:
        _check(f"{name}[]", check_id, ref, required=True)
    if len(set(refs)) != len(refs):
        raise RelationError(f"{name} must be unique", field=name)


def _decode(name: str, payload: object, allowed: frozenset[str], required: frozenset[str]) -> dict[str, Any]:
    """Décodage strict commun : clé privée nommée comme telle, clé de protocole aussi, puis aucune clé inconnue."""

    scan_private_keys(payload, name)
    if isinstance(payload, dict):
        protocol = sorted(FORBIDDEN_PROTOCOL_KEYS & payload.keys())
        if protocol:
            raise RelationError(f"a relation has semantics, not a protocol: {protocol} is not allowed",
                                code="relation_is_not_a_protocol", field=protocol[0])
    return strict_keys(_fail, name, payload, allowed, required=required)


def _list(data: Mapping[str, Any], key: str) -> tuple[Any, ...]:
    value = data.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RelationError(f"{key} must be a list", field=key)
    return tuple(value)


# ------------------------------------------------------------------ participants et paquet


@dataclass(frozen=True, slots=True)
class RelationParticipant:
    instance_id: str
    position: ParticipantPosition

    def __post_init__(self) -> None:
        _check("instance_id", check_id, self.instance_id, required=True)
        if not isinstance(self.position, ParticipantPosition):
            raise RelationError("position must be a ParticipantPosition", field="position")

    def to_payload(self) -> dict[str, Any]:
        return {"instance_id": self.instance_id, "position": self.position.value}

    @classmethod
    def from_payload(cls, payload: object) -> RelationParticipant:
        data = _decode("participant", payload, _PARTICIPANT_KEYS, _PARTICIPANT_KEYS)
        return cls(instance_id=data["instance_id"],
                   position=parse_enum(_fail, "position", data["position"], ParticipantPosition))


_PARTICIPANT_KEYS = frozenset({"instance_id", "position"})


def _packet_items(name: str, values: object) -> None:
    if not isinstance(values, tuple) or len(values) > MAX_PACKET_ITEMS:
        raise RelationError(f"{name} must be a tuple of at most {MAX_PACKET_ITEMS} entries", field=name)
    for value in values:
        check_collaboration_text(f"{name}[]", value, MAX_PACKET_ITEM_CHARS)
    if len(set(values)) != len(values):
        raise RelationError(f"{name} entries must be unique", field=name)


@dataclass(frozen=True, slots=True)
class HandoffPacket:
    """Ce que le successeur reçoit (D14). Complet par construction : chaque champ est présent, borné, explicite.

    `key_decisions` et `open_points` peuvent être vides, mais doivent être dits (le décodage exige la clé) ;
    `objective`, `completed_work` et `recommended_next_action` sont requis. Les références sont des ids
    (artefacts, preuves : relation QA, mission, fichier), jamais du texte de raisonnement.
    """

    objective: str
    completed_work: str
    recommended_next_action: str
    key_decisions: tuple[str, ...] = ()
    open_points: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("objective", "completed_work", "recommended_next_action"):
            check_collaboration_text(name, getattr(self, name), MAX_PACKET_TEXT_CHARS)
        _packet_items("key_decisions", self.key_decisions)
        _packet_items("open_points", self.open_points)
        _check_refs("artifact_refs", self.artifact_refs)
        _check_refs("evidence_refs", self.evidence_refs)

    def to_payload(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "completed_work": self.completed_work,
            "recommended_next_action": self.recommended_next_action,
            "key_decisions": list(self.key_decisions),
            "open_points": list(self.open_points),
            "artifact_refs": list(self.artifact_refs),
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_payload(cls, payload: object) -> HandoffPacket:
        # Toutes les clés sont exigées : un paquet tronqué en transit n'est pas un paquet vide.
        data = _decode("handoff packet", payload, _PACKET_KEYS, frozenset())
        missing = sorted(_PACKET_KEYS - data.keys())
        if missing:
            raise RelationError(f"handoff packet is missing fields: {missing}", code="handoff_packet_incomplete",
                                field="handoff")
        return cls(
            objective=data["objective"],
            completed_work=data["completed_work"],
            recommended_next_action=data["recommended_next_action"],
            key_decisions=_list(data, "key_decisions"),
            open_points=_list(data, "open_points"),
            artifact_refs=_list(data, "artifact_refs"),
            evidence_refs=_list(data, "evidence_refs"),
        )


_PACKET_KEYS = frozenset({
    "objective", "completed_work", "recommended_next_action", "key_decisions", "open_points", "artifact_refs",
    "evidence_refs",
})


# ------------------------------------------------------------------ relation


@dataclass(frozen=True, slots=True)
class AgentRelation:
    """Un lien de travail réellement noué pour une mission (D09, D15 : jamais un lien envisagé).

    Les participants sont fixés à la création : changer l'ensemble, c'est nouer une autre relation.
    `created_by_instance_id` : l'instance qui l'a nouée (un Mission Owner le plus souvent), `None` quand c'est
    le cerveau ou Core.
    """

    relation_id: str
    kind: AgentRelationKind
    mission_id: str
    participants: tuple[RelationParticipant, ...]
    purpose: str
    created_at: datetime
    created_by_instance_id: str | None = None
    sub_mission_id: str | None = None
    target_refs: tuple[str, ...] = ()
    handoff: HandoffPacket | None = None
    status: RelationStatus = RelationStatus.OPEN
    closed_at: datetime | None = None
    outcome: RelationOutcome | None = None
    outcome_summary: str = ""
    winner_instance_id: str | None = None

    def __post_init__(self) -> None:
        _check("relation_id", check_id, self.relation_id, required=True)
        if not isinstance(self.kind, AgentRelationKind):
            raise RelationError("kind must be an AgentRelationKind", field="kind")
        _check("mission_id", check_id, self.mission_id, required=True)
        _check("created_by_instance_id", check_id, self.created_by_instance_id, required=False)
        check_collaboration_text("purpose", self.purpose, MAX_PURPOSE_CHARS)
        check_aware(_fail, "created_at", self.created_at)
        self._check_participants()
        self._check_kind_fields()
        self._check_closure()

    def _check_participants(self) -> None:
        participants = self.participants
        if not isinstance(participants, tuple) or not all(isinstance(p, RelationParticipant) for p in participants):
            raise RelationError("participants must be a tuple of RelationParticipant", field="participants")
        if len(participants) > MAX_PARTICIPANTS:
            raise RelationError(f"a relation has at most {MAX_PARTICIPANTS} participants",
                                code="relation_participants_invalid", field="participants")
        ids = [p.instance_id for p in participants]
        if len(set(ids)) != len(ids):
            raise RelationError("an instance takes part in a relation once", code="relation_participant_duplicate",
                                field="participants")
        shape = _SHAPES[self.kind]
        positions = [p.position for p in participants]
        if shape.directed is not None:
            if sorted(positions) != sorted(shape.directed):
                raise RelationError(
                    f"a {self.kind.value} relation has exactly one {shape.directed[0].value} and one "
                    f"{shape.directed[1].value}", code="relation_participants_invalid", field="participants",
                )
        elif len(positions) < 2 or any(position is not shape.peer for position in positions):
            raise RelationError(
                f"a {self.kind.value} relation joins at least two {shape.peer.value}s, all peers",
                code="relation_participants_invalid", field="participants",
            )

    def _check_kind_fields(self) -> None:
        _check("sub_mission_id", check_id, self.sub_mission_id, required=False)
        _check_refs("target_refs", self.target_refs)
        if self.handoff is not None and not isinstance(self.handoff, HandoffPacket):
            raise RelationError("handoff must be a HandoffPacket", field="handoff")
        foreign = [
            name for name, kind, present in (
                ("sub_mission_id", AgentRelationKind.DELEGATION, self.sub_mission_id is not None),
                ("target_refs", AgentRelationKind.QA, bool(self.target_refs)),
                ("handoff", AgentRelationKind.HANDOFF, self.handoff is not None),
            ) if present and self.kind is not kind
        ]
        if foreign:
            raise RelationError(f"{foreign[0]} does not belong to a {self.kind.value} relation",
                                code="relation_field_not_for_kind", field=foreign[0])
        if self.sub_mission_id is not None and self.sub_mission_id == self.mission_id:
            raise RelationError("a delegated sub-mission differs from the delegating mission", field="sub_mission_id")
        if self.kind is AgentRelationKind.HANDOFF and self.handoff is None:
            raise RelationError("a handoff carries its complete packet from creation",
                                code="handoff_packet_incomplete", field="handoff")

    def _check_closure(self) -> None:
        if not isinstance(self.status, RelationStatus):
            raise RelationError("status must be a RelationStatus", field="status")
        _check("winner_instance_id", check_id, self.winner_instance_id, required=False)
        if self.outcome is not None and not isinstance(self.outcome, RelationOutcome):
            raise RelationError("outcome must be a RelationOutcome", field="outcome")
        check_collaboration_text("outcome_summary", self.outcome_summary, MAX_OUTCOME_SUMMARY_CHARS, required=False)
        closed = self.status is RelationStatus.CLOSED
        if closed != (self.closed_at is not None) or closed != (self.outcome is not None):
            raise RelationError("closed_at and outcome are set exactly when the relation is closed",
                                field="closed_at")
        if not closed and (self.outcome_summary or self.winner_instance_id is not None):
            raise RelationError("outcome_summary and winner_instance_id belong to a closed relation", field="outcome")
        if not closed:
            return
        check_aware(_fail, "closed_at", self.closed_at)
        if self.closed_at < self.created_at:
            raise RelationError("closed_at cannot precede created_at", field="closed_at")
        if self.outcome not in OUTCOMES_BY_KIND[self.kind]:
            raise RelationError(
                f"{self.outcome.value} does not close a {self.kind.value} relation "
                f"(allowed: {sorted(o.value for o in OUTCOMES_BY_KIND[self.kind])})",
                code="relation_outcome_invalid", field="outcome",
            )
        if (self.outcome is RelationOutcome.WINNER) != (self.winner_instance_id is not None):
            raise RelationError("winner_instance_id is named exactly when an adversary closes with a winner",
                                code="relation_outcome_invalid", field="winner_instance_id")
        if self.winner_instance_id is not None and self.winner_instance_id not in self.participant_ids:
            raise RelationError("the winner must be one of the producers", code="relation_outcome_invalid",
                                field="winner_instance_id")

    # -------------------------------------------------------------- lecture

    @property
    def participant_ids(self) -> tuple[str, ...]:
        return tuple(p.instance_id for p in self.participants)

    @property
    def is_open(self) -> bool:
        return self.status is RelationStatus.OPEN

    @property
    def directed(self) -> bool:
        return is_directed(self.kind)

    def at(self, position: ParticipantPosition) -> tuple[str, ...]:
        """Les instances qui tiennent `position` (une seule pour une relation dirigée)."""

        return tuple(p.instance_id for p in self.participants if p.position is position)

    def endpoints(self) -> tuple[str, str] | None:
        """`(source, cible)` d'une relation dirigée, `None` pour une relation entre pairs."""

        shape = _SHAPES[self.kind]
        if shape.directed is None:
            return None
        return self.at(shape.directed[0])[0], self.at(shape.directed[1])[0]

    # -------------------------------------------------------------- cycle de vie

    def close(
        self, outcome: RelationOutcome, at: datetime, *, summary: str = "", winner_instance_id: str | None = None,
    ) -> AgentRelation:
        """Clore une relation ouverte. Une relation close ne se rouvre pas ; reclore à l'identique est sans effet."""

        if not self.is_open:
            if (self.outcome, self.closed_at, self.outcome_summary, self.winner_instance_id) == (
                    outcome, at, summary, winner_instance_id):
                return self
            raise RelationError(f"relation {self.relation_id} is already closed ({self.outcome.value})",
                                code="relation_closed", field="status")
        return replace(self, status=RelationStatus.CLOSED, closed_at=at, outcome=outcome, outcome_summary=summary,
                       winner_instance_id=winner_instance_id)

    # -------------------------------------------------------------- codec

    def to_payload(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "kind": self.kind.value,
            "mission_id": self.mission_id,
            "participants": [p.to_payload() for p in self.participants],
            "purpose": self.purpose,
            "created_at": self.created_at.isoformat(),
            "created_by_instance_id": self.created_by_instance_id,
            "sub_mission_id": self.sub_mission_id,
            "target_refs": list(self.target_refs),
            "handoff": self.handoff.to_payload() if self.handoff else None,
            "status": self.status.value,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "outcome": self.outcome.value if self.outcome else None,
            "outcome_summary": self.outcome_summary,
            "winner_instance_id": self.winner_instance_id,
        }

    @classmethod
    def from_payload(cls, payload: object) -> AgentRelation:
        data = _decode("agent relation", payload, _RELATION_KEYS, _RELATION_REQUIRED)
        handoff = data.get("handoff")
        outcome = data.get("outcome")
        return cls(
            relation_id=data["relation_id"],
            kind=parse_enum(_fail, "kind", data["kind"], AgentRelationKind),
            mission_id=data["mission_id"],
            participants=tuple(RelationParticipant.from_payload(item) for item in _list(data, "participants")),
            purpose=data["purpose"],
            created_at=parse_dt(_fail, "created_at", data["created_at"]),
            created_by_instance_id=data.get("created_by_instance_id"),
            sub_mission_id=data.get("sub_mission_id"),
            target_refs=_list(data, "target_refs"),
            handoff=None if handoff is None else HandoffPacket.from_payload(handoff),
            status=parse_enum(_fail, "status", data.get("status", "open"), RelationStatus),
            closed_at=parse_dt(_fail, "closed_at", data.get("closed_at"), required=False),
            outcome=None if outcome is None else parse_enum(_fail, "outcome", outcome, RelationOutcome),
            outcome_summary=data.get("outcome_summary") or "",
            winner_instance_id=data.get("winner_instance_id"),
        )


_RELATION_KEYS = frozenset({
    "relation_id", "kind", "mission_id", "participants", "purpose", "created_at", "created_by_instance_id",
    "sub_mission_id", "target_refs", "handoff", "status", "closed_at", "outcome", "outcome_summary",
    "winner_instance_id",
})
_RELATION_REQUIRED = frozenset({"relation_id", "kind", "mission_id", "participants", "purpose", "created_at"})


# ------------------------------------------------------------------ messages


@dataclass(frozen=True, slots=True)
class RelationMessage:
    """Un message délibéré posté sur le tableau d'une relation (D13).

    `audience` vide : tous les participants. Aucun champ de raisonnement, de prompt ou d'événement brut ;
    l'ordre du fil est celui de l'acceptation par le magasin (Slice 03/06), pas un numéro de tour.
    """

    message_id: str
    relation_id: str
    author_instance_id: str
    type: RelationMessageType
    text: str
    created_at: datetime
    audience: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check("message_id", check_id, self.message_id, required=True)
        _check("relation_id", check_id, self.relation_id, required=True)
        _check("author_instance_id", check_id, self.author_instance_id, required=True)
        if not isinstance(self.type, RelationMessageType):
            raise RelationError("type must be a RelationMessageType", field="type")
        check_collaboration_text("text", self.text, MAX_MESSAGE_CHARS)
        check_aware(_fail, "created_at", self.created_at)
        if not isinstance(self.audience, tuple) or len(self.audience) > MAX_PARTICIPANTS:
            raise RelationError(f"audience must be a tuple of at most {MAX_PARTICIPANTS} instance ids",
                                field="audience")
        for instance_id in self.audience:
            _check("audience[]", check_id, instance_id, required=True)
        if len(set(self.audience)) != len(self.audience):
            raise RelationError("audience must be unique", field="audience")
        if self.author_instance_id in self.audience:
            raise RelationError("the author is not part of its own audience", field="audience")
        _check_refs("artifact_refs", self.artifact_refs)

    def to_payload(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "relation_id": self.relation_id,
            "author_instance_id": self.author_instance_id,
            "type": self.type.value,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "audience": list(self.audience),
            "artifact_refs": list(self.artifact_refs),
        }

    @classmethod
    def from_payload(cls, payload: object) -> RelationMessage:
        data = _decode("relation message", payload, _MESSAGE_KEYS, _MESSAGE_REQUIRED)
        return cls(
            message_id=data["message_id"],
            relation_id=data["relation_id"],
            author_instance_id=data["author_instance_id"],
            type=parse_enum(_fail, "type", data["type"], RelationMessageType),
            text=data["text"],
            created_at=parse_dt(_fail, "created_at", data["created_at"]),
            audience=_list(data, "audience"),
            artifact_refs=_list(data, "artifact_refs"),
        )


_MESSAGE_KEYS = frozenset({
    "message_id", "relation_id", "author_instance_id", "type", "text", "created_at", "audience", "artifact_refs",
})
_MESSAGE_REQUIRED = frozenset({"message_id", "relation_id", "author_instance_id", "type", "text", "created_at"})


def check_message(relation: AgentRelation, message: RelationMessage) -> None:
    """Un message peut-il entrer sur le tableau de `relation` ?

    Auteur et audience parmi les participants, relation ouverte, message pas antérieur à la relation ;
    `handoff_note` sur un relais seulement. Aucune règle d'ordre ni de nombre de messages (D12).
    """

    if message.relation_id != relation.relation_id:
        raise RelationError("the message belongs to another relation", field="relation_id")
    if not relation.is_open:
        raise RelationError(f"relation {relation.relation_id} is closed: its board accepts no new message",
                            code="relation_closed", field="relation_id")
    members = set(relation.participant_ids)
    if message.author_instance_id not in members:
        raise RelationError("only a participant posts on a relation board", code="relation_not_participant",
                            field="author_instance_id")
    outsiders = [instance_id for instance_id in message.audience if instance_id not in members]
    if outsiders:
        raise RelationError(f"audience must be participants, got {preview(outsiders[0])}",
                            code="relation_not_participant", field="audience")
    if message.created_at < relation.created_at:
        raise RelationError("a message cannot precede its relation", field="created_at")
    if message.type is RelationMessageType.HANDOFF_NOTE and relation.kind is not AgentRelationKind.HANDOFF:
        raise RelationError("handoff_note belongs to a handoff relation", code="relation_message_type_invalid",
                            field="type")


# ------------------------------------------------------------------ cohérence avec les instances


def check_relation_participants(
    relation: AgentRelation,
    instances: Mapping[str, AgentInstance],
    *,
    missions: Mapping[str, Mission] | None = None,
) -> None:
    """La relation est cohérente avec les instances (et, si fournies, les missions) qu'elle nomme.

    - chaque participant est une instance connue, jamais éphémère (D08 : une relation durable en ferait un
      nœud d'historique) ;
    - QA : le relecteur a un rôle de QA (`QA_REVIEWER_ROLE_IDS`) ; Adversary : aucun producteur n'en a un
      (D10, un relecteur n'est pas un concurrent) ;
    - délégation vers une sous-mission : le délégataire porte cette sous-mission, fille de la mission ;
    - relais : prédécesseur et successeur sont de la même mission, le successeur est une instance neuve
      (créée au plus tôt avec son prédécesseur). Le rôle peut changer : c'est la voie d'un changement de rôle.
    """

    for participant in relation.participants:
        instance = instances.get(participant.instance_id)
        if instance is None:
            raise RelationError(f"participant {participant.instance_id} is not a known agent instance",
                                code="relation_participant_missing", field="participants")
        if instance.ephemeral:
            raise RelationError(f"participant {participant.instance_id} is ephemeral and leaves no history",
                                code="ephemeral_relation_participant", field="participants")
    kind = relation.kind
    if kind is AgentRelationKind.QA:
        reviewer = instances[relation.at(ParticipantPosition.REVIEWER)[0]]
        if reviewer.role_id not in QA_REVIEWER_ROLE_IDS:
            raise RelationError(f"a QA reviewer needs a QA role, got {preview(reviewer.role_id)}",
                                code="qa_reviewer_role", field="participants")
    elif kind is AgentRelationKind.ADVERSARY:
        for instance_id in relation.participant_ids:
            if instances[instance_id].role_id in QA_REVIEWER_ROLE_IDS:
                raise RelationError(f"adversary producer {instance_id} is a reviewer: request QA instead",
                                    code="adversary_producer_is_reviewer", field="participants")
    elif kind is AgentRelationKind.DELEGATION and relation.sub_mission_id is not None:
        delegatee = instances[relation.at(ParticipantPosition.DELEGATEE)[0]]
        if delegatee.mission_id != relation.sub_mission_id:
            raise RelationError("the delegatee carries the delegated sub-mission", code="delegation_sub_mission",
                                field="sub_mission_id")
        if missions is not None:
            sub = missions.get(relation.sub_mission_id)
            if sub is None or sub.parent_mission_id != relation.mission_id:
                raise RelationError("the delegated sub-mission is a child of the relation's mission",
                                    code="delegation_sub_mission", field="sub_mission_id")
    elif kind is AgentRelationKind.HANDOFF:
        predecessor, successor = (instances[i] for i in relation.endpoints())
        if predecessor.mission_id != relation.mission_id or successor.mission_id != relation.mission_id:
            raise RelationError("a handoff stays within one mission", code="handoff_mission_mismatch",
                                field="mission_id")
        if successor.created_at < predecessor.created_at:
            raise RelationError("a handoff goes to a fresh instance, not an older one",
                                code="handoff_successor_not_fresh", field="participants")
    if missions is not None and relation.mission_id not in missions:
        raise RelationError(f"mission {relation.mission_id} is missing", code="relation_mission_missing",
                            field="mission_id")


def check_handoff_chain(relations: Iterable[AgentRelation]) -> None:
    """Les relais d'un ensemble forment des chaînes : un successeur ne reçoit qu'un relais, sans boucle.

    Un relais retiré (`withdrawn`) ne compte pas : son successeur n'a rien reçu.
    """

    successor_of: dict[str, str] = {}
    for relation in relations:
        if relation.kind is not AgentRelationKind.HANDOFF or relation.outcome is RelationOutcome.WITHDRAWN:
            continue
        predecessor, successor = relation.endpoints()
        if successor in successor_of:
            raise RelationError(f"instance {successor} already received a handoff; a new context is a new instance",
                                code="handoff_successor_reused", field="participants")
        successor_of[successor] = predecessor
    for start in successor_of:
        seen = {start}
        current = successor_of.get(start)
        while current is not None:
            if current in seen:
                raise RelationError(f"handoff cycle through {current}", code="handoff_cycle", field="participants")
            seen.add(current)
            current = successor_of.get(current)
