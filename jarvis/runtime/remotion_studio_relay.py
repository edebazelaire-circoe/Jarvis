"""Relais du Control Center vers Core pour la carte « Remotion » et son Studio optionnel (jarvis-remotion-presentation-integration, Slice 11).

Core possède la capacité locale et le Studio (`docs/remotion-studio.md`) ; le Control Center n'en garde rien. Ces routes relaient
telles quelles vers Core (statut et JSON, erreurs comprises) ; c'est `control_center_remotion_studio.js` qui les appelle.

| Control Center | Core | Délai |
| --- | --- | --- |
| `GET /api/local-capabilities/remotion` | `GET /v1/local-capabilities/remotion` | 10 s |
| `GET /api/local-capabilities/remotion/studio` | `GET /v1/local-capabilities/remotion/studio` | 10 s |
| `POST /api/local-capabilities/remotion/studio/open` | `POST .../studio/open` | 150 s (démarrage ≤ 120 s) |
| `POST /api/local-capabilities/remotion/studio/restart` | `POST .../studio/restart` | 150 s |
| `POST /api/local-capabilities/remotion/studio/sync\\|close` | `POST .../studio/sync\\|close` | 40 s |
| `POST /api/local-capabilities/remotion/install` ou `repair` | `POST /v1/local-capabilities/remotion/install` ou `repair` | 40 s (Slice 20) |

Seules ces huit adresses existent : aucun arrêt ni désinstallation de la capacité, aucun chemin libre n'est relayé d'ici. Depuis la
Slice 20, `install` et `repair` le sont (corps vide imposé, jamais celui de la page) : c'est le geste « réparer » de la carte
d'erreur du moteur, précédé d'une confirmation dans la page (`docs/remotion-runtime.md` §7). Toutes les méthodes sont gardées (Host et origine
de boucle locale, `READ_GUARDED_ROUTES`) : ces routes lancent un processus.

Core injoignable ou non configuré : 503 `core_unreachable` / `core_unconfigured` ; délai dépassé : 504 `core_timeout` (l'issue est
inconnue, l'écran relit l'état). Journal : `remotion_studio.relayed` pour chaque écriture (jamais un corps).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.runtime.journal import RuntimeJournal

CAPABILITY_ROUTE = "/api/local-capabilities/remotion"
STUDIO_ROUTE = CAPABILITY_ROUTE + "/studio"
GUARDED_PREFIXES = ("/api/local-capabilities",)
CORE_CAPABILITY = "/v1/local-capabilities/remotion"
CORE_STUDIO = CORE_CAPABILITY + "/studio"
READ_TIMEOUT_S = 10.0
SHORT_TIMEOUT_S = 40.0
START_TIMEOUT_S = 150.0
MAX_BODY_BYTES = 2048
#: Slice 20 : les deux seules operations de la capacite relayees (le geste « installer / reparer » apres une panne visible).
_CAPABILITY_WRITES = ("install", "repair")
_WRITES = {"open": START_TIMEOUT_S, "restart": START_TIMEOUT_S, "sync": SHORT_TIMEOUT_S, "close": SHORT_TIMEOUT_S}


def _envelope(status: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status, headers=headers)


class RemotionStudioRelayRoutes:
    def __init__(self, *, transport: Callable[[], Any], journal: RuntimeJournal) -> None:
        self._transport = transport
        self._journal = journal
        self._core_down = False

    def routes(self) -> list[web.RouteDef]:
        routes = [web.get(CAPABILITY_ROUTE, self._read(CORE_CAPABILITY)), web.get(STUDIO_ROUTE, self._read(CORE_STUDIO))]
        routes += [web.post(f"{STUDIO_ROUTE}/{action}", self._write(action, timeout)) for action, timeout in _WRITES.items()]
        routes += [web.post(f"{CAPABILITY_ROUTE}/{op}", self._capability_write(op)) for op in _CAPABILITY_WRITES]
        return routes

    @staticmethod
    def owns(path: str) -> bool:
        return path == CAPABILITY_ROUTE or path.startswith(CAPABILITY_ROUTE + "/")

    @staticmethod
    def refusal(exc: web.HTTPException) -> web.Response | None:
        if isinstance(exc, web.HTTPMethodNotAllowed):
            return _envelope(405, "method_not_allowed", "this method is not allowed on this Remotion route",
                             headers={"Allow": ", ".join(sorted(exc.allowed_methods))})
        if isinstance(exc, web.HTTPNotFound):
            return _envelope(404, "not_found", "unknown Remotion route")
        return None

    def _read(self, core_path: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            if request.query:
                return _envelope(400, "remotion_studio_invalid", "unexpected query parameters")
            status, payload = await self._forward("GET", core_path, action="read", timeout_s=READ_TIMEOUT_S)
            return self._answer(status, payload)
        return handler

    def _write(self, action: str, timeout_s: float) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            if request.query:
                return _envelope(400, "remotion_studio_invalid", "unexpected query parameters")
            body = await request.read() if request.can_read_body else b""
            if len(body) > MAX_BODY_BYTES:
                return _envelope(400, "remotion_studio_invalid", "the request body is too large")
            status, payload = await self._forward("POST", f"{CORE_STUDIO}/{action}", action=action, body=body or None, timeout_s=timeout_s)
            error = payload.get("error") if isinstance(payload, dict) else None
            studio = payload.get("studio") if isinstance(payload, dict) else None
            self._journal.emit("remotion_studio.relayed", f"Studio Remotion : {action} relayé à Core (HTTP {status})",
                               level="info" if status < 400 else "warning",
                               data={"action": action, "status": status, "code": error.get("code") if isinstance(error, dict) else None,
                                     "studio_status": studio.get("status") if isinstance(studio, dict) else None})
            return self._answer(status, payload)
        return handler

    def _capability_write(self, operation: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            if request.query:
                return _envelope(400, "remotion_studio_invalid", "unexpected query parameters")
            # Le corps de la page n'est jamais transmis : l'operation n'a pas de parametre (`docs/local-capabilities.md` §7).
            status, payload = await self._forward("POST", f"{CORE_CAPABILITY}/{operation}", action=f"capability_{operation}",
                                                  body=b"{}", timeout_s=SHORT_TIMEOUT_S)
            error = payload.get("error") if isinstance(payload, dict) else None
            self._journal.emit("remotion_studio.relayed", f"Capacite Remotion : {operation} relayé à Core (HTTP {status})",
                               level="info" if status < 400 else "warning",
                               data={"action": f"capability_{operation}", "status": status,
                                     "code": error.get("code") if isinstance(error, dict) else None})
            return self._answer(status, payload)
        return handler

    @staticmethod
    def _answer(status: int, payload: Any) -> web.Response:
        if payload is None:
            return _envelope(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)

    async def _forward(self, method: str, core_path: str, *, action: str, body: bytes | None = None, timeout_s: float) -> tuple[int, Any]:
        transport = self._transport()
        if transport is None:
            return 503, {"error": {"code": "core_unconfigured", "message": "the control center does not know Core"}}
        try:
            status, payload = await transport.forward(method, core_path, body=body, timeout_s=timeout_s)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            self._journal.emit("remotion_studio.core_timeout", f"Core n'a pas répondu à temps pour {action} : issue inconnue",
                               level="warning", data={"code": "core_timeout", "action": action, "exception_type": type(exc).__name__})
            unknown = "" if method == "GET" else "; the outcome is unknown, read the Studio status again"
            return 504, {"error": {"code": "core_timeout", "message": f"Core did not answer in time{unknown}"}}
        except Exception as exc:  # noqa: BLE001 - surfaced as 503 with the real cause, journaled once per outage
            if not self._core_down:
                self._core_down = True
                self._journal.emit("remotion_studio.core_unreachable", f"Studio Remotion : Core injoignable ({type(exc).__name__})",
                                   level="warning", data={"code": "core_unreachable", "action": action, "exception_type": type(exc).__name__})
            return 503, {"error": {"code": "core_unreachable", "message": f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}"}}
        if self._core_down:
            self._core_down = False
            self._journal.emit("remotion_studio.core_restored", "Studio Remotion : Core répond de nouveau", data={"action": action})
        return status, payload
