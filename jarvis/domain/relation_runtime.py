"""Runtime des relations entre agents : demandes, autorité, relais préparé, résumés (Slice 06).

Handoff jarvis-organic-agent-orchestration. Le contrat des relations
(`agent_relations`) dit ce qu'une relation *est* ; ce module dit comment un
agent qui travaille en noue une, y publie, la clôt ou passe la main, sans
jamais imposer de déroulé (D12) :

- **voie d'entrée** : des outils MCP explicites (`RELATION_TOOLS`, serveur
  `jarvis-workspace`) qu'un agent appelle pour dire ce qu'il veut partager. Le
  hook `PreToolUse` y appose l'identité de l'appelant (`CALLER_STAMP_KEY` :
  l'`agent_id` du CLI, absent pour le cerveau), en écrasant toute valeur
  écrite par le modèle ; le champ n'est pas dans le schéma montré au modèle.
  Rien n'entre sur un tableau par une copie du flux du fournisseur (D13, D25) ;
- **autorité** (`check_open_authority`, `check_close_authority`) : seul le
  propriétaire courant de la mission (ou d'une mission ancêtre, D04) noue une
  communication ou un Adversary ; une QA est nouée par lui ou par le relecteur
  lui-même ; seul un participant publie ; le verdict d'une QA est celui du
  relecteur ; délégation et relais sont noués et clos par Core ;
- **relais** (`PendingHandoff`, `handoff_relation`) : le prédécesseur prépare
  un paquet complet, Core le valide et le garde ; le successeur, une instance
  **neuve** lancée avec `[relais]`, devient propriétaire dès sa déclaration,
  dans la même transaction que sa relation et son paquet : avant toute fin du
  prédécesseur, et jamais avec un paquet partiel ;
- **résumés** (`relation_summary`) : une ligne courte par relation, pour le
  contexte du cerveau et les réponses des outils ;
- **consignes** (`relations_brief`, `reviewer_brief`, `handoff_brief`) : ce
  que le hook appose, en bloc distinct, sur la consigne d'un Mission Owner, d'un
  relecteur QA ou d'un successeur de relais. Elles disent quand un outil sert,
  jamais un ordre ni un nombre de tours.

Contrat : `docs/agent-relations.md` §10. Module pur, sans E/S.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any

from jarvis.domain._checks import check_id, preview
from jarvis.domain.agent_relations import (
    MAX_PURPOSE_CHARS, AgentRelation, AgentRelationKind, HandoffPacket, ParticipantPosition, RelationError,
    RelationOutcome, RelationParticipant, check_collaboration_text,
)
from jarvis.domain.missions import AgentInstance, Mission

#: Champ que le hook appose sur l'entrée d'un outil de relation : `{"agent_id": str | None, "agent_type": ...}`.
CALLER_STAMP_KEY = "jarvis_caller"
#: Serveur qui porte les outils de relation, et leurs noms (`mcp__<serveur>__<outil>` côté CLI).
RELATION_SERVER = "jarvis-workspace"
RELATION_TOOLS = ("relation_open", "relation_post", "relation_read", "relation_close", "relation_handoff")
RELATION_TOOL_PREFIX = f"mcp__{RELATION_SERVER}__relation_"
#: Version de l'apposition (reprise QA N2) : le serveur refuse une identité sans elle ou d'une autre version, donc
#: un champ écrit par le modèle sous un CLI sans le hook à jour. Ce n'est pas une signature (voir le modèle de
#: menace, `docs/agent-relations.md` §10.7).
STAMP_VERSION = "relation-stamp@1"
#: Ce qui, dans une liste de participants, désigne l'agent qui appelle.
SELF_REF = "self"
#: Un agentId du CLI (`a2a69a1d01cba9282`) : ASCII court, jamais un chemin.
AGENT_REF = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")

#: Natures qu'un agent noue lui-même. Délégation (sous-mission `[mission]`) et relais (`relation_handoff`) : Core.
AGENT_OPENED_KINDS = frozenset({AgentRelationKind.COMMUNICATION, AgentRelationKind.ADVERSARY, AgentRelationKind.QA})
#: Natures que seul Core clôt : délégation (fin de la sous-mission), relais (transfert de propriété).
CORE_CLOSED_KINDS = frozenset({AgentRelationKind.DELEGATION, AgentRelationKind.HANDOFF})

RELATION_ID_PREFIX = "rel_"
MESSAGE_ID_PREFIX = "msg_"
HANDOFF_ID_PREFIX = "hof_"
#: Un relais préparé attend son successeur au plus ce délai ; ensuite il est oublié et la mission se clôt
#: normalement. Une borne de ressources, pas un protocole.
HANDOFF_TTL_S = 600
MAX_PENDING_HANDOFFS = 64
#: Après la clôture d'une mission, ses relations encore ouvertes acceptent messages et clôtures ce délai durant ;
#: ensuite refus `mission_closed`, et le balayage les retire (`withdrawn`). Reprise QA N4.
CLOSED_MISSION_GRACE_S = 600
#: Résumés de relation par instance dans le contexte du cerveau.
MAX_BRAIN_RELATIONS = 4
MAX_SUMMARY_CHARS = 120

KIND_LABELS = {
    AgentRelationKind.DELEGATION: "délégation",
    AgentRelationKind.COMMUNICATION: "communication",
    AgentRelationKind.ADVERSARY: "adversaire",
    AgentRelationKind.QA: "QA",
    AgentRelationKind.HANDOFF: "relais",
}
POSITION_LABELS = {
    ParticipantPosition.DELEGATOR: "délégant",
    ParticipantPosition.DELEGATEE: "délégataire",
    ParticipantPosition.MEMBER: "membre",
    ParticipantPosition.PRODUCER: "producteur",
    ParticipantPosition.REVIEWER: "relecteur",
    ParticipantPosition.REVIEWED: "relu",
    ParticipantPosition.PREDECESSOR: "prédécesseur",
    ParticipantPosition.SUCCESSOR: "successeur",
}

#: Ce que l'agent qui publie doit faire après un refus codé : la réponse de l'outil le lui rend tel quel.
NEXT_STEPS: Mapping[str, str] = {
    "relation_caller_unstamped": "l'identité de l'appelant n'a pas été apposée par JARVIS (CLI lancé sans le hook à "
                                 "jour) : l'utilisateur doit relancer JARVIS",
    "relation_caller_not_instance": "seul un sous-agent retenu par JARVIS noue ou alimente une relation ; le cerveau "
                                    "peut seulement lire (relation_read)",
    "relation_agent_unknown": "utilisez l'agentId exact que l'outil Agent a rendu (« agentId: … »), ou « self »",
    "relation_agent_not_recorded": "cet agent n'est pas (encore) retenu par JARVIS : un agent éphémère n'entre dans "
                                   "aucune relation ; sinon réessayez dans quelques secondes",
    "relation_not_owner": "seul le Mission Owner courant de la mission (ou d'une mission parente) noue cette "
                          "relation : demandez-le-lui dans votre compte rendu",
    "relation_no_mission": "vous ne travaillez pour aucune mission retenue : une relation se noue au sein d'une mission",
    "relation_kind_not_opened_by_agent": "une délégation se noue en lançant un agent avec [mission] ; un relais avec "
                                         "relation_handoff puis [relais]",
    "relation_closed_by_core": "cette relation se clôt d'elle-même (fin de la sous-mission, transfert de propriété)",
    "relation_not_participant": "seuls les participants publient ; pour parler à d'autres agents, ouvrez une "
                                "communication avec eux",
    "relation_closed": "la relation est close : son tableau n'accepte plus rien ; nouez-en une autre si besoin",
    "relation_unknown": "vérifiez l'identifiant rel_… rendu par relation_open ou relation_read",
    "relation_private_content": "publiez le message explicite destiné aux autres, jamais votre raisonnement ; "
                                "nommez une balise sans chevrons et retirez tout champ privé d'un JSON",
    "relation_raw_payload": "publiez un texte lisible, pas une charge brute",
    "relation_is_not_a_protocol": "une relation n'a ni tours ni phases : retirez ce champ",
    "relation_participants_invalid": "QA : un relecteur et un relu ; Adversary et communication : au moins deux pairs",
    "relation_participant_duplicate": "chaque agent n'apparaît qu'une fois",
    "relation_outcome_invalid": "choisissez une issue permise pour cette nature (voir la description de "
                                "relation_close) ; un vainqueur est l'un des producteurs",
    "qa_reviewer_role": "le relecteur d'une QA a le rôle qa : lancez-le avec [code] [qa] …",
    "adversary_producer_is_reviewer": "un relecteur ne concourt pas : demandez une QA à la place",
    "relation_mission_mismatch": "les participants travaillent pour cette mission ou l'une de ses sous-missions",
    "ephemeral_relation_participant": "un agent éphémère ne laisse aucune trace : relancez-le sans [éphémère]",
    "relation_participant_missing": "cet agent n'est pas retenu par JARVIS : réessayez dans quelques secondes",
    "mission_closed": "la mission est close : elle ne reçoit plus de nouvelle relation, et ses relations ouvertes "
                      "ne reçoivent plus rien 10 min après la clôture ; rendez ce que vous aviez à dire dans votre "
                      "compte rendu",
    "relation_read_not_allowed": "seuls les participants de la relation et les Mission Owners de sa mission (ou d'une "
                                 "mission parente) la lisent ; demandez-la à votre Mission Owner",
    "handoff_not_owner": "seul le Mission Owner courant passe la main",
    "handoff_fan_out": "vous avez déjà passé la main une fois : la propriété ne se transfère qu'une fois",
    "handoff_packet_incomplete": "le paquet de relais exige objectif, travail fait et action suivante recommandée",
    "relation_board_full": "résumez le fil et ouvrez une nouvelle relation",
    "relation_reply_invalid": "reply_to_message_id est le message_id (msg_…) d'un message antérieur de ce même "
                              "tableau, rendu par relation_read ; le rang seq n'en est pas un",
    "relation_message_type_invalid": "handoff_note n'existe que sur un relais",
}


def actionable(code: str | None, message: str) -> str:
    """Le message d'un refus suivi de ce qu'il faut corriger, quand le code a une suite connue."""

    hint = NEXT_STEPS.get(code or "")
    return f"{message.rstrip('. ')}. À faire : {hint}." if hint else message


def _fail(message: str, code: str, field: str | None = None) -> RelationError:
    return RelationError(message, code=code, field=field)


# ------------------------------------------------------------------ identité de l'appelant


@dataclass(frozen=True, slots=True)
class CallerStamp:
    """L'identité qu'a apposée le hook : `agent_id` du CLI pour un sous-agent, `None` pour le cerveau."""

    agent_id: str | None
    agent_type: str | None = None


def read_caller_stamp(arguments: Mapping[str, Any]) -> CallerStamp:
    """L'identité apposée par le hook sur l'entrée d'un outil de relation ; refus actionnable si absente.

    Un champ absent veut dire que le hook n'a pas tourné (CLI lancé avec un ancien réglage) : rien n'est deviné.
    """

    stamp = arguments.get(CALLER_STAMP_KEY)
    if not isinstance(stamp, Mapping) or stamp.get("stamped") is not True:
        raise _fail("caller identity missing", "relation_caller_unstamped", CALLER_STAMP_KEY)
    if stamp.get("hook") != STAMP_VERSION:
        raise _fail(f"caller identity was not stamped by the current hook ({preview(stamp.get('hook'))})",
                    "relation_caller_unstamped", CALLER_STAMP_KEY)
    agent_id = stamp.get("agent_id")
    agent_type = stamp.get("agent_type")
    if agent_id is not None and (not isinstance(agent_id, str) or not AGENT_REF.fullmatch(agent_id)):
        raise _fail(f"caller agent id {preview(agent_id)} is malformed", "relation_caller_unstamped",
                    CALLER_STAMP_KEY)
    return CallerStamp(agent_id=agent_id, agent_type=agent_type if isinstance(agent_type, str) else None)


def caller_stamp(event: Mapping[str, Any]) -> dict[str, Any]:
    """Le champ que le hook appose, à partir de son événement `PreToolUse` (jamais de l'entrée du modèle)."""

    agent_id = event.get("agent_id")
    agent_type = event.get("agent_type")
    return {
        "stamped": True,
        "hook": STAMP_VERSION,
        "agent_id": agent_id if isinstance(agent_id, str) and AGENT_REF.fullmatch(agent_id) else None,
        "agent_type": agent_type if isinstance(agent_type, str) and len(agent_type) <= 64 else None,
    }


def is_relation_tool(tool_name: object) -> bool:
    return isinstance(tool_name, str) and tool_name.startswith(RELATION_TOOL_PREFIX) \
        and tool_name[len(f"mcp__{RELATION_SERVER}__"):] in RELATION_TOOLS


def check_agent_ref(name: str, value: object) -> str:
    """Une référence d'agent reçue d'un outil : un agentId du CLI ou `self`."""

    if not isinstance(value, str) or not (value == SELF_REF or AGENT_REF.fullmatch(value)):
        raise _fail(f"{name} must be an agentId returned by the Agent tool or \"self\", got {preview(value)}",
                    "relation_agent_unknown", name)
    return value


# ------------------------------------------------------------------ autorité


def current_owner_of_scope(caller: AgentInstance, mission: Mission, missions: Mapping[str, Mission]) -> bool:
    """`caller` est-il le propriétaire courant de `mission` ou d'une mission ancêtre (supervision, D04) ?"""

    current, seen = mission, 0
    while current is not None and seen <= 16:
        if current.owner_instance_id == caller.instance_id:
            return True
        current = missions.get(current.parent_mission_id) if current.parent_mission_id else None
        seen += 1
    return False


def check_open_authority(caller: AgentInstance, relation: AgentRelation, missions: Mapping[str, Mission]) -> None:
    """Qui peut nouer `relation` (voir le docstring du module). Lève une `RelationError` codée."""

    if relation.kind not in AGENT_OPENED_KINDS:
        raise _fail(f"a {relation.kind.value} relation is opened by Core", "relation_kind_not_opened_by_agent", "kind")
    mission = missions.get(relation.mission_id)
    if mission is None:
        raise _fail(f"mission {relation.mission_id} is unknown", "relation_no_mission", "mission_id")
    if mission.status.is_closed:
        raise _fail(f"mission {relation.mission_id} is {mission.status.value}", "mission_closed", "mission_id")
    if current_owner_of_scope(caller, mission, missions):
        return
    if relation.kind is AgentRelationKind.QA and relation.at(ParticipantPosition.REVIEWER) == (caller.instance_id,):
        return  # le relecteur ouvre lui-même la revue qu'on lui a confiée
    raise _fail(f"instance {caller.instance_id} is not the current mission owner of {relation.mission_id}",
                "relation_not_owner", "caller")


def check_close_authority(caller: AgentInstance | None, relation: AgentRelation, outcome: RelationOutcome,
                          missions: Mapping[str, Mission]) -> None:
    """Qui peut clore `relation` par `outcome`. Le domaine exige en plus le relecteur pour un verdict QA."""

    if relation.kind in CORE_CLOSED_KINDS:
        raise _fail(f"a {relation.kind.value} relation is closed by Core", "relation_closed_by_core", "relation_id")
    if caller is None:
        raise _fail("the brain does not close a relation", "relation_caller_not_instance", "caller")
    if relation.kind is AgentRelationKind.QA and outcome is not RelationOutcome.WITHDRAWN:
        return  # `AgentRelation.close` exige que ce soit le relecteur (`closed_by_instance_id`)
    mission = missions.get(relation.mission_id)
    owner = mission is not None and current_owner_of_scope(caller, mission, missions)
    if owner or caller.instance_id == relation.created_by_instance_id:
        return
    if relation.kind is AgentRelationKind.COMMUNICATION and caller.instance_id in relation.participant_ids:
        return  # un membre peut dire que la coordination est finie
    raise _fail(f"instance {caller.instance_id} cannot close relation {relation.relation_id}: only its creator or the "
                "current mission owner", "relation_not_owner", "caller")


# ------------------------------------------------------------------ relations nouées par Core


def delegation_relation_id(sub_mission_id: str) -> str:
    """Id déterministe de la délégation d'une sous-mission : un rejeu de la déclaration la retrouve identique."""

    return f"{RELATION_ID_PREFIX}dlg_{sub_mission_id}"


def delegation_relation(*, delegator: AgentInstance, delegatee: AgentInstance, sub_mission: Mission,
                        at: datetime) -> AgentRelation:
    """La délégation qu'aligne `[mission]` : le délégant (l'appelant) confie la sous-mission au délégataire."""

    purpose = sub_mission.objective.strip().splitlines()[0][:MAX_PURPOSE_CHARS] or "Sous-mission"
    return AgentRelation(
        relation_id=delegation_relation_id(sub_mission.mission_id),
        kind=AgentRelationKind.DELEGATION,
        mission_id=sub_mission.parent_mission_id or "",
        participants=(RelationParticipant(delegator.instance_id, ParticipantPosition.DELEGATOR),
                      RelationParticipant(delegatee.instance_id, ParticipantPosition.DELEGATEE)),
        purpose=purpose,
        created_at=max(at, delegatee.created_at),
        created_by_instance_id=delegator.instance_id,
        sub_mission_id=sub_mission.mission_id,
    )


# ------------------------------------------------------------------ relais


@dataclass(frozen=True, slots=True)
class PendingHandoff:
    """Un relais préparé par le propriétaire courant, en attente de son successeur (mémoire de Core seulement).

    Rien de durable n'est écrit avant que le successeur existe : un successeur ne peut donc jamais se prévaloir
    d'un paquet partiel, et un relais jamais lancé ne laisse aucune trace (D15).
    """

    handoff_id: str
    mission_id: str
    predecessor_instance_id: str
    purpose: str
    packet: HandoffPacket
    prepared_at: datetime

    def __post_init__(self) -> None:
        for name in ("handoff_id", "mission_id", "predecessor_instance_id"):
            try:
                check_id(name, getattr(self, name), required=True)
            except (TypeError, ValueError) as exc:
                raise _fail(f"{name}: {exc}", "relation_invalid", name) from exc
        check_collaboration_text("purpose", self.purpose, MAX_PURPOSE_CHARS)
        if not isinstance(self.packet, HandoffPacket):
            raise _fail("packet must be a HandoffPacket", "handoff_packet_incomplete", "packet")

    @property
    def expires_at(self) -> datetime:
        return self.prepared_at + timedelta(seconds=HANDOFF_TTL_S)

    def expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def to_payload(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "mission_id": self.mission_id,
            "predecessor_instance_id": self.predecessor_instance_id,
            "purpose": self.purpose,
            "packet": self.packet.to_payload(),
            "prepared_at": self.prepared_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


def check_handoff_preparation(caller: AgentInstance, mission: Mission | None,
                              relations: Sequence[AgentRelation]) -> None:
    """Le prédécesseur peut-il préparer un relais ? Propriétaire courant d'une mission ouverte, une seule fois."""

    if mission is None or caller.mission_id is None:
        raise _fail("you work for no recorded mission", "relation_no_mission", "caller")
    if mission.status.is_closed:
        raise _fail(f"mission {mission.mission_id} is {mission.status.value}", "mission_closed", "mission_id")
    if mission.owner_instance_id != caller.instance_id:
        raise _fail(f"instance {caller.instance_id} is not the current owner of mission {mission.mission_id}",
                    "handoff_not_owner", "caller")
    for relation in relations:
        if (relation.kind is AgentRelationKind.HANDOFF and relation.outcome is not RelationOutcome.WITHDRAWN
                and relation.at(ParticipantPosition.PREDECESSOR) == (caller.instance_id,)):
            raise _fail(f"instance {caller.instance_id} already handed off ({relation.relation_id})",
                        "handoff_fan_out", "caller")


def handoff_relation(pending: PendingHandoff, *, relation_id: str, successor: AgentInstance,
                     at: datetime) -> AgentRelation:
    """La relation de relais écrite avec le successeur, dans la même transaction que le transfert."""

    if successor.mission_id != pending.mission_id or not successor.mission_owner:
        raise _fail("the successor carries the handed-off mission as its owner", "handoff_mission_mismatch",
                    "successor")
    return AgentRelation(
        relation_id=relation_id,
        kind=AgentRelationKind.HANDOFF,
        mission_id=pending.mission_id,
        participants=(RelationParticipant(pending.predecessor_instance_id, ParticipantPosition.PREDECESSOR),
                      RelationParticipant(successor.instance_id, ParticipantPosition.SUCCESSOR)),
        purpose=pending.purpose,
        created_at=max(at, successor.created_at),
        created_by_instance_id=pending.predecessor_instance_id,
        handoff=pending.packet,
    )


# ------------------------------------------------------------------ résumés


def relation_summary(relation: AgentRelation, instance_id: str | None = None) -> str:
    """Une ligne : nature, id, position de `instance_id`, état. Pour le contexte du cerveau et les outils."""

    position = next((p.position for p in relation.participants if p.instance_id == instance_id), None)
    who = f" ({POSITION_LABELS[position]})" if position is not None else ""
    state = "ouverte" if relation.is_open else f"close : {relation.outcome.value if relation.outcome else '?'}"
    return f"{KIND_LABELS[relation.kind]}{who} {relation.relation_id} {state}"[:MAX_SUMMARY_CHARS]


# ------------------------------------------------------------------ consignes apposées par le hook


RELATIONS_MARK = "RELATIONS ENTRE AGENTS (JARVIS)"
REVIEWER_MARK = "RELATION QA (JARVIS)"
HANDOFF_MARK = "RELAIS DE MISSION (JARVIS)"


def _tool(name: str) -> str:
    return f"mcp__{RELATION_SERVER}__{name}"


def relations_brief() -> str:
    """Bloc apposé après la responsabilité de mission d'un Mission Owner. Une boîte à outils, pas un ordre."""

    return "\n".join((
        RELATIONS_MARK,
        "Des outils explicites nouent une relation entre agents quand elle sert la mission ; aucune n'est obligatoire "
        "et aucune n'impose de tours. Chargez-les avec ToolSearch au besoin. Un agent se désigne par l'agentId que "
        "rend l'outil Agent (« agentId: … ») ; « self » vous désigne.",
        f"- Second regard sur un résultat : lancez un relecteur ([code] [qa] …) en lui donnant l'agentId du travail "
        f"à relire ; il ouvre la relation QA ({_tool('relation_open')}, kind qa) et rend son verdict "
        f"({_tool('relation_close')}).",
        "- Approches concurrentes : lancez au moins deux producteurs sur des approches différentes, puis "
        "relation_open (kind adversary, producteurs = leurs agentId) ; faites-les défendre leur travail l'un face à "
        "l'autre et tranchez par relation_close (winner, synthesis, unresolved, escalated).",
        f"- Coordination explicite : relation_open (kind communication, membres) ; chacun publie ses messages "
        f"délibérés avec {_tool('relation_post')} et lit le fil avec {_tool('relation_read')}. SendMessage reste le "
        "moyen de joindre un agent ; le tableau garde ce qui a été dit, jamais un raisonnement privé. Si vous "
        "comptez faire publier un agent sur un tableau, dites-le dès sa consigne : une demande reçue plus tard par "
        "SendMessage peut être prise pour celle d'un tiers.",
        f"- Contexte neuf ou autre spécialité pour continuer : préparez le paquet avec {_tool('relation_handoff')}, "
        "puis lancez le successeur au premier plan avec [relais] après son rôle ; la mission lui appartient dès son "
        "lancement et vous recevez son compte rendu.",
        "Un refus dit quoi corriger ; ce que vous n'avez pas noué n'existe pas.",
    ))


def reviewer_brief() -> str:
    """Bloc apposé sur la consigne d'un relecteur QA : la revue est asymétrique (D11)."""

    return "\n".join((
        REVIEWER_MARK,
        "Vous relisez le travail d'un autre agent ; vous ne produisez pas une solution concurrente.",
        f"Si votre consigne donne l'agentId du travail relu et aucune relation QA ouverte (rel_…), ouvrez-la : "
        f"{_tool('relation_open')} (kind qa, reviewer « self », reviewed = cet agentId, target_refs utiles). "
        f"Publiez vos constats explicites ({_tool('relation_post')}, type critique), puis rendez votre verdict avec "
        f"{_tool('relation_close')} : approved, findings, correction_requested ou rejected, avec un résumé.",
        "Sans agentId du travail relu, faites la relecture et dites dans votre compte rendu qu'aucune relation n'a été "
        "ouverte.",
    ))


def _items(values: Sequence[str]) -> str:
    return "\n".join(f"  - {value}" for value in values) if values else "  (aucun)"


def handoff_brief(*, handoff_id: str, mission_id: str, purpose: str, packet: HandoffPacket) -> str:
    """Bloc apposé sur la consigne du successeur : le paquet complet, explicite, borné (D14)."""

    refs = ", ".join(packet.artifact_refs) or "(aucun)"
    evidence = ", ".join(packet.evidence_refs) or "(aucune)"
    return "\n".join((
        HANDOFF_MARK,
        f"Vous reprenez la mission {mission_id} d'une instance précédente (relais {handoff_id}) : vous en êtes "
        "désormais le Mission Owner. Repartez de ce paquet ; ne refaites pas ce qui est fait, sauf preuve contraire.",
        f"Objet du relais : {purpose}",
        f"Objectif : {packet.objective}",
        f"Travail fait : {packet.completed_work}",
        "Décisions clés :",
        _items(packet.key_decisions),
        "Points ouverts :",
        _items(packet.open_points),
        f"Artefacts : {refs}",
        f"Preuves : {evidence}",
        f"Action suivante recommandée : {packet.recommended_next_action}",
    ))
