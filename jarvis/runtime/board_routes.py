"""Routes Boards et Sessions du Control Center : relais de Core (handoff board-session, Slice 04b).

Core possède les Boards, les Sessions, la bascule et l'autorité de parole
(`docs/boards.md`). Le Control Center n'en garde rien : ces routes relaient
tel quel vers Core, et ce sont elles que l'UI (Slice 06) et le serveur MCP
`jarvis-console` (Slice 05) appellent — jamais Core directement.

| Control Center | Core |
| --- | --- |
| `GET/POST /api/boards` | `GET/POST /v1/boards` |
| `GET /api/boards/active` | `GET /v1/boards/active` |
| `POST /api/boards/switch` | `POST /v1/boards/switch` |
| `GET/PATCH /api/boards/{board_id}` | `GET/PATCH /v1/boards/{board_id}` |
| `POST /api/boards/{board_id}/archive` | `POST /v1/boards/{board_id}/archive` |
| `GET /api/sessions/current` | `GET /v1/sessions/current` |
| `GET /api/sessions` | `GET /v1/sessions` |
| `POST /api/sessions/new` | `POST /v1/sessions/new` |

**Relais transparent.** Statut et corps JSON de Core rendus tels quels, erreurs
comprises (`{"error": {"code", "message"}}`, codes `BoardErrorCode`). Core
injoignable ou non configuré : 503 `{"error": {"code": "core_unreachable" |
"core_unconfigured", "message"}}`, journalisé.

**Demande du cerveau (`origin: "brain"`).** `POST /api/boards/switch` et
`POST /api/sessions/new` acceptent `origin` (`user` par défaut, `brain` pour un
outil MCP appelé pendant un tour). Une demande du cerveau pendant qu'un tour
de l'agent est en vol serait exécutée sous ses pieds : la bascule lui retire
la parole avant même que sa réponse soit dite. Elle est donc **différée**
jusqu'à la fin de ce tour (plus `BRAIN_DEFER_GRACE_S`, le temps que Core
publie la réponse du tour) et la route répond aussitôt 202
`{"ok": true, "status": "scheduled"}`. L'issue différée est journalisée
(`board.request.deferred_applied` / `_failed` / `_expired`). Aucun tour en
vol : exécutée tout de suite, réponse normale. `origin` n'est jamais relayé.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from aiohttp import web

from jarvis.protocol.strict_json import loads_strict_json
from jarvis.runtime.journal import RuntimeJournal

#: Corps relayés : même borne que Core (`MAX_BOARD_BODY_BYTES`).
MAX_PROXY_BODY_BYTES = 128 * 1024
#: Origines d'une demande de bascule / nouvelle Session.
ORIGINS = frozenset({"user", "brain"})
#: Pause après la fin du tour avant d'exécuter une demande différée : Core
#: reçoit la réponse de l'agent puis publie sa parole ; la bascule attend qu'elle
#: soit partie, sinon la porte de parole la retiendrait.
BRAIN_DEFER_GRACE_S = 1.5
#: Échéance d'une demande différée : au-delà du plus long tour permis
#: (`/api/agent/ask`, 1 800 s), elle est abandonnée et le journal le dit.
BRAIN_DEFER_MAX_S = 1_860.0


class BoardSessionRoutes:
    """Relais `/api/boards*`, `/api/sessions*` -> Core. Voir l'en-tête du module."""

    def __init__(
        self,
        *,
        transport: Any,
        journal: RuntimeJournal,
        ask_in_flight: Callable[[], bool],
        wait_asks_idle: Callable[[], Awaitable[None]],
        grace_s: float = BRAIN_DEFER_GRACE_S,
        defer_max_s: float = BRAIN_DEFER_MAX_S,
    ) -> None:
        self._transport = transport
        self._journal = journal
        self._ask_in_flight = ask_in_flight
        self._wait_asks_idle = wait_asks_idle
        self._grace_s = grace_s
        self._defer_max_s = defer_max_s
        self._deferred: set[asyncio.Task[None]] = set()

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get("/api/boards", self.relay("/v1/boards")),
            web.post("/api/boards", self.relay("/v1/boards")),
            web.get("/api/boards/active", self.relay("/v1/boards/active")),
            web.post("/api/boards/switch", self.switch_board),
            web.get("/api/boards/{board_id}", self.relay("/v1/boards/{board_id}")),
            web.patch("/api/boards/{board_id}", self.relay("/v1/boards/{board_id}")),
            web.post("/api/boards/{board_id}/archive", self.relay("/v1/boards/{board_id}/archive")),
            web.get("/api/sessions/current", self.relay("/v1/sessions/current")),
            web.get("/api/sessions", self.relay("/v1/sessions")),
            web.post("/api/sessions/new", self.new_session),
        ]

    async def close(self) -> None:
        """Arrêt du Control Center : les demandes différées sont abandonnées, et c'est dit."""

        for task in tuple(self._deferred):
            task.cancel()
        if self._deferred:
            await asyncio.gather(*self._deferred, return_exceptions=True)

    # ------------------------------------------------------------ relais

    def relay(self, core_path: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            try:
                body = await self._read_body(request)
            except ValueError as exc:
                return _error(400, "invalid_request", str(exc))
            path = core_path.format(**{key: _segment(value) for key, value in request.match_info.items()})
            return await self._forward(request.method, path, params=dict(request.query) or None, body=body)

        return handler

    async def switch_board(self, request: web.Request) -> web.Response:
        return await self._transition(request, "/v1/boards/switch", action="switch")

    async def new_session(self, request: web.Request) -> web.Response:
        return await self._transition(request, "/v1/sessions/new", action="new_session")

    async def _transition(self, request: web.Request, core_path: str, *, action: str) -> web.Response:
        try:
            raw = await self._read_body(request)
            payload = loads_strict_json(raw, invalid_message=f"{action} body must be JSON") if raw else {}
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        if not isinstance(payload, dict):
            return _error(400, "invalid_request", f"{action} body must be a JSON object")
        origin = payload.pop("origin", "user")
        if origin not in ORIGINS:
            return _error(400, "invalid_request", f"origin must be one of {sorted(ORIGINS)}")
        body = json.dumps(payload).encode("utf-8")
        if origin == "brain" and self._ask_in_flight():
            task = asyncio.create_task(self._run_deferred(action, core_path, body, payload),
                                       name=f"jarvis-board-deferred-{action}")
            self._deferred.add(task)
            task.add_done_callback(self._deferred.discard)
            self._journal.emit("board.request.deferred",
                               "Demande du cerveau différée jusqu'à la fin de son tour",
                               data={"action": action, "board_id": payload.get("board_id")})
            return web.json_response({"ok": True, "status": "scheduled", "action": action}, status=202)
        self._journal.emit("board.request.relayed", "Demande Board/Session relayée à Core",
                           data={"action": action, "origin": origin, "board_id": payload.get("board_id")})
        return await self._forward("POST", core_path, body=body)

    async def _run_deferred(self, action: str, core_path: str, body: bytes, payload: dict[str, Any]) -> None:
        """Attendre la fin du tour (borné), puis relayer ; l'issue n'a que le journal pour témoin."""

        data = {"action": action, "board_id": payload.get("board_id")}
        try:
            await asyncio.wait_for(self._wait_asks_idle(), timeout=self._defer_max_s)
            await asyncio.sleep(self._grace_s)
        except asyncio.TimeoutError:
            self._journal.emit("board.request.deferred_expired",
                               f"Demande du cerveau abandonnée : son tour dure plus de {self._defer_max_s:.0f} s",
                               level="warning", data={**data, "code": "board_request_deferred_expired"})
            return
        except asyncio.CancelledError:
            self._journal.emit("board.request.deferred_cancelled",
                               "Demande du cerveau abandonnée : arrêt du Control Center", level="warning",
                               data={**data, "code": "board_request_deferred_cancelled"})
            raise
        try:
            status, answer = await self._transport.forward("POST", core_path, body=body)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: nobody waits for this answer, the journal is its record
            self._journal.emit("board.request.deferred_failed",
                               f"Demande différée non relayée : {type(exc).__name__}: {str(exc)[:200]}",
                               level="error", data={**data, "code": "core_unreachable",
                                                    "exception_type": type(exc).__name__})
            return
        if status >= 400:
            error = answer.get("error") if isinstance(answer, dict) and isinstance(answer.get("error"), dict) else {}
            self._journal.emit("board.request.deferred_failed",
                               f"Demande différée refusée par Core (HTTP {status}) : {str(error.get('message'))[:200]}",
                               level="error", data={**data, "status": status, "code": error.get("code") or "http_error"})
            return
        self._journal.emit("board.request.deferred_applied", "Demande différée du cerveau appliquée par Core",
                           data={**data, "status": status})

    async def _forward(self, method: str, core_path: str, *, params: dict[str, str] | None = None,
                       body: bytes | None = None) -> web.Response:
        if self._transport is None:
            return _error(503, "core_unconfigured", "the control center does not know Core")
        try:
            status, payload = await self._transport.forward(method, core_path, params=params, body=body)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced: 503 with the real cause, and journaled
            self._journal.emit("board.request.core_unreachable",
                               f"Core injoignable pour {method} {core_path} : {type(exc).__name__}: {str(exc)[:200]}",
                               level="warning", data={"code": "core_unreachable", "method": method, "path": core_path,
                                                      "exception_type": type(exc).__name__})
            return _error(503, "core_unreachable", f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}")
        if payload is None:
            return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)

    @staticmethod
    async def _read_body(request: web.Request) -> bytes | None:
        if not request.can_read_body:
            return None
        raw = await request.content.read(MAX_PROXY_BODY_BYTES + 1)
        if len(raw) > MAX_PROXY_BODY_BYTES:
            raise ValueError(f"request body exceeds {MAX_PROXY_BODY_BYTES} bytes")
        return raw or None


def _segment(value: str) -> str:
    return quote(value, safe="")


def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)
