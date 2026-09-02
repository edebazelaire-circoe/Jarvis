from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from jarvis.adapters.fake_calendar import InMemoryCalendarBackend
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.windows_notifications import NullNotificationDelivery
from jarvis.core.calendar_service import CalendarService
from jarvis.core.v2_services import ConversationService, CoreEventBus, JobService, NotificationService, SchedulerService
from jarvis.core.v2_tools import CoreToolRouter
from jarvis.domain.v2 import Device, Notification, NotificationPriority


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

    def __init__(self, *, data_root: Path, timezone: str = "Europe/Paris", calendar_backend=None, notification_delivery=None, workers=None) -> None:
        root = Path(data_root).resolve()
        self.state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
        self.history = JsonlHistoryStore(root / "history")
        self.events = CoreEventBus()
        self.conversations = ConversationService(self.state, self.history)
        self.scheduler = SchedulerService(self.state, self.events)
        self.jobs = JobService(self.state, self.events, workers or {})
        self.notifications = NotificationService(self.state, notification_delivery or NullNotificationDelivery())
        self.calendar = CalendarService(calendar_backend or InMemoryCalendarBackend())
        self.tools = CoreToolRouter(scheduler=self.scheduler, calendar=self.calendar, timezone=timezone)
        self.health = CoreHealth()
        self._stopped = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        try:
            await self.state.initialize()
            await self.state.save_device(Device())
            await self.jobs.recover()
            await self.notifications.recover()
            await self.scheduler.start()
            self._notification_task = asyncio.create_task(self._notification_loop(), name="jarvis-v2-notifications")
            self.health.ready = True
            self.health.status = "ok"
        except Exception as exc:
            self.health.ready = False
            self.health.status = "fail"
            self.health.detail = f"{type(exc).__name__}: {exc}"
            raise

    async def _notification_loop(self) -> None:
        queue = self.events.subscribe()
        try:
            while True:
                event = await queue.get()
                if event.message_type not in {"schedule.triggered", "schedule.triggered_late", "job.completed", "job.failed", "job.interrupted"}:
                    continue
                reference = str(event.payload.get("scheduled_item_id") or event.payload.get("job_id") or event.correlation_id)
                if event.message_type.startswith("schedule."):
                    payload = event.payload.get("payload") if isinstance(event.payload.get("payload"), dict) else {}
                    summary = "Rappel Jarvis"
                    body = str(payload.get("message") or "Un rappel est arrivé à échéance.")
                elif event.message_type == "job.completed":
                    summary, body = "Tâche Jarvis terminée", f"La tâche {event.payload.get('kind', '')} est terminée."
                else:
                    summary, body = "Tâche Jarvis à vérifier", f"État: {event.message_type}."
                notification = Notification(summary=summary, body=body, priority=NotificationPriority.NORMAL, originating_reference_id=reference, idempotency_key=f"event:{event.message_type}:{reference}")
                await self.notifications.create(notification, deliver=True)
        finally:
            self.events.unsubscribe(queue)

    async def stop(self) -> None:
        self.health.ready = False
        self.health.status = "stopping"
        task, self._notification_task = self._notification_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.jobs.stop()
        await self.scheduler.stop()
        await self.state.close()
        self.health.status = "stopped"
        self._stopped.set()

    async def wait(self) -> None:
        await self._stopped.wait()
