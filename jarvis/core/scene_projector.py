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
- **archivé** : une étoile archivée par l'utilisateur ne renaît jamais ; la
  projection lit la pierre tombale avant d'écrire et n'envoie rien.

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
from dataclasses import dataclass
import hashlib
from typing import Protocol

from jarvis.core.v2_services import CoreEventBus, NullDiagnosticSink
from jarvis.core.work_state import CORE_WORK_UPDATED
from jarvis.domain._checks import MAX_ID_CHARS
from jarvis.domain.scene import (
    EXECUTION_KINDS,
    MAX_PAYLOAD_SUMMARY_CHARS,
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
    SceneRelation,
    SceneSnapshot,
    SceneUpdate,
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
SCENE_SIGNAL_RAISED_KIND = "core.scene.signal_raised"
SCENE_SIGNAL_RETIRED_KIND = "core.scene.signal_retired"

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


class SceneProjectionTarget(Protocol):
    """Ce que la projection utilise de la scène : `SceneService` le fournit."""

    async def apply(self, command: SceneCommand) -> SceneUpdate: ...

    async def snapshot(self) -> SceneSnapshot: ...


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
    ) -> None:
        if queue_size < 1 or retry_min_s <= 0 or retry_max_s < retry_min_s or stop_drain_s < 0:
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
        self.stats = SceneProjectionStats()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------ cycle de vie

    def start(self) -> None:
        """S'abonner (avant toute lecture, pour ne rien manquer) puis lancer la boucle."""

        if self._task is not None:
            return
        self._queue = self._events.subscribe(max_queue=self._queue_size, lossy=True)
        self._dirty = "start"
        self._task = asyncio.get_running_loop().create_task(self._run(self._queue), name="jarvis-scene-projector")

    async def stop(self) -> None:
        task, self._task = self._task, None
        queue, self._queue = self._queue, None
        if queue is not None:
            self._events.unsubscribe(queue)
        if task is None:
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

    # ------------------------------------------------------------ boucle

    async def _run(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        retry = self._retry_min_s
        while True:
            try:
                if self._dirty is not None:
                    if not await self._reconcile(self._dirty):
                        await self._wait_outage(queue, retry)
                        retry = min(retry * 2, self._retry_max_s)
                        continue
                    retry = self._retry_min_s
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
            await self._project(item)
        except SceneStoreError as exc:
            self._outage(exc)
        except Exception as exc:
            self._failed("event", exc)

    # ------------------------------------------------------------ réconciliation

    async def _reconcile(self, reason: str) -> bool:
        """Projeter tout l'instantané de travail ; faux si la scène ne répond pas."""

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

    # ------------------------------------------------------------ projection

    async def _project(self, item: WorkItem) -> None:
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
                work_ref=work_ref(item),
                payload=payload if self._owns_payload(current, payload) else None,
            )
        update = await self._apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=star_id, fields=fields))
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
        if item.parent_external_id is not None:
            await self._link_parent(item)
        await self._project_signal(item, star_id)

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

    async def _project_signal(self, item: WorkItem, star_id: str) -> None:
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
                        exec_state=state,
                        work_ref=work_ref(item),
                        payload=signal_payload(item),
                    ),
                )
            )
            if update.changed and not live:
                self._emit(
                    SCENE_SIGNAL_RAISED_KIND,
                    "signal posé sur une étoile",
                    data={"object_id": signal_id, "target_id": star_id, "status": item.status.value, "error_class": item.error_class},
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


def _runtime_star(item: SceneObject | None) -> bool:
    return item is not None and item.kind in EXECUTION_KINDS and item.origin is SceneActor.RUNTIME
