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
| `POST /api/chat/uploads` (multipart) | `PUT /v1/uploads/{client_upload_id}?purpose=chat` (flux) | 07 |
| `POST /api/boards/drop?board_id=` (multipart) | `PUT /v1/uploads/{client_upload_id}?purpose=board&board_id=` (flux) | 08 |
| `POST /api/boards/drop-link` | `POST /v1/uploads/links` | 08 |

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

**Pièce jointe** (`docs/chat.md` › *Control Center `POST /api/chat/uploads`*) :
multipart `client_upload_id` puis `file`, lu **en flux** (`request.multipart()`,
morceaux de 64 Kio) et relayé à Core en corps `chunked` par un générateur :
jamais tenu en mémoire, jamais écrit sur disque ici. Refus tôt si
`Content-Length` dépasse la borne (`JARVIS_UPLOAD_MAX_BYTES`) plus la marge
multipart ; la borne exacte est tenue par Core, au morceau près. La réponse
rend `brain_readable` tel que Core l'a calculé pour l'agent du premier plan
(passé en `agent`) ; jamais un chemin.
Journal `chat.upload.relayed` (statut, code, `artifact_id`, taille, type),
jamais le nom d'origine ni un octet.

**Dépôt sur le Board** (Slice 08, `docs/chat.md` › *Board drop*) : le même
relais en flux, `purpose=board` et le `board_id` affiché par la page ; l'URL
déposée part en JSON fermé `{client_upload_id, url, board_id}` vers
`POST /v1/uploads/links`. Ni tour, ni conversation, ni requête vers l'URL.
`/api/boards/drop` et `/api/boards/drop-link` sont gardés comme `/api/chat`
(`GUARDED_PREFIXES`). Journal `board.drop.relayed` / `board.drop_link.relayed`
(statut, code, `artifact_id`, `relinked`), jamais un nom, un octet ni l'URL.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import json
import os
import re
from typing import Any
from urllib.parse import quote
import uuid

from aiohttp import web

from jarvis.domain.uploads import (
    BRAIN_AGENTS, MULTIPART_MARGIN_BYTES, UPLOAD_CHUNK_BYTES, check_client_upload_id, upload_bounds,
)
from jarvis.protocol.strict_json import loads_strict_json, read_bounded
from jarvis.runtime.capture_relay import CaptureRelayRoutes, _code_of

CHAT_ROUTE = "/api/chat"
#: Dépôt sur le Board affiché (Slice 08) : fichier (multipart, en flux) et URL inerte.
BOARD_DROP_ROUTE = "/api/boards/drop"
BOARD_DROP_LINK_ROUTE = "/api/boards/drop-link"
GUARDED_PREFIXES = (CHAT_ROUTE, BOARD_DROP_ROUTE, BOARD_DROP_LINK_ROUTE)
#: Corps JSON relayé au plus (`docs/chat.md` › *Error codes*).
MAX_CHAT_BODY_BYTES = 64 * 1024
#: Codes rendus quand Core n'a pas répondu (pas de `core_status`).
_TRANSPORT_CODES = frozenset({"core_unreachable", "core_unconfigured", "core_timeout"})
#: Budget d'un tour écrit relayé (s) : au-delà, 504 `core_timeout`, issue inconnue, rejouer.
CHAT_TURN_TIMEOUT_S = 15.0
#: Champs d'un refus de Core rendus au navigateur en plus du code (`docs/chat.md`).
_RELAYED_DETAILS = ("reason", "current_conversation_id", "active_board_id")
#: Corps de `POST /api/chat/turns` : fermé.
_TURN_FIELDS = frozenset({"conversation_id", "client_request_id", "content", "attachments"})
#: Attente de la réponse de Core une fois le fichier envoyé (s) : finalisation, `fsync`.
CHAT_UPLOAD_READ_TIMEOUT_S = 120.0
_MAX_UPLOAD_ID_FIELD_BYTES = 256
#: Corps de `POST /api/boards/drop-link` : fermé, trois chaînes.
_LINK_FIELDS = frozenset({"client_upload_id", "url", "board_id"})
#: Un id de Board tient dans un paramètre (Core le revalide contre le Board actif).
_BOARD_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


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
    """Relais `/api/chat*` et dépôt sur le Board (`/api/boards/drop*`) -> Core. Voir l'en-tête."""

    JOURNAL_PREFIX = "chat.request"
    MAX_BODY_BYTES = MAX_CHAT_BODY_BYTES

    def __init__(self, *, transport: Callable[[], Any], journal: Any,
                 agent_id: Callable[[], str | None] = lambda: None) -> None:
        super().__init__(transport=transport, journal=journal)
        #: CLI du premier plan, relu à chaque requête : décide `brain_readable` d'une pièce jointe.
        self._agent_id = agent_id

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get(CHAT_ROUTE + "/state", self._chat("chat_state", "/v1/chat/state")),
            web.post(CHAT_ROUTE + "/voice/disable", self._chat("voice_disable", "/v1/voice/channel/disable")),
            web.post(CHAT_ROUTE + "/turns", self.turn),
            web.post(CHAT_ROUTE + "/uploads", self.upload),
            web.post(BOARD_DROP_ROUTE, self.board_drop),
            web.post(BOARD_DROP_LINK_ROUTE, self.board_drop_link),
        ]

    async def upload(self, request: web.Request) -> web.Response:
        """`POST /api/chat/uploads` -> `PUT /v1/uploads/{client_upload_id}?purpose=chat`, en flux (Slice 07)."""

        if request.query:
            return chat_error(400, "invalid_request", "unexpected query parameters")
        return await self._stream_upload(request, purpose="chat", board_id=None)

    async def board_drop(self, request: web.Request) -> web.Response:
        """`POST /api/boards/drop?board_id=` -> `PUT /v1/uploads/{id}?purpose=board&board_id=`, en flux (Slice 08)."""

        board_id = request.query.get("board_id", "")
        if set(request.query) != {"board_id"} or len(request.query.getall("board_id")) != 1 \
                or not _BOARD_ID.fullmatch(board_id):
            return chat_error(400, "invalid_request", "query must be ?board_id=<the displayed Board>")
        return await self._stream_upload(request, purpose="board", board_id=board_id)

    async def board_drop_link(self, request: web.Request) -> web.Response:
        """`POST /api/boards/drop-link` -> `POST /v1/uploads/links` (Slice 08). L'URL n'est jamais récupérée."""

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
            body = loads_strict_json(raw, invalid_message="invalid link drop JSON")
            if not isinstance(body, dict) or set(body) != _LINK_FIELDS or not all(isinstance(body[key], str)
                                                                                 for key in _LINK_FIELDS):
                raise ValueError("body must be {client_upload_id, url, board_id}, three strings")
        except ValueError as exc:
            return chat_error(400, "invalid_request", str(exc)[:200])
        status, payload = await self._forward("POST", "/v1/uploads/links", action="board_drop_link", params=None,
                                              body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                              timeout_s=None)
        ok = status in (200, 201) and isinstance(payload, dict)
        self._journal.emit("board.drop_link.relayed", f"URL déposée relayée à Core (HTTP {status})",
                           level="info" if ok else "warning",
                           data={"status": status, "code": None if ok else _code_of(payload),
                                 "artifact_id": payload.get("artifact_id") if ok else None,
                                 "relinked": payload.get("relinked") if ok else None})
        if ok:
            keys = ("artifact_id", "kind", "url", "host", "state", "replayed", "board_id", "relinked",
                    "also_linked_board_id")
            return web.json_response({"ok": True, **{key: payload.get(key) for key in keys}}, status=status)
        return self._answer(status, payload)

    async def _stream_upload(self, request: web.Request, *, purpose: str, board_id: str | None) -> web.Response:
        """Un fichier du navigateur vers Core, en flux : le seul relais de téléversement (chat et Board)."""

        action, journal = ("chat_upload", "chat.upload.relayed") if board_id is None else \
            ("board_drop", "board.drop.relayed")
        if request.content_type != "multipart/form-data":
            return chat_error(415, "invalid_content_type", "Content-Type: multipart/form-data expected")
        bounds = upload_bounds(os.environ)
        if request.content_length is not None and request.content_length > bounds.max_bytes + MULTIPART_MARGIN_BYTES:
            return chat_error(413, "upload_too_large", f"the file exceeds the {bounds.max_bytes}-byte upload bound")
        transport = self._transport()
        if transport is None:
            return chat_error(503, "core_unconfigured", "the control center does not know Core")
        try:
            reader = await request.multipart()
            part = await reader.next()
            if part is None or part.name != "client_upload_id":
                raise ValueError("the first multipart field must be client_upload_id")
            raw = await part.read_chunk(_MAX_UPLOAD_ID_FIELD_BYTES + 1)
            if len(raw) > _MAX_UPLOAD_ID_FIELD_BYTES or await part.read_chunk(1):
                raise ValueError("client_upload_id is too long")
            client_upload_id = check_client_upload_id(raw.decode("utf-8", errors="strict").strip())
            file = await reader.next()
            if file is None or file.name != "file":
                raise ValueError("the second multipart field must be file")
        except (ValueError, UnicodeDecodeError, AttributeError) as exc:
            return chat_error(400, "invalid_request", str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 - capture: unreadable multipart framing, said with its cause
            return chat_error(400, "invalid_request", f"unreadable multipart body ({type(exc).__name__})")
        agent = self._agent_id()
        cut: list[str] = []

        async def chunks() -> AsyncIterator[bytes]:
            # Un morceau à la fois, du navigateur vers Core : la seule mémoire tenue ici.
            try:
                while chunk := await file.read_chunk(UPLOAD_CHUNK_BYTES):
                    yield chunk
            except Exception as exc:  # noqa: BLE001 - rethrown: Core sees a cut body and fails the upload
                cut.append(type(exc).__name__)
                raise

        headers = {"Content-Type": file.headers.get("Content-Type") or "application/octet-stream",
                   "X-Jarvis-Upload-Name": quote(file.filename or "", safe="")}
        params = [("purpose", purpose)] + ([("board_id", board_id)] if board_id is not None else []) \
            + ([("agent", agent)] if agent in BRAIN_AGENTS else [])
        path = f"/v1/uploads/{client_upload_id}"
        try:
            status, payload = await transport.forward_upload(path, params=params, headers=headers, body=chunks(),
                                                             read_timeout_s=CHAT_UPLOAD_READ_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            self._unreachable(action, "PUT", "/v1/uploads", "core_timeout", "TimeoutError")
            status, payload = 504, {"error": {"code": "core_timeout",
                                              "message": "Core did not answer in time; resend the same client_upload_id"}}
        except Exception as exc:  # noqa: BLE001 - surfaced: browser cut (400) or Core unreachable (503), journaled
            if cut:
                status, payload = 400, {"error": {"code": "upload_incomplete",
                                                  "message": f"the browser stopped sending the file ({cut[0]})"}}
            else:
                self._unreachable(action, "PUT", "/v1/uploads", "core_unreachable", type(exc).__name__)
                status, payload = 503, {"error": {"code": "core_unreachable",
                                                  "message": f"Core is unreachable: {type(exc).__name__}"}}
        ok = status in (200, 201) and isinstance(payload, dict)
        data = {"status": status, "code": None if ok else _code_of(payload),
                "artifact_id": payload.get("artifact_id") if ok else None,
                "size_bytes": payload.get("size_bytes") if ok else None,
                "mime_type": payload.get("mime_type") if ok else None}
        if board_id is not None:
            data["relinked"] = payload.get("relinked") if ok else None
        self._journal.emit(journal, f"{'fichier déposé' if board_id else 'pièce jointe'} relayé à Core (HTTP {status})",
                           level="info" if ok else "warning", data=data)
        if ok:
            keys = ("artifact_id", "original_name", "mime_type", "size_bytes", "state", "replayed")
            extra = {} if board_id is None else {key: payload.get(key)
                                                 for key in ("board_id", "relinked", "also_linked_board_id")}
            return web.json_response({"ok": True, **{key: payload.get(key) for key in keys},
                                      # La valeur de Core, calculée pour le même agent : jamais recalculée ici.
                                      "brain_readable": payload.get("brain_readable") is True, **extra},
                                     status=status)
        return self._answer(status, payload)

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
