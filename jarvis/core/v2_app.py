from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from jarvis.adapters.fake_calendar import InMemoryCalendarBackend
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_conversation_events import SQLiteConversationEventStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.windows_notifications import NullNotificationDelivery
from jarvis.core.brain_context import ATTENTION_QUEUE_SIZE, DEFAULT_WAKE_INTERVAL_S, BrainContextBuilder, WorkAttentionPolicy
from jarvis.core.brain_service import DEFAULT_TURN_BUDGET_S, BrainOrchestrator
from jarvis.core.calendar_service import CalendarService
from jarvis.core.drive_service import DriveService
from jarvis.core.v2_services import ConversationService, CoreEventBus, JobService, NotificationService, SchedulerService
from jarvis.core.v2_tools import CoreToolRouter
from jarvis.core.work_state import WorkStateStore
from jarvis.core.voice_ledger import VoiceLedgerService
from jarvis.core.live_lifecycle import LiveLifecycleService
from jarvis.core.live_reaper import LiveLifecycleWatchdog
from jarvis.domain.v2 import Device, Job, MissedRunPolicy, Notification, NotificationPriority, ProtocolEnvelope, ScheduledItem, ScheduledStatus, utc_now
from jarvis.ports.v2 import DiagnosticSink


@dataclass(slots=True)
class CoreHealth:
    ready: bool = False
    status: str = "starting"
    detail: str = ""


class JarvisCoreApplication:
    """Long-lived provider-neutral v0.2 application container.

    Concrete adapters are injected. Defaults are deterministic/local so Core can
    start headlessly with no microphone, Realtime provider, Calendar credentials
    or Windows UI dependency.
    """

    def __init__(self, *, data_root: Path, timezone: str = "Europe/Paris", calendar_backend=None, drive_backend=None, brain_backend=None, notification_delivery=None, workers=None, diagnostics: DiagnosticSink | None = None, supersede_stale_replies: bool = True, brain_turn_budget_s: float = DEFAULT_TURN_BUDGET_S, live_sideband_closer=None, work_attention_wake_interval_s: float = DEFAULT_WAKE_INTERVAL_S) -> None:
        root = Path(data_root).resolve()
        self.health = CoreHealth()
        self.state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
        self.history = JsonlHistoryStore(root / "history")
        # Conversation Event log (handoff conversation-observability, Slice 02):
        # same state DB, connection and lifecycle as `self.state` (schema v2).
        # Core owns it; producers and routes are wired by later Slices.
        self.conversation_events = SQLiteConversationEventStore(self.state, diagnostics=diagnostics)
        self.events = CoreEventBus(diagnostics=diagnostics)
        self.conversations = ConversationService(self.state, self.history)
        self.voice_ledger = VoiceLedgerService(self.conversations, diagnostics=diagnostics)
        self.live_lifecycle = LiveLifecycleService(
            self.state, diagnostics=diagnostics, accepting_new=lambda: self.health.ready,
        )
        self.live_reaper = LiveLifecycleWatchdog(
            self.live_lifecycle, closer=live_sideband_closer, diagnostics=diagnostics,
        )
        self.scheduler = SchedulerService(self.state, self.events)
        # État de travail détaillé, possédé par Core (handoff work-state, tâche
        # 11) : alimenté par les jobs et par l'ingress `/v1/work/observations`,
        # en mémoire seulement (voir `jarvis/core/work_state.py`).
        self.work_state = WorkStateStore(events=self.events, diagnostics=diagnostics)
        self.jobs = JobService(self.state, self.events, workers or {}, diagnostics=diagnostics, work_state=self.work_state)
        # Tâche 12 : le cerveau lit ce même magasin à chaque tour, et une
        # politique abonnée à `core.work.updated` retient pour lui les échecs,
        # interruptions et blocages (voir `jarvis/core/brain_context.py`).
        #
        # Le réveil est câblé. Sans lui, la politique n'était qu'un tampon :
        # un sous-agent pouvait mourir sans un mot, et l'utilisateur ne
        # l'apprenait qu'en reparlant de lui-même — donc jamais s'il se taisait.
        # Le rappel arrive par une fermeture, car `self.brain` n'existe que
        # plus bas ; il ne dit rien lui-même, il ouvre un tour et laisse le
        # cerveau choisir ses mots.
        self.work_attention = WorkAttentionPolicy(
            diagnostics=diagnostics,
            wake=self._wake_brain_for_work,
            wake_interval_s=work_attention_wake_interval_s,
        )
        self.brain_context = BrainContextBuilder(
            reader=self.work_state,
            store_id=self.work_state.store_id,
            attention=self.work_attention,
            diagnostics=diagnostics,
        )
        self.notifications =NotificationService(self.state, notification_delivery or NullNotificationDelivery())
        self.calendar = CalendarService(calendar_backend or InMemoryCalendarBackend())
        # Pas de repli en mémoire pour Drive : un faux Drive donnerait à
        # l'utilisateur la certitude d'avoir déposé un fichier qui n'existe pas.
        self.drive = DriveService(drive_backend)
        # Le cerveau autoritaire vit dans Core (Décision 01). Le backend fort est
        # injecté depuis l'extérieur (Décision 28) : à défaut, l'objet nul défini
        # dans `brain_service` garde un démarrage headless possible sans jamais
        # faire croire qu'un tour a été traité.
        # `jobs` est la couture d'annulation (`WorkCanceller`) : une décision
        # explicite du cerveau doit arrêter le job qu'elle vise, sinon
        # l'annulation ne serait qu'une écriture d'état.
        self.brain = BrainOrchestrator(
            conversations=self.conversations,
            events=self.events,
            backend=brain_backend,
            jobs=self.jobs,
            diagnostics=diagnostics,
            supersede_stale_replies=supersede_stale_replies,
            turn_budget_s=brain_turn_budget_s,
            work_context=self.brain_context,
            voice_ledger=self.voice_ledger,
        )
        self.outcomes = self.brain.outcomes
        self.voice_admission = self.brain.admission
        from jarvis.core.back_brain import BackBrainTaskService
        self.back_brain = BackBrainTaskService(self.jobs, self.conversations, self.voice_ledger)
        self.tools = CoreToolRouter(scheduler=self.scheduler, calendar=self.calendar, drive=self.drive, timezone=timezone)
        self._stopped = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None
        self._notification_queue: asyncio.Queue[ProtocolEnvelope] | None = None
        # Relais spontanés du cerveau (fin d'un sous-agent) : capacité
        # optionnelle du backend, détectée structurellement comme les autres.
        self._brain_notices = getattr(brain_backend, "next_notices", None)
        self._brain_notice_task: asyncio.Task[None] | None = None
        self._work_attention_task: asyncio.Task[None] | None = None
        self._work_attention_queue: asyncio.Queue[ProtocolEnvelope] | None = None

    async def start(self) -> None:
        if self.health.ready:
            return
        try:
            await self.state.initialize()
            self.live_reaper.start()
            await self.state.save_device(Device())
            # Subscribe before recovery: overdue schedules and interrupted jobs
            # may emit events immediately during startup.
            self._notification_queue = self.events.subscribe()
            self._notification_task = asyncio.create_task(self._notification_loop(self._notification_queue), name="jarvis-v2-notifications")
            # Abonné tolérant : une éviction éteindrait l'attention pour la vie
            # du processus (rien ne se réabonne), alors qu'une rafale coûte au
            # pire une note — le statut du travail, lui, reste dans l'instantané.
            self._work_attention_queue = self.events.subscribe(max_queue=ATTENTION_QUEUE_SIZE, lossy=True)
            self._work_attention_task = asyncio.create_task(self.work_attention.run(self._work_attention_queue), name="jarvis-work-attention")
            await self.notifications.recover()
            await self.jobs.recover()
            await self._ensure_system_schedules()
            await self.scheduler.start()
            if callable(self._brain_notices):
                self._brain_notice_task = asyncio.create_task(self._brain_notice_loop(self._brain_notices), name="jarvis-brain-notices")
            self.health.ready = True
            self.health.status = "ok"
            self.health.detail = ""
        except Exception as exc:
            self.health.ready = False
            self.health.status = "fail"
            self.health.detail = f"{type(exc).__name__}: {exc}"
            await self.live_reaper.stop()
            await self._stop_notification_loop()
            await self._stop_work_attention()
            try:
                await self.state.close()
            except Exception:
                pass
            raise

    async def _wake_brain_for_work(self, notes) -> None:
        """Rappel de `WorkAttentionPolicy` : ouvrir un tour sur un changement de fond.

        Rien n'est dit ici, et rien n'est consommé : le cerveau décide s'il
        parle, et seuls les changements qu'un contexte de tour a vraiment
        portés sont retirés de l'attente (`take_delivered`). Une exception est
        déjà absorbée et signalée par la politique appelante
        (`core.work.attention_wake_failed`) ; le changement attend alors le
        tour suivant plutôt que d'éteindre la boucle.
        """

        await self.brain.wake_for_work_attention(tuple(notes))

    async def _ensure_system_schedules(self) -> None:
        if "memory_maintenance" not in self.jobs.workers:
            return
        existing = await self.state.list_scheduled_items()
        if any(item.idempotency_key == "system:memory-maintenance-daily" and item.status is not ScheduledStatus.CANCELLED for item in existing):
            return
        item = ScheduledItem(
            kind="job",
            payload={"job_kind": "memory_maintenance", "payload": {}},
            next_fire_at=utc_now() + timedelta(days=1),
            recurrence_seconds=24 * 60 * 60,
            missed_run_policy=MissedRunPolicy.SKIP,
            idempotency_key="system:memory-maintenance-daily",
        )
        await self.scheduler.create(item)

    async def _notification_loop(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        try:
            while True:
                event = await queue.get()
                if event.message_type not in {"schedule.triggered", "schedule.triggered_late", "job.completed", "job.failed", "job.interrupted"}:
                    continue
                reference = str(event.payload.get("scheduled_item_id") or event.payload.get("job_id") or event.correlation_id)
                if event.message_type.startswith("schedule."):
                    payload = event.payload.get("payload") if isinstance(event.payload.get("payload"), dict) else {}
                    if event.payload.get("kind") == "job":
                        job_kind = str(payload.get("job_kind") or "").strip()
                        job_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
                        scheduled_for = str(event.payload.get("scheduled_for") or "unknown")
                        try:
                            await self.jobs.submit(Job(kind=job_kind, payload=job_payload, requested_by_conversation_id=event.conversation_id, idempotency_key=f"schedule:{reference}:{scheduled_for}"))
                        except Exception as exc:
                            notification = Notification(summary="Tâche planifiée Jarvis en échec", body=f"Impossible de lancer {job_kind or 'la tâche'} ({type(exc).__name__}).", priority=NotificationPriority.HIGH, originating_reference_id=reference, idempotency_key=f"schedule-dispatch-failed:{reference}:{scheduled_for}")
                            try:
                                await self.notifications.create(notification, deliver=True)
                            except Exception:
                                pass
                        continue
                    summary = "Rappel Jarvis"
                    body = str(payload.get("message") or "Un rappel est arrivé à échéance.")
                elif event.message_type == "job.completed":
                    summary, body = "Tâche Jarvis terminée", f"La tâche {event.payload.get('kind', '')} est terminée."
                else:
                    summary, body = "Tâche Jarvis à vérifier", f"État: {event.message_type}."
                notification = Notification(summary=summary, body=body, priority=NotificationPriority.NORMAL, originating_reference_id=reference, idempotency_key=f"event:{event.message_type}:{reference}")
                try:
                    await self.notifications.create(notification, deliver=True)
                except Exception:
                    # Notification state is persisted as FAILED by the service;
                    # the Core event loop must stay alive if the OS channel fails.
                    continue
        finally:
            self.events.unsubscribe(queue)

    async def _brain_notice_loop(self, next_notices) -> None:
        """Faire dire, dès qu'ils arrivent, les relais que le cerveau rédige seul.

        `next_notices()` attend (longuement) et ne lève pas en temps normal ;
        une exception inattendue est absorbée avec une pause, pour que la
        boucle survive à un backend fautif sans tourner à vide.
        """
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            try:
                texts = await next_notices()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5.0)
                continue
            for text in texts or ():
                await self.brain.announce_notice(str(text))
            if not texts and loop.time() - started < 0.05:
                # Un backend qui rend la main aussitôt ne doit pas monopoliser la boucle.
                await asyncio.sleep(1.0)

    async def _stop_brain_notice_loop(self) -> None:
        task, self._brain_notice_task = self._brain_notice_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _stop_notification_loop(self) -> None:
        task, self._notification_task = self._notification_task, None
        queue, self._notification_queue = self._notification_queue, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if queue is not None:
            self.events.unsubscribe(queue)

    async def _stop_work_attention(self) -> None:
        task, self._work_attention_task = self._work_attention_task, None
        queue, self._work_attention_queue = self._work_attention_queue, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if queue is not None:
            self.events.unsubscribe(queue)
        await self.work_attention.stop()

    async def stop(self) -> None:
        if self.health.status == "stopped":
            return
        self.health.ready = False
        self.health.status = "stopping"
        self.back_brain.stopping = True
        self.jobs.owned.stopping = True
        await self.live_reaper.stop()
        # Le cerveau s'arrête en premier : ses tâches écrivent en base via
        # ConversationService et publient sur le bus, deux ressources fermées plus bas.
        # Le relais spontané le précède : il alimente le cerveau.
        await self._stop_brain_notice_loop()
        # La politique d'état de travail aussi : un réveil pourrait nourrir le cerveau.
        await self._stop_work_attention()
        await self.brain.stop()
        await self._stop_notification_loop()
        await self.scheduler.stop()
        if not await self.back_brain.stop():
            self.health.status = "state_persistence_unknown"
            self.health.detail = "back brain submission remains owned while storage completes"
            return
        if not await self.jobs.stop():
            self.health.status = "state_persistence_unknown" if self.jobs.owned.persistence_failures else "cleanup_unknown"
            self.health.detail = "back brain finalization remains owned and unconfirmed"
            return
        await self.state.close()
        self.health.status = "stopped"
        self._stopped.set()

    async def wait(self) -> None:
        await self._stopped.wait()
