from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jarvis.domain.v2 import new_id


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("calendar datetimes must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CalendarAttendee:
    email: str
    display_name: str | None = None
    response_status: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    id: str = field(default_factory=new_id)
    title: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str = "Europe/Paris"
    attendees: tuple[CalendarAttendee, ...] = ()
    description: str = ""
    location: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("calendar title is required")
        if self.start_at is None or self.end_at is None:
            raise ValueError("calendar start/end are required")
        _aware(self.start_at)
        _aware(self.end_at)
        if self.end_at <= self.start_at:
            raise ValueError("calendar end must be after start")


@dataclass(frozen=True, slots=True)
class CalendarQuery:
    start_at: datetime
    end_at: datetime
    text: str | None = None

    def __post_init__(self) -> None:
        _aware(self.start_at)
        _aware(self.end_at)
        if self.end_at <= self.start_at:
            raise ValueError("query end must be after start")
