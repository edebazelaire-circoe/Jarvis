from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.domain.calendar import CalendarAttendee, CalendarEvent, CalendarQuery


class GoogleCalendarBackend:
    """Google Calendar adapter; provider objects stay outside Core contracts."""

    SCOPES = ("https://www.googleapis.com/auth/calendar",)

    def __init__(self, service: Any, *, calendar_id: str = "primary") -> None:
        self.service = service
        self.calendar_id = calendar_id
        self._idempotency: dict[str, object] = {}

    @classmethod
    def from_oauth_files(cls, client_secret_file: Path, token_file: Path, *, calendar_id: str = "primary") -> "GoogleCalendarBackend":
        try:
            from google.auth.transport.requests import Request  # type: ignore
            from google.oauth2.credentials import Credentials  # type: ignore
            from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Google Calendar support requires the calendar-google optional dependencies") from exc
        creds = Credentials.from_authorized_user_file(str(token_file), cls.SCOPES) if token_file.exists() else None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), cls.SCOPES)
                creds = flow.run_local_server(port=0)
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")
        return cls(build("calendar", "v3", credentials=creds, cache_discovery=False), calendar_id=calendar_id)

    async def list_events(self, query: CalendarQuery):
        import asyncio
        data = await asyncio.to_thread(lambda: self.service.events().list(calendarId=self.calendar_id, timeMin=query.start_at.isoformat(), timeMax=query.end_at.isoformat(), singleEvents=True, orderBy="startTime", q=query.text).execute())
        return tuple(self._from_google(item) for item in data.get("items", []))

    async def get_event(self, event_id: str):
        import asyncio
        try:
            item = await asyncio.to_thread(lambda: self.service.events().get(calendarId=self.calendar_id, eventId=event_id).execute())
        except Exception as exc:
            if getattr(getattr(exc, "resp", None), "status", None) == 404:
                return None
            raise
        return self._from_google(item)

    async def create_event(self, event: CalendarEvent, *, idempotency_key: str):
        import asyncio
        cached = self._idempotency.get(idempotency_key)
        if isinstance(cached, CalendarEvent):
            return cached
        item = await asyncio.to_thread(lambda: self.service.events().insert(calendarId=self.calendar_id, body=self._to_google(event), sendUpdates="all" if event.attendees else "none").execute())
        result = self._from_google(item)
        self._idempotency[idempotency_key] = result
        return result

    async def update_event(self, event: CalendarEvent, *, idempotency_key: str):
        import asyncio
        cached = self._idempotency.get(idempotency_key)
        if isinstance(cached, CalendarEvent):
            return cached
        item = await asyncio.to_thread(lambda: self.service.events().update(calendarId=self.calendar_id, eventId=event.id, body=self._to_google(event), sendUpdates="all" if event.attendees else "none").execute())
        result = self._from_google(item)
        self._idempotency[idempotency_key] = result
        return result

    async def delete_event(self, event_id: str, *, idempotency_key: str) -> None:
        import asyncio
        if idempotency_key in self._idempotency:
            return
        await asyncio.to_thread(lambda: self.service.events().delete(calendarId=self.calendar_id, eventId=event_id, sendUpdates="all").execute())
        self._idempotency[idempotency_key] = True

    @staticmethod
    def _date(value: dict[str, str]) -> datetime:
        raw = value.get("dateTime")
        if not raw:
            raise ValueError("all-day events are not supported by the v0.2 timed-event adapter")
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    @classmethod
    def _from_google(cls, item: dict[str, Any]) -> CalendarEvent:
        return CalendarEvent(id=str(item["id"]), title=str(item.get("summary") or "(sans titre)"), start_at=cls._date(item["start"]), end_at=cls._date(item["end"]), timezone=str(item.get("start", {}).get("timeZone") or item.get("end", {}).get("timeZone") or "Europe/Paris"), attendees=tuple(CalendarAttendee(email=str(a.get("email") or ""), display_name=a.get("displayName"), response_status=a.get("responseStatus")) for a in item.get("attendees", []) if a.get("email")), description=str(item.get("description") or ""), location=str(item.get("location") or ""), metadata={"html_link": item.get("htmlLink")})

    @staticmethod
    def _to_google(event: CalendarEvent) -> dict[str, Any]:
        return {"summary": event.title, "description": event.description, "location": event.location, "start": {"dateTime": event.start_at.isoformat(), "timeZone": event.timezone}, "end": {"dateTime": event.end_at.isoformat(), "timeZone": event.timezone}, "attendees": [{"email": a.email} for a in event.attendees]}
