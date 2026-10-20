"""Service Core de l'historique durable des missions (handoff organic-agent-orchestration, Slice 03).

Core Work State reste la **seule** vérité d'exécution vivante (D16) : en
mémoire, borné, vidé à chaque redémarrage de Core. Ce service tient ce qui doit
lui survivre (D18) — instances d'agent à rôle figé, missions et leurs
propriétaires successifs, relations typées, fils de relation, paquets de relais
— dans `jarvis.sqlite3` (v10, `sqlite_mission_history`), sans aucune colonne de
statut. Contrat : `docs/mission-history.md`.

Entrées :

- `record_declaration` : la déclaration d'un sous-agent (`AgentDeclarationFact`,
  source : le hook `PreToolUse`, câblage Slice 05), rattachée à son identité de
  travail `(work_source, work_external_id)` — le `work_key` stable de la tâche,
  jamais l'id brut ni un libellé. Ne lève jamais : rend un `DeclarationResult` ;
- `observe_work_item` : chaque changement de Work State (abonnement tolérant au
  bus, `core.work.updated`), pour la seule règle éphémère et le contrôle du rôle ;
- `close_mission`, `transfer_ownership`, `create_relation`, `close_relation`,
  `post_message` : l'API d'écriture des Slices 05/06. Un refus de contrat lève
  l'erreur codée du domaine ; un magasin indisponible lève
  `MissionHistoryUnavailable` après avoir marqué l'historique dégradé.

Règles :

- **Éphémère (D08)** : aucune ligne durable tant que l'instance l'est. Sa
  déclaration attend en mémoire (bornée) l'issue de son travail dans Work
  State : réussite → oubliée, et un rejeu tardif ne la ressuscite pas (mémoire
  bornée des clés écartées) ; échec, arrêt, interruption ou blocage → drapeau
  rabaissé (`missions.retained_in_history`), instance retenue
  (`ephemeral_lowered`). Un redémarrage de Core vide cette attente : rien de
  durable n'a été écrit, le rejeu du producteur la reconstitue.
- **Redémarrage et rejeu** : l'historique n'est pas rejoué, il est déjà
  durable. Une déclaration rejouée passe par `missions.reconcile_instance` :
  identique → `duplicate`, rien n'est réécrit ; rôle ou affectation différents
  → `refused` (`immutable_field`), l'historique garde la première valeur. Le
  statut vivant d'une instance se lit dans Work State (`None` tant que le
  producteur n'a pas rejoué) ; il n'est jamais déduit de l'historique.
- **Contradiction avec Work State** : le rôle porté par un `WorkItem` qui
  diffère de celui de l'instance retenue est signalé
  (`mission_history.role_mismatch`), sans rien réécrire d'un côté ni de
  l'autre.
- **Fournisseur dégradé** : une écriture refusée par SQLite marque
  l'historique `degraded` (diagnostic d'erreur, `health()`), garde l'écriture
  en attente bornée et la rejoue au balayage suivant ; le travail vivant
  continue, rien ne remonte vers l'ingestion de Work State. Le premier succès
  rétablit l'état (`mission_history.recovered`).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol, TypeVar
import uuid

from jarvis.core.v2_services import CoreEventBus, NullDiagnosticSink, SystemClock
from jarvis.core.work_state import CORE_WORK_UPDATED
from jarvis.domain.agent_relations import AgentRelation, RelationError, RelationMessage, RelationOutcome
from jarvis.domain.mission_history import (
    AGENT_DECLARED_KIND, AgentDeclarationFact, DeclarationOutcome, DeclarationResult, HistoryHealth, InstanceView,
    MissionHistoryError, MissionTree, StoredInstance, join_live, live_status,
)
from jarvis.domain.missions import (
    AgentInstance, Mission, MissionError, MissionStatus, instance_from_declaration, reconcile_instance,
    retained_in_history,
)
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.domain.work_state import WorkItem, WorkSnapshot, WorkStatus
from jarvis.ports.mission_history import MissionHistoryRepository, MissionHistoryStoreError, MissionHistoryUnavailable
from jarvis.ports.v2 import Clock, DiagnosticSink

T = TypeVar("T")

MISSION_HISTORY_READY_KIND = "mission_history.ready"
MISSION_HISTORY_DEGRADED_KIND = "mission_history.degraded"
MISSION_HISTORY_RECOVERED_KIND = "mission_history.recovered"
MISSION_HISTORY_DECLARATION_REFUSED_KIND = "mission_history.declaration_refused"
MISSION_HISTORY_ROLE_MISMATCH_KIND = "mission_history.role_mismatch"
MISSION_HISTORY_EPHEMERAL_DISCARDED_KIND = "mission_history.ephemeral_discarded"
MISSION_HISTORY_EPHEMERAL_RETAINED_KIND = "mission_history.ephemeral_retained"
MISSION_HISTORY_PENDING_DROPPED_KIND = "mission_history.pending_dropped"
MISSION_HISTORY_EVENT_FAILED_KIND = "mission_history.event_failed"

#: Déclarations éphémères en attente d'issue (en mémoire seulement). Au-delà, la plus ancienne est oubliée :
#: elle ne laissera aucune trace, même si elle échoue ensuite — c'est dit au diagnostic.
MAX_PENDING_EPHEMERAL = 256
#: Écritures durables en attente d'un magasin rétabli. Au-delà, la plus ancienne est perdue (dit au diagnostic) ;
#: le rejeu du producteur la rapportera.
MAX_UNSAVED = 256
#: Clés d'éphémères réussies, retenues pour qu'un rejeu tardif ne les ressuscite pas.
MAX_DISCARDED_KEYS = 4_096
#: Rôles connus par identité de travail, pour le contrôle de cohérence avec Work State.
MAX_ROLE_CACHE = 1_024
_MAX_REPORTED = 256

WorkKey = tuple[str, str]


class WorkSnapshotReader(Protocol):
    def current_snapshot(self) -> WorkSnapshot: ...


@dataclass(slots=True)
class _Pending:
    instance: AgentInstance
    fact: AgentDeclarationFact


@dataclass(slots=True)
class _Unsaved:
    instance: AgentInstance
    fact: AgentDeclarationFact | None
    lowered: bool
    mission: Mission | None


def new_instance_id() -> str:
    return f"ainst_{uuid.uuid4().hex}"


class MissionHistoryService:
    """Propriétaire Core de l'historique durable des missions. Voir le docstring du module."""

    def __init__(
        self,
        repository: MissionHistoryRepository,
        *,
        work_state: WorkSnapshotReader,
        events: CoreEventBus | None = None,
        diagnostics: DiagnosticSink | None = None,
        clock: Clock | None = None,
        instance_ids: Callable[[], str] = new_instance_id,
        queue_size: int = 256,
    ) -> None:
        self._repository = repository
        self._work_state = work_state
        self._events = events
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._clock: Clock = clock or SystemClock()
        self._instance_ids = instance_ids
        self._queue_size = queue_size
        self._health = HistoryHealth()
        self._pending: OrderedDict[WorkKey, _Pending] = OrderedDict()
        self._unsaved: OrderedDict[WorkKey, _Unsaved] = OrderedDict()
        self._discarded: OrderedDict[WorkKey, None] = OrderedDict()
        self._roles: OrderedDict[WorkKey, str] = OrderedDict()
        self._reported: set[tuple[str, ...]] = set()
        self._queue: asyncio.Queue[ProtocolEnvelope] | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ état

    def health(self) -> HistoryHealth:
        self._health.pending_ephemeral = len(self._pending)
        return replace(self._health, outcomes=dict(self._health.outcomes))

    @property
    def degraded(self) -> bool:
        return self._health.degraded

    def _count(self, outcome: DeclarationOutcome) -> None:
        self._health.outcomes[outcome.value] = self._health.outcomes.get(outcome.value, 0) + 1

    # ------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        """Journaliser l'état du magasin (chemin normal), puis s'abonner au bus. Ne lève jamais."""

        try:
            counts = await self._guard("counts", self._repository.counts())
        except (MissionHistoryUnavailable, MissionHistoryStoreError, MissionHistoryError):
            counts = None  # intentional: `_guard` has already marked the history degraded and reported it
        if counts is not None:
            self._emit(MISSION_HISTORY_READY_KIND, "historique des missions prêt", data=counts)
        if self._events is not None and self._task is None:
            self._queue = self._events.subscribe(max_queue=self._queue_size, lossy=True)
            self._task = asyncio.get_running_loop().create_task(self._run(self._queue), name="jarvis-mission-history")

    async def stop(self) -> None:
        task, self._task = self._task, None
        queue, self._queue = self._queue, None
        if queue is not None and self._events is not None:
            self._events.unsubscribe(queue)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        while True:
            envelope = await queue.get()
            if envelope.message_type != CORE_WORK_UPDATED:
                continue
            try:
                item = WorkItem.from_payload(envelope.payload["item"])
                await self.observe_work_item(item)
                await self.sweep()
            except Exception as exc:  # the loop must survive one bad event; the failure is reported below
                self._report(("event", type(exc).__name__), MISSION_HISTORY_EVENT_FAILED_KIND,
                             "événement d'état de travail non traité par l'historique des missions",
                             level="error", data={"error": type(exc).__name__, "detail": str(exc)[:200]})

    # ------------------------------------------------------------ déclarations

    async def record_declaration(
        self,
        fact: AgentDeclarationFact,
        *,
        work_source: str,
        work_external_id: str,
        parent_work_external_id: str | None = None,
        mission: Mission | None = None,
    ) -> DeclarationResult:
        """Accepter la déclaration d'un sous-agent. Ne lève jamais : l'issue est rendue, comptée, journalisée.

        `parent_work_external_id` : l'identité de travail du parent dans la même source (`WorkItem.parent_external_id`) ;
        le parent devient `parent_instance_id` s'il est retenu, sinon l'instance n'a pas de parent durable.
        `mission` : la mission que cette instance ouvre et possède (`fact.mission_owner`).
        """

        key: WorkKey = (work_source, work_external_id)
        result = await self._declare(fact, key, parent_work_external_id, mission)
        self._count(result.outcome)
        if result.outcome is DeclarationOutcome.REFUSED:
            self._report(("refused", *key, result.code or ""), MISSION_HISTORY_DECLARATION_REFUSED_KIND,
                         f"déclaration de sous-agent refusée : {result.message}", level="warning",
                         data={"work_source": key[0], "work_external_id": key[1], "code": result.code})
        elif result.outcome in (DeclarationOutcome.RECORDED, DeclarationOutcome.EPHEMERAL_PENDING,
                                DeclarationOutcome.EPHEMERAL_RETAINED):
            self._emit(AGENT_DECLARED_KIND, "sous-agent déclaré", data={
                "work_source": key[0], "work_external_id": key[1], "role_id": fact.role_id,
                "role_status": fact.role_status.value, "ephemeral": fact.ephemeral,
                "mission_id": fact.mission_id, "outcome": result.outcome.value,
                "instance_id": result.instance.instance_id if result.instance else None,
            })
        return result

    async def _declare(self, fact: AgentDeclarationFact, key: WorkKey, parent_work_external_id: str | None,
                       mission: Mission | None) -> DeclarationResult:
        if not isinstance(fact, AgentDeclarationFact):
            return DeclarationResult(DeclarationOutcome.REFUSED, code="mission_history_invalid",
                                     message="expected an AgentDeclarationFact")
        if key in self._discarded:
            # D08 : l'éphémère a bien fini ; son rejeu tardif ne lui donne pas de trace durable.
            return DeclarationResult(DeclarationOutcome.EPHEMERAL_DISCARDED)
        try:
            stored = await self._guard("find_instance", self._repository.find_instance(*key))
            parent_id = None
            if parent_work_external_id is not None and parent_work_external_id != key[1]:
                parent = await self._guard("find_instance", self._repository.find_instance(key[0],
                                                                                        parent_work_external_id))
                parent_id = parent.instance.instance_id if parent is not None else None
        except MissionHistoryUnavailable as exc:
            return DeclarationResult(DeclarationOutcome.DEGRADED, code=exc.code, message=str(exc))
        except (MissionHistoryStoreError, MissionHistoryError) as exc:
            return DeclarationResult(DeclarationOutcome.REFUSED, code=getattr(exc, "code", None), message=str(exc))
        try:
            instance = instance_from_declaration(
                fact.declaration(), instance_id=stored.instance.instance_id if stored else self._instance_ids(),
                work_source=key[0], work_external_id=key[1], created_at=fact.declared_at, mission_id=fact.mission_id,
                mission_owner=fact.mission_owner, parent_instance_id=parent_id,
            )
        except MissionError as exc:
            return DeclarationResult(DeclarationOutcome.REFUSED, code=exc.code, message=str(exc))

        if stored is not None:
            # Rejeu ou redémarrage : identique ou refusé, jamais réécrit (D01). Une éphémère retenue après un
            # échec se rejoue avec son drapeau d'origine : c'est la même déclaration.
            # Le parent n'est pas déclaré, Core le résout au premier enregistrement : il fait foi (un parent
            # retenu plus tard, une éphémère échouée par exemple, ne réécrit pas l'instance).
            incoming = replace(instance, ephemeral=False if stored.ephemeral_lowered else instance.ephemeral,
                               parent_instance_id=stored.instance.parent_instance_id)
            try:
                reconcile_instance(stored.instance, incoming)
            except MissionError as exc:
                return DeclarationResult(DeclarationOutcome.REFUSED, stored.instance, code=exc.code, message=str(exc))
            return await self._persist(key, incoming, fact, stored.ephemeral_lowered, None)

        pending = self._pending.get(key)
        if pending is not None:
            try:
                reconcile_instance(pending.instance, replace(instance, instance_id=pending.instance.instance_id))
            except MissionError as exc:
                return DeclarationResult(DeclarationOutcome.REFUSED, pending.instance, code=exc.code, message=str(exc))
            return DeclarationResult(DeclarationOutcome.EPHEMERAL_PENDING, pending.instance)

        if instance.ephemeral:
            item = self._live().get(key)
            if item is not None and not retained_in_history(instance, item.status):
                if item.status is WorkStatus.COMPLETED:
                    self._discard(key, instance)
                    return DeclarationResult(DeclarationOutcome.EPHEMERAL_DISCARDED)
            elif item is not None:
                return await self._retain_lowered(key, instance, fact)
            self._hold(key, _Pending(instance, fact))
            return DeclarationResult(DeclarationOutcome.EPHEMERAL_PENDING, instance)
        return await self._persist(key, instance, fact, False, mission)

    async def _persist(self, key: WorkKey, instance: AgentInstance, fact: AgentDeclarationFact | None, lowered: bool,
                       mission: Mission | None) -> DeclarationResult:
        try:
            stored, created = await self._guard(
                "record_instance",
                self._repository.record_instance(instance, declaration=fact, ephemeral_lowered=lowered, mission=mission))
        except MissionHistoryUnavailable as exc:
            self._keep_unsaved(key, _Unsaved(instance, fact, lowered, mission))
            return DeclarationResult(DeclarationOutcome.DEGRADED, instance, code=exc.code, message=str(exc))
        except (MissionError, RelationError, MissionHistoryError, MissionHistoryStoreError) as exc:
            return DeclarationResult(DeclarationOutcome.REFUSED, instance, code=getattr(exc, "code", None),
                                     message=str(exc))
        self._unsaved.pop(key, None)
        self._remember_role(key, stored.instance.role_id)
        if lowered and created:
            return DeclarationResult(DeclarationOutcome.EPHEMERAL_RETAINED, stored.instance)
        return DeclarationResult(DeclarationOutcome.RECORDED if created else DeclarationOutcome.DUPLICATE,
                                 stored.instance)

    async def _retain_lowered(self, key: WorkKey, instance: AgentInstance, fact: AgentDeclarationFact
                              ) -> DeclarationResult:
        """Une éphémère dont le travail a mal fini redevient ordinaire et est retenue (`ephemeral_lowered`)."""

        self._pending.pop(key, None)
        result = await self._persist(key, replace(instance, ephemeral=False), fact, True, None)
        if result.outcome is DeclarationOutcome.EPHEMERAL_RETAINED:
            self._emit(MISSION_HISTORY_EPHEMERAL_RETAINED_KIND, "éphémère retenue après une fin anormale",
                       data={"work_source": key[0], "work_external_id": key[1],
                             "instance_id": result.instance.instance_id if result.instance else None})
        return result

    def _discard(self, key: WorkKey, instance: AgentInstance) -> None:
        self._pending.pop(key, None)
        self._discarded[key] = None
        self._discarded.move_to_end(key)
        while len(self._discarded) > MAX_DISCARDED_KEYS:
            self._discarded.popitem(last=False)
        self._emit(MISSION_HISTORY_EPHEMERAL_DISCARDED_KIND, "éphémère terminée : aucune trace durable",
                   data={"work_source": key[0], "work_external_id": key[1], "role_id": instance.role_id})

    def _hold(self, key: WorkKey, pending: _Pending) -> None:
        self._pending[key] = pending
        self._pending.move_to_end(key)
        while len(self._pending) > MAX_PENDING_EPHEMERAL:
            dropped, _ = self._pending.popitem(last=False)
            self._report(("pending_dropped", *dropped), MISSION_HISTORY_PENDING_DROPPED_KIND,
                         "trop d'éphémères en attente : la plus ancienne ne sera pas retenue même si elle échoue",
                         level="warning", data={"work_source": dropped[0], "work_external_id": dropped[1],
                                                "max_pending": MAX_PENDING_EPHEMERAL})

    def _keep_unsaved(self, key: WorkKey, unsaved: _Unsaved) -> None:
        self._unsaved[key] = unsaved
        self._unsaved.move_to_end(key)
        while len(self._unsaved) > MAX_UNSAVED:
            dropped, _ = self._unsaved.popitem(last=False)
            self._report(("unsaved_dropped", *dropped), MISSION_HISTORY_PENDING_DROPPED_KIND,
                         "historique indisponible trop longtemps : une instance attendue est perdue jusqu'au rejeu",
                         level="error", data={"work_source": dropped[0], "work_external_id": dropped[1],
                                              "max_unsaved": MAX_UNSAVED})

    def _remember_role(self, key: WorkKey, role_id: str) -> None:
        self._roles[key] = role_id
        self._roles.move_to_end(key)
        while len(self._roles) > MAX_ROLE_CACHE:
            self._roles.popitem(last=False)

    # ------------------------------------------------------------ Work State

    async def observe_work_item(self, item: WorkItem) -> DeclarationResult | None:
        """Appliquer la règle éphémère et contrôler le rôle pour un élément de Work State. Ne lève jamais.

        Ne lit de l'élément que son statut et son `role_id` : rien n'est copié dans l'historique.
        """

        key = item.key
        known = self._roles.get(key)
        if item.role_id is not None and known is not None and known != item.role_id:
            self._report(("role_mismatch", *key), MISSION_HISTORY_ROLE_MISMATCH_KIND,
                         "le rôle porté par Work State contredit l'historique : aucun des deux n'est réécrit",
                         level="warning", data={"work_source": key[0], "work_external_id": key[1],
                                                "history_role_id": known, "work_role_id": item.role_id})
        pending = self._pending.get(key)
        if pending is None:
            return None
        if retained_in_history(pending.instance, item.status):
            result = await self._retain_lowered(key, pending.instance, pending.fact)
        elif item.status is WorkStatus.COMPLETED:
            self._discard(key, pending.instance)
            result = DeclarationResult(DeclarationOutcome.EPHEMERAL_DISCARDED)
        else:
            return None
        self._count(result.outcome)
        return result

    async def sweep(self) -> int:
        """Rattraper ce qu'un événement perdu (bus tolérant) ou un magasin indisponible a laissé en attente.

        Éphémères en attente comparées à l'instantané de Work State, puis écritures non enregistrées rejouées.
        Rend le nombre d'entrées résolues. Ne lève jamais.
        """

        resolved = 0
        items = self._live()
        for key in list(self._pending):
            item = items.get(key)
            if item is not None and await self.observe_work_item(item) is not None:
                resolved += 1
        for key, unsaved in list(self._unsaved.items()):
            result = await self._persist(key, unsaved.instance, unsaved.fact, unsaved.lowered, unsaved.mission)
            if result.outcome is DeclarationOutcome.DEGRADED:
                break
            self._unsaved.pop(key, None)
            resolved += 1
        return resolved

    def _live(self) -> dict[WorkKey, WorkItem]:
        return {item.key: item for item in self._work_state.current_snapshot().items}

    # ------------------------------------------------------------ API d'écriture (Slices 05/06)

    async def close_mission(self, mission_id: str, status: MissionStatus) -> Mission:
        return await self._guard("close_mission", self._repository.close_mission(mission_id, status,
                                                                                 self._clock.now()))

    async def transfer_ownership(self, mission_id: str, successor_instance_id: str, *, handoff_relation_id: str
                                 ) -> Mission:
        return await self._guard("transfer_ownership", self._repository.transfer_ownership(
            mission_id, successor_instance_id, handoff_relation_id=handoff_relation_id, at=self._clock.now()))

    async def create_relation(self, relation: AgentRelation) -> AgentRelation:
        return await self._guard("create_relation", self._repository.create_relation(relation))

    async def close_relation(self, relation_id: str, outcome: RelationOutcome, *, summary: str = "",
                             winner_instance_id: str | None = None, closed_by: str | None = None) -> AgentRelation:
        return await self._guard("close_relation", self._repository.close_relation(
            relation_id, outcome, self._clock.now(), summary=summary, winner_instance_id=winner_instance_id,
            closed_by=closed_by))

    async def post_message(self, message: RelationMessage) -> int:
        return await self._guard("append_message", self._repository.append_message(message))

    # ------------------------------------------------------------ lecture

    async def instance_for_work(self, work_source: str, work_external_id: str) -> InstanceView | None:
        stored = await self._guard("find_instance", self._repository.find_instance(work_source, work_external_id))
        if stored is None:
            return None
        return InstanceView(stored, live_status(stored.instance, self._live()))

    async def mission_view(self, mission_id: str) -> tuple[MissionTree, tuple[InstanceView, ...]] | None:
        """L'arbre de la mission et, pour chaque instance, son statut vivant lu dans Work State (ou `None`)."""

        tree = await self._guard("mission_tree", self._repository.mission_tree(mission_id))
        if tree is None:
            return None
        return tree, join_live(tree.instances, self._work_state.current_snapshot())

    async def recent_instances(self, *, limit: int = 50) -> tuple[StoredInstance, ...]:
        return await self._guard("recent_instances", self._repository.recent_instances(limit=limit))

    async def thread(self, relation_id: str, *, after: int = 0, limit: int = 100
                     ) -> tuple[tuple[int, RelationMessage], ...]:
        return await self._guard("thread", self._repository.thread(relation_id, after=after, limit=limit))

    # ------------------------------------------------------------ dégradation

    async def _guard(self, operation: str, call: Awaitable[T]) -> T:
        """Exécuter un appel du magasin : un refus de SQLite marque l'historique dégradé, un succès le rétablit."""

        try:
            result = await call
        except MissionHistoryUnavailable as exc:
            self._degrade(operation, exc)
            raise
        except MissionHistoryStoreError as exc:
            # Ligne illisible : un fichier abîmé, jamais réparé ici. Dit une fois par clé, à l'erreur.
            self._report(("unreadable", exc.table, exc.key), MISSION_HISTORY_DEGRADED_KIND,
                         f"historique des missions illisible : {exc}", level="error",
                         data={"operation": operation, "table": exc.table, "key": exc.key})
            raise
        self._recover()
        return result

    def _degrade(self, operation: str, exc: Exception) -> None:
        health = self._health
        health.failed_writes += 1
        if health.degraded:
            return
        health.degraded = True
        health.since = self._clock.now()
        health.reason = str(exc)[:300]
        self._emit(MISSION_HISTORY_DEGRADED_KIND,
                   "historique des missions indisponible : le travail continue, l'historique est en retard",
                   level="error", data={"operation": operation, "error": type(exc).__name__,
                                        "detail": str(exc)[:300]})

    def _recover(self) -> None:
        health = self._health
        if not health.degraded:
            return
        since = health.since
        failed = health.failed_writes
        health.degraded, health.since, health.reason = False, None, ""
        self._emit(MISSION_HISTORY_RECOVERED_KIND, "historique des missions rétabli",
                   data={"since": since.isoformat() if since else None, "failed_writes": failed,
                         "unsaved": len(self._unsaved)})

    # ------------------------------------------------------------ diagnostic

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any]) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            pass  # intentional: an unavailable journal never stops history or live work (same rule as WorkStateStore)

    def _report(self, dedupe: tuple[str, ...], kind: str, message: str, *, level: str, data: dict[str, Any]) -> None:
        """Signaler une anomalie une fois par clé, dans une mémoire bornée."""

        if dedupe in self._reported:
            return
        if len(self._reported) >= _MAX_REPORTED:
            self._reported.clear()
        self._reported.add(dedupe)
        self._emit(kind, message, level=level, data=data)
