from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from jarvis.domain.v2 import (
    BrainTurnSource, Conversation, ConversationStatus, ConversationTurn, HistoryRecord, Job, JobProgress, JobStatus,
    MissedRunPolicy, Notification, NotificationState, ProtocolEnvelope, ScheduledItem,
    ScheduledStatus, TurnKind, new_id, utc_now,
)
from jarvis.domain.work_state import (
    MAX_ACTIVITY_CHARS, MAX_ERROR_CLASS_CHARS, MAX_LABEL_CHARS, WorkLink, WorkObservation, WorkStatus, clip_text,
)
from jarvis.ports.v2 import (
    Clock, DiagnosticSink, HistoryStore, JobProgressSink, JobWorker, NotificationDelivery,
    ProgressReportingJobWorker, StateRepository,
)
from jarvis.ports.work_state import WorkObservationSink

# Type d'evenement du contrat public d'avancement
# (`docs/handoff-realtime-brain/docs/05-event-contracts.md`). Il est defini ici
# plutot que dans `brain_service` parce que `JobService` en est une source
# legitime — un job qui avance **est** du travail cerveau qui avance — et que
# `brain_service` importe deja ce module (l'inverse creerait un cycle).
BRAIN_WORK_PROGRESS = "brain.work.progress"

#: Marque, dans les métadonnées d'un tour, celui que Core a ouvert lui-même
#: plutôt que reçu d'une surface. Personne ne l'a dit : il ne fait donc pas
#: partie du contexte de conversation relu par le modèle vocal.
SYSTEM_TURN_SOURCE = BrainTurnSource.SYSTEM.value

# Canal de diagnostic emis quand de l'avancement a ete coalesce a la source.
JOB_PROGRESS_COALESCED_KIND = "core.job.progress_coalesced"

# Source des observations de travail emises par `JobService` (tache 11 du
# handoff work-state), et diagnostic d'une observation qui n'a pas pu partir.
JOB_WORK_SOURCE = "job"
JOB_WORK_STATE_FAILED_KIND = "core.job.work_state_failed"
#: Arrêt demandé par l'utilisateur (Slice 08) : attente de la fin du job avant
#: de répondre `cancel_requested` plutôt que `cancelled`.
USER_CANCEL_SETTLE_S = 5.0
#: Journal d'un arrêt de job demandé par l'utilisateur (issue, statut relu).
JOB_USER_CANCEL_KIND = "core.job.user_cancel"


def _work_error_class(exc: BaseException) -> str:
    """`error_class` d'un job en echec : le nom de l'exception s'il est un jeton valide.

    Un nom de classe Python peut contenir des lettres non ASCII, que le contrat
    refuse : l'observation d'echec serait perdue et le travail resterait
    « en cours » pour toujours. Repli sur `error` plutot.
    """

    name = type(exc).__name__.lstrip("_")[:MAX_ERROR_CLASS_CHARS]
    return name if name.isascii() and name else "error"


def is_speculative_job(job: Job) -> bool:
    """Vrai pour une analyse spéculative du back brain (`scope = speculative_analysis`)."""

    return isinstance(job.payload, dict) and job.payload.get("scope") == "speculative_analysis"


class SystemClock:
    def now(self) -> datetime:
        return utc_now()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class NullDiagnosticSink:
    """Puits de diagnostic inerte.

    Défaut du bus : les appelants qui n'injectent rien gardent exactement le
    comportement historique, sans dépendance vers un journal concret.
    """

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        return None


class CoreEventBus:
    """Bus d'événements borné, avec éviction observable.

    La politique reste inchangée : un abonné dont la file est pleine est
    désabonné (le bus ne devient jamais illimité). Ce qui change, c'est que
    l'éviction n'est plus silencieuse — elle est signalée au puits de
    diagnostic injecté, sinon une surface pourrait disparaître du flux sans
    laisser de trace.

    Un abonné peut demander l'autre borne (`subscribe(lossy=True)`) : sa file
    pleine perd l'événement le plus ancien au lieu de le faire désabonner. Le
    bus reste tout aussi borné, mais la surface survit à une rafale. Réservé
    aux abonnés permanents de Core qu'une éviction condamnerait pour la vie
    du processus, et dont la perte d'un événement ne perd pas le fait : leur
    état reste lisible dans l'instantané.
    """

    EVICTION_KIND = "core.event_bus.subscriber_evicted"
    DROP_KIND = "core.event_bus.event_dropped"
    _MAX_REPORTED_DROPS = 32

    def __init__(self, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._subscribers: set[asyncio.Queue[ProtocolEnvelope]] = set()
        self._lossy: set[asyncio.Queue[ProtocolEnvelope]] = set()
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._evicted_total = 0
        self._dropped_total = 0
        self._reported_drops: set[str] = set()

    @property
    def evicted_total(self) -> int:
        """Nombre cumulé d'abonnés évincés depuis la création du bus."""
        return self._evicted_total

    @property
    def dropped_total(self) -> int:
        """Événements perdus par un abonné tolérant depuis la création du bus."""
        return self._dropped_total

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: ProtocolEnvelope) -> None:
        dead: list[asyncio.Queue[ProtocolEnvelope]] = []
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                if queue in self._lossy:
                    self._drop_oldest(event, queue)
                else:
                    dead.append(queue)
        for queue in dead:
            self._subscribers.discard(queue)
            self._lossy.discard(queue)
            self._evicted_total += 1
            self._report_eviction(event, queue)

    def _drop_oldest(self, event: ProtocolEnvelope, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        """Faire de la place chez un abonné tolérant, et le dire une fois par type."""

        try:
            queue.get_nowait()
            queue.put_nowait(event)
        except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover - un seul fil publie
            return
        self._dropped_total += 1
        if event.message_type in self._reported_drops:
            return
        if len(self._reported_drops) >= self._MAX_REPORTED_DROPS:
            self._reported_drops.clear()
        self._reported_drops.add(event.message_type)
        try:
            self._diagnostics.emit(
                self.DROP_KIND,
                "événement perdu par un abonné tolérant : file saturée, abonnement gardé",
                level="warning",
                data={
                    "message_type": event.message_type,
                    "queue_maxsize": queue.maxsize,
                    "dropped_total": self._dropped_total,
                },
            )
        except Exception:
            # Même règle que pour l'éviction : l'observabilité ne casse jamais
            # la diffusion.
            pass

    def _report_eviction(self, event: ProtocolEnvelope, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        payload = {
            "message_type": event.message_type,
            "correlation_id": event.correlation_id,
            "conversation_id": event.conversation_id,
            "queue_maxsize": queue.maxsize,
            "queue_size": queue.qsize(),
            "remaining_subscribers": len(self._subscribers),
            "evicted_total": self._evicted_total,
        }
        try:
            self._diagnostics.emit(
                self.EVICTION_KIND,
                "abonné évincé du bus : file d'événements saturée",
                level="warning",
                data=payload,
            )
        except Exception:
            # L'observabilité ne doit jamais casser la diffusion d'événements :
            # un journal indisponible (disque plein, fichier verrouillé) ne peut
            # pas faire échouer un publish. La perte reste comptée dans
            # `evicted_total`, qui est lisible par l'appelant.
            pass

    def subscribe(self, *, max_queue: int = 128, lossy: bool = False) -> asyncio.Queue[ProtocolEnvelope]:
        queue: asyncio.Queue[ProtocolEnvelope] = asyncio.Queue(maxsize=max_queue)
        self._subscribers.add(queue)
        if lossy:
            self._lossy.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        self._subscribers.discard(queue)
        self._lossy.discard(queue)


class ConversationService:
    def __init__(self, state: StateRepository, history: HistoryStore, *, recent_turn_limit: int = 12) -> None:
        self.state = state
        self.history = history
        self.recent_turn_limit = max(1, recent_turn_limit)

    async def create(self, *, device_id: str = "windows-desktop") -> Conversation:
        conversation = Conversation(originating_device_id=device_id, current_device_id=device_id)
        await self.state.save_conversation(conversation)
        return conversation

    async def resume(self, conversation_id: str, *, transport_session_id: str | None = None) -> Conversation:
        conversation = await self.state.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        updated = replace(conversation, status=ConversationStatus.ACTIVE, updated_at=utc_now(), transport_session_id=transport_session_id)
        await self.state.save_conversation(updated)
        return updated

    async def close(self, conversation_id: str) -> Conversation:
        conversation = await self.resume(conversation_id)
        closed = replace(conversation, status=ConversationStatus.CLOSED, updated_at=utc_now(), transport_session_id=None)
        await self.state.save_conversation(closed)
        return closed

    async def append_turn(self, conversation_id: str, kind: TurnKind, content: str, *, correlation_id: str, reference_id: str | None = None, metadata: dict | None = None, turn_id: str | None = None, created_at: datetime | None = None) -> ConversationTurn:
        conversation = await self.state.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        turn = ConversationTurn(id=turn_id or new_id(), conversation_id=conversation_id, kind=kind, content=content, correlation_id=correlation_id, reference_id=reference_id, metadata=metadata or {}, created_at=created_at or utc_now())
        await self.state.save_turn(turn)
        await self.state.save_conversation(replace(conversation, updated_at=max(conversation.updated_at, turn.created_at)))
        await self.history.append(HistoryRecord(id=turn.id, kind=kind, created_at=turn.created_at, correlation_id=correlation_id, conversation_id=conversation_id, content=content, reference_id=reference_id, metadata=turn.metadata))
        return turn

    async def project_confirmed_voice_text(self, conversation_id: str, output_key: str, text: str, *,
                                           correlation_id: str, reference_id: str | None,
                                           metadata: dict, created_at: datetime) -> tuple[int, int]:
        """Append only new heard suffixes, replaying exact pending ranges first.

        SQLite stages a range before either existing store writes it. A crash
        after archive append but before completion can therefore never turn an
        old 0:5 range into overlapping 0:7 when a longer confirmation arrives.
        """
        offset, pending = await self.state.get_voice_projection(conversation_id, output_key)
        completed = 0
        while pending is not None or offset < len(text):
            if pending is None:
                end = len(text)
                pending = ConversationTurn(
                    id=f"voice-heard-{output_key}-{offset}-{end}", conversation_id=conversation_id,
                    kind=TurnKind.ASSISTANT, content=text[offset:end], created_at=created_at,
                    correlation_id=correlation_id, reference_id=reference_id,
                    metadata={**metadata, "confirmed_start": offset, "confirmed_end": end},
                )
                offset, pending = await self.state.stage_voice_projection(conversation_id, output_key, offset, pending)
            await self.append_turn(
                conversation_id, pending.kind, pending.content, correlation_id=pending.correlation_id,
                reference_id=pending.reference_id, metadata=pending.metadata,
                turn_id=pending.id, created_at=pending.created_at,
            )
            offset = await self.state.complete_voice_projection(conversation_id, output_key, pending.id)
            completed += 1
            pending = None
        return offset, completed

    async def list_turns(self, conversation_id: str, *, limit: int | None = None):
        """Derniers tours persistes, du plus ancien au plus recent.

        Passe-plat assume vers le magasin d'etat : il evite que les services du
        coeur (l'orchestrateur cerveau, notamment) aient a atteindre
        `ConversationService.state` a travers l'objet, ce qui rendrait la
        propriete du magasin illisible.
        """

        return await self.state.list_turns(conversation_id, limit=limit or self.recent_turn_limit)

    async def rehydration_context(self, conversation_id: str) -> dict[str, object]:
        conversation = await self.state.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        turns = await self.state.list_turns(conversation_id, limit=self.recent_turn_limit)
        # Les tours ouverts par Core lui-même (`BrainTurnSource.SYSTEM` : le
        # réveil sur un changement de travail de fond) sont persistés comme
        # tours d'entrée, parce qu'ils font autorité et portent une intention.
        # Mais personne ne les a dits : les laisser ici les ferait relire au
        # modèle vocal comme une phrase de l'utilisateur, consigne interne
        # comprise. Le contexte de conversation ne porte que ce qui a été dit.
        spoken = [turn for turn in turns if turn.metadata.get("source") != SYSTEM_TURN_SOURCE]
        return {
            "conversation_id": conversation.id,
            "summary": conversation.summary,
            "recent_turns": [{"kind": t.kind.value, "content": t.content, "created_at": t.created_at.isoformat()} for t in spoken],
        }


class SchedulerService:
    def __init__(self, state: StateRepository, events: CoreEventBus, *, clock: Clock | None = None) -> None:
        self.state = state
        self.events = events
        self.clock = clock or SystemClock()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._fired_keys: set[str] = set()

    async def create(self, item: ScheduledItem) -> ScheduledItem:
        await self.state.save_scheduled_item(item)
        return item

    async def cancel(self, item_id: str) -> None:
        for item in await self.state.list_scheduled_items():
            if item.id == item_id:
                await self.state.save_scheduled_item(replace(item, status=ScheduledStatus.CANCELLED))
                return
        raise KeyError(item_id)

    async def recover(self) -> None:
        now = self.clock.now()
        for item in await self.state.list_scheduled_items(active_only=True):
            if item.next_fire_at <= now:
                await self._evaluate_due(item, now, recovering=True)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        await self.recover()
        self._task = asyncio.create_task(self._run(), name="jarvis-v2-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            now = self.clock.now()
            for item in await self.state.list_scheduled_items(active_only=True):
                if item.next_fire_at <= now:
                    await self._evaluate_due(item, now, recovering=False)
            await self.clock.sleep(0.5)

    async def _evaluate_due(self, item: ScheduledItem, now: datetime, *, recovering: bool) -> None:
        scheduled_for = item.next_fire_at.isoformat()
        late_s = max(0.0, (now - item.next_fire_at).total_seconds())
        should_fire = True
        event_type = "schedule.triggered"
        if recovering:
            if item.missed_run_policy is MissedRunPolicy.SKIP:
                should_fire = False
            elif item.missed_run_policy is MissedRunPolicy.RUN_IF_RECENT:
                should_fire = late_s <= float(item.max_lateness_seconds or 0)
            elif item.missed_run_policy is MissedRunPolicy.REQUIRE_CONFIRMATION:
                should_fire = False
                event_type = "schedule.confirmation_required"
            elif item.missed_run_policy is MissedRunPolicy.NOTIFY_LATE:
                event_type = "schedule.triggered_late"
        fire_key = f"{item.id}:{scheduled_for}"
        if should_fire and fire_key not in self._fired_keys:
            self._fired_keys.add(fire_key)
            await self.events.publish(ProtocolEnvelope(message_type=event_type, payload={"scheduled_item_id": item.id, "scheduled_for": scheduled_for, "kind": item.kind, "payload": item.payload, "late_seconds": int(late_s)}, conversation_id=item.requested_by_conversation_id))
        elif not should_fire and event_type == "schedule.confirmation_required":
            await self.events.publish(ProtocolEnvelope(message_type=event_type, payload={"scheduled_item_id": item.id, "scheduled_for": scheduled_for, "payload": item.payload}, conversation_id=item.requested_by_conversation_id))

        if item.recurrence_seconds:
            next_fire = item.next_fire_at
            while next_fire <= now:
                next_fire += timedelta(seconds=item.recurrence_seconds)
            updated = replace(item, next_fire_at=next_fire, last_fire_at=now if should_fire else item.last_fire_at)
        else:
            updated = replace(item, status=ScheduledStatus.COMPLETED, last_fire_at=now if should_fire else item.last_fire_at)
        await self.state.save_scheduled_item(updated)


@dataclass(frozen=True, slots=True)
class _WorkLink:
    """Rattachement d'un job au travail cerveau qui l'a demande.

    En memoire uniquement, et volontairement : ce lien ne sert que pendant
    l'execution. Un redemarrage de Core marque de toute facon les jobs RUNNING
    comme INTERRUPTED (`JobService.recover`), donc rien de ce lien ne survivrait
    a un usage utile. Le persister imposerait une migration de schema pour une
    donnee qui n'a plus de sens au redemarrage.
    """

    work_id: str
    correlation_id: str


class _JobProgressChannel:
    """Puits d'avancement d'un job unique, borne a la source.

    Propriete
    ---------
    Cree et detruit par `JobService._execute`, confine a la tache du job. Le
    worker ne le partage avec personne, donc aucun verrou n'est pris ; cette
    invariante devrait etre revue si un jour un worker deleguait `emit` a
    plusieurs taches.

    Debit
    -----
    `CoreEventBus` reste borne a 128 et evince l'abonne dont la file deborde
    (Decision 25, question ouverte 6). Un worker bavard pourrait donc faire
    disparaitre la surface vocale du flux. Le debit est limite **ici**, a la
    source, plutot qu'en elargissant le bus :

    - la premiere progression part immediatement ;
    - ensuite, une progression au plus par `min_interval_s` ;
    - ce qui arrive dans la fenetre est coalesce : seule la plus recente
      survit, et elle sera publiee par le premier `emit()` qui tombe hors de
      la fenetre.

    Ce qui reste en attente a la fin du job est **jete, pas rejoue** :
    `brain.work.completed` porte deja la verite finale, et la Decision 31
    interdit de prononcer une progression qui n'est plus vraie. Consequence
    assumee : un worker qui emet une rafale puis se tait longtemps verra sa
    derniere progression perdue jusqu'a la fin du job. Le compteur
    `coalesced_total` rend cette perte visible au diagnostic.
    """

    def __init__(
        self,
        *,
        job: Job,
        events: CoreEventBus,
        link: _WorkLink,
        min_interval_s: float,
        clock: Clock,
        on_published: Callable[[JobProgress], Awaitable[None]] | None = None,
    ) -> None:
        self._job = job
        self._events = events
        self._link = link
        self._min_interval_s = max(0.0, min_interval_s)
        self._clock = clock
        # Suit la meme cadence que le bus : l'etat de travail ne recoit que les
        # progressions publiees, donc deja etranglees.
        self._on_published = on_published
        self._last_published_at: datetime | None = None
        self._pending: JobProgress | None = None
        self._published_total = 0
        self._coalesced_total = 0

    @property
    def published_total(self) -> int:
        return self._published_total

    @property
    def coalesced_total(self) -> int:
        """Progressions absorbees par la coalescence, donc jamais publiees."""

        return self._coalesced_total

    async def emit(self, job_id: str, progress: JobProgress) -> None:
        """Signaler un fait d'avancement. Ne decide jamais d'une prise de parole."""

        if job_id != self._job.id:
            raise ValueError(f"progress reported for another job: {job_id!r}")
        now = self._clock.now()
        if self._last_published_at is not None and (now - self._last_published_at).total_seconds() < self._min_interval_s:
            if self._pending is not None:
                self._coalesced_total += 1
            self._pending = progress
            return
        if self._pending is not None:
            # La plus recente prime : publier l'ancienne ferait dire au bus une
            # etape que le worker a deja depassee.
            self._coalesced_total += 1
            self._pending = None
        await self._publish(progress, now)

    def close(self) -> None:
        """Solder le canal a la fin du job, sans rien rejouer."""

        if self._pending is not None:
            self._coalesced_total += 1
            self._pending = None

    async def _publish(self, progress: JobProgress, now: datetime) -> None:
        self._last_published_at = now
        self._published_total += 1
        await self._events.publish(
            ProtocolEnvelope(
                message_type=BRAIN_WORK_PROGRESS,
                payload={
                    "work_id": self._link.work_id,
                    "job_id": self._job.id,
                    **progress.to_payload(),
                },
                correlation_id=self._link.correlation_id,
                conversation_id=self._job.requested_by_conversation_id,
            )
        )
        if self._on_published is not None:
            await self._on_published(progress)


class JobService:
    """Execution de travail long, avec une couture d'avancement neutre.

    Le service publie des **faits** (`brain.work.progress`) ; il ne fabrique
    jamais de parole. C'est le cerveau qui decide si un avancement merite
    d'etre dit (spec section 13). Un worker n'a donc aucun moyen, par cette
    couture, d'imposer une phrase a la surface vocale.
    """

    #: Intervalle minimal entre deux progressions publiees pour un meme job.
    #: 0,5 s borne le debit a deux evenements par seconde et par job, soit
    #: environ une minute de marge devant un abonne de 128 places, tout en
    #: restant sous le seuil de perception d'un humain qui ecoute.
    DEFAULT_PROGRESS_MIN_INTERVAL_S = 0.5

    def __init__(
        self,
        state: StateRepository,
        events: CoreEventBus,
        workers: dict[str, JobWorker],
        *,
        clock: Clock | None = None,
        diagnostics: DiagnosticSink | None = None,
        progress_min_interval_s: float | None = None,
        work_state: WorkObservationSink | None = None,
    ) -> None:
        self.state = state
        self.events = events
        self.workers = dict(workers)
        self.clock = clock or SystemClock()
        self.diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self.progress_min_interval_s = (
            self.DEFAULT_PROGRESS_MIN_INTERVAL_S if progress_min_interval_s is None else progress_min_interval_s
        )
        # Observateur de bord comme un autre (tache 11) : `JobService` garde la
        # persistance et l'execution des jobs, l'etat de travail normalise
        # appartient au magasin Core. Absent, rien ne change.
        self.work_state = work_state
        self._running: dict[str, asyncio.Task[None]] = {}
        self._links: dict[str, _WorkLink] = {}
        # Rattachement tel qu'affirme par l'appelant, sans le repli
        # synthetique `job:<id>` de `_links` : ce repli n'est pas un travail
        # cerveau et ne doit jamais apparaitre comme tel dans l'etat de travail.
        self._work_links: dict[str, WorkLink] = {}
        # Annulation idempotente (Slice 08, reprise QA) : `_started` note les
        # jobs dont `_execute` a commencé, `_cancel_requested` ceux dont
        # l'annulation est déjà demandée. Un second `cancel()` ne relance
        # jamais `task.cancel()` : il interromprait l'écriture de `cancelled`.
        self._started: set[str] = set()
        self._cancel_requested: set[str] = set()
        from jarvis.core.owned_job_execution import OwnedJobExecution
        self.owned = OwnedJobExecution(self)

    async def recover(self) -> None:
        for job in await self.state.list_jobs():
            if job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
                continue
            interrupted = replace(job, status=JobStatus.INTERRUPTED, error="core_restarted", completed_at=utc_now(), revision=job.revision + 1)
            await self.state.save_job(interrupted)
            if job.kind == "back_brain":
                from jarvis.domain.back_brain import BackBrainWorkPayload
                source = getattr(BackBrainWorkPayload.from_payload(job.payload).provenance, "source", None)
                if source is not None:
                    self._work_links[job.id] = WorkLink(work_id=job.id, correlation_id=source.correlation_id)
                await self.owned._publish(interrupted, "interrupted")
            else:
                await self.events.publish(ProtocolEnvelope(message_type="job.interrupted", payload={"job_id": job.id, "kind": job.kind}, conversation_id=job.requested_by_conversation_id))
            await self._observe_work(interrupted, WorkStatus.INTERRUPTED, error_class="core_restarted")
            self._work_links.pop(job.id, None)

    async def _observe_work(
        self,
        job: Job,
        status: WorkStatus,
        *,
        activity: str = "",
        progress_fraction: float | None = None,
        error_class: str | None = None,
    ) -> None:
        """Remettre un constat au magasin d'etat de travail. Ne leve jamais.

        L'etat de travail est une vue : son echec ne doit ni faire echouer un
        job, ni empecher sa persistance ou ses evenements `job.*`.
        """

        if self.work_state is None or is_speculative_job(job):
            # Une analyse spéculative n'est pas un travail du cerveau : ni
            # pendant son exécution (`OwnedJobExecution._observe_work`) ni à la
            # reprise après redémarrage (`recover`), elle n'entre dans l'état de
            # travail, donc jamais dans la scène.
            return
        try:
            await self.work_state.observe(
                WorkObservation(
                    source=JOB_WORK_SOURCE,
                    external_id=job.id,
                    status=status,
                    observed_at=utc_now(),
                    kind="job",
                    label=clip_text(job.kind, MAX_LABEL_CHARS),
                    activity=clip_text(activity, MAX_ACTIVITY_CHARS),
                    link=self._work_links.get(job.id, WorkLink()),
                    progress_fraction=progress_fraction,
                    error_class=error_class,
                    started_at=job.started_at,
                )
            )
        except Exception as exc:
            try:
                self.diagnostics.emit(
                    JOB_WORK_STATE_FAILED_KIND,
                    "etat de travail non mis a jour pour ce job",
                    level="warning",
                    data={"job_id": job.id, "status": status.value, "exception_type": type(exc).__name__},
                )
            except Exception:
                pass

    async def _observe_progress(self, job: Job, progress: JobProgress) -> None:
        await self._observe_work(
            job,
            WorkStatus.RUNNING,
            activity=progress.public_summary or progress.phase,
            progress_fraction=progress.fraction,
        )

    async def submit(self, job: Job, *, work_id: str | None = None, correlation_id: str | None = None) -> Job:
        """Lancer un job, en le rattachant si besoin au travail cerveau qui le demande.

        `work_id` et `correlation_id` sont optionnels : un job soumis par le
        planificateur n'appartient a aucun tour de conversation. Quand ils sont
        fournis, l'avancement publie porte le meme `work_id` que les
        `brain.work.*` du cerveau, ce qui rend les deux sources rattachables
        sans que `JobService` connaisse l'orchestrateur.
        """

        if job.kind == "back_brain":
            raise ValueError("back_brain requires canonical admitted ingress")
        if job.kind not in self.workers:
            raise KeyError(f"no worker for job kind {job.kind}")
        for existing in await self.state.list_jobs():
            if existing.idempotency_key == job.idempotency_key:
                return existing
        if job.id in self._running:
            return job
        await self.state.save_job(job)
        self._links[job.id] = _WorkLink(
            work_id=work_id or f"job:{job.id}",
            correlation_id=correlation_id or new_id(),
        )
        try:
            self._work_links[job.id] = WorkLink(work_id=work_id or None, correlation_id=correlation_id or None)
        except (TypeError, ValueError):
            # Identifiant hors contrat (trop long, espaces) : le job part quand
            # meme, son travail reste simplement non rattache.
            self._work_links[job.id] = WorkLink()
        task = asyncio.create_task(self._execute(job), name=f"jarvis-job-{job.id}")
        self._running[job.id] = task
        return job

    async def _execute(self, job: Job) -> None:
        # Première instruction, synchrone : dès ici `cancel()` annule la tâche
        # au lieu de seulement noter la demande (une tâche annulée avant son
        # premier pas n'exécuterait aucune ligne, et le job resterait `pending`).
        self._started.add(job.id)
        worker = self.workers[job.kind]
        link = self._links.get(job.id) or _WorkLink(work_id=f"job:{job.id}", correlation_id=new_id())
        running = replace(job, status=JobStatus.RUNNING, started_at=utc_now())
        channel = _JobProgressChannel(
            job=running,
            events=self.events,
            link=link,
            min_interval_s=self.progress_min_interval_s,
            clock=self.clock,
            on_published=lambda progress: self._observe_progress(running, progress),
        )
        try:
            if job.id in self._cancel_requested:
                # Annulé avant de démarrer : jamais exécuté, terminé annulé.
                await self._settle_cancelled(replace(job, status=JobStatus.CANCELLED, completed_at=utc_now()))
                return
            await self.state.save_job(running)
            await self._observe_work(running, WorkStatus.RUNNING)
            result = await self._run_worker(worker, running, channel)
            completed = replace(running, status=JobStatus.COMPLETED, result=dict(result), completed_at=utc_now())
            await self.state.save_job(completed)
            await self.events.publish(ProtocolEnvelope(message_type="job.completed", payload={"job_id": job.id, "kind": job.kind, "result": result}, correlation_id=link.correlation_id, conversation_id=job.requested_by_conversation_id))
            await self._observe_work(running, WorkStatus.COMPLETED)
        except asyncio.CancelledError:
            await self._settle_cancelled(replace(running, status=JobStatus.CANCELLED, completed_at=utc_now()))
            raise
        except Exception as exc:
            failed = replace(running, status=JobStatus.FAILED, error=f"{type(exc).__name__}: {exc}", completed_at=utc_now())
            await self.state.save_job(failed)
            await self.events.publish(ProtocolEnvelope(message_type="job.failed", payload={"job_id": job.id, "kind": job.kind, "error_class": type(exc).__name__}, correlation_id=link.correlation_id, conversation_id=job.requested_by_conversation_id))
            await self._observe_work(running, WorkStatus.FAILED, error_class=_work_error_class(exc))
        finally:
            channel.close()
            self._report_progress_budget(job, link, channel)
            self._running.pop(job.id, None)
            self._started.discard(job.id)
            self._cancel_requested.discard(job.id)
            self._links.pop(job.id, None)
            self._work_links.pop(job.id, None)

    async def _settle_cancelled(self, cancelled: Job) -> None:
        """Écrire la fin annulée et l'observer, sans qu'une annulation de plus ne la coupe.

        La persistance tourne dans sa propre tâche, attendue sous `shield` :
        une annulation qui arrive pendant l'écriture (second arrêt, arrêt de
        Core) est absorbée jusqu'à la fin de l'écriture ; l'appelant relève
        ensuite sa propre `CancelledError`. Jamais un job `running` à jamais.
        """

        async def persist() -> None:
            await self.state.save_job(cancelled)
            await self._observe_work(cancelled, WorkStatus.CANCELLED)

        write = asyncio.ensure_future(persist())
        while not write.done():
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                if write.done():
                    break
                continue
        write.result()

    async def _run_worker(self, worker: JobWorker, job: Job, progress: JobProgressSink) -> dict[str, object]:
        """Executer le worker, avec la couture d'avancement s'il la declare.

        Detection structurelle et non par inspection de signature : un worker
        historique n'a pas `execute_with_progress`, il continue donc d'etre
        appele par `execute` sans la moindre modification.
        """

        if isinstance(worker, ProgressReportingJobWorker):
            return await worker.execute_with_progress(job, progress)
        return await worker.execute(job)

    def _report_progress_budget(self, job: Job, link: _WorkLink, channel: _JobProgressChannel) -> None:
        """Rendre visible ce que l'etranglement a absorbe (Decision 25).

        Une progression coalescee n'est pas une panne : elle est le prix,
        assume, de ne pas saturer un bus borne. Elle doit malgre tout laisser
        une trace, sinon un worker devenu bavard passerait inapercu.
        """

        if channel.coalesced_total <= 0:
            return
        self.diagnostics.emit(
            JOB_PROGRESS_COALESCED_KIND,
            "avancement coalesce a la source pour proteger le bus",
            level="info",
            data={
                "job_id": job.id,
                "kind": job.kind,
                "work_id": link.work_id,
                "correlation_id": link.correlation_id,
                "published_total": channel.published_total,
                "coalesced_total": channel.coalesced_total,
                "min_interval_s": self.progress_min_interval_s,
            },
        )

    async def cancel_work(self, work_id: str) -> tuple[str, ...]:
        """Annuler les jobs rattaches a un `work_id` du cerveau, et eux seuls.

        Implemente le port `WorkCanceller`. La selection passe par les liens
        poses a la soumission (`_WorkLink`) : un job soumis sans `work_id` a
        recu un lien synthetique `job:<id>`, donc il ne peut pas etre atteint
        par erreur depuis une decision du cerveau.

        Rend les identifiants de job reellement annules — la liste vide est un
        cas normal, pas une panne : le cerveau peut retirer du travail qui
        n'avait aucun job executable derriere lui.
        """

        if not work_id:
            return ()
        # Instantane : `_execute` retire le lien en fin de job, donc iterer
        # directement sur le dictionnaire le muterait en cours de parcours.
        targets = tuple(job_id for job_id, link in self._links.items() if link.work_id == work_id)
        for job_id in targets:
            await self.cancel(job_id)
        return targets

    async def cancel_for_user(self, job_id: str, *, settle_s: float = USER_CANCEL_SETTLE_S) -> tuple[str, Job]:
        """Arrêt d'un job demandé par l'utilisateur depuis la scène (Slice 08).

        Même primitive que `cancel_work` (`cancel(job_id)`), mais sur **un**
        job désigné par son identifiant : l'étoile `job` porte
        `work_ref = (job, <job id>)`. `cancel_work(work_id)` ne convient pas
        ici : il annulerait tous les jobs d'un même travail du cerveau, et
        n'atteint pas les jobs `back_brain` (sans lien `_links`).

        Rend `(issue, job relu)` : `cancelled` (terminé annulé dans le délai),
        `cancel_requested` (annulation demandée, fin pas encore observée dans
        `settle_s`), `cleanup_unknown` (job `back_brain` : annulation demandée,
        nettoyage de l'exécution non confirmé), `already_terminal` (rien à
        arrêter). Job inconnu ou analyse spéculative (jamais une étoile) :
        `KeyError`. Arrête **ce** job seulement : l'élément de travail du
        cerveau qui l'aurait demandé n'est pas touché (sa fin vient de ses
        propres observations). Deux arrêts concurrents, ou un arrêt pendant
        `cancel_work`, n'annulent la tâche qu'une fois (`cancel`).
        """

        job = await self.state.get_job(job_id)
        if job is None or is_speculative_job(job):
            raise KeyError(f"job {job_id} not found")
        if job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
            return "already_terminal", job
        await self.cancel(job_id)
        task = self._running.get(job_id)
        if task is not None and not task.done():
            # Attendre la fin sans jamais l'annuler une seconde fois : `wait` ne touche pas la tâche.
            await asyncio.wait({task}, timeout=max(0.0, settle_s))
        latest = await self.state.get_job(job_id) or job
        if latest.status is JobStatus.CANCELLED:
            outcome = "cancelled"
        elif latest.cancellation == "cleanup_unknown":
            outcome = "cleanup_unknown"
        else:
            outcome = "cancel_requested"
        self.diagnostics.emit(
            JOB_USER_CANCEL_KIND,
            "arrêt d'un job demandé par l'utilisateur",
            level="info",
            data={"job_id": job_id, "kind": job.kind, "outcome": outcome, "status": latest.status.value},
        )
        return outcome, latest

    async def cancel(self, job_id: str) -> None:
        job = await self.state.get_job(job_id)
        if job is not None and job.kind == "back_brain":
            await self.owned.cancel(job_id)
            return
        task = self._running.get(job_id)
        if task and not task.done() and job_id not in self._cancel_requested:
            self._cancel_requested.add(job_id)
            if job_id in self._started:
                task.cancel()
            # Pas encore démarrée : `_execute` voit la demande à son premier pas.
        for worker in self.workers.values():
            try:
                await worker.cancel(job_id)
            except Exception:
                continue

    async def stop(self) -> bool:
        if not await self.owned.stop():
            return False
        tasks = tuple(self._running.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._running.clear()
        return True


class NotificationService:
    def __init__(self, state: StateRepository, delivery: NotificationDelivery) -> None:
        self.state = state
        self.delivery = delivery
        self._delivering: set[str] = set()

    async def create(self, notification: Notification, *, deliver: bool = True) -> Notification:
        existing = [n for n in await self.state.list_notifications() if n.idempotency_key == notification.idempotency_key]
        if existing:
            return existing[0]
        await self.state.save_notification(notification)
        if deliver:
            await self.deliver(notification.id)
        return notification

    async def deliver(self, notification_id: str) -> None:
        if notification_id in self._delivering:
            return
        candidates = [n for n in await self.state.list_notifications() if n.id == notification_id]
        if not candidates:
            raise KeyError(notification_id)
        notification = candidates[0]
        if notification.state in {NotificationState.DELIVERED, NotificationState.ACKNOWLEDGED, NotificationState.EXPIRED}:
            return
        if notification.expires_at and notification.expires_at <= utc_now():
            await self.state.save_notification(replace(notification, state=NotificationState.EXPIRED))
            return
        self._delivering.add(notification_id)
        try:
            await self.delivery.deliver(notification)
            await self.state.save_notification(replace(notification, state=NotificationState.DELIVERED, delivered_at=utc_now()))
        except Exception:
            await self.state.save_notification(replace(notification, state=NotificationState.FAILED))
            raise
        finally:
            self._delivering.discard(notification_id)

    async def recover(self) -> None:
        for notification in await self.state.list_notifications(state=NotificationState.PENDING.value):
            try:
                await self.deliver(notification.id)
            except Exception:
                continue
