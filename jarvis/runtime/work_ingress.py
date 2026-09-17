"""Relais de l'état des sous-tâches vers Core (handoff work-state, tâche 11).

`AgentTaskTracker` vit dans le processus du Control Center, Core dans un
autre. Ce module fait passer le premier dans le second, sans que la lecture
du flux de l'agent en dépende jamais :

    stream-json ─► AgentTaskTracker ─► TrackerWorkObserver ─► WorkIngressForwarder
                                         (différence d'état)     (file bornée, lots)
                                                                       │ POST /v1/work/observations
                                                                       ▼
                                                                Core WorkStateStore

- `TrackerWorkObserver` relit le tracker après chaque changement et émet une
  `WorkObservation` par tâche dont l'état public a changé. Rien du flux brut
  (prompt, trace, `subagent_type`, `tool_use_id`) n'en sort ;
- `WorkIngressForwarder` range ces observations dans une file bornée
  (coalescée par tâche, la plus ancienne sort si elle déborde), et les envoie
  par lots depuis sa propre tâche. `offer()` ne bloque ni n'attend jamais ;
- `CoreWorkTransport` joint Core par la boucle locale, avec le jeton de
  session relu à chaque reconnexion (Core peut démarrer après le Control
  Center, et change de jeton à chaque démarrage).

Core indisponible : les observations attendent (dans la borne), l'envoi
reprend avec un délai croissant, et le premier contact avec une instance de
Core inconnue — ou après une perte — renvoie l'état complet du tracker. Sans
rien à envoyer, l'état complet repart aussi toutes les `resync_interval_s` :
un Core redémarré pendant qu'aucune sous-tâche ne bougeait (commande de fond
silencieuse) n'attend pas le prochain événement du flux pour la connaître.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from typing import Any
import uuid

from jarvis.domain.work_state import (
    MAX_ACTIVITY_CHARS,
    MAX_LABEL_CHARS,
    MAX_MODEL_CHARS,
    MAX_OBSERVATION_BATCH,
    MAX_SUMMARY_CHARS,
    WorkObservation,
    WorkObservationBatch,
    WorkStatus,
    clip_text,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.agent_tasks import AgentTask, AgentTaskTracker
from jarvis.runtime.core_forwarder import CoreBatchForwarder, CoreBatchRejected, CoreLoopbackTransport
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.subagent_conversation import utc_from_ms


#: Fins d'une tâche Claude demandées par quelqu'un : conservées comme
#: `error_class`, lisibles sans ambiguïté.
_CANCELLED_STATUSES = frozenset({"killed", "stopped", "cancelled"})
_PENDING_STATUSES = frozenset({"pending", "queued"})
#: `error_class` d'une tâche interrompue par l'arrêt de son processus.
PROCESS_STOPPED = "process_stopped"
#: `error_class` d'un doublon clos après la fusion de deux tâches.
MERGED = "merged"
#: Statut terminal inconnu du contrat : fin anormale, statut brut non transmis.
UNKNOWN_STATUS = "unknown_status"


#: Horodatage UTC d'une milliseconde du tracker (helper partagé avec les spans de sous-agents).
_utc = utc_from_ms


def task_status(raw: str) -> tuple[WorkStatus, str | None]:
    """Statut normalisé et `error_class` d'un statut de tâche Claude."""

    if raw in _PENDING_STATUSES:
        return WorkStatus.PENDING, None
    if raw in {"", "running", "started"}:
        return WorkStatus.RUNNING, None
    if raw == "completed":
        return WorkStatus.COMPLETED, None
    if raw == "failed":
        return WorkStatus.FAILED, None
    if raw in _CANCELLED_STATUSES:
        return WorkStatus.CANCELLED, raw
    if raw == "interrupted":
        return WorkStatus.INTERRUPTED, PROCESS_STOPPED
    return WorkStatus.FAILED, UNKNOWN_STATUS


def task_observation(task: AgentTask, *, source: str, parent_key: str | None, now_ms: int) -> WorkObservation:
    """Constat normalisé d'une tâche, à l'instant `now_ms`.

    Une tâche finie est datée de sa fin : renvoyée plus tard (reprise après un
    redémarrage de Core), elle garde sa vraie date de fin et reste un doublon.
    """

    status, error_class = task_status(task.status)
    observed_ms = task.ended_ms if status.is_terminal and task.ended_ms is not None else now_ms
    return WorkObservation(
        source=source,
        external_id=task.work_key,
        status=status,
        observed_at=_utc(observed_ms),
        kind=task.kind,
        label=clip_text(task.description, MAX_LABEL_CHARS),
        activity="" if status.is_terminal else clip_text(task.activity, MAX_ACTIVITY_CHARS),
        summary=clip_text(task.summary, MAX_SUMMARY_CHARS, single_line=False),
        model=clip_text(task.model, MAX_MODEL_CHARS),
        parent_external_id=parent_key,
        error_class=error_class,
        # 0 est la valeur par défaut du tracker : « pas encore compté ».
        tool_uses=task.tool_uses or None,
        tokens=task.tokens or None,
        background=task.background,
        started_at=_utc(min(task.started_ms, observed_ms)),
    )


def _signature(task: AgentTask, parent_key: str | None) -> tuple[Any, ...]:
    """Ce qui, changé, mérite une nouvelle observation."""

    return (
        task.status, task.kind, task.description, task.activity if task.running else "", task.summary,
        task.model, parent_key, task.tokens, task.tool_uses, task.background, task.started_ms, task.ended_ms,
    )


class TrackerWorkObserver:
    """Projection d'un `AgentTaskTracker` en observations normalisées, par différence.

    Abonné au tracker (`subscribe(observer.sync)`), il ne publie que les
    tâches dont l'état public a changé depuis son dernier envoi, sous leur
    `work_key` stable. Sa mémoire suit celle du tracker : une tâche élaguée
    par le tracker est oubliée ici aussi.
    """

    def __init__(self, tracker: AgentTaskTracker, emit: Callable[[WorkObservation], None]) -> None:
        self.tracker = tracker
        self._emit = emit
        self._sent: dict[str, tuple[Any, ...]] = {}

    def sync(self, *, retired: tuple[str, ...] = ()) -> int:
        """Émettre ce qui a changé ; rend le nombre d'observations émises.

        Une tâche impossible à décrire (identifiant hors contrat) n'empêche
        pas les autres : la première erreur est relevée après le parcours,
        pour que l'appelant la consigne. `retired` ajoute des clôtures que
        l'appelant a déjà retirées du suivi (voir `resync`).
        """

        tracker = self.tracker
        now_ms = tracker.now_ms()
        emitted = 0
        errors: list[Exception] = []
        for key in (*retired, *tracker.drain_retired_work_keys()):
            if self._sent.pop(key, None) is None:
                continue  # jamais publiée : rien à clore côté Core
            try:
                self._emit(WorkObservation(source=tracker.provider, external_id=key, status=WorkStatus.CANCELLED, observed_at=_utc(now_ms), error_class=MERGED))
                emitted += 1
            except (TypeError, ValueError) as exc:
                errors.append(exc)
        live: set[str] = set()
        for task in tracker.tasks():
            key = task.work_key
            if not key:
                continue
            live.add(key)
            parent = tracker.parent_of(task)
            parent_key = parent.work_key if parent is not None and parent.work_key not in ("", key) else None
            signature = _signature(task, parent_key)
            if self._sent.get(key) == signature:
                continue
            # Noté avant l'envoi : une tâche indescriptible n'est pas retentée
            # à chaque événement du flux.
            self._sent[key] = signature
            try:
                self._emit(task_observation(task, source=tracker.provider, parent_key=parent_key, now_ms=now_ms))
                emitted += 1
            except (TypeError, ValueError) as exc:
                errors.append(exc)
        for key in [key for key in self._sent if key not in live]:
            del self._sent[key]
        if errors:
            raise errors[0]
        return emitted

    def resync(self) -> int:
        """Tout renvoyer : Core a redémarré, ou des observations ont été perdues.

        Les clôtures encore dues (doublons fusionnés, retirés du suivi)
        survivent au vidage de la mémoire d'envoi : vider sans elles laisserait
        le doublon actif dans Core pour toujours, puisque le suivi ne le
        rendra plus jamais.
        """

        retired = tuple(key for key in self.tracker.drain_retired_work_keys() if key in self._sent)
        kept = {key: self._sent[key] for key in retired}
        self._sent.clear()
        self._sent.update(kept)
        return self.sync(retired=retired)


class WorkIngressRejected(CoreBatchRejected):
    """Core a refusé le lot (400) : le rejouer à l'identique ne servirait à rien."""


class CoreWorkTransport(CoreLoopbackTransport):
    """Accès à l'ingress Core par la boucle locale.

    Le jeton de session est relu à chaque (re)connexion : Core écrit un jeton
    neuf à chaque démarrage, et peut démarrer après le Control Center
    (`CoreLoopbackTransport`).
    """

    async def post(self, batch: WorkObservationBatch) -> dict[str, Any]:
        """Envoyer un lot ; un jeton refusé est relu et le lot renvoyé une fois.

        Un 401 veut dire que Core a redémarré avec un autre jeton, et que rien
        du lot n'a été appliqué : le renvoyer aussitôt avec le jeton relu est
        sûr (Slice 10). Sans cela, le relais attendait son délai croissant
        (jusqu'à 30 s) avant de redire son état au nouveau Core, et la grâce de
        redémarrage de la scène devait couvrir deux délais au lieu d'un.
        """

        payload = batch.to_payload()
        try:
            return await self._post_once(payload)
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        # Core a redémarré avec un autre jeton : relu, une seule nouvelle tentative.
        await self.close()
        try:
            return await self._post_once(payload)
        except CoreProtocolError as exc:
            if exc.status == 401:
                await self.close()  # relu encore au prochain envoi
            raise

    async def _post_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._connect().ingest_work_observations(payload)
        except CoreProtocolError as exc:
            if exc.status == 400:
                raise WorkIngressRejected(str(exc)) from exc
            raise

    async def snapshot(self) -> dict[str, Any]:
        """Lire l'état de travail normalisé de Core (`GET /v1/work/snapshot`).

        Lecture seule, pour le panneau Agents (tâche 13) : une instance
        distincte de celle du relais, pour qu'un jeton périmé côté lecture ne
        ferme pas la session d'un envoi en cours. Jeton refusé (Core
        redémarré) : relu et une seule nouvelle tentative, sans effet de bord.
        """

        try:
            return await self._connect().work_snapshot()
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        await self.close()
        return await self._connect().work_snapshot()

    async def live_session_status(self):
        """Read Core's current unresolved GPT-Live lifecycle record."""
        try:
            return await self._connect().live_session_status()
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        await self.close()
        return await self._connect().live_session_status()


class WorkIngressForwarder(CoreBatchForwarder):
    """File bornée d'observations vers Core, vidée par lots depuis sa propre tâche.

    Son entrée, `offer`, est synchrone parce qu'elle est appelée sur le
    chemin de lecture du flux : ni attente, ni réseau, ni exception de
    transport. La boucle d'envoi, le délai croissant et l'arrêt borné sont
    ceux de `CoreBatchForwarder` (`jarvis/runtime/core_forwarder.py`).

    Coalescence : une observation remplace celle de la même tâche encore en
    attente — elle porte l'état complet —, sauf qu'une fin n'est jamais
    remplacée par un état non terminal. Débordement : la plus ancienne sort,
    `dropped_total` la compte, et l'état complet est renvoyé au prochain
    envoi réussi. Un lot refusé par Core (400) est abandonné de la même
    façon : `rejected_total` le compte et le même renvoi complet est armé,
    sans quoi une tâche finie resterait « en cours » dans Core.
    """

    TASK_NAME = "jarvis-work-ingress"
    UNAVAILABLE_KIND = "work.ingress_unavailable"
    UNAVAILABLE_MESSAGE = "Core injoignable : l'état des sous-tâches attend, l'agent continue."
    RESTORED_KIND = "work.ingress_restored"
    RESTORED_MESSAGE = "Core joint : l'état des sous-tâches lui parvient de nouveau."
    REJECTED_KIND = "work.ingress_rejected"
    REJECTED_MESSAGE = "Core a refusé un lot d'état des sous-tâches : lot abandonné."

    def __init__(
        self,
        *,
        source: str,
        transport: CoreWorkTransport,
        journal: RuntimeJournal | None = None,
        max_pending: int = 256,
        max_batch: int = MAX_OBSERVATION_BATCH,
        flush_interval_s: float = 0.5,
        retry_min_s: float = 1.0,
        retry_max_s: float = 30.0,
        close_timeout_s: float = 2.0,
        resync_interval_s: float = 30.0,
    ) -> None:
        if max_pending < 1 or not 1 <= max_batch <= MAX_OBSERVATION_BATCH or resync_interval_s <= 0:
            raise ValueError("invalid work ingress bounds")
        # Au repos, délai avant de renvoyer l'état complet (`idle_interval_s`).
        # Les doublons sont sans effet dans Core (ni révision, ni événement) :
        # c'est la sonde qui révèle un Core redémarré, au prix d'un lot borné
        # par intervalle.
        super().__init__(
            transport=transport, journal=journal, flush_interval_s=flush_interval_s, retry_min_s=retry_min_s,
            retry_max_s=retry_max_s, close_timeout_s=close_timeout_s, idle_interval_s=resync_interval_s,
        )
        self.source = source
        #: Identité de cette instance du producteur : Core interrompt les
        #: travaux encore actifs d'une instance précédente.
        self.producer_id = uuid.uuid4().hex
        self.max_pending = max_pending
        self.max_batch = max_batch
        self.resync_interval_s = resync_interval_s
        #: Appelé quand Core doit recevoir l'état complet (nouvelle instance de
        #: Core, observations perdues, repos prolongé) : branché sur
        #: `TrackerWorkObserver.resync`.
        self.on_resync: Callable[[], Any] | None = None
        self.dropped_total = 0
        self.rejected_total = 0
        self._pending: OrderedDict[str, WorkObservation] = OrderedDict()
        self._store_id: str | None = None
        self._lost = False
        self._resync_failures: set[str] = set()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # ------------------------------------------------------------ entrée

    def offer(self, observation: WorkObservation) -> None:
        """Mettre une observation en attente d'envoi. Synchrone, borné, immédiat."""

        if observation.source != self.source:
            raise ValueError(f"observation source {observation.source!r} is not {self.source!r}")
        self._put(observation, newest=True)
        self._wake.set()

    def _put(self, observation: WorkObservation, *, newest: bool) -> None:
        key = observation.external_id
        waiting = self._pending.get(key)
        if waiting is not None:
            ends = observation.status.is_terminal and not waiting.status.is_terminal
            if waiting.status.is_terminal and not observation.status.is_terminal:
                return  # une fin en attente n'est jamais écrasée
            if not newest and not ends:
                return  # une observation plus récente attend déjà
        self._pending[key] = observation
        self._pending.move_to_end(key, last=newest)
        while len(self._pending) > self.max_pending:
            self._pending.popitem(last=False)
            self.dropped_total += 1
            self._lost = True

    # ------------------------------------------------------------ cycle

    def _on_idle(self) -> None:
        # Rien n'a bougé : l'état complet sert de sonde. Un tracker vide
        # n'émet rien, et rien ne part.
        self._resync()

    async def flush(self) -> bool:
        """Envoyer tout ce qui attend ; faux si Core est injoignable (rien n'est perdu)."""

        while self._pending:
            batch = [self._pending.pop(key) for key in list(self._pending)[: self.max_batch]]
            try:
                response = await self.transport.post(
                    WorkObservationBatch(source=self.source, producer_id=self.producer_id, observations=tuple(batch))
                )
            except asyncio.CancelledError:
                self._requeue(batch)
                raise
            except CoreBatchRejected as exc:
                self.rejected_total += len(batch)
                # Le lot est perdu pour Core : sans renvoi complet, une tâche
                # finie y resterait « en cours » jusqu'au redémarrage.
                self._lost = True
                self._report_rejected(exc)
                continue
            except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, réseau
                self._requeue(batch)
                self._report_unavailable(exc)
                return False
            self._acknowledge(response)
        return True

    def _requeue(self, batch: list[WorkObservation]) -> None:
        for observation in reversed(batch):
            self._put(observation, newest=False)

    def _acknowledge(self, response: Any) -> None:
        # Un lot accepté clôt la panne et la série de refus : la suivante sera consignée.
        self._note_accepted()
        store_id = response.get("store_id") if isinstance(response, dict) else None
        if store_id == self._store_id and not self._lost:
            return
        # Instance de Core inconnue (premier contact, redémarrage) ou pertes :
        # Core doit recevoir l'état complet. Les doublons y sont sans effet.
        self._store_id, self._lost = store_id, False
        self._resync()

    def _resync(self) -> None:
        if self.on_resync is None:
            return
        try:
            self.on_resync()
        except Exception as exc:  # noqa: BLE001
            # Une tâche indescriptible échoue à chaque renvoi, périodique
            # compris : consignée une fois par type, comme dans le tracker.
            name = type(exc).__name__
            if name not in self._resync_failures:
                self._resync_failures.add(name)
                self._report("work.ingress_resync_failed", "Renvoi complet de l'état des sous-tâches en échec.", "error", exc)

    # --------------------------------------------------------- diagnostic

    def _report_data(self) -> dict[str, Any]:
        return {"source": self.source, "pending": len(self._pending), "dropped_total": self.dropped_total}
