from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.core.calendar_service import CalendarService
from jarvis.core.v2_services import SchedulerService
from jarvis.domain.calendar import CalendarEvent, CalendarQuery
from jarvis.domain.v2 import MissedRunPolicy, ScheduledItem, new_id
from jarvis.security.v2_policy import ActionDisposition, V2ActionBroker


class CoreToolRouter:
    """Authoritative tool boundary for Voice/Realtime clients."""

    def __init__(self, *, scheduler: SchedulerService, calendar: CalendarService, timezone: str = "Europe/Paris") -> None:
        self.scheduler = scheduler
        self.calendar = calendar
        self.timezone = ZoneInfo(timezone)
        self.policy = V2ActionBroker()

    async def call(self, name: str, arguments: dict[str, object], *, conversation_id: str | None) -> dict[str, object]:
        ambiguous = not isinstance(arguments, dict) or self._is_ambiguous(name, arguments)
        disposition = self.policy.evaluate(name, explicit_request=True, ambiguous=ambiguous)
        if disposition is not ActionDisposition.EXECUTE:
            return {"disposition": disposition.value, "executed": False, "action": name}
        if name == "reminder_create":
            due_at = self._datetime(arguments["due_at"])
            item = ScheduledItem(kind="reminder", payload={"message": str(arguments["message"])}, next_fire_at=due_at, missed_run_policy=MissedRunPolicy(str(arguments.get("missed_run_policy") or MissedRunPolicy.NOTIFY_LATE.value)), max_lateness_seconds=int(arguments["max_lateness_seconds"]) if arguments.get("max_lateness_seconds") is not None else None, requested_by_conversation_id=conversation_id)
            await self.scheduler.create(item)
            return {"disposition": disposition.value, "executed": True, "scheduled_item_id": item.id, "next_fire_at": item.next_fire_at.isoformat()}
        if name == "calendar_list":
            query = CalendarQuery(start_at=self._datetime(arguments["start_at"]), end_at=self._datetime(arguments["end_at"]), text=str(arguments["text"]) if arguments.get("text") else None)
            events = await self.calendar.find(query)
            return {"disposition": disposition.value, "executed": True, "events": [self._event_payload(e) for e in events]}
        if name == "calendar_create":
            event = CalendarEvent(title=str(arguments["title"]), start_at=self._datetime(arguments["start_at"]), end_at=self._datetime(arguments["end_at"]), timezone=str(arguments.get("timezone") or self.timezone.key), description=str(arguments.get("description") or ""), location=str(arguments.get("location") or ""))
            created = await self.calendar.create(event, idempotency_key=str(arguments.get("idempotency_key") or new_id()))
            return {"disposition": disposition.value, "executed": True, "event": self._event_payload(created)}
        return {"disposition": ActionDisposition.DENY.value, "executed": False, "action": name}

    def _datetime(self, value: object) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("datetime string required")
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=self.timezone)
        return result

    @staticmethod
    def _event_payload(event: CalendarEvent) -> dict[str, object]:
        return {"id": event.id, "title": event.title, "start_at": event.start_at.isoformat(), "end_at": event.end_at.isoformat(), "timezone": event.timezone, "description": event.description, "location": event.location}

    @staticmethod
    def _is_ambiguous(name: str, args: dict[str, object]) -> bool:
        required = {"reminder_create": {"message", "due_at"}, "calendar_list": {"start_at", "end_at"}, "calendar_create": {"title", "start_at", "end_at"}, "calendar_update": {"event_id"}, "calendar_delete": {"event_id"}, "calendar_invite": {"event_id", "attendee"}}.get(name, set())
        return any(not args.get(key) for key in required)
