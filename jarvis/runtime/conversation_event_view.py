"""Control Center read access to the Conversation Event log held by Core (Slice 04).

Binding contract: `docs/conversation-events.md`, section "Query and live API".
The browser never talks to Core: `/api/conversations...` routes call this view,
which reads Core through `LocalCoreClient` (loopback, session token) and maps
every failure to an explicit error the page can show.

Error mapping (`ConversationEventViewError.status` / `code`):

- no reader wired: 503 `not_configured`; view closed (Control Center stopping):
  503 `control_center_stopping`, and no session is reopened;
- Core down, token file missing, network error, no answer in time: 503 `core_unreachable`;
- Core 503 (store failing, Core stopping): 503 `conversation_events_unavailable`;
- Core 400: 400 `invalid_request` (the Control Center validates first, so this
  means both sides disagree on the contract);
- Core 401 after one token re-read: 502 `core_unauthorized`;
- any other Core refusal: 502 `core_refused`; an answer out of contract: 502
  `invalid_core_response`.

Long-polls (`events(wait_ms > 0)`) are bounded on this side too:

- at most `MAX_LONG_POLLS` wait at Core at once; a request over the cap is sent
  with `wait_ms=0` (a plain poll: same page, same cursor, answered at once);
- they use their own Core session (`POLL_CONNECTIONS`), so held long-polls can
  never starve list and detail reads (`READ_CONNECTIONS`);
- aiohttp does not cancel a handler whose browser left: the view watches
  `disconnected()` every `DISCONNECT_CHECK_S` and cancels the Core request, which
  closes that connection; Core stops its own wait the same way.

Diagnostics: one `ui.conversation_events_unavailable` warning per failure
episode (code and `exception_type`, never a value), one
`ui.conversation_events_recovered` info when a read succeeds again, one
`ui.conversation_events_invalid_response` error per exception type. A page
polling every second therefore cannot flood the journal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import aiohttp

from jarvis.domain.conversation_event_store import (
    ConversationEventPage, ConversationEventSummaryPage, StoredConversationEvent,
)
from jarvis.domain.conversation_events import ConversationVisibility
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal
from jarvis.v2_config import validate_loopback_host

#: Budget of a plain read; a long-poll adds its own `wait_ms`.
DEFAULT_READ_TIMEOUT_S = 5.0
#: Long-polls allowed to wait at Core at the same time; more are sent as plain polls.
MAX_LONG_POLLS = 8
#: Connection pools of the two Core sessions (aiohttp's default is 100 shared).
POLL_CONNECTIONS = MAX_LONG_POLLS + 2
READ_CONNECTIONS = 16
#: How often a long-poll checks that the browser is still connected.
DISCONNECT_CHECK_S = 0.25

NOT_CONFIGURED = "not_configured"
STOPPING = "control_center_stopping"
CORE_UNREACHABLE = "core_unreachable"
EVENTS_UNAVAILABLE = "conversation_events_unavailable"
INVALID_REQUEST = "invalid_request"
CORE_UNAUTHORIZED = "core_unauthorized"
CORE_REFUSED = "core_refused"
INVALID_CORE_RESPONSE = "invalid_core_response"
CLIENT_DISCONNECTED = "client_disconnected"

UNAVAILABLE_KIND = "ui.conversation_events_unavailable"
RECOVERED_KIND = "ui.conversation_events_recovered"
INVALID_RESPONSE_KIND = "ui.conversation_events_invalid_response"


class ConversationEventViewError(Exception):
    def __init__(self, status: int, code: str, message: str, *, core_status: int | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.core_status = status, code, message, core_status

    def to_payload(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "error": self.message, "core_status": self.core_status}


class ConversationEventReader(Protocol):
    """Typed Core reads (`CoreConversationEventReader` in production)."""

    async def list_event_conversations(self, **query: Any) -> ConversationEventSummaryPage: ...
    async def list_event_sessions(self, conversation_id: str, **query: Any) -> ConversationEventSummaryPage: ...
    async def list_conversation_events(self, conversation_id: str, **query: Any) -> ConversationEventPage: ...
    async def lookup_conversation_events(self, field: str, value: str, **query: Any) -> ConversationEventPage: ...
    async def get_conversation_event(self, event_id: str) -> StoredConversationEvent | None: ...
    async def close(self) -> None: ...


class CoreConversationEventReader:
    """Loopback reads on two Core sessions: `read` (lists, details) and `poll` (long-polls).

    The session token file is read when a session opens and re-read after a 401
    (Core restarted): the new token is set on both clients and the call retried
    once, **without closing** the sessions, so other in-flight polls keep running.
    After `close()` no session is reopened (`ConnectionError`).
    """

    def __init__(self, *, host: str, port: int, token_file: Path) -> None:
        self.host = validate_loopback_host(host)
        self.port = port
        self.token_file = Path(token_file)
        self._lanes: dict[str, tuple[LocalCoreClient, aiohttp.ClientSession]] = {}
        self._closed = False

    def _token(self) -> str:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConnectionError("Core session token is unavailable; is `jarvis core` running?") from exc
        if not token:
            raise ConnectionError("Core session token is empty")
        return token

    def _client(self, lane: str) -> LocalCoreClient:
        if self._closed:
            raise ConnectionError("conversation event reader is closed")
        existing = self._lanes.get(lane)
        if existing is not None:
            return existing[0]
        limit = POLL_CONNECTIONS if lane == "poll" else READ_CONNECTIONS
        token = self._token()
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10),
                                        connector=aiohttp.TCPConnector(limit=limit))
        client = LocalCoreClient(host=self.host, port=self.port, token=token, session=session)
        self._lanes[lane] = (client, session)
        return client

    async def _call(self, lane: str, name: str, *args: Any, **kwargs: Any) -> Any:
        client = self._client(lane)
        try:
            return await getattr(client, name)(*args, **kwargs)
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        token = self._token()
        for other, _ in self._lanes.values():
            other.token = token
        return await getattr(client, name)(*args, **kwargs)

    async def list_event_conversations(self, **query: Any) -> ConversationEventSummaryPage:
        return await self._call("read", "list_event_conversations", **query)

    async def list_event_sessions(self, conversation_id: str, **query: Any) -> ConversationEventSummaryPage:
        return await self._call("read", "list_event_sessions", conversation_id, **query)

    async def list_conversation_events(self, conversation_id: str, **query: Any) -> ConversationEventPage:
        lane = "poll" if query.get("wait_ms") else "read"
        return await self._call(lane, "list_conversation_events", conversation_id, **query)

    async def lookup_conversation_events(self, field: str, value: str, **query: Any) -> ConversationEventPage:
        return await self._call("read", "lookup_conversation_events", field, value, **query)

    async def get_conversation_event(self, event_id: str) -> StoredConversationEvent | None:
        return await self._call("read", "get_conversation_event", event_id)

    async def close(self) -> None:
        self._closed = True
        lanes, self._lanes = self._lanes, {}
        for _, session in lanes.values():
            await session.close()


class ConversationEventView:
    def __init__(self, reader: ConversationEventReader | None, *, journal: RuntimeJournal | None = None,
                 timeout_s: float = DEFAULT_READ_TIMEOUT_S, max_long_polls: int = MAX_LONG_POLLS) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.reader = reader
        self.journal = journal
        self.timeout_s = timeout_s
        self.max_long_polls = max_long_polls
        #: Long-polls currently waiting at Core.
        self.long_polls = 0
        #: Long-polls sent as plain polls because the cap was reached.
        self.long_polls_downgraded = 0
        self._closed = False
        self._failing: str | None = None
        self._reported_invalid: set[str] = set()

    # --------------------------------------------------------------- reads

    async def conversations(self, *, before_sequence: int | None, limit: int) -> ConversationEventSummaryPage:
        return await self._read("conversations", lambda r: r.list_event_conversations(
            before_sequence=before_sequence, limit=limit))

    async def sessions(self, conversation_id: str, *, after_sequence: int, limit: int) -> ConversationEventSummaryPage:
        return await self._read("sessions", lambda r: r.list_event_sessions(
            conversation_id, after_sequence=after_sequence, limit=limit))

    async def events(self, conversation_id: str, *, after_sequence: int, limit: int,
                     visibility: ConversationVisibility | None, wait_ms: int,
                     disconnected: Callable[[], bool] | None = None) -> ConversationEventPage:
        def call(wait: int):
            return lambda r: r.list_conversation_events(conversation_id, after_sequence=after_sequence, limit=limit,
                                                        visibility=visibility, wait_ms=wait)

        if wait_ms <= 0:
            return await self._read("events", call(0))
        if self.long_polls >= self.max_long_polls:
            self.long_polls_downgraded += 1
            return await self._read("events", call(0))
        self.long_polls += 1
        try:
            return await self._read("events", call(wait_ms), extra_s=wait_ms / 1000, disconnected=disconnected)
        finally:
            self.long_polls -= 1

    async def lookup(self, field: str, value: str, *, conversation_id: str | None, after_sequence: int, limit: int,
                     visibility: ConversationVisibility | None) -> ConversationEventPage:
        return await self._read("lookup", lambda r: r.lookup_conversation_events(
            field, value, conversation_id=conversation_id, after_sequence=after_sequence, limit=limit,
            visibility=visibility))

    async def event(self, event_id: str) -> StoredConversationEvent | None:
        return await self._read("event", lambda r: r.get_conversation_event(event_id))

    async def aclose(self) -> None:
        self._closed = True
        if self.reader is None:
            return
        try:
            await self.reader.close()
        except Exception:  # noqa: BLE001 - argued: the Control Center stop must never hang on a read session
            pass

    # ------------------------------------------------------------ plumbing

    async def _read(self, operation: str, call, *, extra_s: float = 0.0,
                    disconnected: Callable[[], bool] | None = None) -> Any:
        if self.reader is None:
            raise ConversationEventViewError(503, NOT_CONFIGURED, "Lecture des Conversation Events Core non configurée.")
        if self._closed:
            raise ConversationEventViewError(503, STOPPING, "Le Control Center s'arrête.")
        timeout_s = self.timeout_s + extra_s
        try:
            if disconnected is None:
                result = await asyncio.wait_for(call(self.reader), timeout=timeout_s)
            else:
                result = await self._watched(call(self.reader), timeout_s, disconnected)
        except asyncio.CancelledError:
            raise
        except ConversationEventViewError:
            raise
        except CoreProtocolError as exc:
            raise self._refused(operation, exc) from exc
        except ValueError as exc:
            raise self._invalid(operation, exc) from exc
        except TimeoutError as exc:
            raise self._unreachable(operation, exc, f"Core n'a pas répondu en {timeout_s:.1f} s.") from exc
        except Exception as exc:  # noqa: BLE001 - Core stopped, token file missing, connection refused
            if self._closed:
                raise ConversationEventViewError(503, STOPPING, "Le Control Center s'arrête.") from exc
            raise self._unreachable(operation, exc, f"Core injoignable : {type(exc).__name__}.") from exc
        if self._failing is not None:
            self._emit(RECOVERED_KIND, "Conversation Events Core lisibles à nouveau.", "info",
                       {"operation": operation, "previous_code": self._failing})
            self._failing = None
        return result

    @staticmethod
    async def _watched(coro, timeout_s: float, disconnected: Callable[[], bool]) -> Any:
        """Run a long Core call; cancel it (closing its Core connection) when the browser has left."""
        task = asyncio.ensure_future(coro)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=min(DISCONNECT_CHECK_S, max(0.0, deadline - loop.time())))
                if done:
                    return task.result()
                if disconnected():
                    raise ConversationEventViewError(499, CLIENT_DISCONNECTED, "Le navigateur a quitté la requête.")
                if loop.time() >= deadline:
                    raise TimeoutError
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def _refused(self, operation: str, exc: CoreProtocolError) -> ConversationEventViewError:
        if exc.status == 400:
            return ConversationEventViewError(400, INVALID_REQUEST, str(exc), core_status=400)
        if exc.status == 503:
            error = ConversationEventViewError(503, EVENTS_UNAVAILABLE,
                                               "Core ne peut pas lire les Conversation Events pour l'instant.",
                                               core_status=503)
        elif exc.status == 401:
            error = ConversationEventViewError(502, CORE_UNAUTHORIZED,
                                               "Core refuse le jeton de session, même relu.", core_status=401)
        else:
            error = ConversationEventViewError(502, CORE_REFUSED, f"Core a refusé la lecture ({exc.status} {exc.code}).",
                                               core_status=exc.status)
        self._episode(operation, error, type(exc).__name__)
        return error

    def _unreachable(self, operation: str, exc: BaseException, message: str) -> ConversationEventViewError:
        error = ConversationEventViewError(503, CORE_UNREACHABLE, message)
        self._episode(operation, error, type(exc).__name__)
        return error

    def _invalid(self, operation: str, exc: ValueError) -> ConversationEventViewError:
        name = type(exc).__name__
        if name not in self._reported_invalid:
            self._reported_invalid.add(name)
            # The decode message names fields and rules, never values.
            self._emit(INVALID_RESPONSE_KIND, "Réponse Conversation Events de Core hors contrat.", "error",
                       {"code": INVALID_CORE_RESPONSE, "operation": operation, "exception_type": name,
                        "detail": str(exc)[:300]})
        return ConversationEventViewError(502, INVALID_CORE_RESPONSE, "Réponse de Core illisible (hors contrat).")

    def _episode(self, operation: str, error: ConversationEventViewError, exception_type: str) -> None:
        if self._failing is not None:
            return
        self._failing = error.code
        self._emit(UNAVAILABLE_KIND, "Conversation Events Core illisibles : la vue affiche l'erreur.", "warning",
                   {"code": error.code, "operation": operation, "exception_type": exception_type,
                    "core_status": error.core_status})

    def _emit(self, kind: str, message: str, level: str, data: dict[str, Any]) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001 - argued: a journal write failure must not turn a visible error into a crash
            pass
