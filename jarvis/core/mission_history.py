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
    MissionHistoryError, MissionOpening, MissionTree, StoredInstance, join_live, live_status,
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
MISSION_HISTORY_DISCARDED_FORGOTTEN_KIND = "mission_history.discarded_forgotten"
MISSION_HISTORY_UNSAVED_REFUSED_KIND = "mission_history.unsaved_refused"
MISSION_HISTORY_MISSION_CLOSED_KIND = "mission_history.mission_closed"
MISSION_HISTORY_CLOSE_FAILED_KIND = "mission_history.mission_close_failed"
MISSION_HISTORY_CLOSE_DEFERRED_KIND = "mission_history.mission_close_deferred"
MISSION_HISTORY_PARENT_CLOSED_KIND = "mission_history.mission_parent_closed"
MISSION_HISTORY_MEMBER_AFTER_CLOSE_KIND = "mission_history.member_after_close"
#: Missions ouvertes réévaluées par balayage, et profondeur de sous-missions réévaluée d'un coup. Le balayage
#: tourne (curseur `(created_at, mission_id)`) : chaque mission ouverte est revue au bout de ⌈ouvertes / 64⌉ passes.
MAX_SWEPT_MISSIONS = 64
#: Délai de grâce après le démarrage de Core (relais du Control Center rejoué compris, sonde de 30 s) avant de dire
#: « état inconnu » d'une mission ouverte dont ni le propriétaire ni aucun membre n'est connu de Work State.
ORPHAN_GRACE_S = 600.0
MISSION_HISTORY_ORPHANED_KIND = "mission_history.mission_orphaned"
MAX_CLOSE_DEPTH = 16
MISSION_HISTORY_SWEEP_FAILED_KIND = "mission_history.sweep_failed"

#: Balayage périodique (Slice 05, note N5 de la Slice 03) : rattrape un événement perdu ou un magasin rétabli même
#: quand aucun travail ne bouge. Un balayage a aussi lieu au démarrage.
SWEEP_INTERVAL_S = 30.0
#: Issue d'une mission quand le travail de son propriétaire courant se termine (Slice 05).
MISSION_STATUS_FOR_WORK = {
    WorkStatus.COMPLETED: MissionStatus.COMPLETED,
    WorkStatus.FAILED: MissionStatus.FAILED,
    WorkStatus.CANCELLED: MissionStatus.CANCELLED,
    WorkStatus.INTERRUPTED: MissionStatus.CANCELLED,
}

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
#: Appartenance de mission connue par identité de travail (`mission_ref`, clôture à la fin du propriétaire).
MAX_MISSION_CACHE = 1_024
_MAX_REPORTED = 256

WorkKey = tuple[str, str]


class WorkSnapshotReader(Protocol):
    def current_snapshot(self) -> WorkSnapshot: ...


@dataclass(frozen=True, slots=True)
class MissionRef:
    """L'appartenance de mission d'une instance retenue : ce que le contexte du cerveau et la clôture lisent."""

    instance_id: str
    mission_id: str | None
    mission_owner: bool


@dataclass(slots=True)
class _Pending:
    instance: AgentInstance
    fact: AgentDeclarationFact


@dataclass(slots=True)
class _Unsaved:
    """Une écriture d'instance prête, que le magasin a refusée (panne) : rejouée telle quelle."""

    instance: AgentInstance
    fact: AgentDeclarationFact | None
    lowered: bool
    mission: Mission | None


@dataclass(slots=True)
class _UnsavedDeclaration:
    """Une déclaration que le magasin n'a même pas pu lire (panne totale) : rejouée intégralement."""

    fact: AgentDeclarationFact
    parent_work_external_id: str | None
    mission: MissionOpening | Mission | None
    inherit_mission: bool = False


def _from_caller(mission: object) -> bool:
    return isinstance(mission, MissionOpening) and mission.parent_from_caller


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
        sweep_interval_s: float | None = SWEEP_INTERVAL_S,
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
        self._unsaved: OrderedDict[WorkKey, _Unsaved | _UnsavedDeclaration] = OrderedDict()
        self._discarded: OrderedDict[WorkKey, None] = OrderedDict()
        self._roles: OrderedDict[WorkKey, str] = OrderedDict()
        #: identité de travail -> (instance, mission ou None, propriétaire) ; `None` = aucune instance retenue.
        self._missions: OrderedDict[WorkKey, MissionRef | None] = OrderedDict()
        #: mission -> issue de son propriétaire courant, vue avant que la clôture soit possible (équipe active) :
        #: elle survit à l'élagage du propriétaire dans Work State.
        self._owner_ended: OrderedDict[str, WorkStatus] = OrderedDict()
        self._reported: set[tuple[str, ...]] = set()
        self._queue: asyncio.Queue[ProtocolEnvelope] | None = None
        self._task: asyncio.Task[None] | None = None
        self._sweeper: asyncio.Task[None] | None = None
        #: Curseur du balayage tournant des missions ouvertes ; `None` = reprendre au début.
        self._sweep_cursor: tuple[Any, str] | None = None
        #: Naissance de ce service (≈ démarrage de Core) : le délai de grâce des missions orphelines part d'ici.
        self._born = self._clock.now()
        self._sweep_interval_s = sweep_interval_s
        self._sweep_lock = asyncio.Lock()

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
        if self._sweep_interval_s is not None and self._sweeper is None:
            self._sweeper = asyncio.get_running_loop().create_task(self._sweep_periodically(),
                                                                   name="jarvis-mission-history-sweep")

    async def stop(self) -> None:
        task, self._task = self._task, None
        sweeper, self._sweeper = self._sweeper, None
        queue, self._queue = self._queue, None
        if queue is not None and self._events is not None:
            self._events.unsubscribe(queue)
        for running in (task, sweeper):
            if running is not None:
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)

    async def _sweep_periodically(self) -> None:
        """Un balayage au démarrage, puis toutes les `sweep_interval_s` secondes. Survit à un balayage en échec."""

        while True:
            try:
                await self.sweep()
            except Exception as exc:  # the periodic sweep must survive; the failure is reported once per type
                self._report(("sweep", type(exc).__name__), MISSION_HISTORY_SWEEP_FAILED_KIND,
                             "balayage de l'historique des missions en échec", level="error",
                             data={"error": type(exc).__name__, "detail": str(exc)[:200]})
            await asyncio.sleep(self._sweep_interval_s or SWEEP_INTERVAL_S)

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
        mission: MissionOpening | Mission | None = None,
        inherit_mission: bool = False,
    ) -> DeclarationResult:
        """Accepter la déclaration d'un sous-agent. Ne lève jamais : l'issue est rendue, comptée, journalisée.

        `parent_work_external_id` : l'identité de travail du parent dans la même source (`WorkItem.parent_external_id`) ;
        le parent devient `parent_instance_id` s'il est retenu, sinon l'instance n'a pas de parent durable.
        `mission` : la mission que cette instance ouvre et possède (`fact.mission_owner`, id `fact.mission_id`),
        normalement une `MissionOpening` (objectif, mission parente). Core pose lui-même le propriétaire (l'id de
        l'instance qu'il crée ici), la racine (celle du parent) et la date (`fact.declared_at`). Une `Mission`
        complète est acceptée pour sa forme, mais son `owner_instance_id` et sa racine sont remplacés de même :
        l'appelant ne peut pas connaître l'id d'une instance qui n'existe pas encore.
        `inherit_mission` (Slice 05, ingestion du hook) : une instance qui n'ouvre pas de mission et n'en nomme pas
        devient membre de la mission de son parent retenu ; une `MissionOpening(parent_from_caller=True)` prend
        pour parente cette même mission. Sans parent retenu (ou parent sans mission) : pas de mission, ou racine.
        """

        key: WorkKey = (work_source, work_external_id)
        result = await self._declare(fact, key, parent_work_external_id, mission, inherit_mission)
        self._settled(key, result)
        self._count(result.outcome)
        if result.outcome is DeclarationOutcome.REFUSED:
            self._report(("refused", *key, result.code or ""), MISSION_HISTORY_DECLARATION_REFUSED_KIND,
                         f"déclaration de sous-agent refusée : {result.message}", level="warning",
                         data={"work_source": key[0], "work_external_id": key[1], "code": result.code})
        elif result.outcome in (DeclarationOutcome.RECORDED, DeclarationOutcome.EPHEMERAL_PENDING,
                                DeclarationOutcome.EPHEMERAL_RETAINED):
            self._declared(key, fact, result)
        if result.outcome is DeclarationOutcome.RECORDED and fact.mission_owner:
            # La fin du travail a pu arriver avant la déclaration (deux relais distincts) : la mission ouverte
            # se clôt aussitôt, sinon elle resterait ouverte pour toujours.
            item = self._live().get(key)
            if item is not None and item.status.is_terminal:
                await self._on_terminal(key, item.status)
        return result

    def _settled(self, key: WorkKey, result: DeclarationResult) -> None:
        """Le magasin a répondu (autre chose que `degraded`) : plus rien n'attend pour cette clé, état rétabli."""

        if result.outcome is not DeclarationOutcome.DEGRADED:
            self._unsaved.pop(key, None)
            self._recover()

    def _declared(self, key: WorkKey, fact: AgentDeclarationFact, result: DeclarationResult) -> None:
        """`agent.declared` : une instance connue de Core, par la déclaration ou par l'observation qui la retient."""

        self._emit(AGENT_DECLARED_KIND, "sous-agent déclaré", data={
            "work_source": key[0], "work_external_id": key[1], "role_id": fact.role_id,
            "role_status": fact.role_status.value, "ephemeral": fact.ephemeral,
            # La mission de l'instance (héritée de l'appelant pour un membre, Slice 05), sinon celle du fait.
            "mission_id": result.instance.mission_id if result.instance else fact.mission_id,
            "mission_owner": fact.mission_owner, "outcome": result.outcome.value,
            "instance_id": result.instance.instance_id if result.instance else None,
        })

    async def _opened_mission(self, opening: MissionOpening | Mission, fact: AgentDeclarationFact,
                              owner: AgentInstance) -> Mission:
        """La `Mission` que `owner` ouvre : id du fait, propriétaire = l'instance créée, racine = celle du parent.

        Lève `MissionError` (contrat) ou une erreur du magasin (lecture du parent), rendue par l'appelant.
        """

        if not fact.mission_owner or fact.mission_id is None:
            raise MissionError("only a mission owner declaration naming its mission opens a mission",
                               code="ownership_invalid", field="mission_owner")
        if isinstance(opening, Mission):
            if opening.mission_id != fact.mission_id:
                raise MissionError(f"the mission opened ({opening.mission_id}) is not the declared one "
                                   f"({fact.mission_id})", field="mission_id")
            opening = MissionOpening(objective=opening.objective, parent_mission_id=opening.parent_mission_id,
                                     dossier_path=opening.dossier_path, origin_kind=opening.origin_kind)
        if not isinstance(opening, MissionOpening):
            raise MissionError("mission must be a MissionOpening", field="mission")
        root = None
        if opening.parent_mission_id is not None:
            parent = await self._guard("get_mission", self._repository.get_mission(opening.parent_mission_id),
                                       recover=False)
            if parent is None:
                raise MissionError(f"parent mission {opening.parent_mission_id} is missing",
                                   code="mission_parent_missing", field="parent_mission_id")
            if parent.status.is_closed:
                # Une mission close est gelée : elle ne reçoit plus de sous-mission.
                raise MissionError(f"parent mission {parent.mission_id} is {parent.status.value}",
                                   code="mission_closed", field="parent_mission_id")
            root = parent.root_mission_id
        return opening.mission(mission_id=fact.mission_id, owner_instance_id=owner.instance_id,
                               created_at=fact.declared_at, root_mission_id=root)

    async def _declare(self, fact: AgentDeclarationFact, key: WorkKey, parent_work_external_id: str | None,
                       mission: MissionOpening | Mission | None, inherit_mission: bool = False) -> DeclarationResult:
        if not isinstance(fact, AgentDeclarationFact):
            return DeclarationResult(DeclarationOutcome.REFUSED, code="mission_history_invalid",
                                     message="expected an AgentDeclarationFact")
        if key in self._discarded:
            # D08 : l'éphémère a bien fini ; son rejeu tardif ne lui donne pas de trace durable.
            return DeclarationResult(DeclarationOutcome.EPHEMERAL_DISCARDED)
        try:
            stored = await self._guard("find_instance", self._repository.find_instance(*key), recover=False)
            parent = None
            if parent_work_external_id is not None and parent_work_external_id != key[1]:
                parent = await self._guard("find_instance", self._repository.find_instance(
                    key[0], parent_work_external_id), recover=False)
            parent_id = parent.instance.instance_id if parent is not None else None
        except MissionHistoryUnavailable as exc:
            # Panne totale : rien n'a pu être lu. Le fait brut attend et sera rejoué intégralement (`sweep`).
            self._keep_unsaved(key, _UnsavedDeclaration(fact, parent_work_external_id, mission, inherit_mission))
            return DeclarationResult(DeclarationOutcome.DEGRADED, code=exc.code, message=str(exc))
        except (MissionHistoryStoreError, MissionHistoryError) as exc:
            return DeclarationResult(DeclarationOutcome.REFUSED, code=getattr(exc, "code", None), message=str(exc))
        caller_mission = parent.instance.mission_id if parent is not None else None
        mission_id = fact.mission_id
        if inherit_mission and mission_id is None and not fact.mission_owner:
            mission_id = caller_mission  # membre de la mission de son appelant (Slice 05)
        if (isinstance(mission, MissionOpening) and mission.parent_from_caller and mission.parent_mission_id is None
                and caller_mission is not None):
            mission = replace(mission, parent_mission_id=caller_mission)
        try:
            instance = instance_from_declaration(
                fact.declaration(), instance_id=stored.instance.instance_id if stored else self._instance_ids(),
                work_source=key[0], work_external_id=key[1], created_at=fact.declared_at, mission_id=mission_id,
                mission_owner=fact.mission_owner, parent_instance_id=parent_id,
            )
        except MissionError as exc:
            return DeclarationResult(DeclarationOutcome.REFUSED, code=exc.code, message=str(exc))
        if mission is not None and (not fact.mission_owner or fact.mission_id is None):
            # Une ouverture de mission sans déclaration de Mission Owner est refusée, jamais ignorée en silence
            # (éphémère comprise).
            return DeclarationResult(DeclarationOutcome.REFUSED, instance, code="ownership_invalid",
                                     message="only a mission owner declaration naming its mission opens a mission")

        if stored is not None:
            # Rejeu ou redémarrage : identique ou refusé, jamais réécrit (D01). Une éphémère retenue après un
            # échec se rejoue avec son drapeau d'origine : c'est la même déclaration.
            # Le parent n'est pas déclaré, Core le résout au premier enregistrement : il fait foi (un parent
            # retenu plus tard, une éphémère échouée par exemple, ne réécrit pas l'instance).
            incoming = replace(instance, ephemeral=False if stored.ephemeral_lowered else instance.ephemeral,
                               parent_instance_id=stored.instance.parent_instance_id)
            if (_from_caller(mission) and fact.mission_owner and stored.instance.mission_id is None
                    and not stored.instance.mission_owner):
                # Sous-mission refusée à la première fois (parent clos) : son rejeu est la même instance.
                incoming = replace(incoming, mission_id=None, mission_owner=False)
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
        opened = None
        if mission is not None:
            try:
                opened = await self._opened_mission(mission, fact, instance)
            except MissionHistoryUnavailable as exc:
                self._keep_unsaved(key, _UnsavedDeclaration(fact, parent_work_external_id, mission, inherit_mission))
                return DeclarationResult(DeclarationOutcome.DEGRADED, instance, code=exc.code, message=str(exc))
            except MissionError as exc:
                if exc.code != "mission_closed" or not _from_caller(mission):
                    return DeclarationResult(DeclarationOutcome.REFUSED, instance, code=exc.code, message=str(exc))
                # `[mission]` sous une mission close : l'agent a bien tourné, il est retenu (D18), sans
                # sous-mission ; une mission close ne reçoit plus de sous-mission.
                instance = replace(instance, mission_id=None, mission_owner=False)
                self._report(("parent_closed", *key), MISSION_HISTORY_PARENT_CLOSED_KIND,
                             "sous-mission demandée sous une mission close : agent retenu sans mission",
                             level="warning", data={"work_source": key[0], "work_external_id": key[1],
                                                    "code": "mission_parent_closed",
                                                    "parent_mission_id": mission.parent_mission_id})
            except MissionHistoryStoreError as exc:
                return DeclarationResult(DeclarationOutcome.REFUSED, instance, code=getattr(exc, "code", None),
                                         message=str(exc))
        elif inherit_mission and instance.mission_id is not None and not instance.mission_owner:
            await self._note_late_member(key, instance.mission_id)
        return await self._persist(key, instance, fact, False, opened)

    async def _note_late_member(self, key: WorkKey, mission_id: str) -> None:
        """Un membre qui rejoint une mission déjà close est retenu tel quel (D18) ; c'est dit au diagnostic."""

        try:
            mission = await self._guard("get_mission", self._repository.get_mission(mission_id), recover=False)
        except (MissionHistoryUnavailable, MissionHistoryStoreError):
            return  # intentional: `_guard` reported the store failure; the member is still persisted just after
        if mission is not None and mission.status.is_closed:
            self._report(("late_member", *key), MISSION_HISTORY_MEMBER_AFTER_CLOSE_KIND,
                         "membre déclaré après la clôture de sa mission : retenu tel quel", level="warning",
                         data={"work_source": key[0], "work_external_id": key[1], "mission_id": mission_id,
                               "mission_status": mission.status.value})

    async def _persist(self, key: WorkKey, instance: AgentInstance, fact: AgentDeclarationFact | None, lowered: bool,
                       mission: Mission | None) -> DeclarationResult:
        try:
            stored, created = await self._guard(
                "record_instance",
                self._repository.record_instance(instance, declaration=fact, ephemeral_lowered=lowered, mission=mission),
                recover=False)
        except MissionHistoryUnavailable as exc:
            self._keep_unsaved(key, _Unsaved(instance, fact, lowered, mission))
            return DeclarationResult(DeclarationOutcome.DEGRADED, instance, code=exc.code, message=str(exc))
        except (MissionError, RelationError, MissionHistoryError, MissionHistoryStoreError) as exc:
            self._unsaved.pop(key, None)
            self._recover()  # the store answered: it is reachable again
            return DeclarationResult(DeclarationOutcome.REFUSED, instance, code=getattr(exc, "code", None),
                                     message=str(exc))
        # Retiré avant `_recover`, pour que `recovered` compte exactement ce qui reste en attente.
        self._unsaved.pop(key, None)
        self._recover()
        self._remember_role(key, stored.instance.role_id)
        self._remember_mission(key, stored.instance)
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
            forgotten, _ = self._discarded.popitem(last=False)
            # Une fois par vie du service : la borne est atteinte, la plus ancienne clé ne protège plus d'un rejeu.
            self._report(("discarded_forgotten",), MISSION_HISTORY_DISCARDED_FORGOTTEN_KIND,
                         "mémoire des éphémères écartées pleine : les plus anciennes ne sont plus protégées d'un "
                         "rejeu tardif", level="warning",
                         data={"work_source": forgotten[0], "work_external_id": forgotten[1],
                               "max_discarded": MAX_DISCARDED_KEYS})
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

    def _remember_mission(self, key: WorkKey, instance: AgentInstance | None) -> None:
        self._missions[key] = (MissionRef(instance.instance_id, instance.mission_id, instance.mission_owner)
                               if instance is not None else None)
        self._missions.move_to_end(key)
        while len(self._missions) > MAX_MISSION_CACHE:
            self._missions.popitem(last=False)

    def mission_ref(self, work_source: str, work_external_id: str) -> MissionRef | None:
        """L'appartenance de mission connue d'un travail (mémoire bornée, sans E/S), ou `None`.

        Lecture synchrone pour le contexte du cerveau : elle ne dit que ce que ce Core a déjà enregistré ou lu.
        """

        return self._missions.get((work_source, work_external_id))

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
        if item.status.is_terminal:
            await self._on_terminal(key, item.status)
        pending = self._pending.get(key)
        if pending is None:
            return None
        if retained_in_history(pending.instance, item.status):
            result = await self._retain_lowered(key, pending.instance, pending.fact)
            if result.outcome is DeclarationOutcome.EPHEMERAL_RETAINED:
                self._declared(key, pending.fact, result)
        elif item.status is WorkStatus.COMPLETED:
            self._discard(key, pending.instance)
            result = DeclarationResult(DeclarationOutcome.EPHEMERAL_DISCARDED)
        else:
            return None
        self._count(result.outcome)
        return result

    async def _ref(self, key: WorkKey) -> MissionRef | None:
        """L'appartenance de mission d'un travail : mémoire bornée, sinon une lecture (mise en mémoire, même `None`)."""

        if key not in self._missions:
            stored = await self._guard("find_instance", self._repository.find_instance(*key))
            self._remember_mission(key, stored.instance if stored is not None else None)
        return self._missions.get(key)

    async def _on_terminal(self, key: WorkKey, status: WorkStatus) -> None:
        """Un travail vient de finir : noter la fin d'un propriétaire courant, réévaluer sa mission. Ne lève jamais."""

        try:
            ref = await self._ref(key)
            if ref is None or ref.mission_id is None:
                return
            if ref.mission_owner:
                mission = await self._guard("get_mission", self._repository.get_mission(ref.mission_id))
                # Seul le propriétaire COURANT compte (après un relais, la fin du prédécesseur ne dit rien).
                if mission is not None and mission.owner_instance_id == ref.instance_id and not mission.status.is_closed:
                    self._owner_ended[ref.mission_id] = status
                    self._owner_ended.move_to_end(ref.mission_id)
                    while len(self._owner_ended) > MAX_MISSION_CACHE:
                        self._owner_ended.popitem(last=False)
            await self._try_close(ref.mission_id)
        except (MissionError, MissionHistoryUnavailable, MissionHistoryStoreError, MissionHistoryError) as exc:
            self._report(("close", *key), MISSION_HISTORY_CLOSE_FAILED_KIND,
                         f"clôture de mission non évaluée : {exc}", level="warning",
                         data={"work_source": key[0], "work_external_id": key[1], "code": getattr(exc, "code", None)})

    async def _try_close(self, mission_id: str, *, live: dict[WorkKey, WorkItem] | None = None,
                         depth: int = 0) -> bool:
        """Clore `mission_id` si son propriétaire courant a fini ET que plus rien de son équipe ne vit. Rend vrai si
        la mission est close (déjà ou maintenant). Lève les erreurs du magasin (l'appelant les signale).

        Règle (Slice 05, reprise QA M2) : un membre encore vivant au regard de Work State, ou une sous-mission encore
        ouverte (réévaluée d'abord), diffère la clôture ; elle est réévaluée à chaque fin observée et à chaque
        balayage. L'issue est celle du propriétaire courant (`interrupted` → `cancelled`), lue dans Work State, ou
        retenue quand il en a été élagué. Un propriétaire dont Core ne sait rien (redémarrage, aucune fin vue) laisse
        la mission ouverte : rien n'est deviné.
        """

        live = self._live() if live is None else live
        tree = await self._guard("mission_tree", self._repository.mission_tree(mission_id))
        if tree is None:
            return False
        missions = {item.mission_id: item for item in tree.missions}
        mission = missions.get(mission_id)
        if mission is None:
            return False
        if mission.status.is_closed:
            self._owner_ended.pop(mission_id, None)
            return True

        def status_of(instance: AgentInstance) -> WorkStatus | None:
            item = live.get(instance.work_identity)
            return item.status if item is not None else None

        instances = [stored.instance for stored in tree.instances]
        owner = next((item for item in instances if item.instance_id == mission.owner_instance_id), None)
        owner_status = status_of(owner) if owner is not None else None
        if owner_status is None:
            owner_status = self._owner_ended.get(mission_id)
        if owner_status is None and self._is_orphan(mission, instances, live):
            # Aucune issue n'est inventée : la mission reste ouverte, sa vue dit « état inconnu » (`live_unknown`).
            self._report(("orphaned", mission_id), MISSION_HISTORY_ORPHANED_KIND,
                         "mission ouverte dont ni le propriétaire ni aucun membre n'est connu de Work State : "
                         "état inconnu, rien n'est deviné", level="warning",
                         data={"mission_id": mission_id, "grace_s": ORPHAN_GRACE_S})
        if owner_status is None or not owner_status.is_terminal:
            return False
        alive = [item.instance_id for item in instances if item.mission_id == mission_id
                 and item.instance_id != mission.owner_instance_id
                 and (status_of(item) is not None and not status_of(item).is_terminal)]
        open_children = []
        for child in (item for item in tree.missions if item.parent_mission_id == mission_id):
            if child.status.is_closed:
                continue
            if depth >= MAX_CLOSE_DEPTH or not await self._try_close(child.mission_id, live=live, depth=depth + 1):
                open_children.append(child.mission_id)
        if alive or open_children:
            self._report(("deferred", mission_id), MISSION_HISTORY_CLOSE_DEFERRED_KIND,
                         "propriétaire terminé, équipe encore active : clôture différée", level="info",
                         data={"mission_id": mission_id, "alive_members": len(alive),
                               "open_sub_missions": len(open_children), "owner_status": owner_status.value})
            return False
        closed = await self.close_mission(mission_id, MISSION_STATUS_FOR_WORK[owner_status])
        self._owner_ended.pop(mission_id, None)
        self._emit(MISSION_HISTORY_MISSION_CLOSED_KIND, "mission close : propriétaire terminé, équipe terminée",
                   data={"mission_id": closed.mission_id, "status": closed.status.value,
                         "owner_status": owner_status.value, "parent_mission_id": closed.parent_mission_id})
        if closed.parent_mission_id is not None and depth == 0:
            # La dernière sous-mission close peut libérer la mission parente.
            await self._try_close(closed.parent_mission_id, live=live)
        return True

    def _is_orphan(self, mission: Mission, instances: list[AgentInstance], live: dict[WorkKey, WorkItem]) -> bool:
        """Ouverte, plus vieille que le délai de grâce, Core né depuis plus que ce délai, aucune fin retenue, et ni
        son propriétaire ni aucun membre connu de Work State. Dérivé, jamais persisté."""

        now = self._clock.now()
        if (mission.status.is_closed or mission.mission_id in self._owner_ended
                or (now - self._born).total_seconds() < ORPHAN_GRACE_S
                or (now - mission.created_at).total_seconds() < ORPHAN_GRACE_S):
            return False
        team = [item for item in instances if item.mission_id == mission.mission_id
                or item.instance_id == mission.owner_instance_id]
        return all(live.get(item.work_identity) is None for item in team)

    def live_unknown(self, tree: MissionTree) -> frozenset[str]:
        """Les missions de l'arbre dont l'état vivant est inconnu (`_is_orphan`), pour la vue. Sans E/S."""

        live = self._live()
        instances = [stored.instance for stored in tree.instances]
        return frozenset(mission.mission_id for mission in tree.missions if self._is_orphan(mission, instances, live))

    async def _sweep_missions(self) -> None:
        """Réévaluer les missions ouvertes, `MAX_SWEPT_MISSIONS` par passe, par un curseur qui tourne (reprise QA) :
        clôture différée, fin perdue (bus tolérant), orphelines signalées. Ne lève jamais."""

        try:
            missions = await self._guard("open_missions_after", self._repository.open_missions_after(
                self._sweep_cursor, limit=MAX_SWEPT_MISSIONS))
            # Moins qu'une page : la fin est atteinte, la passe suivante reprend au début.
            self._sweep_cursor = ((missions[-1].created_at, missions[-1].mission_id)
                                  if len(missions) >= MAX_SWEPT_MISSIONS else None)
            live = self._live()
            for mission in missions:
                await self._try_close(mission.mission_id, live=live)
        except (MissionError, MissionHistoryUnavailable, MissionHistoryStoreError, MissionHistoryError) as exc:
            self._report(("sweep_missions", type(exc).__name__), MISSION_HISTORY_CLOSE_FAILED_KIND,
                         f"réévaluation des missions ouvertes en échec : {exc}", level="warning",
                         data={"code": getattr(exc, "code", None)})

    async def sweep(self) -> int:
        """Rattraper ce qu'un événement perdu (bus tolérant) ou un magasin indisponible a laissé en attente.

        Éphémères en attente comparées à l'instantané de Work State, puis écritures non enregistrées rejouées.
        Rend le nombre d'entrées résolues. Ne lève jamais. Un seul balayage à la fois (événement et minuterie).
        """

        async with self._sweep_lock:
            return await self._sweep()

    async def _sweep(self) -> int:
        resolved = 0
        items = self._live()
        for key in list(self._pending):
            item = items.get(key)
            if item is not None and await self.observe_work_item(item) is not None:
                resolved += 1
        for key, unsaved in list(self._unsaved.items()):
            if isinstance(unsaved, _UnsavedDeclaration):
                result = await self._declare(unsaved.fact, key, unsaved.parent_work_external_id, unsaved.mission,
                                             unsaved.inherit_mission)
                if result.outcome is not DeclarationOutcome.DEGRADED:
                    self._settled(key, result)
                    self._count(result.outcome)
                    if result.outcome in (DeclarationOutcome.RECORDED, DeclarationOutcome.EPHEMERAL_PENDING,
                                          DeclarationOutcome.EPHEMERAL_RETAINED):
                        self._declared(key, unsaved.fact, result)
            else:
                result = await self._persist(key, unsaved.instance, unsaved.fact, unsaved.lowered, unsaved.mission)
            if result.outcome is DeclarationOutcome.DEGRADED:
                break
            if result.outcome is DeclarationOutcome.REFUSED:
                # L'écriture attendue est perdue : le magasin la refuse maintenant (contrat), on le dit.
                self._emit(MISSION_HISTORY_UNSAVED_REFUSED_KIND,
                           f"écriture d'historique en attente refusée au rejeu : {result.message}", level="error",
                           data={"work_source": key[0], "work_external_id": key[1], "code": result.code})
            resolved += 1
        await self._sweep_missions()
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

    async def _guard(self, operation: str, call: Awaitable[T], *, recover: bool = True) -> T:
        """Exécuter un appel du magasin : un refus de SQLite marque l'historique dégradé, un succès le rétablit
        (`recover=False` : l'appelant rétablit lui-même, après avoir mis à jour ce qui reste en attente)."""

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
        if recover:
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
