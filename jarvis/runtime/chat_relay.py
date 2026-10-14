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
| `POST /api/chat/turns` | `POST /v1/conversations/{id}/brain-turns` (`source=text`) | 03 |

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
code) ; jamais un corps. Tour écrit : `chat.turn.relayed` (statut, code,
`correlation_id`, nombre de pièces jointes), jamais le texte. Panne de Core :
`chat.request.core_unreachable`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import re
from typing import Any
from urllib.parse import quote
import uuid

from aiohttp import web

from jarvis.protocol.strict_json import loads_strict_json, read_bounded
from jarvis.runtime.capture_relay import CaptureRelayRoutes, _code_of

CHAT_ROUTE = "/api/chat"
GUARDED_PREFIXES = (CHAT_ROUTE,)
#: Corps JSON relayé au plus (`docs/chat.md` › *Error codes*).
MAX_CHAT_BODY_BYTES = 64 * 1024
#: Codes rendus quand Core n'a pas répondu (pas de `core_status`).
_TRANSPORT_CODES = frozenset({"core_unreachable", "core_unconfigured", "core_timeout"})
#: Budget d'un tour écrit relayé (s) : au-delà, 504 `core_timeout`, issue inconnue, rejouer.
CHAT_TURN_TIMEOUT_S = 15.0
#: Champs d'un refus de Core rendus au navigateur en plus du code (`docs/chat.md`).
_RELAYED_DETAILS = ("reason", "current_conversation_id")
#: Corps de `POST /api/chat/turns` : fermé.
_TURN_FIELDS = frozenset({"conversation_id", "client_request_id", "content", "attachments"})


def _turn_body(raw: bytes) -> tuple[str, str, dict[str, Any]]:
    """(conversation, corrélation, corps Core) d'un tour écrit ; `ValueError` sans jamais citer le texte."""

    body = loads_strict_json(raw, invalid_message="invalid chat turn JSON")
    if not isinstance(body, dict) or not set(body) <= _TURN_FIELDS or not {"conversation_id", "client_request_id",
                                                                           "content"} <= set(body):
        raise ValueError("chat turn body must be {conversation_id, client_request_id, content, attachments?}")
    conversation_id = body["conversation_id"]
    if not isinstance(conversation_id, str) or not _CONVERSATION_ID.fullmatch(conversation_id):
        raise ValueError("conversation_id must be a conversation id")
    try:
        client_request_id = str(uuid.UUID(body["client_request_id"]))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("client_request_id must be a UUID string") from None
    content = body["content"]
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    attachments = body.get("attachments", [])
    if not isinstance(attachments, list) or not all(isinstance(item, str) for item in attachments):
        raise ValueError("attachments must be a list of Artifact ids")
    correlation_id = "chat:" + client_request_id
    return conversation_id, correlation_id, {"content": content, "correlation_id": correlation_id, "source": "text",
                                             "addressing": "addressed", "attachments": attachments}


#: Un id de conversation tient dans un segment de chemin (Core le revalide).
_CONVERSATION_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


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
            web.post(CHAT_ROUTE + "/turns", self.turn),
        ]

    async def turn(self, request: web.Request) -> web.Response:
        """`POST /api/chat/turns` -> `POST /v1/conversations/{id}/brain-turns` `source=text` (Slice 03).

        Le corps du navigateur est relu, jamais relayé tel quel : Core reçoit la
        forme fermée de `docs/chat.md` › *Sending text*. Réponse : 202 (nouveau)
        ou 200 (doublon) `{"ok": true, "correlation_id", "turn_id", "duplicate"}`.
        Journal `chat.turn.relayed` sans le texte.
        """

        if request.query:
            return chat_error(400, "invalid_request", "unexpected query parameters")
        if request.content_type != "application/json":
            return chat_error(415, "invalid_content_type", "Content-Type: application/json expected")
        if request.content_length is not None and request.content_length > self.MAX_BODY_BYTES:
            return chat_error(413, "request_too_large", f"JSON body exceeds {self.MAX_BODY_BYTES} bytes")
        try:
            raw = await read_bounded(request.content, self.MAX_BODY_BYTES)
        except ValueError:
            return chat_error(413, "request_too_large", f"JSON body exceeds {self.MAX_BODY_BYTES} bytes")
        try:
            conversation_id, correlation_id, core_body = _turn_body(raw)
        except ValueError as exc:
            return chat_error(400, "invalid_request", str(exc))
        status, payload = await self._forward(
            "POST", f"/v1/conversations/{quote(conversation_id, safe='')}/brain-turns", action="chat_turn",
            params=None, body=json.dumps(core_body, ensure_ascii=False).encode("utf-8"), timeout_s=CHAT_TURN_TIMEOUT_S)
        if status == 504:
            payload = {"error": {"code": "core_timeout",
                                 "message": "outcome unknown: resend the same client_request_id"}}
        code = _code_of(payload)
        self._journal.emit("chat.turn.relayed", f"tour écrit relayé à Core (HTTP {status})",
                           level="info" if status < 400 else "warning",
                           data={"status": status, "code": code, "correlation_id": correlation_id,
                                 "attachments": len(core_body["attachments"])})
        if status in (200, 202) and isinstance(payload, dict):
            return web.json_response({"ok": True, "correlation_id": payload.get("correlation_id"),
                                      "turn_id": payload.get("turn_id"), "duplicate": bool(payload.get("duplicate"))},
                                     status=status)
        return self._answer(status, payload)

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
        response = chat_error(status, code, message, core_status=status)
        details = {key: error[key] for key in _RELAYED_DETAILS if isinstance(error, dict) and isinstance(error.get(key), str)}
        if details:
            # `reason` du verrou, conversation courante : l'UI se réaligne sans relire l'état.
            response = web.json_response({"ok": False, "code": code, "error": message, "core_status": status, **details},
                                         status=status)
        return response
