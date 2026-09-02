from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jarvis.adapters.fake_calendar import InMemoryCalendarBackend
from jarvis.core.calendar_service import CalendarAmbiguityError, CalendarService
from jarvis.domain.calendar import CalendarEvent, CalendarQuery


@pytest.mark.asyncio
async def test_fake_calendar_idempotency_and_ambiguity():
    start = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    first = CalendarEvent(title="Projet", start_at=start, end_at=start + timedelta(hours=1))
    second = CalendarEvent(title="Projet bis", start_at=start + timedelta(hours=2), end_at=start + timedelta(hours=3))
    backend = InMemoryCalendarBackend((first, second))
    service = CalendarService(backend)
    query = CalendarQuery(start_at=start - timedelta(hours=1), end_at=start + timedelta(hours=4), text="Projet")
    with pytest.raises(CalendarAmbiguityError):
        await service.resolve_unique(query)
    created = CalendarEvent(title="Nouveau", start_at=start + timedelta(days=1), end_at=start + timedelta(days=1, hours=1))
    a = await service.create(created, idempotency_key="same")
    b = await service.create(CalendarEvent(title="Autre", start_at=start + timedelta(days=2), end_at=start + timedelta(days=2, hours=1)), idempotency_key="same")
    assert a.id == b.id
