"""Routes de Core : import d'un modèle Remotion amont (handoff jarvis-remotion-presentation-integration, Slice 18 ; `docs/remotion-import.md`).

Servies par `LocalProtocolServer` (jeton porteur). Aucune route du Control Center : l'import est une demande explicite de l'utilisateur. Le cerveau ne l'appelle que par
`remotion_import` (serveur `jarvis-remotion`, Slice 21), dans le tour de l'utilisateur, jamais de sa propre initiative.

| Méthode | Route | Corps | Réponse |
| --- | --- | --- | --- |
| POST | `/v1/remotion/imports/plan` | `{"repo_url", "commit", "composition_id"?, "subdir"?, "composition"?, "title"?, "ref"?}` | `{plan, validated, publishes: false}` ; télécharge et analyse, n'écrit rien |
| POST | `/v1/remotion/imports` | idem + `"presentation_id"` (+ `"scene_id"`?) | `{imported, scope: "presentation", prefab: {prefab_id, version, fingerprint}, plan, published_to_library: false}` |

Refus : `{"error": {"code", "message", "details"?}}` ; 400 requête / origine / commit non épinglé, 403 origine hors liste blanche, 404
présentation inconnue, 409 import déjà en cours, 413 archive trop grosse, 422 source lue mais inacceptable (licence, dépendance,
archive, gardes), 502 / 504 panne amont, 503 Core sans service d'import.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.remotion_import_service import status_of
from jarvis.domain.remotion_upstream import UpstreamRefusal
from jarvis.protocol.capture_routes import _only, error_response
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

PREFIX = "/v1/remotion/imports"
MAX_BODY_BYTES = 8 * 1024
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class RemotionImportProtocolRoutes:
    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [web.post(PREFIX + "/plan", g(self.plan)), web.post(PREFIX, g(self.import_template))]

    def _guarded(self, handler: Handler) -> Handler:
        async def run(request: web.Request) -> web.StreamResponse:
            try:
                if not self._core.health.ready:
                    return error_response(503, "core_unavailable", "core is not ready")
                if getattr(self._core, "remotion_import", None) is None:
                    return error_response(503, "remotion_import_unavailable", "this Core has no upstream importer")
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except UpstreamRefusal as exc:
                return error_response(status_of(exc.code), exc.code, exc.message, details=list(exc.details) or None)
            except ValueError as exc:
                return error_response(400, "request_invalid", str(exc))
            except Exception as exc:  # noqa: BLE001 - jamais un défaut muet : journalisé durablement, 500 codé
                service = getattr(self._core, "remotion_import", None)
                if service is not None:
                    service.report_failure(exc)
                return error_response(500, "remotion_import_failed", "the import failed unexpectedly: see the Core error log")

        return run

    @staticmethod
    async def _body(request: web.Request) -> Any:
        _only(request, set())
        return loads_strict_json(await read_bounded(request.content, MAX_BODY_BYTES), invalid_message="body must be JSON")

    async def plan(self, request: web.Request) -> web.Response:
        return web.json_response(await self._core.remotion_import.plan(await self._body(request)), headers={"Cache-Control": "no-store"})

    async def import_template(self, request: web.Request) -> web.Response:
        return web.json_response(await self._core.remotion_import.import_template(await self._body(request)),
                                 headers={"Cache-Control": "no-store"})
