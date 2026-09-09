from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import time
from typing import Callable
import unicodedata
from zoneinfo import ZoneInfo

from jarvis.core.calendar_service import CalendarService
from jarvis.core.drive_service import DriveService
from jarvis.core.v2_services import SchedulerService
from jarvis.domain.calendar import CalendarAttendee, CalendarEvent, CalendarQuery
from jarvis.domain.drive import DriveFile, DriveQuery
from jarvis.domain.v2 import MissedRunPolicy, ScheduledItem, new_id
from jarvis.security.v2_policy import ActionDisposition, V2ActionBroker


class CoreToolRouter:
    """Authoritative tool boundary for Voice/Realtime clients."""

    def __init__(self, *, scheduler: SchedulerService, calendar: CalendarService, drive: DriveService | None = None, timezone: str = "Europe/Paris", confirmation_timeout_s: float = 45.0, clock: Callable[[], float] = time.monotonic) -> None:
        if confirmation_timeout_s <= 0:
            raise ValueError("confirmation_timeout_s must be positive")
        self.scheduler = scheduler
        self.calendar = calendar
        self.drive = drive or DriveService()
        self.timezone = ZoneInfo(timezone)
        self.policy = V2ActionBroker()
        self.confirmation_timeout_s = confirmation_timeout_s
        self.clock = clock
        self._pending: dict[str, tuple[str, dict[str, object], str | None, float]] = {}

    async def call(self, name: str, arguments: dict[str, object], *, conversation_id: str | None) -> dict[str, object]:
        ambiguous = not isinstance(arguments, dict) or self._is_ambiguous(name, arguments)
        disposition = self.policy.evaluate(name, explicit_request=True, ambiguous=ambiguous)
        if disposition is ActionDisposition.CLARIFY:
            return {"disposition": disposition.value, "executed": False, "action": name}
        if disposition is ActionDisposition.CONFIRM:
            action_id = new_id()
            self._pending[action_id] = (name, dict(arguments), conversation_id, self.clock() + self.confirmation_timeout_s)
            return {"disposition": disposition.value, "executed": False, "action": name, "action_id": action_id, "message": "Confirmation requise. Répondez exactement oui ou non."}
        if disposition is not ActionDisposition.EXECUTE:
            return {"disposition": disposition.value, "executed": False, "action": name}
        return await self._execute(name, arguments, conversation_id=conversation_id)

    async def resolve_confirmation(self, action_id: str, text: str) -> dict[str, object]:
        pending = self._pending.get(action_id)
        if pending is None:
            return {"disposition": "deny", "executed": False, "action_id": action_id, "message": "Confirmation inconnue ou expirée."}
        name, arguments, conversation_id, expires_at = pending
        if self.clock() >= expires_at:
            self._pending.pop(action_id, None)
            return {"disposition": "deny", "executed": False, "action_id": action_id, "message": "Confirmation expirée."}
        normalized = self._normalize_confirmation(text)
        if normalized in {"non", "no"}:
            self._pending.pop(action_id, None)
            return {"disposition": "deny", "executed": False, "action_id": action_id, "message": "Action annulée."}
        if normalized not in {"oui", "yes"}:
            return {"disposition": "confirm", "executed": False, "action_id": action_id, "message": "Confirmation ambiguë. Répondez exactement oui ou non."}
        self._pending.pop(action_id, None)
        result = await self._execute(name, arguments, conversation_id=conversation_id)
        return {**result, "action_id": action_id}

    async def _execute(self, name: str, arguments: dict[str, object], *, conversation_id: str | None) -> dict[str, object]:
        result = await self._dispatch(name, arguments, conversation_id=conversation_id)
        if name.startswith("calendar_") and result.get("executed"):
            # Sans cela un succès sur l'agenda de repli en mémoire est
            # indiscernable d'un rendez-vous réellement enregistré : ni la trace
            # ni le modèle ne peuvent dire à l'utilisateur où l'événement a
            # atterri.
            result = {**result, "calendar": self.calendar.storage}
        if name.startswith("drive_") and result.get("executed"):
            result = {**result, "drive": self.drive.storage}
        return result

    async def _dispatch(self, name: str, arguments: dict[str, object], *, conversation_id: str | None) -> dict[str, object]:
        if name == "reminder_create":
            due_at = self._datetime(arguments["due_at"])
            item = ScheduledItem(kind="reminder", payload={"message": str(arguments["message"])}, next_fire_at=due_at, missed_run_policy=MissedRunPolicy(str(arguments.get("missed_run_policy") or MissedRunPolicy.NOTIFY_LATE.value)), max_lateness_seconds=int(arguments["max_lateness_seconds"]) if arguments.get("max_lateness_seconds") is not None else None, requested_by_conversation_id=conversation_id)
            await self.scheduler.create(item)
            return {"disposition": "execute", "executed": True, "scheduled_item_id": item.id, "next_fire_at": item.next_fire_at.isoformat()}
        if name == "calendar_list":
            query = CalendarQuery(start_at=self._datetime(arguments["start_at"]), end_at=self._datetime(arguments["end_at"]), text=str(arguments["text"]) if arguments.get("text") else None)
            events = await self.calendar.find(query)
            return {"disposition": "execute", "executed": True, "events": [self._event_payload(e) for e in events]}
        if name == "calendar_get":
            event_id = str(arguments["event_id"])
            event = await self.calendar.backend.get_event(event_id)
            if event is None:
                raise KeyError(event_id)
            return {"disposition": "execute", "executed": True, "event": self._event_payload(event)}
        if name == "calendar_create":
            event = CalendarEvent(title=str(arguments["title"]), start_at=self._datetime(arguments["start_at"]), end_at=self._datetime(arguments["end_at"]), timezone=str(arguments.get("timezone") or self.timezone.key), description=str(arguments.get("description") or ""), location=str(arguments.get("location") or ""))
            created = await self.calendar.create(event, idempotency_key=str(arguments.get("idempotency_key") or new_id()))
            return {"disposition": "execute", "executed": True, "event": self._event_payload(created)}
        if name == "calendar_update":
            event_id = str(arguments["event_id"])
            current = await self.calendar.backend.get_event(event_id)
            if current is None:
                raise KeyError(event_id)
            updated = replace(current, title=str(arguments.get("title") or current.title), start_at=self._datetime(arguments["start_at"]) if arguments.get("start_at") else current.start_at, end_at=self._datetime(arguments["end_at"]) if arguments.get("end_at") else current.end_at, description=str(arguments.get("description") if arguments.get("description") is not None else current.description), location=str(arguments.get("location") if arguments.get("location") is not None else current.location))
            result = await self.calendar.update(updated, idempotency_key=str(arguments.get("idempotency_key") or new_id()))
            return {"disposition": "execute", "executed": True, "event": self._event_payload(result)}
        if name == "calendar_delete":
            event_id = str(arguments["event_id"])
            await self.calendar.delete(event_id, idempotency_key=str(arguments.get("idempotency_key") or new_id()))
            return {"disposition": "execute", "executed": True, "deleted_event_id": event_id}
        if name == "calendar_invite":
            event_id = str(arguments["event_id"])
            current = await self.calendar.backend.get_event(event_id)
            if current is None:
                raise KeyError(event_id)
            email = str(arguments["attendee"]).strip()
            if "@" not in email:
                raise ValueError("attendee must be an email address")
            if any(a.email.casefold() == email.casefold() for a in current.attendees):
                return {"disposition": "execute", "executed": True, "event": self._event_payload(current)}
            updated = replace(current, attendees=current.attendees + (CalendarAttendee(email=email),))
            result = await self.calendar.update(updated, idempotency_key=str(arguments.get("idempotency_key") or new_id()))
            return {"disposition": "execute", "executed": True, "event": self._event_payload(result)}
        if name.startswith("drive_"):
            return await self._dispatch_drive(name, arguments)
        return {"disposition": ActionDisposition.DENY.value, "executed": False, "action": name}

    async def _dispatch_drive(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if not self.drive.available:
            return {"disposition": "deny", "executed": False, "action": name, "message": "Aucun Google Drive n'est configuré."}
        key = str(arguments.get("idempotency_key") or new_id())
        if name == "drive_search":
            query = DriveQuery(text=str(arguments["text"]).strip() if arguments.get("text") else None, parent_id=str(arguments["parent_id"]) if arguments.get("parent_id") else None, mime_type=str(arguments["mime_type"]) if arguments.get("mime_type") else None, limit=int(arguments.get("limit") or 25))
            files = await self.drive.find(query)
            return {"disposition": "execute", "executed": True, "files": [self._file_payload(f) for f in files]}
        if name == "drive_get":
            file_id = str(arguments["file_id"])
            found = await self.drive.get(file_id)
            if found is None:
                raise KeyError(file_id)
            return {"disposition": "execute", "executed": True, "file": self._file_payload(found)}
        if name == "drive_read":
            content = await self.drive.read(str(arguments["file_id"]), max_chars=int(arguments.get("max_chars") or 20000))
            return {"disposition": "execute", "executed": True, "file": self._file_payload(content.file), "text": content.text, "truncated": content.truncated, "exported_as": content.exported_as}
        if name == "drive_create":
            created = await self.drive.create(str(arguments["name"]), content=str(arguments.get("content") or ""), mime_type=str(arguments.get("mime_type") or "text/plain"), parent_id=str(arguments["parent_id"]) if arguments.get("parent_id") else None, idempotency_key=key)
            return {"disposition": "execute", "executed": True, "file": self._file_payload(created)}
        if name == "drive_update":
            updated = await self.drive.update(str(arguments["file_id"]), content=str(arguments["content"]), idempotency_key=key)
            return {"disposition": "execute", "executed": True, "file": self._file_payload(updated)}
        if name == "drive_delete":
            file_id = str(arguments["file_id"])
            await self.drive.delete(file_id, idempotency_key=key)
            # « trashed » et non « deleted » : le fichier reste récupérable, et
            # l'utilisateur doit s'entendre dire exactement cela.
            return {"disposition": "execute", "executed": True, "trashed_file_id": file_id}
        if name == "drive_share":
            email = str(arguments["email"]).strip()
            if "@" not in email:
                raise ValueError("email address required")
            shared = await self.drive.share(str(arguments["file_id"]), email=email, role=str(arguments.get("role") or "reader"), idempotency_key=key)
            return {"disposition": "execute", "executed": True, "file": self._file_payload(shared), "shared_with": email}
        return {"disposition": ActionDisposition.DENY.value, "executed": False, "action": name}

    def _datetime(self, value: object) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("datetime string required")
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=self.timezone)
        return result

    @staticmethod
    def _file_payload(file: DriveFile) -> dict[str, object]:
        return {"id": file.id, "name": file.name, "mime_type": file.mime_type, "size": file.size, "modified_at": file.modified_at.isoformat() if file.modified_at else None, "web_link": file.web_link, "is_folder": file.is_folder, "parents": list(file.parents)}

    @staticmethod
    def _event_payload(event: CalendarEvent) -> dict[str, object]:
        return {"id": event.id, "title": event.title, "start_at": event.start_at.isoformat(), "end_at": event.end_at.isoformat(), "timezone": event.timezone, "description": event.description, "location": event.location, "attendees": [a.email for a in event.attendees]}

    @staticmethod
    def _normalize_confirmation(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.strip().casefold())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return " ".join("".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in normalized).split())

    @staticmethod
    def _is_ambiguous(name: str, args: dict[str, object]) -> bool:
        required = {"reminder_create": {"message", "due_at"}, "calendar_list": {"start_at", "end_at"}, "calendar_get": {"event_id"}, "calendar_create": {"title", "start_at", "end_at"}, "calendar_update": {"event_id"}, "calendar_delete": {"event_id"}, "calendar_invite": {"event_id", "attendee"}, "drive_get": {"file_id"}, "drive_read": {"file_id"}, "drive_create": {"name"}, "drive_update": {"file_id", "content"}, "drive_delete": {"file_id"}, "drive_share": {"file_id", "email"}}.get(name, set())
        return any(not args.get(key) for key in required)
