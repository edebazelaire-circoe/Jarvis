from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

from jarvis.domain.v2 import (
    Conversation, ConversationStatus, ConversationTurn, HistoryRecord, Job, JobStatus,
    MissedRunPolicy, Notification, NotificationState, ProtocolEnvelope, ScheduledItem,
    ScheduledStatus, TurnKind, utc_now,
)
from jarvis.ports.v2 import Clock, HistoryStore, JobWorker, NotificationDelivery, StateRepository


class SystemClock:
    def now(self) -> datetime:
        return utc_now()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class CoreEventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[ProtocolEnvelope]] = set()

    async def publish(self, event: ProtocolEnvelope) -> None:
        dead: list[asyncio.Queue[ProtocolEnvelope]] = []
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._subscribers.discard(queue)

    def subscribe(self, *, max_queue: int = 128) -> asyncio.Queue[ProtocolEnvelope]:
        queue: asyncio.Queue[ProtocolEnvelope] = asyncio.Queue(maxsize=max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        self._subscribers.discard(queue)


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

    async def append_turn(self, conversation_id: str, kind: TurnKind, content: str, *, correlation_id: str, reference_id: str | None = None, metadata: dict | None = None) -> ConversationTurn:
        conversation = await self.state.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        turn = ConversationTurn(conversation_id=conversation_id, kind=kind, content=content, correlation_id=correlation_id, reference_id=reference_id, metadata=metadata or {})
        await self.state.save_turn(turn)
        await self.state.save_conversation(replace(conversation, updated_at=turn.created_at))
        await self.history.append(HistoryRecord(id=turn.id, kind=kind, created_at=turn.created_at, correlation_id=correlation_id, conversation_id=conversation_id, content=content, reference_id=reference_id, metadata=turn.metadata))
        return turn

    async def rehydration_context(self, conversation_id: str) -> dict[str, object]:
        conversation = await self.state.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        turns = await self.state.list_turns(conversation_id, limit=self.recent_turn_limit)
        return {
            "conversation_id": conversation.id,
            "summary": conversation.summary,
            "recent_turns": [{"kind": t.kind.value, "content": t.content, "created_at": t.created_at.isoformat()} for t in turns],
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


class JobService:
    def __init__(self, state: StateRepository, events: CoreEventBus, workers: dict[str, JobWorker]) -> None:
        self.state = state
        self.events = events
        self.workers = dict(workers)
        self._running: dict[str, asyncio.Task[None]] = {}

    async def recover(self) -> None:
        for job in await self.state.list_jobs(status=JobStatus.RUNNING.value):
            await self.state.save_job(replace(job, status=JobStatus.INTERRUPTED, error="core restarted while job was running", completed_at=utc_now()))
            await self.events.publish(ProtocolEnvelope(message_type="job.interrupted", payload={"job_id": job.id, "kind": job.kind}, conversation_id=job.requested_by_conversation_id))

    async def submit(self, job: Job) -> Job:
        if job.kind not in self.workers:
            raise KeyError(f"no worker for job kind {job.kind}")
        for existing in await self.state.list_jobs():
            if existing.idempotency_key == job.idempotency_key:
                return existing
        if job.id in self._running:
            return job
        await self.state.save_job(job)
        task = asyncio.create_task(self._execute(job), name=f"jarvis-job-{job.id}")
        self._running[job.id] = task
        return job

    async def _execute(self, job: Job) -> None:
        worker = self.workers[job.kind]
        running = replace(job, status=JobStatus.RUNNING, started_at=utc_now())
        await self.state.save_job(running)
        try:
            result = await worker.execute(running)
            completed = replace(running, status=JobStatus.COMPLETED, result=dict(result), completed_at=utc_now())
            await self.state.save_job(completed)
            await self.events.publish(ProtocolEnvelope(message_type="job.completed", payload={"job_id": job.id, "kind": job.kind, "result": result}, conversation_id=job.requested_by_conversation_id))
        except asyncio.CancelledError:
            cancelled = replace(running, status=JobStatus.CANCELLED, completed_at=utc_now())
            await self.state.save_job(cancelled)
            raise
        except Exception as exc:
            failed = replace(running, status=JobStatus.FAILED, error=f"{type(exc).__name__}: {exc}", completed_at=utc_now())
            await self.state.save_job(failed)
            await self.events.publish(ProtocolEnvelope(message_type="job.failed", payload={"job_id": job.id, "kind": job.kind, "error_class": type(exc).__name__}, conversation_id=job.requested_by_conversation_id))
        finally:
            self._running.pop(job.id, None)

    async def cancel(self, job_id: str) -> None:
        task = self._running.get(job_id)
        if task:
            task.cancel()
        for worker in self.workers.values():
            try:
                await worker.cancel(job_id)
            except Exception:
                continue

    async def stop(self) -> None:
        tasks = tuple(self._running.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._running.clear()


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
