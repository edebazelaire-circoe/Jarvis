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
refus `{"error": {"code", "message"[, "artifact_id", "state"]}}`. Jamais un
chemin, ni absolu ni relatif.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.core.upload_service import UploadRefused, UploadService, upload_view

UPLOAD_ROUTE = "/v1/uploads/{client_upload_id}"
_PARAMS = frozenset({"purpose", "agent", "board_id"})


def _refusal(refusal: UploadRefused) -> web.Response:
    error = {"code": refusal.code, "message": refusal.message[:500]}
    if refusal.artifact is not None:
        error.update(artifact_id=refusal.artifact.artifact_id, state=refusal.artifact.state.value)
    return web.json_response({"error": error}, status=refusal.status)


class UploadProtocolRoutes:
    def __init__(self, uploads: UploadService | None) -> None:
        self._uploads = uploads

    def routes(self) -> list[web.RouteDef]:
        return [web.put(UPLOAD_ROUTE, self.put)]

    async def put(self, request: web.Request) -> web.Response:
        if self._uploads is None:
            return web.json_response({"error": {"code": "core_unavailable", "message": "uploads are not wired"}},
                                     status=503)
        unknown = sorted(set(request.query) - _PARAMS)
        if unknown or any(len(request.query.getall(key)) > 1 for key in request.query):
            return _refusal(UploadRefused(400, "invalid_request", f"unexpected query parameters {unknown[:5]}"))
        try:
            outcome = await self._uploads.put(
                client_upload_id=request.match_info["client_upload_id"], purpose=request.query.get("purpose", ""),
                agent=request.query.get("agent"), declared_mime=request.headers.get("Content-Type"),
                name_header=request.headers.get("X-Jarvis-Upload-Name"), content_length=request.content_length,
                read=request.content.read)
        except UploadRefused as refusal:
            return _refusal(refusal)
        return web.json_response({**upload_view(outcome.artifact), "replayed": outcome.replayed},
                                 status=200 if outcome.replayed else 201)
