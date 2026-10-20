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
  `MissionHistoryUnavailable` après avoir marqué l'historique dégradé ;
- Slice 06, runtime des relations (`relation_runtime`) : `open_relation`,
  `publish_message`, `finish_relation`, `read_relation` (ce que les outils des
  agents demandent, appelant résolu par son identité de travail), `prepare_handoff`
  puis la reprise du successeur dans `record_declaration` (instance, relation,
  paquet, transfert et clôture en une transaction, avant toute fin du
  prédécesseur : la clôture de la mission attend un relais préparé), la
  délégation alignée sur l'ouverture d'une sous-mission `[mission]` et close à
  sa fin, et `relation_refs` (résumés du contexte du cerveau, sans E/S).

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
from jarvis.domain.agent_relations import (
    AgentRelation, AgentRelationKind, HandoffPacket, ParticipantPosition, RelationError, RelationMessage,
    RelationMessageType, RelationOutcome, RelationParticipant,
)
from jarvis.domain import relation_runtime
from jarvis.domain.relation_runtime import PendingHandoff
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
#: Slice 06 : runtime des relations. Des ids, des codes et des tailles au journal, jamais un texte de message.
MISSION_HISTORY_RELATION_OPENED_KIND = "mission_history.relation_opened"
MISSION_HISTORY_RELATION_MESSAGE_KIND = "mission_history.relation_message"
MISSION_HISTORY_RELATION_CLOSED_KIND = "mission_history.relation_closed"
MISSION_HISTORY_RELATION_REFUSED_KIND = "mission_history.relation_refused"
MISSION_HISTORY_HANDOFF_PREPARED_KIND = "mission_history.handoff_prepared"
MISSION_HISTORY_HANDOFF_TRANSFERRED_KIND = "mission_history.handoff_transferred"
MISSION_HISTORY_HANDOFF_FAILED_KIND = "mission_history.handoff_failed"
MISSION_HISTORY_DELEGATION_FAILED_KIND = "mission_history.delegation_failed"
MISSION_HISTORY_MESSAGE_AFTER_CLOSE_KIND = "mission_history.relation_message_after_close"
#: Relations retenues par instance pour les résumés du cerveau ; instances suivies ; lectures de réchauffage par
#: balayage (après un redémarrage, le cache se remplit des travaux vivants, sans tout relire d'un coup).
MAX_RELATIONS_PER_INSTANCE = 8
MAX_RELATION_CACHE = 1_024
MAX_RELATION_WARMUPS = 16

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


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


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
        #: Slice 06 : relais préparés en attente de leur successeur (mémoire seulement, bornés, expirés au balayage).
        self._handoffs: OrderedDict[str, PendingHandoff] = OrderedDict()
        #: instance -> ses relations connues (les plus récentes en fin), pour `relation_refs` sans E/S.
        self._relations: OrderedDict[str, OrderedDict[str, AgentRelation]] = OrderedDict()

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

        if stored is None and fact.handoff_id is not None and not instance.ephemeral:
            # Slice 06 : le successeur d'un relais préparé reprend la mission, en une transaction.
            return await self._take_over(key, instance, fact, parent_work_external_id, inherit_mission)
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
            result = await self._persist(key, incoming, fact, stored.ephemeral_lowered, None)
            if result.outcome is DeclarationOutcome.DUPLICATE and stored.instance.mission_owner and _from_caller(mission):
                # Rejeu : la délégation d'une sous-mission a pu manquer (panne entre deux écritures). Idempotent.
                await self._align_delegation(stored.instance)
            return result

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
        result = await self._persist(key, instance, fact, False, opened)
        if (result.outcome is DeclarationOutcome.RECORDED and opened is not None and opened.parent_mission_id
                and result.instance is not None):
            # Slice 06 : `[mission]` est une délégation ; elle est nouée avec l'ouverture de la sous-mission.
            await self._align_delegation(result.instance, opened)
        return result

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
        pending = self._pending_handoff_for(mission_id)
        if pending is not None:
            # Slice 06 : un relais préparé attend son successeur ; la fin du prédécesseur ne clôt pas la mission.
            self._report(("deferred_handoff", mission_id, pending.handoff_id), MISSION_HISTORY_CLOSE_DEFERRED_KIND,
                         "propriétaire terminé, relais préparé en attente de son successeur : clôture différée",
                         level="info", data={"mission_id": mission_id, "handoff_id": pending.handoff_id,
                                             "owner_status": owner_status.value})
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
        if closed.parent_mission_id is not None:
            await self._return_delegation(closed)
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
        self._expire_handoffs()
        await self._warm_relations(items)
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

    # ------------------------------------------------------------ runtime des relations (Slice 06)

    async def _instance_for(self, ref: WorkKey | None, what: str) -> AgentInstance | None:
        """L'instance retenue pour une identité de travail ; refus codé si elle ne l'est pas."""

        if ref is None:
            return None
        stored = await self._guard("find_instance", self._repository.find_instance(*ref))
        if stored is None:
            raise RelationError(f"{what} {ref[0]}/{ref[1]} is not recorded in mission history",
                                code="relation_agent_not_recorded", field=what)
        return stored.instance

    async def _caller(self, ref: WorkKey | None) -> AgentInstance:
        caller = await self._instance_for(ref, "caller")
        if caller is None:
            raise RelationError("the brain is not a mission instance", code="relation_caller_not_instance",
                                field="caller")
        return caller

    async def _scope(self, mission_id: str) -> dict[str, Mission]:
        tree = await self._guard("mission_tree", self._repository.mission_tree(mission_id))
        return {mission.mission_id: mission for mission in tree.missions} if tree is not None else {}

    def _refuse(self, operation: str, exc: Exception, **data: Any) -> None:
        """Un refus de relation, dit au journal avec son code (jamais le texte reçu), puis relevé par l'appelant."""

        self._emit(MISSION_HISTORY_RELATION_REFUSED_KIND, f"relation refusée ({operation}) : {getattr(exc, 'code', '')}",
                   level="warning", data={"operation": operation, "code": getattr(exc, "code", None),
                                          "field": getattr(exc, "field", None), **data})

    async def open_relation(self, *, caller: WorkKey | None, kind: AgentRelationKind,
                            participants: list[tuple[WorkKey, ParticipantPosition]], purpose: str,
                            target_refs: tuple[str, ...] = ()) -> AgentRelation:
        """Nouer une relation demandée par un agent (communication, Adversary, QA). Lève l'erreur codée."""

        try:
            author = await self._caller(caller)
            if author.mission_id is None:
                raise RelationError(f"instance {author.instance_id} works for no mission", code="relation_no_mission",
                                    field="caller")
            members = [(await self._instance_for(ref, "participant"), position) for ref, position in participants]
            relation = AgentRelation(
                relation_id=_new_id(relation_runtime.RELATION_ID_PREFIX), kind=kind, mission_id=author.mission_id,
                participants=tuple(RelationParticipant(instance.instance_id, position) for instance, position in members),
                purpose=purpose, created_at=self._clock.now(), created_by_instance_id=author.instance_id,
                target_refs=tuple(target_refs),
            )
            relation_runtime.check_open_authority(author, relation, await self._scope(author.mission_id))
            created = await self.create_relation(relation)
        except (RelationError, MissionError) as exc:
            self._refuse("open", exc, kind=getattr(kind, "value", str(kind)))
            raise
        self._note_relation(created)
        self._emit(MISSION_HISTORY_RELATION_OPENED_KIND, "relation nouée par un agent", data={
            "relation_id": created.relation_id, "kind": created.kind.value, "mission_id": created.mission_id,
            "participants": len(created.participants), "created_by_instance_id": created.created_by_instance_id})
        return created

    async def publish_message(self, *, caller: WorkKey | None, relation_id: str, type: RelationMessageType, text: str,
                              audience: list[WorkKey] = (), artifact_refs: tuple[str, ...] = (),
                              reply_to_message_id: str | None = None) -> tuple[int, RelationMessage]:
        """Publier un message délibéré sur le tableau d'une relation. Lève l'erreur codée (contenu compris)."""

        try:
            author = await self._caller(caller)
            relation = await self._relation(relation_id)
            mission = await self._guard("get_mission", self._repository.get_mission(relation.mission_id))
            targets = [await self._instance_for(ref, "audience") for ref in audience]
            message = RelationMessage(
                message_id=_new_id(relation_runtime.MESSAGE_ID_PREFIX), relation_id=relation.relation_id,
                author_instance_id=author.instance_id, type=type, text=text,
                created_at=max(self._clock.now(), relation.created_at),
                audience=tuple(target.instance_id for target in targets if target is not None),
                artifact_refs=tuple(artifact_refs), reply_to_message_id=reply_to_message_id,
            )
            seq = await self.post_message(message)
        except (RelationError, MissionError) as exc:
            self._refuse("post", exc, relation_id=relation_id)
            raise
        self._emit(MISSION_HISTORY_RELATION_MESSAGE_KIND, "message publié sur un tableau de relation", data={
            "relation_id": relation.relation_id, "message_id": message.message_id, "seq": seq, "type": message.type.value,
            "chars": len(message.text), "author_instance_id": author.instance_id})
        if mission is not None and mission.status.is_closed:
            # Constaté en bac à sable : un agent repris par SendMessage après la fin de sa tâche travaille encore
            # quand la mission se clôt (Work State ne le voit plus vivant). Sa relation ouverte garde ce qu'il dit
            # (D18, comme un membre tardif) ; c'est dit au journal.
            self._report(("message_after_close", relation.relation_id), MISSION_HISTORY_MESSAGE_AFTER_CLOSE_KIND,
                         "message publié sur une relation ouverte d'une mission close : retenu", level="warning",
                         data={"relation_id": relation.relation_id, "mission_id": mission.mission_id,
                               "mission_status": mission.status.value})
        return seq, message

    async def finish_relation(self, *, caller: WorkKey | None, relation_id: str, outcome: RelationOutcome,
                              summary: str = "", winner: WorkKey | None = None) -> AgentRelation:
        """Clore une relation à la demande d'un agent (verdict QA, issue d'un Adversary, fin d'une communication)."""

        try:
            author = await self._caller(caller)
            relation = await self._relation(relation_id)
            winner_instance = await self._instance_for(winner, "winner")
            relation_runtime.check_close_authority(author, relation, outcome, await self._scope(relation.mission_id))
            closed = await self.close_relation(relation.relation_id, outcome, summary=summary,
                                               winner_instance_id=winner_instance.instance_id if winner_instance else None,
                                               closed_by=author.instance_id)
        except (RelationError, MissionError) as exc:
            self._refuse("close", exc, relation_id=relation_id)
            raise
        self._note_relation(closed)
        self._emit(MISSION_HISTORY_RELATION_CLOSED_KIND, "relation close", data={
            "relation_id": closed.relation_id, "kind": closed.kind.value, "outcome": closed.outcome.value,
            "closed_by_instance_id": closed.closed_by_instance_id, "winner_instance_id": closed.winner_instance_id})
        return closed

    async def read_relation(self, relation_id: str, *, after: int = 0, limit: int = 100
                            ) -> tuple[AgentRelation, tuple[tuple[int, RelationMessage], ...], tuple[InstanceView, ...]]:
        """Une relation, son fil (à partir du rang `after`) et ses participants avec leur statut vivant."""

        relation = await self._relation(relation_id)
        thread = await self.thread(relation.relation_id, after=after, limit=limit)
        live = self._live()
        views = []
        for instance_id in relation.participant_ids:
            stored = await self._guard("get_instance", self._repository.get_instance(instance_id))
            if stored is not None:
                views.append(InstanceView(stored, live_status(stored.instance, live)))
        return relation, thread, tuple(views)

    async def _relation(self, relation_id: str) -> AgentRelation:
        relation = await self._guard("get_relation", self._repository.get_relation(relation_id))
        if relation is None:
            raise RelationError(f"relation {relation_id} is unknown", code="relation_unknown", field="relation_id")
        return relation

    # -- relais

    async def prepare_handoff(self, *, caller: WorkKey | None, purpose: str, packet: HandoffPacket) -> PendingHandoff:
        """Le propriétaire courant prépare un relais : paquet validé et gardé, rien de durable avant le successeur.

        Un nouveau relais du même prédécesseur remplace le précédent, encore en attente (il n'a pas été lancé).
        """

        try:
            author = await self._caller(caller)
            mission = (await self._guard("get_mission", self._repository.get_mission(author.mission_id))
                       if author.mission_id is not None else None)
            relations = ()
            if mission is not None:
                tree = await self._guard("mission_tree", self._repository.mission_tree(mission.mission_id))
                relations = tuple(item for item in (tree.relations if tree else ()) if item.mission_id == mission.mission_id)
            relation_runtime.check_handoff_preparation(author, mission, relations)
            pending = PendingHandoff(handoff_id=_new_id(relation_runtime.HANDOFF_ID_PREFIX),
                                     mission_id=mission.mission_id, predecessor_instance_id=author.instance_id,
                                     purpose=purpose, packet=packet, prepared_at=self._clock.now())
        except (RelationError, MissionError) as exc:
            self._refuse("handoff", exc)
            raise
        for handoff_id, other in list(self._handoffs.items()):
            if other.predecessor_instance_id == author.instance_id:
                self._handoffs.pop(handoff_id, None)
        self._handoffs[pending.handoff_id] = pending
        while len(self._handoffs) > relation_runtime.MAX_PENDING_HANDOFFS:
            dropped, old = self._handoffs.popitem(last=False)
            self._emit(MISSION_HISTORY_HANDOFF_FAILED_KIND, "trop de relais préparés : le plus ancien est oublié",
                       level="warning", data={"handoff_id": dropped, "mission_id": old.mission_id,
                                              "code": "handoff_pending_dropped"})
        self._emit(MISSION_HISTORY_HANDOFF_PREPARED_KIND, "relais préparé : en attente de son successeur", data={
            "handoff_id": pending.handoff_id, "mission_id": pending.mission_id,
            "predecessor_instance_id": author.instance_id})
        return pending

    def pending_handoff(self, handoff_id: str) -> PendingHandoff | None:
        pending = self._handoffs.get(handoff_id)
        return pending if pending is not None and not pending.expired(self._clock.now()) else None

    def _pending_handoff_for(self, mission_id: str) -> PendingHandoff | None:
        now = self._clock.now()
        return next((item for item in self._handoffs.values()
                     if item.mission_id == mission_id and not item.expired(now)), None)

    def _expire_handoffs(self) -> None:
        now = self._clock.now()
        for handoff_id, pending in list(self._handoffs.items()):
            if pending.expired(now):
                self._handoffs.pop(handoff_id, None)
                self._emit(MISSION_HISTORY_HANDOFF_FAILED_KIND, "relais préparé expiré sans successeur", level="warning",
                           data={"handoff_id": handoff_id, "mission_id": pending.mission_id, "code": "handoff_expired",
                                 "ttl_s": relation_runtime.HANDOFF_TTL_S})

    async def _take_over(self, key: WorkKey, instance: AgentInstance, fact: AgentDeclarationFact,
                         parent_work_external_id: str | None, inherit_mission: bool) -> DeclarationResult:
        """Le successeur d'un relais : instance, relation (paquet), transfert, clôture — en une transaction.

        Relais inconnu, expiré, d'une autre mission ou d'un autre prédécesseur, ou refusé par le magasin : le
        successeur est quand même retenu (il a tourné, D18), sans devenir propriétaire, et c'est dit à l'erreur.
        """

        pending = self.pending_handoff(fact.handoff_id or "")
        problem = None
        if pending is None:
            problem = "handoff_unknown"
        elif pending.mission_id != instance.mission_id:
            problem = "handoff_mission_mismatch"
        elif instance.parent_instance_id != pending.predecessor_instance_id:
            problem = "handoff_wrong_predecessor"
        if problem is None:
            now = self._clock.now()
            try:
                relation = relation_runtime.handoff_relation(pending, relation_id=_new_id(relation_runtime.RELATION_ID_PREFIX),
                                                             successor=instance, at=now)
                stored, closed, mission = await self._guard("record_handoff", self._repository.record_handoff(
                    instance, declaration=fact, relation=relation, at=relation.created_at,
                    summary="Propriété de la mission transférée au successeur."), recover=False)
            except MissionHistoryUnavailable as exc:
                self._keep_unsaved(key, _UnsavedDeclaration(fact, parent_work_external_id, None, inherit_mission))
                return DeclarationResult(DeclarationOutcome.DEGRADED, instance, code=exc.code, message=str(exc))
            except (MissionError, RelationError, MissionHistoryError, MissionHistoryStoreError) as exc:
                problem = getattr(exc, "code", None) or "handoff_refused"
                detail = str(exc)[:300]
            else:
                self._handoffs.pop(pending.handoff_id, None)
                self._unsaved.pop(key, None)
                self._recover()
                self._remember_role(key, stored.instance.role_id)
                self._remember_mission(key, stored.instance)
                self._note_relation(closed)
                self._emit(MISSION_HISTORY_HANDOFF_TRANSFERRED_KIND, "relais : mission transférée au successeur", data={
                    "handoff_id": pending.handoff_id, "relation_id": closed.relation_id, "mission_id": mission.mission_id,
                    "predecessor_instance_id": pending.predecessor_instance_id,
                    "successor_instance_id": stored.instance.instance_id})
                return DeclarationResult(DeclarationOutcome.RECORDED, stored.instance)
        else:
            detail = problem
        self._report(("handoff", *key), MISSION_HISTORY_HANDOFF_FAILED_KIND,
                     f"relais non transféré ({problem}) : le successeur est retenu sans la propriété de la mission",
                     level="error", data={"work_source": key[0], "work_external_id": key[1], "code": problem,
                                          "handoff_id": fact.handoff_id, "detail": detail})
        return await self._persist(key, instance, fact, False, None)

    # -- délégation alignée sur `[mission]`

    async def _align_delegation(self, owner: AgentInstance, mission: Mission | None = None) -> None:
        """La délégation de la sous-mission que `owner` vient d'ouvrir : délégant = l'instance appelante. Ne lève
        jamais : un échec est dit (`mission_history.delegation_failed`), la déclaration reste enregistrée."""

        try:
            if owner.parent_instance_id is None or owner.mission_id is None:
                return
            mission = mission or await self._guard("get_mission", self._repository.get_mission(owner.mission_id))
            if mission is None or mission.parent_mission_id is None:
                return
            parent = await self._guard("get_instance", self._repository.get_instance(owner.parent_instance_id))
            if parent is None or parent.instance.mission_id != mission.parent_mission_id:
                return  # l'appelant ne travaille pas pour la mission parente : pas de délégation à affirmer
            relation = relation_runtime.delegation_relation(delegator=parent.instance, delegatee=owner,
                                                            sub_mission=mission, at=mission.created_at)
            self._note_relation(await self.create_relation(relation))
        except (MissionError, RelationError, MissionHistoryError, MissionHistoryUnavailable,
                MissionHistoryStoreError) as exc:
            self._report(("delegation", owner.instance_id), MISSION_HISTORY_DELEGATION_FAILED_KIND,
                         f"délégation de la sous-mission non nouée : {exc}", level="warning",
                         data={"instance_id": owner.instance_id, "mission_id": owner.mission_id,
                               "code": getattr(exc, "code", None)})

    async def _return_delegation(self, sub_mission: Mission) -> None:
        """Clore `returned` la délégation d'une sous-mission close. Ne lève jamais."""

        relation_id = relation_runtime.delegation_relation_id(sub_mission.mission_id)
        try:
            relation = await self._guard("get_relation", self._repository.get_relation(relation_id))
            if relation is None or not relation.is_open:
                return
            closed = await self.close_relation(relation_id, RelationOutcome.RETURNED,
                                               summary=f"Sous-mission close : {sub_mission.status.value}.")
            self._note_relation(closed)
        except (MissionError, RelationError, MissionHistoryError, MissionHistoryUnavailable,
                MissionHistoryStoreError) as exc:
            self._report(("delegation_return", sub_mission.mission_id), MISSION_HISTORY_DELEGATION_FAILED_KIND,
                         f"délégation non close à la fin de la sous-mission : {exc}", level="warning",
                         data={"mission_id": sub_mission.mission_id, "code": getattr(exc, "code", None)})

    # -- résumés pour le contexte du cerveau

    def _note_relation(self, relation: AgentRelation) -> None:
        for instance_id in relation.participant_ids:
            known = self._relations.setdefault(instance_id, OrderedDict())
            known[relation.relation_id] = relation
            known.move_to_end(relation.relation_id)
            while len(known) > MAX_RELATIONS_PER_INSTANCE:
                known.popitem(last=False)
            self._relations.move_to_end(instance_id)
        while len(self._relations) > MAX_RELATION_CACHE:
            self._relations.popitem(last=False)

    def relation_refs(self, work_source: str, work_external_id: str) -> tuple[str, ...]:
        """Les relations connues d'un travail, une ligne chacune, les plus récentes d'abord. Sans E/S."""

        ref = self._missions.get((work_source, work_external_id))
        if ref is None:
            return ()
        known = self._relations.get(ref.instance_id)
        if not known:
            return ()
        relations = list(known.values())[::-1][:relation_runtime.MAX_BRAIN_RELATIONS]
        return tuple(relation_runtime.relation_summary(item, ref.instance_id) for item in relations)

    async def _warm_relations(self, items: dict[WorkKey, WorkItem]) -> None:
        """Après un redémarrage, relire les relations des travaux vivants retenus (borné par balayage)."""

        budget = MAX_RELATION_WARMUPS
        for key, item in items.items():
            if budget <= 0:
                return
            ref = self._missions.get(key)
            if ref is None or item.status.is_terminal or ref.instance_id in self._relations:
                continue
            budget -= 1
            try:
                found = await self._guard("relations_of_instance",
                                          self._repository.relations_of_instance(ref.instance_id))
            except (MissionHistoryUnavailable, MissionHistoryStoreError):
                return  # intentional: `_guard` reported the store failure; the next sweep retries
            self._relations.setdefault(ref.instance_id, OrderedDict())
            for relation in reversed(found):
                self._note_relation(relation)

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
