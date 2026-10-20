"""Runtime des relations côté Control Center : des agentId du CLI aux identités de travail de Core (Slice 06).

Handoff jarvis-organic-agent-orchestration. Les outils de relation
(`relation_runtime.RELATION_TOOLS`, serveur MCP `jarvis-workspace`) appellent
les routes du Control Center ; ce module :

- **résout** l'appelant (l'`agent_id` apposé par le hook ; `None` = le cerveau)
  et chaque agent nommé (agentId rendu par l'outil `Agent`, ou `self`) en
  identité de travail `(source, work_key)` par le suivi des tâches
  (`DeclarationRelay.task_for_agent`). Un agentId inconnu est refusé ici,
  avec ce qu'il faut corriger ;
- **remet d'abord** les déclarations en attente (`DeclarationRelay.settle`) :
  un agent qui noue une relation juste après avoir lancé ses pairs les trouve
  retenus par Core ;
- relaie vers Core (`/v1/missions/relations*`, `/v1/missions/handoffs`) et rend
  tel quel le refus codé et actionnable de Core ;
- pour un relais préparé, dépose le **billet** que le hook réclamera au
  lancement du successeur (`agent_handoffs.write_ticket`) ;
- traduit les participants d'une relation lue en agentId, quand le suivi les
  connaît encore.

Chaque refus est consigné (`missions.relation_failed`, code, jamais le texte
d'un message) ; chaque succès aussi (`missions.relation_relayed`). Contrat :
`docs/agent-relations.md` §10.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from jarvis.domain.agent_relations import HandoffPacket, RelationError
from jarvis.domain.relation_runtime import SELF_REF, actionable, check_agent_ref
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime import agent_handoffs
from jarvis.runtime.journal import RuntimeJournal

#: Délai d'une écriture de relation chez Core (lecture du suivi comprise) : l'outil de l'agent attend la réponse.
DEFAULT_TIMEOUT_S = 8.0
#: Remise des déclarations en attente avant de résoudre les participants : bornée, puis on essaie quand même.
SETTLE_TIMEOUT_S = 3.0
RELAYED_KIND = "missions.relation_relayed"
FAILED_KIND = "missions.relation_failed"


class RelationRelayError(Exception):
    """Refus rendu à l'outil de l'agent : statut HTTP, code stable, message actionnable."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


WorkRef = dict[str, str]


class RelationRelay:
    """Voir le docstring du module. `declarations` : le `DeclarationRelay` (suivi des tâches, remise)."""

    def __init__(self, *, declarations: Any, transport: Any, runtime_root: Any,
                 journal: RuntimeJournal | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.declarations = declarations
        self.transport = transport
        self.runtime_root = runtime_root
        self.journal = journal
        self.timeout_s = timeout_s

    # ------------------------------------------------------------ résolution

    def _ref(self, agent_id: str, *, caller: str | None, name: str) -> WorkRef:
        """L'identité de travail d'un agent nommé par un outil (`self` = l'appelant)."""

        try:
            agent_id = check_agent_ref(name, agent_id)
        except RelationError as exc:
            raise RelationRelayError(400, exc.code, actionable(exc.code, str(exc))) from None
        if agent_id == SELF_REF:
            if caller is None:
                raise RelationRelayError(403, "relation_caller_not_instance", actionable(
                    "relation_caller_not_instance", f"{name}: \"self\" names the caller, and the brain is no instance"))
            agent_id = caller
        found = self.declarations.task_for_agent(agent_id)
        if found is None:
            raise RelationRelayError(404, "relation_agent_unknown", actionable(
                "relation_agent_unknown", f"{name}: agent {agent_id} is not tracked by JARVIS"))
        source, task = found
        return {"work_source": source, "work_external_id": task.work_key}

    def _caller(self, caller: str | None) -> WorkRef | None:
        return None if caller is None else self._ref(caller, caller=caller, name="caller")

    def _agent_of(self, work_source: str, work_external_id: str) -> str | None:
        for tracker in tuple(getattr(self.declarations, "_trackers", {}).values()):
            task = tracker.find(work_external_id)
            if task is not None and task.work_key == work_external_id and task.task_id:
                return task.task_id
        return None

    async def _settle(self) -> None:
        try:
            await asyncio.wait_for(self.declarations.settle(), timeout=SETTLE_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported; Core then says precisely which agent is not recorded
            self._log(FAILED_KIND, "Remise des déclarations avant une relation en échec : on essaie quand même.",
                      "warning", {"operation": "settle", "code": "declarations_unsettled",
                                  "error": f"{type(exc).__name__}: {exc}"[:200]})

    # ------------------------------------------------------------ appels

    async def _call(self, operation: str, call: Callable[[], Awaitable[dict[str, Any]]],
                    data: Mapping[str, Any]) -> dict[str, Any]:
        try:
            body = await asyncio.wait_for(call(), timeout=self.timeout_s)
        except asyncio.CancelledError:
            raise
        except CoreProtocolError as exc:
            status, code, message = exc.status, exc.code, exc.message
        except TimeoutError:
            status, code = 503, "core_unreachable"
            message = f"Core n'a pas répondu en {self.timeout_s:g} s : rien n'est garanti écrit, relisez avant de refaire."
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, réseau : dit tel quel, consigné
            status, code, message = 503, "core_unreachable", f"Core injoignable : {type(exc).__name__}: {exc}"
        else:
            self._log(RELAYED_KIND, f"Relation : {operation} remis à Core.", "info", {"operation": operation, **data})
            return body
        self._log(FAILED_KIND, f"Relation refusée ({operation}) : {code}", "warning" if status < 500 else "error",
                  {"operation": operation, "status": status, "code": code, **data})
        raise RelationRelayError(status, code, message)

    async def open(self, *, caller: str | None, kind: str, participants: list[tuple[str, str]], purpose: str,
                   target_refs: list[str]) -> dict[str, Any]:
        """`participants` : `(agentId ou self, position)`. Rend la relation nouée, participants en agentId."""

        await self._settle()
        body = {
            "caller": self._caller(caller), "kind": kind, "purpose": purpose, "target_refs": target_refs,
            "participants": [{"ref": self._ref(agent, caller=caller, name=f"participants[{index}]"), "position": pos}
                             for index, (agent, pos) in enumerate(participants)],
        }
        result = await self._call("open", lambda: self.transport.open_relation(body),
                                  {"kind": kind, "participants": len(participants)})
        relation = result.get("relation") if isinstance(result, dict) else None
        named = relation.get("participants") if isinstance(relation, dict) else None
        if isinstance(named, list) and len(named) == len(participants):
            # Même ordre que la demande : l'agentId de chaque instance nouée, pour la réponse de l'outil.
            result = {**result, "agents": {item.get("instance_id"): caller if agent == SELF_REF else agent
                                           for item, (agent, _pos) in zip(named, participants)
                                           if isinstance(item, dict)}}
        return result

    async def post(self, *, caller: str | None, relation_id: str, type: str, text: str, audience: list[str],
                   artifact_refs: list[str], reply_to_message_id: str | None) -> dict[str, Any]:
        body = {"caller": self._caller(caller), "type": type, "text": text, "artifact_refs": artifact_refs,
                "audience": [self._ref(agent, caller=caller, name=f"audience[{index}]")
                             for index, agent in enumerate(audience)],
                "reply_to_message_id": reply_to_message_id}
        return await self._call("post", lambda: self.transport.post_relation_message(relation_id, body),
                                {"relation_id": relation_id, "type": type, "chars": len(text)})

    async def close(self, *, caller: str | None, relation_id: str, outcome: str, summary: str,
                    winner: str | None) -> dict[str, Any]:
        body = {"caller": self._caller(caller), "outcome": outcome, "summary": summary,
                "winner": self._ref(winner, caller=caller, name="winner") if winner else None}
        result = await self._call("close", lambda: self.transport.close_relation(relation_id, body),
                                  {"relation_id": relation_id, "outcome": outcome})
        return self._with_agents(result)

    async def read(self, *, relation_id: str, after: int, limit: int) -> dict[str, Any]:
        result = await self._call("read", lambda: self.transport.read_relation(relation_id, after=after, limit=limit),
                                  {"relation_id": relation_id})
        return self._with_agents(result)

    async def handoff(self, *, caller: str | None, purpose: str, packet: dict[str, Any]) -> dict[str, Any]:
        """Préparer un relais chez Core, puis déposer le billet que le hook réclamera au lancement du successeur."""

        if caller is None:
            raise RelationRelayError(403, "relation_caller_not_instance", actionable(
                "relation_caller_not_instance", "the brain does not hand off a mission"))
        body = {"caller": self._caller(caller), "purpose": purpose, "packet": packet}
        result = await self._call("handoff", lambda: self.transport.prepare_handoff(body), {})
        handoff = result.get("handoff") if isinstance(result, dict) else None
        try:
            ticket = agent_handoffs.HandoffTicket(
                handoff_id=handoff["handoff_id"], mission_id=handoff["mission_id"], predecessor_agent_id=caller,
                purpose=handoff["purpose"], packet=HandoffPacket.from_payload(handoff["packet"]),
                expires_at_ms=int(datetime.fromisoformat(handoff["expires_at"]).timestamp() * 1000))
            agent_handoffs.write_ticket(self.runtime_root, ticket)
        except (KeyError, TypeError, ValueError, RelationError, OSError) as exc:
            self._log(FAILED_KIND, "Billet de relais non déposé : le successeur ne pourra pas le réclamer.", "error",
                      {"operation": "handoff_ticket", "code": "handoff_ticket_failed",
                       "error": f"{type(exc).__name__}: {exc}"[:200]})
            raise RelationRelayError(500, "handoff_ticket_failed",
                                     "Relais validé par Core, mais son billet n'a pas pu être déposé sur ce poste : "
                                     f"{type(exc).__name__}. Le successeur ne serait pas reconnu ; réessayez "
                                     "relation_handoff.") from None
        self._log(RELAYED_KIND, "Billet de relais déposé : en attente du successeur.", "info",
                  {"operation": "handoff_ticket", "handoff_id": ticket.handoff_id, "mission_id": ticket.mission_id})
        return result

    # ------------------------------------------------------------ présentation

    def _with_agents(self, result: dict[str, Any]) -> dict[str, Any]:
        """Ajouter l'agentId des participants que le suivi connaît encore (`agent_id`, sinon `None`)."""

        if not isinstance(result, dict):
            return result
        agents = {}
        for view in result.get("participants") or ():
            if isinstance(view, dict) and isinstance(view.get("instance_id"), str):
                agents[view["instance_id"]] = self._agent_of(str(view.get("work_source") or ""),
                                                             str(view.get("work_external_id") or ""))
        if agents:
            result = {**result, "agents": agents}
        return result

    def _log(self, kind: str, message: str, level: str, data: Mapping[str, Any]) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=dict(data))
        except OSError:
            pass  # intentional: an unwritable journal must not turn the answer into a second failure

    async def close_transport(self) -> None:
        await self.transport.close()
