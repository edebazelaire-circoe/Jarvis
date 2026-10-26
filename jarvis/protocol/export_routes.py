"""Routes de Core : export explicite d'un fichier final (handoff jarvis-presentation-edition-v1, Slice 03 ; `docs/export.md`).

| Méthode | Route | Corps | Réponse |
| --- | --- | --- | --- |
| GET | `/v1/exports/root` | — | `{root: {available, root, exists?, code?, message?}}` (libellé, jamais un chemin absolu ; ne crée rien) |
| POST | `/v1/exports` | `{artifact_id, file_name?, actor?}` | 201 `{export: {artifact_id, format, file_name, destination: {root, display_path}, size_bytes, sha256, exported_at, renamed, copy: true}}` |

Clés fermées : aucune clé de chemin n'existe (ni source, ni destination) ; une clé inconnue est `export_invalid`. `actor`
vaut `user` (défaut, l'interface) ou `brain` (l'outil MCP, sur la demande attestée de l'utilisateur). Jeton porteur de Core
obligatoire. Refus : `{"error": {"code": "export_*", "message"}}` avec le statut de `ExportErrorCode`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web

from jarvis.domain.document_export import ExportError, ExportErrorCode as E

PREFIX = "/v1/exports"
MAX_BODY_BYTES = 4096
EXPORT_KEYS = frozenset({"artifact_id", "file_name", "actor"})


class ExportProtocolRoutes:
    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        return [web.get(PREFIX + "/root", self._guard(self.root)), web.post(PREFIX, self._guard(self.create))]

    def _service(self):
        service = getattr(self._core, "document_export", None)
        if service is None:
            raise ExportError(E.UNAVAILABLE, "this Core has no export service")
        return service

    def _guard(self, handler):
        async def run(request: web.Request) -> web.Response:
            try:
                if request.query:
                    raise ExportError(E.INVALID, "unexpected query parameters")
                return await handler(request)
            except ExportError as exc:
                return web.json_response({"error": {"code": exc.code.value, "message": exc.detail}}, status=exc.status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - never a silent defect: journalled (error) and answered as a coded 500
                diagnostics = getattr(self._core, "diagnostics", None) or getattr(self._core, "_diagnostics", None)
                if diagnostics is not None:
                    try:
                        diagnostics.emit("core.export.route_failed", f"{request.method} {request.path}: {type(exc).__name__}",
                                         level="error", data={"exception": type(exc).__name__})
                    except Exception:  # noqa: BLE001 - argued: an unavailable journal never changes the answer
                        pass
                return web.json_response({"error": {"code": E.FAILED.value, "message": f"unexpected {type(exc).__name__}"}}, status=500)
        return run

    async def root(self, request: web.Request) -> web.Response:
        return web.json_response({"root": self._service().root()})

    async def create(self, request: web.Request) -> web.Response:
        raw = await request.content.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            raise ExportError(E.INVALID, "the request body is too large")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise ExportError(E.INVALID, "the body must be JSON") from None
        if not isinstance(body, dict):
            raise ExportError(E.INVALID, "the body must be a JSON object")
        stray = sorted(str(k)[:40] for k in body if k not in EXPORT_KEYS)
        if stray:
            raise ExportError(E.INVALID, f"unknown key(s): {', '.join(stray[:5])} (an export takes artifact_id, file_name, actor; never a path)")
        result = await self._service().export(body.get("artifact_id"), file_name=body.get("file_name"),
                                              actor=body.get("actor") or "user")
        # 200 when the same bytes already sat under one of its names (nothing copied), 201 for a new copy
        return web.json_response({"export": result.to_dict()}, status=200 if result.already_exported else 201)
