"""Port du décideur du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 5, lacune G8).

Contrat : `docs/tool-brain-contracts.md` §13. Le décideur est **un modèle remplaçable** : il reçoit une
requête bornée (déclencheur, perception, manifeste, intentions, lectures déjà faites) et rend un **plan
structuré** : des lectures ciblées à faire (`inspections`) et/ou des appels d'interface proposés (`actions`).
Jamais du code, jamais une mutation : il n'a aucun accès aux services. Le runtime (`tool_brain_runtime`)
valide chaque proposition (`validate_call`) et, en mode `shadow`, n'exécute rien.

Aucun format de fournisseur ici : une réponse de modèle est ramenée à `ToolBrainReply` par
`reply_from_payload` (codec strict, borné), les adaptateurs ne font que du texte -> JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

#: Codes stables d'un appel de décideur raté (`DeciderError.code`).
DECIDER_UNAVAILABLE = "tool_brain_decider_unavailable"
DECIDER_TIMEOUT = "tool_brain_decider_timeout"
DECIDER_FAILED = "tool_brain_decider_failed"
DECIDER_INVALID_OUTPUT = "tool_brain_decider_invalid_output"

MAX_INSPECTIONS_PER_REPLY = 3
MAX_ACTIONS_PER_REPLY = 6
MAX_QUEUE_OPS_PER_REPLY = 6
QUEUE_OPS = ("cancel", "reprioritize", "reschedule")
MAX_REASON_CHARS = 200
MAX_RATIONALE_CHARS = 300
MAX_ARGUMENT_BYTES = 2048


class DeciderError(RuntimeError):
    """Appel au décideur raté ; `code` stable, `detail` = la cause dite par le fournisseur (bornée)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail[:300]}" if detail else code)
        self.code = code
        self.detail = detail[:300]


@dataclass(frozen=True, slots=True)
class InspectionRequest:
    """Une lecture ciblée voulue (`INSPECTION_READS`) ; `id` absent pour `get_queue_state`."""

    read: str
    id: str | None = None


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """Un appel d'outil d'interface **proposé** : jamais exécuté par le décideur."""

    server: str
    tool: str
    arguments: Mapping[str, Any]
    reason: str = ""
    #: Intention de Jarvis que cette action sert (`intent_id`), si le décideur la nomme.
    intent_id: str | None = None
    #: S6 : quand agir (`{type: now|speech_chunk|speech|intent|event|delay, ...}`, décodé par la file ; absent = tout de
    #: suite), priorité (`high|normal|low`), actions en attente remplacées, code court de la raison. Le port ne juge pas.
    trigger: Mapping[str, Any] | None = None
    priority: str | None = None
    replaces: tuple[str, ...] = ()
    reason_code: str = ""


@dataclass(frozen=True, slots=True)
class QueueOp:
    """Opération sur la file d'actions (S6) : `cancel`, `reprioritize` ou `reschedule` (`replace` = action + `replaces`)."""

    op: str
    action_id: str
    priority: str | None = None
    trigger: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ToolBrainRequest:
    decision_id: str
    #: Résumé du déclencheur (classes de réveil, raisons, ids de corrélation) ; jamais de contenu parlé.
    trigger: Mapping[str, Any]
    perception: Mapping[str, Any]
    manifest: Mapping[str, Any]
    intents: tuple[Mapping[str, Any], ...] = ()
    #: Résultats des lectures demandées aux tours précédents de cette décision.
    inspections: tuple[Mapping[str, Any], ...] = ()
    round: int = 0
    #: Lectures encore permises (0 : le décideur doit conclure).
    inspections_left: int = 0


@dataclass(frozen=True, slots=True)
class ToolBrainReply:
    inspections: tuple[InspectionRequest, ...] = ()
    actions: tuple[ProposedAction, ...] = ()
    rationale: str = ""
    model: str = ""
    cost_usd: float | None = None
    duration_ms: int | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    #: S6 : annulations / changements de priorité / report d'actions déjà en file (jamais exécutés par le décideur).
    queue_ops: tuple[QueueOp, ...] = ()


class ToolBrainDecider(Protocol):
    """Un tour borné, sans outil. Lève `DeciderError` ; l'annulation de la tâche l'interrompt."""

    #: Nom lisible (journal, historique) ; jamais une clé.
    name: str

    async def decide(self, request: ToolBrainRequest, *, timeout_s: float) -> ToolBrainReply: ...


def _text(value: object, limit: int, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DeciderError(DECIDER_INVALID_OUTPUT, f"{what} must be a string")
    return " ".join(value.split())[:limit]


def reply_from_payload(payload: object, *, model: str = "", cost_usd: float | None = None,
                       duration_ms: int | None = None, usage: Mapping[str, Any] | None = None) -> ToolBrainReply:
    """Codec strict d'une réponse JSON de décideur : `{inspections?, actions?, rationale?}`.

    Champs inconnus, formes inattendues ou dépassement de borne : `DeciderError(DECIDER_INVALID_OUTPUT)`.
    La validité **sémantique** (ids légaux, outil d'interface) n'est pas jugée ici : c'est `validate_call`.
    """

    if not isinstance(payload, dict):
        raise DeciderError(DECIDER_INVALID_OUTPUT, "the plan must be a JSON object")
    unknown = sorted(str(key)[:40] for key in set(payload) - {"inspections", "actions", "rationale", "queue_ops"})
    if unknown:
        raise DeciderError(DECIDER_INVALID_OUTPUT, f"unknown plan fields: {unknown[:5]}")
    raw_inspections = payload.get("inspections") or []
    raw_actions = payload.get("actions") or []
    raw_ops = payload.get("queue_ops") or []
    if not isinstance(raw_inspections, list) or not isinstance(raw_actions, list) or not isinstance(raw_ops, list):
        raise DeciderError(DECIDER_INVALID_OUTPUT, "inspections, actions and queue_ops must be lists")
    if (len(raw_inspections) > MAX_INSPECTIONS_PER_REPLY or len(raw_actions) > MAX_ACTIONS_PER_REPLY
            or len(raw_ops) > MAX_QUEUE_OPS_PER_REPLY):
        raise DeciderError(DECIDER_INVALID_OUTPUT, "too many inspections or actions in one plan")
    inspections: list[InspectionRequest] = []
    for item in raw_inspections:
        if not isinstance(item, dict) or set(item) - {"read", "id"} or not isinstance(item.get("read"), str):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "an inspection is {read, id?}")
        identifier = item.get("id")
        if identifier is not None and not isinstance(identifier, str):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "inspection id must be a string")
        inspections.append(InspectionRequest(item["read"][:60], identifier[:120] if identifier else None))
    actions: list[ProposedAction] = []
    for item in raw_actions:
        if (not isinstance(item, dict)
                or set(item) - {"server", "tool", "arguments", "reason", "intent_id", "trigger", "priority",
                                "replaces", "reason_code"}
                or not isinstance(item.get("server"), str) or not isinstance(item.get("tool"), str)):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "an action is {server, tool, arguments, reason?, intent_id?, "
                                                       "trigger?, priority?, replaces?, reason_code?}")
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict) or not all(isinstance(key, str) for key in arguments):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "action arguments must be an object")
        if len(repr(arguments).encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise DeciderError(DECIDER_INVALID_OUTPUT, "action arguments are too large")
        intent_id = item.get("intent_id")
        if intent_id is not None and not isinstance(intent_id, str):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "intent_id must be a string")
        trigger = item.get("trigger")
        if trigger is not None and (not isinstance(trigger, dict) or len(repr(trigger)) > 400):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "trigger must be a small object")
        priority = item.get("priority")
        if priority is not None and not isinstance(priority, str):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "priority must be a string")
        replaces = item.get("replaces") or []
        if not isinstance(replaces, list) or len(replaces) > 4 or not all(isinstance(old, str) for old in replaces):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "replaces must be a short list of action ids")
        actions.append(ProposedAction(item["server"][:60], item["tool"][:80], dict(arguments),
                                      _text(item.get("reason"), MAX_REASON_CHARS, "reason"),
                                      intent_id[:80] if intent_id else None,
                                      dict(trigger) if trigger else None, priority[:12] if priority else None,
                                      tuple(old[:120] for old in replaces),
                                      _text(item.get("reason_code"), 40, "reason_code")))
    queue_ops: list[QueueOp] = []
    for item in raw_ops:
        if (not isinstance(item, dict) or set(item) - {"op", "action_id", "priority", "trigger"}
                or item.get("op") not in QUEUE_OPS or not isinstance(item.get("action_id"), str)):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "a queue op is {op: cancel|reprioritize|reschedule, action_id, "
                                                       "priority?, trigger?}")
        trigger, priority = item.get("trigger"), item.get("priority")
        if (trigger is not None and (not isinstance(trigger, dict) or len(repr(trigger)) > 400))                 or (priority is not None and not isinstance(priority, str)):
            raise DeciderError(DECIDER_INVALID_OUTPUT, "queue op priority/trigger have the wrong shape")
        queue_ops.append(QueueOp(item["op"], item["action_id"][:120], priority[:12] if priority else None,
                                 dict(trigger) if trigger is not None else None))
    return ToolBrainReply(tuple(inspections), tuple(actions), _text(payload.get("rationale"), MAX_RATIONALE_CHARS,
                                                                    "rationale"),
                          model=model, cost_usd=cost_usd, duration_ms=duration_ms, usage=dict(usage or {}),
                          queue_ops=tuple(queue_ops))


__all__ = [
    "DECIDER_FAILED", "DECIDER_INVALID_OUTPUT", "DECIDER_TIMEOUT", "DECIDER_UNAVAILABLE", "DeciderError",
    "InspectionRequest", "MAX_ACTIONS_PER_REPLY", "MAX_INSPECTIONS_PER_REPLY", "MAX_QUEUE_OPS_PER_REPLY", "ProposedAction",
    "QUEUE_OPS", "QueueOp", "ToolBrainDecider",
    "ToolBrainReply", "ToolBrainRequest", "reply_from_payload",
]
