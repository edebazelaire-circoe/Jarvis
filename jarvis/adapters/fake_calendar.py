from __future__ import annotations

from jarvis.domain.calendar import CalendarEvent, CalendarQuery


class InMemoryCalendarBackend:
    def __init__(self, events=()) -> None:
        self._events = {event.id: event for event in events}
        self._results: dict[str, object] = {}

    async def list_events(self, query: CalendarQuery):
        text = (query.text or "").casefold()
        return tuple(sorted((e for e in self._events.values() if e.start_at < query.end_at and e.end_at > query.start_at and (not text or text in e.title.casefold())), key=lambda e: (e.start_at, e.id)))

    async def get_event(self, event_id: str):
        return self._events.get(event_id)

    async def create_event(self, event: CalendarEvent, *, idempotency_key: str):
        cached = self._results.get(idempotency_key)
        if isinstance(cached, CalendarEvent):
            return cached
        self._events[event.id] = event
        self._results[idempotency_key] = event
        return event

    async def update_event(self, event: CalendarEvent, *, idempotency_key: str):
        cached = self._results.get(idempotency_key)
        if isinstance(cached, CalendarEvent):
            return cached
        if event.id not in self._events:
            raise KeyError(event.id)
        self._events[event.id] = event
        self._results[idempotency_key] = event
        return event

    async def delete_event(self, event_id: str, *, idempotency_key: str) -> None:
        if idempotency_key in self._results:
            return
        if event_id not in self._events:
            raise KeyError(event_id)
        del self._events[event_id]
        self._results[idempotency_key] = True
