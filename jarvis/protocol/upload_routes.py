"""Route de téléversement de Core (handoff jarvis-unified-chat-and-board-drop, Slice 07).

`PUT /v1/uploads/{client_upload_id}?purpose=chat[&agent=claude|codex]` : un
fichier par requête, corps brut lu **en flux** (`request.content`, jamais
`read()` : la borne du corps entier de Core, 6 Mio, ne s'applique pas ici ;
c'est `JARVIS_UPLOAD_MAX_BYTES` qui borne, à chaque morceau). Servie par
`LocalProtocolServer` (jeton porteur exigé par son middleware) ; logique dans
`jarvis/core/upload_service.py`. Le Control Center la relaie depuis
`POST /api/chat/uploads` (`jarvis/runtime/chat_relay.py`). Contrat :
`docs/chat.md` › *Attachments*.

En-têtes : `Content-Length` (sinon `Transfer-Encoding: chunked`, le corps que
relaie le Control Center), `Content-Type` (déclaré, gardé pour mémoire,
jamais cru), `X-Jarvis-Upload-Name` (nom d'origine, UTF-8 encodé pourcent).

Réponse : 201 (nouveau) ou 200 (rejeu) `{artifact_id, original_name,
mime_type, size_bytes, brain_readable, state, error_code, replayed}` ;
refus `{"error": {"code", "message"[, "artifact_id", "state", "active_board_id"]}}`.
Jamais un chemin, ni absolu ni relatif.

Dépôt sur un Board (Slice 08, `docs/chat.md` › *Board drop*) :
`PUT /v1/uploads/{client_upload_id}?purpose=board&board_id=…` (même flux ;
la réponse ajoute `board_id` et `relinked`) et `POST /v1/uploads/links`
`{client_upload_id, url, board_id}` → `{artifact_id, kind: "link", url, host,
state, replayed, board_id, relinked}`, 201 ou 200 (rejeu). L'URL n'est
**jamais** récupérée. Refus : 400 `link_invalid`, 409
`board_drop_target_inactive` (avec `active_board_id`).
"""

from __future__ import annotations

from aiohttp import web

from jarvis.core.upload_service import UploadRefused, UploadService, link_view, upload_view
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

UPLOAD_ROUTE = "/v1/uploads/{client_upload_id}"
LINK_ROUTE = "/v1/uploads/links"
_PARAMS = frozenset({"purpose", "agent", "board_id"})
_LINK_FIELDS = frozenset({"client_upload_id", "url", "board_id"})
#: Corps de `POST /v1/uploads/links` : trois chaînes, dont une URL de 2048 caractères au plus.
MAX_LINK_BODY_BYTES = 16 * 1024


def _refusal(refusal: UploadRefused) -> web.Response:
    error = {"code": refusal.code, "message": refusal.message[:500], **refusal.details}
    if refusal.artifact is not None:
        error.update(artifact_id=refusal.artifact.artifact_id, state=refusal.artifact.state.value)
    return web.json_response({"error": error}, status=refusal.status)


def _unwired() -> web.Response:
    return web.json_response({"error": {"code": "core_unavailable", "message": "uploads are not wired"}}, status=503)


class UploadProtocolRoutes:
    def __init__(self, uploads: UploadService | None) -> None:
        self._uploads = uploads

    def routes(self) -> list[web.RouteDef]:
        return [web.post(LINK_ROUTE, self.link), web.put(UPLOAD_ROUTE, self.put)]

    async def put(self, request: web.Request) -> web.Response:
        if self._uploads is None:
            return _unwired()
        unknown = sorted(set(request.query) - _PARAMS)
        if unknown or any(len(request.query.getall(key)) > 1 for key in request.query):
            return _refusal(UploadRefused(400, "invalid_request", f"unexpected query parameters {unknown[:5]}"))
        try:
            outcome = await self._uploads.put(
                client_upload_id=request.match_info["client_upload_id"], purpose=request.query.get("purpose", ""),
                agent=request.query.get("agent"), declared_mime=request.headers.get("Content-Type"),
                name_header=request.headers.get("X-Jarvis-Upload-Name"), content_length=request.content_length,
                read=request.content.read, board_id=request.query.get("board_id"))
        except UploadRefused as refusal:
            return _refusal(refusal)
        body = {**upload_view(outcome.artifact), "replayed": outcome.replayed}
        if outcome.board_id is not None:
            body.update(board_id=outcome.board_id, relinked=outcome.relinked)
        return web.json_response(body, status=200 if outcome.replayed else 201)

    async def link(self, request: web.Request) -> web.Response:
        """`POST /v1/uploads/links` : une URL déposée sur le Board affiché (Slice 08). Jamais récupérée."""

        if self._uploads is None:
            return _unwired()
        if request.query:
            return _refusal(UploadRefused(400, "invalid_request", "unexpected query parameters"))
        try:
            raw = await read_bounded(request.content, MAX_LINK_BODY_BYTES)
        except ValueError:
            return _refusal(UploadRefused(413, "request_too_large", f"body exceeds {MAX_LINK_BODY_BYTES} bytes"))
        try:
            body = loads_strict_json(raw, invalid_message="invalid link drop JSON")
        except ValueError as exc:
            return _refusal(UploadRefused(400, "invalid_request", str(exc)))
        if not isinstance(body, dict) or set(body) != _LINK_FIELDS:
            return _refusal(UploadRefused(400, "invalid_request", "body must be {client_upload_id, url, board_id}"))
        try:
            outcome = await self._uploads.put_link(client_upload_id=body["client_upload_id"], url=body["url"],
                                                   board_id=body["board_id"])
        except UploadRefused as refusal:
            return _refusal(refusal)
        return web.json_response({**link_view(outcome.artifact), "replayed": outcome.replayed,
                                  "board_id": outcome.board_id, "relinked": outcome.relinked},
                                 status=200 if outcome.replayed else 201)
