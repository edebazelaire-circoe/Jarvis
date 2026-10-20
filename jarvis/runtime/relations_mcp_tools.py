"""Outils MCP de relation entre agents, sur le serveur `jarvis-workspace` (Slice 06).

Handoff jarvis-organic-agent-orchestration. C'est **la** voie par laquelle un
agent noue une relation, publie sur son tableau, la lit, la clôt ou passe la
main (`relation_runtime.RELATION_TOOLS`) — jamais une copie du flux du
fournisseur (D13, D25). Pourquoi des outils MCP d'un serveur existant :

- un sous-agent du CLI hérite des serveurs MCP du cerveau (constaté en Slice 05
  pour `jarvis-tools`) : `jarvis-workspace` est déclaré à chaque lancement,
  sans interrupteur ;
- l'appel est synchrone : le refus codé de Core revient à l'agent qui publie,
  avec ce qu'il doit corriger (un fait déposé par le hook ne le pourrait pas) ;
- l'identité de l'appelant n'est jamais un argument du modèle : le hook
  `PreToolUse` (court, hors ligne) appose `relation_runtime.CALLER_STAMP_KEY`
  (l'`agent_id` du CLI) sur l'entrée, champ absent du schéma montré ;
  `CURRENT_CALLER` le porte jusqu'à l'outil.

Façade, jamais propriétaire : chaque outil appelle les routes
`/api/missions/relations*` et `/api/missions/handoffs` du Control Center
(`relation_relay.py`), qui résout les agentId et relaie vers Core
(`MissionHistoryService`). Contrat : `docs/agent-relations.md` §10,
`docs/mcp/tool-contract.md`.
"""

# Pas de `from __future__ import annotations` : FastMCP lit les annotations des outils définis dans `register`, à
# l'exécution (même règle que `workspace_mcp`).
import contextvars
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import Field

from jarvis.domain.agent_relations import RelationError
from jarvis.domain.relation_runtime import CALLER_STAMP_KEY, CallerStamp, actionable, read_caller_stamp

#: L'identité apposée par le hook, retirée de l'entrée par le serveur avant la validation stricte des arguments.
CURRENT_CALLER: contextvars.ContextVar[Any] = contextvars.ContextVar("jarvis_relation_caller", default=None)
RELATIONS_ROUTE = "/api/missions/relations"
HANDOFFS_ROUTE = "/api/missions/handoffs"
#: Le Control Center attend Core 8 s (`relation_relay.DEFAULT_TIMEOUT_S`), plus la remise des déclarations : un
#: peu plus.
WRITE_TIMEOUT_S = 15.0
READ_TIMEOUT_S = 10.0
MAX_READ = 50


def _q(value: str) -> str:
    return quote(value, safe="")


class RelationTools:
    """La logique des outils de relation, sans FastMCP. `call` : `BoardTools.call` (refus codés, journalisés)."""

    def __init__(self, call: Callable[..., Any], error: Callable[[str, str], Exception],
                 emit: Callable[..., None] | None = None) -> None:
        self._call = call
        self._error = error
        #: Journal du serveur (`WorkspaceTools._emit`) : chaque refus local est consigné, jamais silencieux.
        self._emit = emit

    def _refused(self, tool: str, code: str, message: str) -> Exception:
        if self._emit is not None:
            self._emit("relation.tool_failed", f"{tool} : {code}", level="warning", data={"tool": tool, "code": code})
        return self._error(code, message)

    def _caller(self, tool: str) -> CallerStamp:
        try:
            return read_caller_stamp({CALLER_STAMP_KEY: CURRENT_CALLER.get()})
        except RelationError as exc:
            raise self._refused(tool, exc.code, actionable(
                exc.code, "Identité de l'appelant absente : rien n'a été envoyé")) from None

    def _invalid(self, message: str) -> Exception:
        return self._refused("relation_open", "relation_arguments_invalid", f"{message} Rien n'a été envoyé.")

    async def _send(self, tool: str, method: str, route: str, *, payload: Any = None,
                    params: dict[str, str] | None = None, timeout_s: float = WRITE_TIMEOUT_S) -> dict[str, Any]:
        _, body = await self._call(tool, method, route, payload=payload, params=params, timeout_s=timeout_s)
        return body

    @staticmethod
    def _participants(relation: dict[str, Any], agents: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"agent_id": agents.get(item.get("instance_id")), "instance_id": item.get("instance_id"),
                 "position": item.get("position")} for item in relation.get("participants") or ()]

    @staticmethod
    def _compact(relation: dict[str, Any]) -> dict[str, Any]:
        keys = ("relation_id", "kind", "mission_id", "purpose", "status", "outcome", "outcome_summary",
                "winner_instance_id", "closed_by_instance_id", "created_by_instance_id", "target_refs")
        return {key: relation.get(key) for key in keys if relation.get(key) not in (None, "", [])}

    async def open(self, *, kind: str, purpose: str, reviewer: str | None = None, reviewed: str | None = None,
                   producers: Sequence[str] = (), members: Sequence[str] = (),
                   target_refs: Sequence[str] = ()) -> dict[str, Any]:
        caller = self._caller("relation_open")
        given = {"reviewer": reviewer, "reviewed": reviewed, "producers": producers, "members": members}
        wanted = {"qa": ("reviewer", "reviewed"), "adversary": ("producers",), "communication": ("members",)}
        extra = [name for name, value in given.items() if value and name not in wanted.get(kind, given)]
        if extra:
            # Le nom exact du champ en trop : constaté en bac à sable, un refus vague fait réessayer à l'aveugle.
            raise self._invalid(f"Retirez {', '.join(extra)} : une relation {kind} n'a que "
                                f"{' et '.join(wanted[kind])}.")
        if kind == "qa":
            if not reviewer or not reviewed:
                raise self._invalid("Une QA nomme reviewer (rôle qa, souvent « self ») et reviewed (agentId du "
                                    "travail relu).")
            participants = [(reviewer, "reviewer"), (reviewed, "reviewed")]
        elif kind == "adversary":
            if len(producers) < 2:
                raise self._invalid("Un Adversary nomme au moins deux producers (agentId des producteurs qui "
                                    "concourent) ; un relecteur est une QA.")
            participants = [(agent, "producer") for agent in producers]
        elif kind == "communication":
            if len(members) < 2:
                raise self._invalid("Une communication nomme au moins deux members (« self » compris si vous en "
                                    "êtes).")
            participants = [(agent, "member") for agent in members]
        else:
            raise self._invalid("kind vaut qa, adversary ou communication ; une délégation se noue par [mission], "
                                "un relais par relation_handoff.")
        if target_refs and kind != "qa":
            raise self._invalid("target_refs n'existe que pour une QA.")
        body = await self._send("relation_open", "POST", RELATIONS_ROUTE, payload={
            "caller_agent_id": caller.agent_id, "kind": kind, "purpose": purpose, "target_refs": list(target_refs),
            "participants": [{"agent": agent, "position": position} for agent, position in participants]})
        relation = body.get("relation") or {}
        return {**self._compact(relation), "participants": self._participants(relation, body.get("agents") or {}),
                "next": "Publiez avec relation_post (relation_id), lisez avec relation_read, closez avec "
                        "relation_close quand l'issue est connue ; aucun tour n'est imposé."}

    async def post(self, *, relation_id: str, text: str, type: str = "message", audience: Sequence[str] = (),
                   artifact_refs: Sequence[str] = (), reply_to_message_id: str | None = None) -> dict[str, Any]:
        caller = self._caller("relation_post")
        body = await self._send("relation_post", "POST", f"{RELATIONS_ROUTE}/{_q(relation_id)}/messages", payload={
            "caller_agent_id": caller.agent_id, "type": type, "text": text, "audience": list(audience),
            "artifact_refs": list(artifact_refs), "reply_to_message_id": reply_to_message_id})
        message = body.get("message") or {}
        return {"relation_id": relation_id, "seq": body.get("seq"), "message_id": message.get("message_id"),
                "type": message.get("type"), "published": True}

    async def read(self, *, relation_id: str, after: int = 0, limit: int = 20) -> dict[str, Any]:
        self._caller("relation_read")  # lecture permise au cerveau aussi ; l'identité doit tout de même avoir été apposée
        body = await self._send("relation_read", "GET", f"{RELATIONS_ROUTE}/{_q(relation_id)}",
                                params={"after": str(after), "limit": str(min(limit, MAX_READ))},
                                timeout_s=READ_TIMEOUT_S)
        relation = body.get("relation") or {}
        agents = body.get("agents") or {}
        roles = {view.get("instance_id"): view.get("role_id") for view in body.get("participants") or ()
                 if isinstance(view, dict)}
        status = {view.get("instance_id"): view.get("work_status") for view in body.get("participants") or ()
                  if isinstance(view, dict)}
        messages = [{"seq": item.get("seq"), "message_id": item.get("message_id"), "author_agent_id": agents.get(item.get("author_instance_id")),
                     "author_instance_id": item.get("author_instance_id"), "type": item.get("type"),
                     "text": item.get("text"), "created_at": item.get("created_at"),
                     **({"reply_to_message_id": item["reply_to_message_id"]} if item.get("reply_to_message_id")
                        else {})}
                    for item in body.get("messages") or () if isinstance(item, dict)]
        participants = [{**entry, "role_id": roles.get(entry["instance_id"]),
                         "work_status": status.get(entry["instance_id"])}
                        for entry in self._participants(relation, agents)]
        return {**self._compact(relation), "participants": participants, "messages": messages,
                "next_after": messages[-1]["seq"] if messages else after}

    async def close(self, *, relation_id: str, outcome: str, summary: str = "",
                    winner: str | None = None) -> dict[str, Any]:
        caller = self._caller("relation_close")
        body = await self._send("relation_close", "POST", f"{RELATIONS_ROUTE}/{_q(relation_id)}/close", payload={
            "caller_agent_id": caller.agent_id, "outcome": outcome, "summary": summary, "winner": winner})
        return self._compact(body.get("relation") or {})

    async def handoff(self, *, purpose: str, objective: str, completed_work: str, recommended_next_action: str,
                      key_decisions: Sequence[str] = (), open_points: Sequence[str] = (),
                      artifact_refs: Sequence[str] = (), evidence_refs: Sequence[str] = ()) -> dict[str, Any]:
        caller = self._caller("relation_handoff")
        body = await self._send("relation_handoff", "POST", HANDOFFS_ROUTE, payload={
            "caller_agent_id": caller.agent_id, "purpose": purpose, "packet": {
                "objective": objective, "completed_work": completed_work,
                "recommended_next_action": recommended_next_action, "key_decisions": list(key_decisions),
                "open_points": list(open_points), "artifact_refs": list(artifact_refs),
                "evidence_refs": list(evidence_refs)}})
        handoff = body.get("handoff") or {}
        return {"handoff_id": handoff.get("handoff_id"), "mission_id": handoff.get("mission_id"),
                "expires_at": handoff.get("expires_at"),
                "next": ("Lancez maintenant le successeur avec l'outil Agent, au premier plan, en ajoutant [relais] après "
                         "son rôle (par exemple « [code] [coder] [relais] Suite »). Il reçoit ce paquet et devient "
                         "Mission Owner dès son lancement ; restez disponible jusqu'à son compte rendu.")}


def register(mcp: Any, tools: RelationTools, *, annotations: Callable[[str], Any]) -> None:
    """Déclarer les cinq outils sur le serveur FastMCP, dans l'ordre de `mcp_tool_meta` (après le Dossier)."""

    from jarvis.runtime.mcp_results import (
        RelationCloseResult, RelationHandoffResult, RelationOpenResult, RelationPostResult, RelationReadResult,
    )
    from jarvis.domain.agent_relations import (
        MAX_MESSAGE_CHARS, MAX_OUTCOME_SUMMARY_CHARS, MAX_PACKET_ITEM_CHARS, MAX_PACKET_ITEMS, MAX_PACKET_TEXT_CHARS,
        MAX_PARTICIPANTS, MAX_PURPOSE_CHARS, MAX_REFS,
    )

    # Schémas compacts (coût de contexte, `test_mcp_catalog`) : les règles de forme sont dans les descriptions des
    # outils, Core revalide tout. Champ vide ou liste vide = absent.
    AgentRef = Annotated[str, Field(pattern=r"^[\w-]{0,96}$")]
    RelationId = Annotated[str, Field(pattern=r"^rel_[\w-]{1,120}$")]
    Purpose = Annotated[str, Field(min_length=1, max_length=MAX_PURPOSE_CHARS)]
    Refs = Annotated[list[str], Field(max_length=MAX_REFS)]
    Agents = Annotated[list[AgentRef], Field(max_length=MAX_PARTICIPANTS)]
    PacketText = Annotated[str, Field(min_length=1, max_length=MAX_PACKET_TEXT_CHARS)]
    PacketItems = Annotated[list[Annotated[str, Field(max_length=MAX_PACKET_ITEM_CHARS)]],
                            Field(max_length=MAX_PACKET_ITEMS)]

    @mcp.tool(annotations=annotations("relation_open"))
    async def relation_open(
        kind: Literal["qa", "adversary", "communication"],
        purpose: Purpose,
        reviewer: AgentRef = "",
        reviewed: AgentRef = "",
        producers: Agents = [],  # noqa: B006 - schéma FastMCP ; jamais modifiée
        members: Agents = [],  # noqa: B006
        target_refs: Refs = [],  # noqa: B006
    ) -> RelationOpenResult:
        """Nouer une relation réelle dans votre mission ; agents = agentId rendus par l'outil Agent, ou self.
        qa : reviewer (rôle qa) relit reviewed ; adversary : ≥ 2 producers concurrents ; communication : ≥ 2 members."""
        return await tools.open(kind=kind, purpose=purpose, reviewer=reviewer or None, reviewed=reviewed or None,
                                producers=producers, members=members, target_refs=target_refs)

    @mcp.tool(annotations=annotations("relation_post"))
    async def relation_post(
        relation_id: RelationId,
        text: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)],
        type: Literal["message", "proposal", "critique", "question", "decision", "result_summary",
                      "handoff_note"] = "message",
        audience: Agents = [],  # noqa: B006
        artifact_refs: Refs = [],  # noqa: B006
        reply_to_message_id: Annotated[str, Field(pattern=r"^(msg_[\w-]{1,120})?$")] = "",
    ) -> RelationPostResult:
        """Publier sur le tableau d'une relation dont vous êtes participant : ce que vous dites aux autres, jamais
        votre raisonnement privé."""
        return await tools.post(relation_id=relation_id, text=text, type=type, audience=audience,
                                artifact_refs=artifact_refs, reply_to_message_id=reply_to_message_id or None)

    @mcp.tool(annotations=annotations("relation_read"))
    async def relation_read(
        relation_id: RelationId,
        after: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=MAX_READ)] = 20,
    ) -> RelationReadResult:
        """Lire une relation : participants (agentId, rôle, état) et messages après le rang after."""
        return await tools.read(relation_id=relation_id, after=after, limit=limit)

    @mcp.tool(annotations=annotations("relation_close"))
    async def relation_close(
        relation_id: RelationId,
        outcome: Literal["approved", "findings", "correction_requested", "rejected", "winner", "synthesis",
                         "unresolved", "escalated", "ended", "withdrawn"],
        summary: Annotated[str, Field(max_length=MAX_OUTCOME_SUMMARY_CHARS)] = "",
        winner: AgentRef = "",
    ) -> RelationCloseResult:
        """Clore : qa → approved, findings, correction_requested, rejected (le relecteur) ; adversary → winner (avec
        winner), synthesis, unresolved, escalated ; communication → ended ; toute nature → withdrawn."""
        return await tools.close(relation_id=relation_id, outcome=outcome, summary=summary, winner=winner or None)

    @mcp.tool(annotations=annotations("relation_handoff"))
    async def relation_handoff(
        purpose: Purpose,
        objective: PacketText,
        completed_work: PacketText,
        recommended_next_action: PacketText,
        key_decisions: PacketItems = [],  # noqa: B006
        open_points: PacketItems = [],  # noqa: B006
        artifact_refs: Refs = [],  # noqa: B006
        evidence_refs: Refs = [],  # noqa: B006
    ) -> RelationHandoffResult:
        """Passer votre mission à une instance neuve (Mission Owner courant, une fois) : le paquet, puis lancer le
        successeur avec [relais] après son rôle."""
        return await tools.handoff(purpose=purpose, objective=objective, completed_work=completed_work,
                                   recommended_next_action=recommended_next_action, key_decisions=key_decisions,
                                   open_points=open_points, artifact_refs=artifact_refs, evidence_refs=evidence_refs)
