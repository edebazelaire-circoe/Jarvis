from __future__ import annotations

from jarvis.domain.calendar import CalendarEvent, CalendarQuery
from jarvis.ports.calendar import CalendarBackend


class CalendarAmbiguityError(ValueError):
    def __init__(self, candidates: tuple[CalendarEvent, ...]) -> None:
        super().__init__("calendar request is ambiguous")
        self.candidates = candidates


class CalendarService:
    def __init__(self, backend: CalendarBackend) -> None:
        self.backend = backend

    async def find(self, query: CalendarQuery):
        return tuple(await self.backend.list_events(query))

    async def resolve_unique(self, query: CalendarQuery) -> CalendarEvent:
        matches = tuple(await self.backend.list_events(query))
        if len(matches) != 1:
            raise CalendarAmbiguityError(matches)
        return matches[0]

    async def create(self, event: CalendarEvent, *, idempotency_key: str):
        return await self.backend.create_event(event, idempotency_key=idempotency_key)

    async def update(self, event: CalendarEvent, *, idempotency_key: str):
        return await self.backend.update_event(event, idempotency_key=idempotency_key)

    async def delete(self, event_id: str, *, idempotency_key: str) -> None:
        await self.backend.delete_event(event_id, idempotency_key=idempotency_key)
