"""Projection runtime de l'état de travail vers la scène (handoff jarvis-constellation-scene-runtime, Slice 04).

Sans aucun tour du cerveau, chaque sous-agent réel et chaque job Core devient
une étoile de la scène, les liens parent → enfant apparaissent et les fins
anormales ou les blocages y posent un signal minimal (Décisions 3, 4, 17).

    WorkStateStore ──core.work.updated──► CoreEventBus ──(abonné tolérant)──► SceneProjector
          ▲                                                                       │ actor=runtime
          └────────────── snapshot() (démarrage, trou, autre store_id) ◄──────────┤
                                                                                  ▼
                                                                         SceneService.apply()

Règles (voir `docs/ARCHITECTURE.md` › *Runtime scene projection*) :

- **étoiles** : un travail `kind = agent` (sous-agent Claude) ou `kind = job`
  (job Core) devient une étoile `agent` / `job`. `shell` et `other` n'en
  deviennent jamais (Décision 4) ;
- **identité** : `star_object_id(source, external_id)`, déterministe et
  injective ; la même règle dérive l'identifiant du signal et du lien parent ;
- **vérité** : `exec_state` reflète `WorkStatus`, `work_ref` porte
  `(source, external_id, work_id)`. Une fin ne change ni la visibilité ni la
  disposition (Décision 12). La catégorie et la charge ne sont posées qu'à la
  création ; ensuite la charge n'est rafraîchie que tant qu'elle est encore
  celle que la projection a écrite (le cerveau ou l'utilisateur peuvent la
  réécrire, la projection ne l'écrase pas) ;
- **topologie** : `parent_external_id` (même source) donne un `parent_of`
  parent → enfant dès que les deux étoiles existent, dans quelque ordre
  qu'elles arrivent. Un parent sans étoile (commande shell) ne donne rien ;
- **signaux** : `failed`, `interrupted`, `blocked` → un seul objet `attention`
  vivant par travail, mis à jour sur place et relié par `attach_signal`. Quand
  le travail quitte cet état, la projection retire son propre signal : elle
  délie le lien `explains` (droit ouvert au runtime par la Slice 04) puis note
  l'état du travail dans l'`exec_state` du signal ;
- **fin** : le passage à un état terminal (`completed`, `failed`, `cancelled`,
  `interrupted`) journalise `core.scene.star_finished`, une seule fois par
  étoile (un état terminal ne le redevient pas). Rien d'autre ne change : la
  page seule en tire une marque (anneau vert et coche pour une fin normale,
  rouge et croix pour un échec) ;
- **archivé** : une étoile archivée par l'utilisateur ne renaît jamais ; la
  projection lit la pierre tombale avant d'écrire et n'envoie rien ;
- **redémarrage de Core** (Slice 10) : au démarrage, avant la première
  réconciliation, chaque étoile runtime dont l'`exec_state` n'est pas
  terminal passe à `unknown` (« état inconnu depuis le redémarrage ») : l'état
  de travail de Core, en mémoire, est reparti vide. Une observation du même
  `(source, external_id)` rend l'état réel. Après `restart_grace_s` (au moins
  deux renvois complets d'un producteur), une étoile encore `unknown` passe à
  `interrupted` avec un signal `core_restarted_unobserved`, signal d'abord.
  Rien n'est supprimé, aucune disposition ne change, et un changement de
  `store_id` en cours de vie ne marque rien ;
- **saturation** : scène pleine (`MAX_SCENE_OBJECTS`), une création d'étoile
  ou de signal est différée, pas perdue tant que Core tourne. Le travail est
  retenu en mémoire (dernier état connu, au plus `MAX_PENDING_CREATIONS` ; au-delà
  les plus anciens terminés sont oubliés d'abord, et comptés). Dès que de la
  place se libère (archivage de l'utilisateur, ou au plus tard toutes les
  `saturation_retry_s`), les créations différées reprennent : travail en cours
  d'abord (Décision 4), puis travail terminé, les plus anciens d'abord dans
  chaque groupe. L'avertissement de saturation est limité à un toutes les
  `SATURATION_WARNING_INTERVAL_S`. Décision 12 : rien n'est retiré
  automatiquement.

Robustesse : l'abonnement est tolérant (`lossy=True`), jamais évincé et sans
effet sur les autres abonnés. Un saut de révision, un autre `store_id` ou le
démarrage déclenchent une réconciliation bornée depuis
`WorkStateStore.snapshot()` (au plus `MAX_WORK_ITEMS` éléments). Une scène
indisponible ou une écriture échouée est journalisée une fois par panne ; la
projection réessaie avec un délai croissant et réconcilie au retour. Rien
n'est publié sur le bus.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import time
from typing import Callable, Protocol

from jarvis.core.v2_services import JOB_WORK_SOURCE, CoreEventBus, NullDiagnosticSink
from jarvis.core.work_state import CORE_WORK_UPDATED
from jarvis.domain._checks import MAX_ID_CHARS
from jarvis.domain.scene import (
    EXECUTION_KINDS,
    MAX_PAYLOAD_SUMMARY_CHARS,
    MAX_SCENE_OBJECTS,
    MAX_TITLE_CHARS,
    ExecState,
    RelationKind,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneObject,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    SceneUpdate,
    TERMINAL_EXEC_STATES,
    WorkRef,
    is_live_signal,
)
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.domain.work_state import MAX_SUMMARY_CHARS, WorkItem, WorkSnapshot, WorkStatus, clip_text
from jarvis.ports.scene import SceneStoreError
from jarvis.ports.v2 import DiagnosticSink

SCENE_PROJECTION_RECONCILED_KIND = "core.scene.projection_reconciled"
SCENE_PROJECTION_UNAVAILABLE_KIND = "core.scene.projection_unavailable"
SCENE_PROJECTION_RESTORED_KIND = "core.scene.projection_restored"
SCENE_PROJECTION_FAILED_KIND = "core.scene.projection_failed"
SCENE_PROJECTION_CONFLICT_KIND = "core.scene.projection_conflict"
SCENE_STAR_CREATED_KIND = "core.scene.star_created"
#: Fin de travail : l'étoile vient d'atteindre un état terminal
#: (`completed`, `failed`, `cancelled`, `interrupted`). Pendant de
#: `star_created` : la page en fait un anneau vert (fin normale) ou rouge
#: (échec) autour de l'étoile, avec sa petite icône.
SCENE_STAR_FINISHED_KIND = "core.scene.star_finished"
SCENE_SIGNAL_RAISED_KIND = "core.scene.signal_raised"
SCENE_SIGNAL_RETIRED_KIND = "core.scene.signal_retired"
SCENE_PROJECTION_SATURATED_KIND = "core.scene.projection_saturated"
SCENE_PROJECTION_DESATURATED_KIND = "core.scene.projection_desaturated"
SCENE_PROJECTION_PENDING_OVERFLOW_KIND = "core.scene.projection_pending_overflow"
#: Slice 10 : une ligne de synthèse au marquage (démarrage), une à la fin de
#: la grâce ; le détail par étoile au niveau `debug`.
SCENE_RESTART_MARKED_KIND = "core.scene.restart_marked"
SCENE_RESTART_GRACE_EXPIRED_KIND = "core.scene.restart_grace_expired"
SCENE_RESTART_STAR_KIND = "core.scene.restart_star"

#: `error_class` (titre du signal) d'une étoile jamais revue après un
#: redémarrage de Core, au terme de la grâce.
CORE_RESTARTED_UNOBSERVED = "core_restarted_unobserved"
#: Grâce entre le marquage `unknown` et l'interruption des étoiles non revues.
#: Alignée sur le renvoi des producteurs : le relais du Control Center renvoie
#: tout son état au plus tard toutes les 30 s au repos, et son délai croissant
#: plafonne à 30 s quand Core est resté longtemps injoignable ; son premier
#: envoi à un Core redémarré réussit alors en ~31 s (jeton relu et renvoyé
#: aussitôt). 60 s couvrent deux périodes de renvoi : un renvoi manqué ou lent
#: ne fait pas interrompre à tort. Surchargée par
#: `JARVIS_SCENE_RESTART_GRACE_S` (validation réelle, tests).
RESTART_GRACE_S = 60.0
#: Au plus tant d'identifiants d'étoile dans une ligne de synthèse.
_RESTART_SAMPLE = 16
#: Résumé du signal posé à la fin de la grâce (texte de l'utilisateur).
_UNOBSERVED_SUMMARY = (
    "Core a redémarré et aucun producteur n'a redit ce travail pendant la grâce : "
    "il est considéré comme interrompu."
)

#: `WorkItem.kind` qui devient une étoile. `shell` et `other` : jamais
#: (Décision 4). La catégorie de l'étoile reprend ce jeton.
STAR_WORK_KINDS: dict[str, SceneObjectKind] = {"agent": SceneObjectKind.AGENT, "job": SceneObjectKind.JOB}
#: Statuts qui posent un signal vivant.
SIGNAL_STATUSES = frozenset({WorkStatus.FAILED, WorkStatus.INTERRUPTED, WorkStatus.BLOCKED})
#: File de l'abonné tolérant : une rafale perd les plus anciens événements,
#: rattrapés par la réconciliation (saut de révision), jamais l'abonnement.
PROJECTION_QUEUE_SIZE = 512
#: Message borné d'un signal.
MAX_SIGNAL_MESSAGE_CHARS = 240
#: Charges écrites retenues pour savoir si une étoile porte encore la charge de
#: la projection. Au-delà, la plus ancienne est oubliée (repli : même titre).
MAX_REMEMBERED_PAYLOADS = 1_024
#: Créations différées retenues pendant une saturation. Au-delà, la plus
#: ancienne est oubliée (comptée, journalisée une fois par épisode) : elle ne
#: revient que si son travail est encore dans l'instantané de Core.
MAX_PENDING_CREATIONS = 1_024
#: Contrôle d'espace périodique pendant une saturation (borne de
#: `wait_for_revision`) ; un archivage le déclenche aussitôt.
SATURATION_RETRY_S = 30.0
#: Au plus un avertissement `projection_saturated` par intervalle : à la limite,
#: un utilisateur qui archive une étoile par nouveau sous-agent ouvre un
#: épisode par sous-agent. Les épisodes tus sont comptés dans le suivant.
SATURATION_WARNING_INTERVAL_S = 600.0
#: Type interne que la veille d'espace met dans la file de la projection ;
#: jamais publié sur le bus.
_SPACE_CHECK = "scene.projection.space_check"
#: Réveil de la boucle au terme de la grâce de redémarrage (même file, jamais le bus).
_RESTART_GRACE = "scene.projection.restart_grace"
#: Réveil de la boucle pour un marquage de redémarrage demandé après `start()`.
_RESTART_REQUESTED = "scene.projection.restart_requested"
_MAX_REPORTED = 64
_HASH_CHARS = 24


# ------------------------------------------------------------------ identités


def _bounded_id(head: str, separator: str, body: str, hash_key: str) -> str:
    """`head + separator + body` s'il tient dans `MAX_ID_CHARS`, sinon une forme hachée.

    Forme hachée : `head + "#" + sha256(hash_key)[:24] + separator + début de body`.
    `#` n'apparaît jamais dans `head` (jeton ou marqueur fixe), donc une forme
    hachée ne peut pas égaler une forme courte ; deux formes hachées ne
    coïncident que si 96 bits de SHA-256 coïncident.
    """

    short = f"{head}{separator}{body}"
    if len(short) <= MAX_ID_CHARS:
        return short
    digest = hashlib.sha256(hash_key.encode("utf-8")).hexdigest()[:_HASH_CHARS]
    prefix = f"{head}#{digest}{separator}"
    # `rstrip` : un identifiant ne finit pas par une espace ; le hachage garde
    # l'identité même si la coupe tombe sur des espaces.
    return (prefix + body[: MAX_ID_CHARS - len(prefix)]).rstrip()


def star_object_id(source: str, external_id: str) -> str:
    """Identifiant de l'étoile du travail `(source, external_id)`.

    `source:external_id` (lisible, et injectif : une source est un jeton sans
    `:`), ou `source#<hachage>:<début>` au-delà de 128 caractères.
    """

    return _bounded_id(source, ":", external_id, f"{source}\x00{external_id}")


def signal_object_id(star_id: str) -> str:
    """Identifiant de l'unique signal d'une étoile : `attention!<étoile>`.

    `!` précède tout `:` : aucun identifiant d'étoile (dont la tête est un
    jeton, éventuellement suivi de `#<hachage>`) n'a cette forme.
    """

    return _bounded_id("attention", "!", star_id, star_id)


def parent_relation_id(child_star_id: str) -> str:
    """Identifiant du lien `parent_of` vers une étoile : `parent_of!<enfant>`.

    Un travail n'a qu'un parent (`parent_external_id` ne se réécrit pas) :
    l'enfant suffit à nommer le lien.
    """

    return _bounded_id("parent_of", "!", child_star_id, child_star_id)


# ------------------------------------------------------------------ ports


class WorkProjectionSource(Protocol):
    """Ce que la projection lit de l'état de travail : `WorkStateStore` le fournit."""

    store_id: str

    async def snapshot(self) -> WorkSnapshot: ...


#: Remet à l'état de travail l'issue persistée de jobs terminés ; rend le
#: nombre d'issues remises (`JobService.observe_persisted_outcomes`). Reçoit
#: `job id → work_id` connu de l'étoile (`None` si aucun).
JobOutcomeSource = Callable[[Mapping[str, str | None]], Awaitable[int]]


class SceneProjectionTarget(Protocol):
    """Ce que la projection utilise de la scène : `SceneService` le fournit."""

    async def apply(self, command: SceneCommand) -> SceneUpdate: ...

    async def snapshot(self) -> SceneSnapshot: ...

    async def wait_for_revision(self, after: int, *, timeout_s: float) -> int: ...


@dataclass(slots=True)
class SceneProjectionStats:
    """Compteurs lisibles par les tests et le diagnostic."""

    events: int = 0
    stale_events: int = 0
    reconciliations: int = 0
    gaps: int = 0
    store_changes: int = 0
    applied: int = 0
    duplicate: int = 0
    refused: int = 0
    skipped_archived: int = 0
    outages: int = 0
    failures: int = 0
    deferred: int = 0
    caught_up: int = 0
    pending_dropped: int = 0
    restart_marked: int = 0
    restart_reobserved: int = 0
    restart_interrupted: int = 0


# ------------------------------------------------------------------ texte


def _title(text: str) -> str:
    return clip_text(text, MAX_TITLE_CHARS)


def _multiline(text: str, limit: int) -> str:
    """Texte multiligne accepté par la scène : ni `\\r` ni autre contrôle C0 que `\\n` et `\\t`."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(ch if ch >= " " or ch in "\n\t" else " " for ch in normalized)
    return clip_text(cleaned, limit, single_line=False) if cleaned.strip() else ""


def star_payload(item: WorkItem) -> ScenePayload:
    return ScenePayload(
        title=_title(item.label),
        summary=_multiline(item.summary, min(MAX_SUMMARY_CHARS, MAX_PAYLOAD_SUMMARY_CHARS)),
    )


def signal_payload(item: WorkItem) -> ScenePayload:
    """`error_class` (ou le statut) en titre, un message borné en résumé."""

    message = item.activity if item.status is WorkStatus.BLOCKED and item.activity else item.summary
    return ScenePayload(
        title=_title(item.error_class or item.status.value),
        summary=_multiline(message, MAX_SIGNAL_MESSAGE_CHARS),
    )


def work_ref(item: WorkItem) -> WorkRef:
    return WorkRef(source=item.source, external_id=item.external_id, work_id=item.link.work_id)


# ------------------------------------------------------------------ projecteur


class SceneProjector:
    """Écrivain runtime de la scène, abonné à `core.work.updated`.

    Une tâche, une file tolérante. `start()` s'abonne puis réconcilie ;
    `stop()` se désabonne, laisse traiter ce qui est déjà en file (au plus
    `stop_drain_s`) puis s'arrête. Il doit être arrêté avant la fermeture de la
    scène.
    """

    def __init__(
        self,
        *,
        work: WorkProjectionSource,
        scene: SceneProjectionTarget,
        events: CoreEventBus,
        diagnostics: DiagnosticSink | None = None,
        queue_size: int = PROJECTION_QUEUE_SIZE,
        retry_min_s: float = 1.0,
        retry_max_s: float = 30.0,
        stop_drain_s: float = 2.0,
        max_pending: int = MAX_PENDING_CREATIONS,
        saturation_retry_s: float = SATURATION_RETRY_S,
        saturation_warning_interval_s: float = SATURATION_WARNING_INTERVAL_S,
        monotonic: Callable[[], float] = time.monotonic,
        restart_grace_s: float = RESTART_GRACE_S,
        job_outcomes: JobOutcomeSource | None = None,
    ) -> None:
        if (
            queue_size < 1 or retry_min_s <= 0 or retry_max_s < retry_min_s or stop_drain_s < 0
            or max_pending < 1 or saturation_retry_s <= 0 or saturation_warning_interval_s < 0
            or not restart_grace_s > 0
        ):
            raise ValueError("invalid scene projector bounds")
        self._work = work
        self._scene = scene
        self._events = events
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._queue_size = queue_size
        self._retry_min_s = retry_min_s
        self._retry_max_s = retry_max_s
        self._stop_drain_s = stop_drain_s
        self._queue: asyncio.Queue[ProtocolEnvelope] | None = None
        self._task: asyncio.Task[None] | None = None
        self._idle = asyncio.Event()
        #: Raison de la prochaine réconciliation, `None` si à jour.
        self._dirty: str | None = None
        self._store_id: str | None = None
        self._revision = 0
        self._unavailable = False
        self._suppressed = 0
        self._reported: set[str] = set()
        self._written: OrderedDict[str, ScenePayload] = OrderedDict()
        self._max_pending = max_pending
        self._saturation_retry_s = saturation_retry_s
        #: Créations différées faute de place, par travail, dans l'ordre du
        #: premier report ; la valeur est le dernier état connu du travail.
        self._pending: OrderedDict[tuple[str, str], WorkItem] = OrderedDict()
        #: Épisode de saturation en cours : `None`, ou ses compteurs.
        self._saturation: dict[str, int] | None = None
        #: L'épisode en cours a-t-il été annoncé (limitation des avertissements) ?
        self._saturation_warned = False
        self._saturation_warning_interval_s = saturation_warning_interval_s
        self._monotonic = monotonic
        self._last_saturation_warning: float | None = None
        self._episodes_silenced = 0
        self._deferred_key: tuple[str, str] | None = None
        self._watch: asyncio.Task[None] | None = None
        self._stopping = False
        # Réconciliation de redémarrage (Slice 10).
        self._restart_grace_s = restart_grace_s
        self._job_outcomes = job_outcomes
        #: Marquage demandé et pas encore mené à bout (scène indisponible,
        #: écriture échouée) : la boucle le reprend avant de réconcilier.
        self._restart_due = False
        #: Étoiles marquées `unknown` et pas encore revues : travail → étoile.
        self._restart_tracked: dict[tuple[str, str], str] = {}
        #: Compteurs de l'épisode de redémarrage, journalisés en synthèse.
        self._restart_counts: dict[str, int] = {}
        self._grace: asyncio.Task[None] | None = None
        #: La grâce a expiré : les étoiles encore suivies sont à interrompre.
        self._grace_due = False
        #: Interruptions en cours (signal différé faute de place) : travail →
        #: (constat synthétique, étoile). Le constat est l'entrée de l'attente.
        self._unobserved: dict[tuple[str, str], tuple[WorkItem, str]] = {}
        self.stats = SceneProjectionStats()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def pending_count(self) -> int:
        """Créations d'étoile ou de signal en attente de place."""

        return len(self._pending)

    @property
    def restart_marking_pending(self) -> bool:
        """Vrai tant que le marquage de redémarrage demandé n'est pas fait (la boucle le mène)."""

        return self._restart_due

    @property
    def restart_tracked_count(self) -> int:
        """Étoiles marquées `unknown` au redémarrage et pas encore revues ni interrompues."""

        return len(self._restart_tracked)

    # ------------------------------------------------------------ cycle de vie

    def start(self) -> None:
        """S'abonner (avant toute lecture, pour ne rien manquer) puis lancer la boucle."""

        if self._task is not None:
            return
        self._queue = self._events.subscribe(max_queue=self._queue_size, lossy=True)
        self._stopping = False
        self._dirty = "start"
        self._task = asyncio.get_running_loop().create_task(self._run(self._queue), name="jarvis-scene-projector")

    async def stop(self) -> None:
        task, self._task = self._task, None
        queue, self._queue = self._queue, None
        # Plus aucune veille d'espace ne démarre à partir d'ici, même si le
        # vidage ci-dessous diffère encore des créations.
        self._stopping = True
        if queue is not None:
            self._events.unsubscribe(queue)
        if task is None:
            await self._stop_watch()
            await self._stop_grace()
            return
        if not task.done() and self._stop_drain_s > 0:
            # Les fins posées pendant l'arrêt (jobs annulés) sont déjà en file :
            # on les laisse atteindre la scène, dans une borne.
            try:
                async with asyncio.timeout(self._stop_drain_s):
                    while not (self._idle.is_set() and (queue is None or queue.empty())):
                        self._idle.clear()
                        await self._idle.wait()
            except TimeoutError:
                pass
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # Après le vidage et la boucle : aucune veille ni minuterie de grâce ne leur survit.
        await self._stop_watch()
        await self._stop_grace()

    async def _stop_grace(self) -> None:
        grace, self._grace = self._grace, None
        if grace is not None:
            grace.cancel()
            await asyncio.gather(grace, return_exceptions=True)

    async def _stop_watch(self) -> None:
        watch, self._watch = self._watch, None
        if watch is not None:
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)

    # ------------------------------------------------------------ boucle

    async def _run(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        retry = self._retry_min_s
        grace_retry = self._retry_min_s
        while True:
            try:
                if self._dirty is not None:
                    if not await self._reconcile(self._dirty):
                        await self._wait_outage(queue, retry)
                        retry = min(retry * 2, self._retry_max_s)
                        continue
                    retry = self._retry_min_s
                if self._grace_due:
                    try:
                        await self._expire_grace()
                        grace_retry = self._retry_min_s
                    except SceneStoreError as exc:
                        # Les étoiles non traitées restent suivies et
                        # `_grace_due` reste vrai : reprise après réconciliation.
                        self._outage(exc)
                        continue
                    except Exception as exc:
                        # Défaut hors scène (lecture de l'état de travail…) :
                        # journalisé une fois par type, puis attente croissante
                        # comme une panne — jamais de boucle à vide. La file est
                        # vidée pendant l'attente : la réconciliation qui suit
                        # couvre ces événements.
                        self._failed("restart_grace", exc)
                        self._dirty = "restart_grace_failed"
                        await self._wait_outage(queue, grace_retry)
                        grace_retry = min(grace_retry * 2, self._retry_max_s)
                        continue
                if queue.empty():
                    self._idle.set()
                envelope = await queue.get()
                self._idle.clear()
                await self._handle(envelope)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Garde-fou : la projection ne s'arrête jamais sur un défaut ;
                # l'état reste lisible dans Core. Une réconciliation qui échoue
                # ainsi attend comme une panne, pour ne pas tourner à vide.
                self._failed("loop", exc)
                if self._dirty is not None:
                    await self._wait_outage(queue, retry)
                    retry = min(retry * 2, self._retry_max_s)

    async def _wait_outage(self, queue: asyncio.Queue[ProtocolEnvelope], delay: float) -> None:
        """Attendre `delay` en vidant la file : la réconciliation suivante couvre ces événements."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + delay
        self._idle.set()
        while (remaining := deadline - loop.time()) > 0:
            try:
                async with asyncio.timeout(remaining):
                    await queue.get()
            except TimeoutError:
                return

    async def _handle(self, envelope: ProtocolEnvelope) -> None:
        if envelope.message_type in (_RESTART_GRACE, _RESTART_REQUESTED):
            return  # simple réveil : la boucle traite `_grace_due` / le marquage en tête de tour
        if envelope.message_type == _SPACE_CHECK:
            if self._pending and self._dirty is None:
                try:
                    await self._catch_up()
                except SceneStoreError as exc:
                    self._outage(exc)
            return
        if envelope.message_type != CORE_WORK_UPDATED:
            return
        self.stats.events += 1
        payload = envelope.payload
        try:
            store_id = payload["store_id"]
            revision = payload["revision"]
            if not isinstance(store_id, str) or isinstance(revision, bool) or not isinstance(revision, int):
                raise TypeError("store_id or revision has the wrong type")
            item = WorkItem.from_payload(payload["item"])
        except (KeyError, TypeError, ValueError) as exc:
            self._report_once(
                f"invalid:{type(exc).__name__}",
                SCENE_PROJECTION_FAILED_KIND,
                "événement d'état de travail illisible : la projection se réconcilie depuis l'instantané",
                level="warning",
                data={"error": type(exc).__name__},
            )
            self._dirty = "invalid_event"
            return
        if store_id != self._store_id:
            self.stats.store_changes += 1
            self._dirty = "store_changed"
            return
        if revision <= self._revision:
            # Déjà couvert par la dernière réconciliation.
            self.stats.stale_events += 1
            return
        if revision != self._revision + 1:
            self.stats.gaps += 1
            self._dirty = "revision_gap"
            return
        self._revision = revision
        try:
            if self._pending and item.status.is_terminal:
                # De la place a pu se libérer : l'attente passe avant un travail fini.
                await self._catch_up()
                await self._project(item)
            else:
                # Un travail en cours devient une étoile tout de suite (Décision 4),
                # avant l'attente ; le rattrapage suit.
                await self._project(item)
                if self._pending:
                    await self._catch_up()
        except SceneStoreError as exc:
            self._outage(exc)
        except Exception as exc:
            self._failed("event", exc)

    # ------------------------------------------------------------ réconciliation

    async def _reconcile(self, reason: str) -> bool:
        """Projeter tout l'instantané de travail ; faux si la scène ne répond pas."""

        if self._restart_due:
            # Marquage de redémarrage resté en suspens : avant l'instantané,
            # pour que tout travail déjà présent rende aussitôt l'état réel.
            try:
                await self._mark_restart()
            except SceneStoreError as exc:
                self._outage(exc)
                return False
            except Exception as exc:
                # Un défaut du marquage ne doit pas arrêter la projection.
                self._restart_abandoned(exc)
        store_id = self._work.store_id
        work = await self._work.snapshot()
        before = (self.stats.applied, self.stats.refused)
        try:
            await self._scene.snapshot()  # sonde : lève si la scène est indisponible
            for item in work.items:
                try:
                    await self._project(item)
                except SceneStoreError:
                    raise
                except Exception as exc:
                    self._failed("reconcile", exc)
            if self._pending:
                await self._catch_up()
        except SceneStoreError as exc:
            self._outage(exc)
            return False
        self._store_id, self._revision, self._dirty = store_id, work.revision, None
        self.stats.reconciliations += 1
        if self._unavailable:
            self._unavailable = False
            self._emit(
                SCENE_PROJECTION_RESTORED_KIND,
                "scène de nouveau joignable : projection réconciliée",
                data={"suppressed": self._suppressed},
            )
            self._suppressed = 0
        self._emit(
            SCENE_PROJECTION_RECONCILED_KIND,
            "projection de la scène réconciliée depuis l'état de travail",
            data={
                "reason": reason,
                "store_id": store_id,
                "work_revision": work.revision,
                "items": len(work.items),
                "applied": self.stats.applied - before[0],
                "refused": self.stats.refused - before[1],
            },
        )
        return True

    # ------------------------------------------------------------ redémarrage (Slice 10)

    async def reconcile_restart(self) -> None:
        """Au démarrage de Core : demander le marquage `unknown` des étoiles d'une vie précédente.

        Ne bloque pas (décision PM, suivi final Slice 10) : la disponibilité de
        Core n'attend pas un commit par étoile. Le marquage est le **premier
        travail de la boucle**, dans sa première réconciliation, avant tout
        événement de travail : aucune observation n'est projetée avant lui.
        Demandé après `start()`, il force une réconciliation au tour suivant.

        L'état de travail de Core vit en mémoire : après un redémarrage il est
        vide, et une étoile persistée « en cours » ne dit plus rien de vrai.
        Chaque étoile d'exécution d'origine `runtime` dont l'`exec_state` n'est
        pas terminal (en attente, en cours, bloquée, ou déjà inconnue après un
        arrêt brutal pendant une grâce) est suivie ; celles qui n'étaient pas
        encore `unknown` le deviennent. Les étoiles terminées, les signaux, les
        objets du cerveau ou de l'utilisateur, les artefacts, les pierres
        tombales, la géométrie, l'épingle, la visibilité et la disposition ne
        sont pas touchés : seul `exec_state` change. Aucune place n'est prise.

        Les jobs suivis dont la base garde une issue terminale la redisent à
        l'état de travail (`job_outcomes`), puis la grâce est armée.

        Ne lève jamais. Dans la boucle, une scène indisponible laisse le
        marquage en suspens (panne journalisée une fois, reprise avec délai) ;
        un défaut inattendu est journalisé et abandonne le marquage sans
        arrêter la projection.
        """

        self._restart_due = True
        queue = self._queue
        if queue is None:
            return  # `start()` réconcilie en premier : le marquage passe avant tout
        if self._dirty is None:
            self._dirty = "restart"
        try:
            queue.put_nowait(ProtocolEnvelope(message_type=_RESTART_REQUESTED, payload={}))
        except asyncio.QueueFull:
            # intentional: une file pleine veut dire une boucle occupée, qui
            # voit `_dirty` en tête de son prochain tour.
            pass

    def _restart_abandoned(self, exc: Exception) -> None:
        """Marquage interrompu par un défaut : journalisé, ce qui est suivi garde sa grâce."""

        self._restart_due = False
        self._failed("restart", exc)
        if self._restart_tracked:
            self._arm_grace()

    async def _mark_restart(self) -> None:
        """Marquer et suivre ; idempotent (une reprise après panne ne recompte rien)."""

        scene = await self._scene.snapshot()
        counts = self._restart_counts
        terminal = 0
        work_ids: dict[str, str | None] = {}
        for star in scene.objects:
            if star.kind not in EXECUTION_KINDS or star.origin is not SceneActor.RUNTIME or star.work_ref is None:
                continue
            if star.exec_state in TERMINAL_EXEC_STATES:
                terminal += 1
                continue
            key = (star.work_ref.source, star.work_ref.external_id)
            if key in self._restart_tracked:
                continue  # déjà compté par une tentative précédente
            previous = star.exec_state
            if previous is not ExecState.UNKNOWN:
                update = await self._apply(
                    SceneCommand(
                        op=SceneOp.PATCH_OBJECT, actor=SceneActor.RUNTIME, object_id=star.object_id,
                        fields=SceneObjectFields(exec_state=ExecState.UNKNOWN),
                    )
                )
                if update.outcome is not SceneCommandOutcome.APPLIED:
                    continue  # refus déjà journalisé par `SceneService` : étoile laissée telle quelle
                counts["marked"] = counts.get("marked", 0) + 1
                self.stats.restart_marked += 1
            else:
                counts["already_unknown"] = counts.get("already_unknown", 0) + 1
            self._restart_tracked[key] = star.object_id
            work_ids[star.object_id] = star.work_ref.work_id
            self._emit(
                SCENE_RESTART_STAR_KIND,
                "étoile marquée : état inconnu depuis le redémarrage",
                level="debug",
                data={"object_id": star.object_id, "action": "unknown", "previous": previous.value},
            )
        self._restart_due = False
        job_hints = {
            external_id: work_ids.get(star_id)
            for (source, external_id), star_id in self._restart_tracked.items()
            if source == JOB_WORK_SOURCE
        }
        if job_hints and self._job_outcomes is not None:
            try:
                counts["job_outcomes"] = await self._job_outcomes(job_hints)
            except Exception as exc:
                # Sans l'issue persistée, ces étoiles suivent la grâce comme les autres.
                self._failed("job_outcomes", exc)
        counts["tracked"] = len(self._restart_tracked)
        self._emit(
            SCENE_RESTART_MARKED_KIND,
            "redémarrage de Core : étoiles en cours marquées « état inconnu » jusqu'à ce qu'un producteur les redise",
            data={
                "marked": counts.get("marked", 0),
                "already_unknown": counts.get("already_unknown", 0),
                "tracked": len(self._restart_tracked),
                "terminal_untouched": terminal,
                "job_outcomes": counts.get("job_outcomes", 0),
                "grace_s": self._restart_grace_s,
                "sample": sorted(self._restart_tracked.values())[:_RESTART_SAMPLE],
            },
        )
        if self._restart_tracked:
            self._arm_grace()
        else:
            self._restart_counts = {}

    def _arm_grace(self) -> None:
        if self._stopping or (self._grace is not None and not self._grace.done()):
            return
        self._grace = asyncio.get_running_loop().create_task(self._grace_timer(), name="jarvis-scene-restart-grace")

    async def _grace_timer(self) -> None:
        await asyncio.sleep(self._restart_grace_s)
        self._grace_due = True
        queue = self._queue
        if queue is None:
            return  # boucle pas encore démarrée : elle lit `_grace_due` à son premier tour
        try:
            queue.put_nowait(ProtocolEnvelope(message_type=_RESTART_GRACE, payload={}))
        except asyncio.QueueFull:
            # intentional: une file pleine veut dire une boucle occupée, qui
            # relit `_grace_due` en tête de son prochain tour.
            pass

    async def _expire_grace(self) -> None:
        """Fin de la grâce : l'état réel s'il est dans Core, sinon `interrupted` et un signal.

        Tourne dans la boucle, comme toute écriture de la projection : une
        observation ne peut pas s'intercaler entre la lecture et l'écriture.
        Une étoile dont le travail est dans l'instantané de Core (projection
        manquée) reçoit cet état. Les autres reçoivent d'abord leur signal
        `core_restarted_unobserved`, puis `exec_state = interrupted` : un
        arrêt brutal entre les deux laisse l'étoile `unknown`, reprise au
        démarrage suivant sans second signal. Sans place pour le signal,
        l'interruption entière attend dans l'attente de saturation (travail
        terminé : après le travail actif). Une `SceneStoreError` remonte : les
        étoiles pas encore traitées restent suivies.
        """

        work = await self._work.snapshot()
        by_key = {item.key: item for item in work.items}
        for key in list(self._restart_tracked):
            star_id = self._restart_tracked.get(key)
            if star_id is None:
                continue  # revue pendant ce parcours
            try:
                item = by_key.get(key)
                if item is not None:
                    await self._project(item)
                    continue
                now = datetime.now(timezone.utc)
                synthetic = WorkItem(
                    source=key[0], external_id=key[1], status=WorkStatus.INTERRUPTED, revision=1,
                    started_at=now, updated_at=now, ended_at=now, error_class=CORE_RESTARTED_UNOBSERVED,
                )
                self._unobserved[key] = (synthetic, star_id)
                await self._project(synthetic)
                self._restart_tracked.pop(key, None)
            except SceneStoreError:
                raise
            except Exception as exc:
                self._restart_tracked.pop(key, None)
                self._unobserved.pop(key, None)
                self._restart_note("failed", star_id)
                self._failed("restart_grace", exc)
        self._grace_due = False
        counts, self._restart_counts = self._restart_counts, {}
        self._emit(
            SCENE_RESTART_GRACE_EXPIRED_KIND,
            "fin de la grâce de redémarrage : étoiles non revues interrompues",
            data={
                "tracked": counts.get("tracked", 0),
                "reobserved": counts.get("reobserved", 0),
                "interrupted": counts.get("interrupted", 0),
                "deferred": len(self._unobserved),
                "left": counts.get("left", 0),
                "failed": counts.get("failed", 0),
                "grace_s": self._restart_grace_s,
            },
        )

    async def _interrupt_unobserved(self, item: WorkItem, star_id: str) -> None:
        """Interrompre une étoile jamais revue : signal d'abord, puis `exec_state`."""

        scene = await self._scene.snapshot()
        star = scene.get_object(star_id)
        if (
            star is None or star.kind not in EXECUTION_KINDS or star.origin is not SceneActor.RUNTIME
            or star.exec_state is not ExecState.UNKNOWN
        ):
            # Archivée par l'utilisateur, ou un état réel écrit entre-temps :
            # plus rien à interrompre.
            self._unobserved.pop(item.key, None)
            self._restart_note("left", star_id)
            return
        signal_id = signal_object_id(star_id)
        existing = scene.get_object(signal_id)
        if scene.is_archived(signal_id):
            pass  # l'utilisateur a rangé ce signal : il ne renaît pas, l'étoile dit l'interruption
        elif existing is not None and (existing.kind is not SceneObjectKind.ATTENTION or existing.origin is not SceneActor.RUNTIME):
            self._conflict(signal_id, existing)
        elif not await self._raise_signal(
            scene, item, star_id, work_ref=star.work_ref,
            payload=ScenePayload(title=CORE_RESTARTED_UNOBSERVED, summary=_UNOBSERVED_SUMMARY),
            error_class=CORE_RESTARTED_UNOBSERVED,
        ):
            return  # signal différé faute de place : l'étoile reste `unknown` (signal d'abord)
        await self._apply(
            SceneCommand(
                op=SceneOp.PATCH_OBJECT, actor=SceneActor.RUNTIME, object_id=star_id,
                fields=SceneObjectFields(exec_state=ExecState.INTERRUPTED),
            )
        )
        self._unobserved.pop(item.key, None)
        self._restart_note("interrupted", star_id)

    async def _raise_signal(
        self, scene: SceneSnapshot, item: WorkItem, star_id: str, *, work_ref: WorkRef | None, payload: ScenePayload,
        error_class: str | None,
    ) -> bool:
        """Poser ou mettre à jour sur place le signal runtime d'une étoile ; faux s'il est différé.

        Partagé par la projection (`failed`/`interrupted`/`blocked`) et
        l'interruption de fin de grâce : un seul signal par travail, `category`
        et `exec_state` = statut de `item`, place vérifiée avant d'écrire, et
        refus `scene_full` raté par la vérification différé aussi. Le travail
        différé est `item` : l'appelant ne doit rien écrire d'autre ensuite
        (l'interruption garde ainsi « signal d'abord »).
        """

        signal_id = signal_object_id(star_id)
        if scene.get_object(signal_id) is None and len(scene.objects) >= MAX_SCENE_OBJECTS:
            self._defer(item, len(scene.objects))
            return False
        live = is_live_signal(scene, signal_id)
        update = await self._apply(
            SceneCommand(
                op=SceneOp.ATTACH_SIGNAL,
                actor=SceneActor.RUNTIME,
                object_id=signal_id,
                target_id=star_id,
                fields=SceneObjectFields(
                    kind=SceneObjectKind.ATTENTION,
                    category=item.status.value,
                    exec_state=ExecState(item.status.value),
                    work_ref=work_ref,
                    payload=payload,
                ),
            )
        )
        if update.reason is SceneRefusal.SCENE_FULL:
            self._defer(item, MAX_SCENE_OBJECTS)
            return False
        if update.changed and not live:
            self._emit(
                SCENE_SIGNAL_RAISED_KIND,
                "signal posé sur une étoile",
                data={"object_id": signal_id, "target_id": star_id, "status": item.status.value, "error_class": error_class},
            )
        return True

    def _restart_note(self, action: str, star_id: str) -> None:
        counts = self._restart_counts
        counts[action] = counts.get(action, 0) + 1
        if action == "reobserved":
            self.stats.restart_reobserved += 1
        elif action == "interrupted":
            self.stats.restart_interrupted += 1
        self._emit(
            SCENE_RESTART_STAR_KIND,
            "étoile de redémarrage : état tranché",
            level="debug",
            data={"object_id": star_id, "action": action},
        )

    # ------------------------------------------------------------ projection

    async def _project(self, item: WorkItem) -> None:
        """Projeter un travail ; s'il reste différé faute de place, il reste en attente."""

        self._deferred_key = None
        unobserved = self._unobserved.get(item.key)
        if unobserved is not None and unobserved[0] is item:
            await self._interrupt_unobserved(item, unobserved[1])
        else:
            # Une observation réelle fait foi : elle clôt le suivi de
            # redémarrage et remplace une interruption encore en attente.
            self._unobserved.pop(item.key, None)
            star_id = self._restart_tracked.pop(item.key, None)
            if star_id is not None:
                self._restart_note("reobserved", star_id)
            await self._project_item(item)
        if self._deferred_key == item.key or self._pending.pop(item.key, None) is None:
            return
        await self._pending_changed()

    async def _pending_changed(self) -> None:
        """Après un retrait de l'attente, quelle qu'en soit la cause : attente vide = fin d'épisode.

        La veille d'espace s'arrête aussitôt, et l'épisode se clôt ; la fin
        n'est journalisée que pour un épisode annoncé.
        """

        if self._pending:
            return
        watch, self._watch = self._watch, None
        if watch is not None and watch is not asyncio.current_task():
            # Pas d'attente ici : la veille est suspendue sur une révision ou un
            # délai, l'annulation la termine au tour de boucle suivant.
            watch.cancel()
        if self._saturation is None:
            return
        episode, warned = self._saturation, self._saturation_warned
        self._saturation, self._saturation_warned = None, False
        if not warned:
            return
        try:
            objects: int | None = len((await self._scene.snapshot()).objects)
        except SceneStoreError:
            objects = None
        self._emit(
            SCENE_PROJECTION_DESATURATED_KIND,
            "scène de nouveau disponible : plus aucune création en attente",
            data={"objects": objects, "object_limit": MAX_SCENE_OBJECTS, **episode},
        )

    async def _catch_up(self) -> None:
        """Rattraper les créations différées tant qu'il y a de la place.

        Ordre (décision PM après QA) : travail non terminé d'abord (en attente,
        en cours, bloqué : il doit devenir une étoile tout de suite,
        Décision 4), puis travail terminé ; les plus anciens d'abord dans chaque
        groupe. Une étoile et son signal restent ensemble : `_project` pose le
        signal juste après l'étoile quand la place le permet.
        """

        while self._pending:
            if len((await self._scene.snapshot()).objects) >= MAX_SCENE_OBJECTS:
                return
            key, item = self._next_pending()
            applied_before = self.stats.applied
            try:
                await self._project(item)
            except SceneStoreError:
                raise
            except Exception as exc:
                # Un travail qu'on ne sait pas projeter ne bloque pas les autres.
                self._pending.pop(key, None)
                self._failed("catch_up", exc)
                await self._pending_changed()
                continue
            if key in self._pending:
                return  # de nouveau différé : plus de place
            if self.stats.applied > applied_before:
                self.stats.caught_up += 1

    def _next_pending(self) -> tuple[tuple[str, str], WorkItem]:
        active = next(((key, item) for key, item in self._pending.items() if not item.status.is_terminal), None)
        return active or next(iter(self._pending.items()))

    def _defer(self, item: WorkItem, objects: int) -> None:
        """Retenir un travail dont la création (étoile ou signal) n'a pas trouvé de place."""

        self._deferred_key = item.key
        self.stats.deferred += 1
        if self._saturation is None:
            self._saturation = {"deferred": 0, "dropped": 0}
            now = self._monotonic()
            last = self._last_saturation_warning
            self._saturation_warned = last is None or now - last >= self._saturation_warning_interval_s
            if self._saturation_warned:
                self._last_saturation_warning = now
                self._emit(
                    SCENE_PROJECTION_SATURATED_KIND,
                    "scène pleine : les nouvelles étoiles attendent un archivage, rien n'est retiré automatiquement",
                    level="warning",
                    data={
                        "objects": objects,
                        "object_limit": MAX_SCENE_OBJECTS,
                        "pending": len(self._pending) + (0 if item.key in self._pending else 1),
                        "suppressed_episodes": self._episodes_silenced,
                    },
                )
                self._episodes_silenced = 0
            else:
                self._episodes_silenced += 1
        self._saturation["deferred"] += 1
        # Affectation sur place : un travail déjà en attente garde son rang.
        self._pending[item.key] = item
        while len(self._pending) > self._max_pending:
            # Oublier d'abord le plus ancien travail terminé ; à défaut, le plus ancien.
            victim = next((key for key, pending in self._pending.items() if pending.status.is_terminal), None)
            if victim is None:
                self._pending.popitem(last=False)
            else:
                del self._pending[victim]
            self.stats.pending_dropped += 1
            self._saturation["dropped"] += 1
            if self._saturation["dropped"] == 1:
                self._emit(
                    SCENE_PROJECTION_PENDING_OVERFLOW_KIND,
                    "trop de créations en attente : les plus anciennes sont oubliées",
                    level="warning",
                    data={"max_pending": self._max_pending},
                )
        if self._stopping or self._queue is None:
            return  # arrêt en cours : aucune veille ne doit survivre à `stop()`
        if self._watch is None or self._watch.done():
            self._watch = asyncio.get_running_loop().create_task(self._watch_space(), name="jarvis-scene-projector-space")

    async def _watch_space(self) -> None:
        """Pendant une saturation : réveiller la boucle à chaque révision de scène, au plus tard toutes les `saturation_retry_s`.

        Vit seulement tant que l'attente n'est pas vide : annulée dès qu'elle se
        vide (`_pending_changed`) et par `stop()`.
        """

        while self._pending and not self._stopping:
            try:
                revision = (await self._scene.snapshot()).revision
                await self._scene.wait_for_revision(revision, timeout_s=self._saturation_retry_s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Scène indisponible (la boucle le journalise) ou défaut : on
                # patiente, sans jamais tourner à vide.
                if not isinstance(exc, SceneStoreError):
                    self._failed("watch", exc)
                await asyncio.sleep(self._saturation_retry_s)
            queue = self._queue
            if queue is None:
                return
            try:
                queue.put_nowait(ProtocolEnvelope(message_type=_SPACE_CHECK, payload={}))
            except asyncio.QueueFull:
                pass  # la boucle est occupée : elle rattrape à l'événement suivant

    async def _project_item(self, item: WorkItem) -> None:
        star_id = star_object_id(item.source, item.external_id)
        scene = await self._scene.snapshot()
        if scene.is_archived(star_id):
            # Archivée par l'utilisateur : ne renaît pas, rien n'est envoyé.
            self.stats.skipped_archived += 1
            return
        current = scene.get_object(star_id)
        if current is None:
            kind = STAR_WORK_KINDS.get(item.kind)
            if kind is None:
                return
            if len(scene.objects) >= MAX_SCENE_OBJECTS:
                self._defer(item, len(scene.objects))
                return
            payload = star_payload(item)
            fields = SceneObjectFields(
                kind=kind, category=kind.value, exec_state=ExecState(item.status.value), work_ref=work_ref(item), payload=payload
            )
        else:
            if current.kind not in EXECUTION_KINDS:
                self._conflict(star_id, current)
                return
            payload = star_payload(item)
            fields = SceneObjectFields(
                exec_state=ExecState(item.status.value),
                work_ref=_kept_work_ref(current, item),
                payload=payload if self._owns_payload(current, payload) else None,
            )
        update = await self._apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=star_id, fields=fields))
        if update.reason is SceneRefusal.SCENE_FULL:
            self._defer(item, MAX_SCENE_OBJECTS)
            return
        if update.changed and fields.payload is not None:
            self._remember(star_id, fields.payload)
        if current is None:
            if not update.changed:
                return
            self._emit(
                SCENE_STAR_CREATED_KIND,
                "étoile créée pour un travail en cours",
                data={"object_id": star_id, "kind": fields.kind.value, "source": item.source, "status": item.status.value},
            )
            await self._link_children(item, star_id)
        reached = ExecState(item.status.value)
        if update.changed and reached in TERMINAL_EXEC_STATES and (current is None or current.exec_state not in TERMINAL_EXEC_STATES):
            # Pendant de `star_created` : le travail vient de finir. Une seule
            # ligne par étoile (un état terminal ne redevient pas terminal), et
            # rien d'autre ne change : ni visibilité, ni disposition (Décision 12).
            self._emit(
                SCENE_STAR_FINISHED_KIND,
                "travail terminé : l'étoile porte sa marque de fin",
                data={"object_id": star_id, "source": item.source, "status": item.status.value},
            )
        if item.parent_external_id is not None:
            await self._link_parent(item)
        await self._project_signal(item, star_id, fields.work_ref)

    def _owns_payload(self, current: SceneObject, wanted: ScenePayload) -> bool:
        """Vrai si la charge de l'étoile est encore celle de la projection.

        Retenue en mémoire : égale à la dernière charge écrite. Sans mémoire
        (redémarrage, oubli) : vide ou de même titre. Sinon le cerveau ou
        l'utilisateur l'ont réécrite, et la projection ne l'écrase pas.
        """

        if current.payload == wanted:
            return False
        written = self._written.get(current.object_id)
        if written is not None:
            return current.payload == written
        return current.payload.title in ("", wanted.title)

    def _remember(self, star_id: str, payload: ScenePayload) -> None:
        self._written[star_id] = payload
        self._written.move_to_end(star_id)
        while len(self._written) > MAX_REMEMBERED_PAYLOADS:
            self._written.popitem(last=False)

    async def _link_parent(self, item: WorkItem) -> None:
        assert item.parent_external_id is not None
        await self._link(star_object_id(item.source, item.parent_external_id), star_object_id(item.source, item.external_id))

    async def _link_children(self, item: WorkItem, star_id: str) -> None:
        """Une étoile vient de naître : relier les enfants arrivés avant elle (instantané borné à 64)."""

        work = await self._work.snapshot()
        for child in work.items:
            if child.source == item.source and child.parent_external_id == item.external_id:
                await self._link(star_id, star_object_id(child.source, child.external_id))

    async def _link(self, parent_id: str, child_id: str) -> None:
        scene = await self._scene.snapshot()
        parent, child = scene.get_object(parent_id), scene.get_object(child_id)
        if not _runtime_star(parent) or not _runtime_star(child):
            # Parent sans étoile (commande shell, pas encore vu, archivé) : le
            # lien viendra quand les deux existeront, ou jamais.
            return
        relation = SceneRelation(parent_relation_id(child_id), RelationKind.PARENT_OF, parent_id, child_id)
        existing = scene.get_relation(relation.relation_id)
        if existing is not None and existing.endpoints == relation.endpoints:
            return
        await self._apply(SceneCommand(op=SceneOp.LINK, actor=SceneActor.RUNTIME, relation=relation))

    async def _project_signal(self, item: WorkItem, star_id: str, ref: WorkRef | None = None) -> None:
        signal_id = signal_object_id(star_id)
        scene = await self._scene.snapshot()
        if scene.get_object(star_id) is None or scene.is_archived(signal_id):
            return
        existing = scene.get_object(signal_id)
        if existing is not None and (existing.kind is not SceneObjectKind.ATTENTION or existing.origin is not SceneActor.RUNTIME):
            self._conflict(signal_id, existing)
            return
        state = ExecState(item.status.value)
        if item.status in SIGNAL_STATUSES:
            await self._raise_signal(
                scene, item, star_id, work_ref=ref or work_ref(item), payload=signal_payload(item), error_class=item.error_class,
            )
            return
        if existing is None:
            return
        # Le travail a quitté l'état qui justifiait le signal : le délier
        # d'abord (il cesse d'être vivant), puis noter l'état atteint.
        if is_live_signal(scene, signal_id):
            update = await self._apply(SceneCommand(op=SceneOp.UNLINK, actor=SceneActor.RUNTIME, relation_id=signal_id))
            if update.changed:
                self._emit(
                    SCENE_SIGNAL_RETIRED_KIND,
                    "signal retiré : le travail a quitté l'état signalé",
                    data={"object_id": signal_id, "target_id": star_id, "status": item.status.value},
                )
        if existing.exec_state is not state:
            await self._apply(
                SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.RUNTIME, object_id=signal_id, fields=SceneObjectFields(exec_state=state))
            )

    async def _apply(self, command: SceneCommand) -> SceneUpdate:
        update = await self._scene.apply(command)
        if update.outcome is SceneCommandOutcome.APPLIED:
            self.stats.applied += 1
        elif update.outcome is SceneCommandOutcome.DUPLICATE:
            self.stats.duplicate += 1
        else:
            # Déjà journalisé une fois par motif par `SceneService`.
            self.stats.refused += 1
        return update

    # ------------------------------------------------------------ diagnostic

    def _outage(self, exc: SceneStoreError) -> None:
        self._dirty = "scene_unavailable"
        self.stats.outages += 1
        if self._unavailable:
            self._suppressed += 1
            return
        self._unavailable = True
        self._emit(
            SCENE_PROJECTION_UNAVAILABLE_KIND,
            "scène indisponible : la projection attend et réconciliera au retour, le travail continue",
            level="warning",
            data={"code": exc.code.value, "error": f"{type(exc).__name__}: {exc}"[:300]},
        )

    def _failed(self, where: str, exc: Exception) -> None:
        self.stats.failures += 1
        self._report_once(
            f"failed:{where}:{type(exc).__name__}",
            SCENE_PROJECTION_FAILED_KIND,
            "projection de la scène en échec sur un travail : ignoré, la projection continue",
            level="error",
            data={"where": where, "error": f"{type(exc).__name__}: {exc}"[:300]},
        )

    def _conflict(self, object_id: str, found: SceneObject) -> None:
        self._report_once(
            f"conflict:{object_id}",
            SCENE_PROJECTION_CONFLICT_KIND,
            "identifiant de projection déjà pris par un objet qui n'est pas le sien : rien n'est écrit",
            level="warning",
            data={"object_id": object_id, "kind": found.kind.value, "origin": found.origin.value},
        )

    def _report_once(self, key: str, kind: str, message: str, *, level: str, data: dict) -> None:
        if key in self._reported:
            return
        if len(self._reported) >= _MAX_REPORTED:
            self._reported.clear()
        self._reported.add(key)
        self._emit(kind, message, level=level, data=data)

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Même règle que `SceneService` et `CoreEventBus` : un journal
            # indisponible ne casse jamais la projection.
            pass


def _kept_work_ref(current: SceneObject, item: WorkItem) -> WorkRef:
    """`work_ref` du travail, en gardant le `work_id` que l'étoile porte déjà s'il n'est plus dit.

    Même règle que l'état de travail (le premier rattachement affirmé fait
    foi) : après un redémarrage, un job repris ou relu en base n'a plus son
    `work_id` en mémoire (`JobService` ne le persiste pas), mais l'étoile le
    garde. Un `work_id` différent annoncé remplace, comme avant.
    """

    ref = work_ref(item)
    known = current.work_ref
    if (
        ref.work_id is None and known is not None and known.work_id is not None
        and (known.source, known.external_id) == (ref.source, ref.external_id)
    ):
        return replace(ref, work_id=known.work_id)
    return ref


def _runtime_star(item: SceneObject | None) -> bool:
    return item is not None and item.kind in EXECUTION_KINDS and item.origin is SceneActor.RUNTIME
