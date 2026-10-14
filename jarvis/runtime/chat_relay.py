"""Routes `/api/chat*` du Control Center : relais de Core (handoff jarvis-unified-chat-and-board-drop, `docs/chat.md`).

Core possède le Chat : la conversation (événements canoniques), le canal
vocal (`VoiceChannelService`) et l'admission des tours texte. Le Control
Center n'en garde **rien** et ne décide rien : il relaie, sur la mécanique de
`capture_relay.py` (transport relu à chaque requête, 401 rejoué une fois par
le transport, panne de Core 503 / délai 504).

| Control Center | Core | Slice |
| --- | --- | --- |
| `GET /api/chat/state` | `GET /v1/chat/state` | 04 |
| `POST /api/chat/voice/disable` | `POST /v1/voice/channel/disable` | 04 |

Jamais `POST /v1/voice/channel/report` : seul le processus Voice rapporte son
état, et rien de ce qui vient du navigateur n'est cru (le corps est relayé tel
quel, Core le valide strictement).

**Enveloppe.** Succès : statut et JSON de Core tels quels. Refus :
`{"ok": false, "code", "error", "core_status"}` (comme `/api/conversations`) ;
un code de Core est rendu tel quel avec son statut, `core_status` = statut de
Core, `null` quand Core n'a pas répondu (`core_unreachable` 503,
`core_unconfigured` 503, `core_timeout` 504). Jeton refusé même relu : 502
`core_unauthorized` ; réponse non JSON : 502 `invalid_core_response`.

**Garde.** `/api/chat` est dans `READ_GUARDED_ROUTES` : toutes les méthodes
exigent un Host de bouclage, un Origin de bouclage s'il existe et jamais
`Sec-Fetch-Site: cross-site`. En plus pour une écriture : `Content-Type:
application/json` (415 `invalid_content_type`), corps ≤ 64 Kio (413
`request_too_large`).

**Journal.** Chaque écriture relayée : `chat.request.relayed` (action, statut,
code) ; jamais un corps. Panne de Core : `chat.request.core_unreachable`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.protocol.strict_json import read_bounded
from jarvis.runtime.capture_relay import CaptureRelayRoutes, _code_of

CHAT_ROUTE = "/api/chat"
GUARDED_PREFIXES = (CHAT_ROUTE,)
#: Corps JSON relayé au plus (`docs/chat.md` › *Error codes*).
MAX_CHAT_BODY_BYTES = 64 * 1024
#: Codes rendus quand Core n'a pas répondu (pas de `core_status`).
_TRANSPORT_CODES = frozenset({"core_unreachable", "core_unconfigured", "core_timeout"})


def chat_error(status: int, code: str, message: str, core_status: int | None = None) -> web.Response:
    return web.json_response({"ok": False, "code": code, "error": message, "core_status": core_status}, status=status)


class ChatRelayRoutes(CaptureRelayRoutes):
    """Relais `/api/chat*` -> Core. Voir l'en-tête."""

    JOURNAL_PREFIX = "chat.request"
    MAX_BODY_BYTES = MAX_CHAT_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get(CHAT_ROUTE + "/state", self._chat("chat_state", "/v1/chat/state")),
            web.post(CHAT_ROUTE + "/voice/disable", self._chat("voice_disable", "/v1/voice/channel/disable")),
        ]

    def _chat(self, action: str, core_path: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            if request.query:
                return chat_error(400, "invalid_request", "unexpected query parameters")
            body: bytes | None = None
            if request.method != "GET":
                if request.content_type != "application/json":
                    return chat_error(415, "invalid_content_type", "Content-Type: application/json expected")
                if request.content_length is not None and request.content_length > self.MAX_BODY_BYTES:
                    return chat_error(413, "request_too_large", f"JSON body exceeds {self.MAX_BODY_BYTES} bytes")
                try:
                    body = await read_bounded(request.content, self.MAX_BODY_BYTES)
                except ValueError:
                    return chat_error(413, "request_too_large", f"JSON body exceeds {self.MAX_BODY_BYTES} bytes")
            status, payload = await self._forward(request.method, core_path, action=action, params=None, body=body,
                                                  timeout_s=None)
            if request.method != "GET":
                self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"{action} relayé à Core (HTTP {status})",
                                   level="info" if status < 400 else "warning",
                                   data={"action": action, "status": status, "code": _code_of(payload)})
            return self._answer(status, payload)

        return handler

    @staticmethod
    def _answer(status: int, payload: Any) -> web.Response:
        if not isinstance(payload, dict):
            return chat_error(502, "invalid_core_response", f"Core answered HTTP {status} without a JSON object",
                              core_status=status)
        if status < 400:
            return web.json_response(payload, status=status)
        code = _code_of(payload) or "http_error"
        error = payload.get("error")
        message = str(error.get("message", "")) if isinstance(error, dict) else ""
        if code in _TRANSPORT_CODES:
            return chat_error(status, code, message)
        if status == 401:
            return chat_error(502, "core_unauthorized", "Core refused the session token, even re-read", core_status=401)
        return chat_error(status, code, message, core_status=status)
