"""Routes HTTP de Core : capacités locales installables (handoff jarvis-remotion-presentation-integration, Slice 04).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ; logique dans
`jarvis/core/local_capability_service.py` (façade) et `jarvis/core/local_capability_host.py` (hôte).
Contrat : `docs/local-capabilities.md` §7 et `docs/remotion-runtime.md` §5. Famille distincte de
`/v1/mcp/plugins` : aucune route, aucun code, aucun champ en commun.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/local-capabilities` | `{capabilities: [vue publique]}` (une entrée `state_unreadable` typée par état illisible) |
| GET | `/v1/local-capabilities/{capability_id}` | `{capability: vue}` ; 404 `local_capability_unknown` |
| POST | `/v1/local-capabilities/{capability_id}/{operation}` | `install`, `update`, `repair`, `uninstall` (longues : 200 si finie en 2 s, sinon 202 + vue courante à relire par GET) ; `start`, `stop`, `health`, `enable`, `disable` (200). Corps vide ou `{}`. |

Refus : `{"error": {"code": "local_capability_*", "message"}}` : 404 inconnue, 400 invalide, 409 occupée /
non installée / désactivée / mise à jour requise, 503 `local_capability_runner_unavailable`, 500 défaut local.
Un ÉCHEC d'opération (npm hors ligne, version de Node trop ancienne...) n'est pas une erreur HTTP : c'est la vue
(`status: install_failed`, `last_error_code`, `last_error_detail`). Rien n'est lancé par le démarrage de Core.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.local_capability_service import OPERATIONS, http_status
from jarvis.domain.local_capabilities import LocalCapabilityError, LocalCapabilityErrorCode as C

PREFIX = "/v1/local-capabilities"
MAX_BODY_BYTES = 1024

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class LocalCapabilityProtocolRoutes:
    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(PREFIX, g(self.list)),
            web.get(PREFIX + "/{capability_id}", g(self.get)),
            web.post(PREFIX + "/{capability_id}/{operation}", g(self.act)),
        ]

    @staticmethod
    def _guarded(handler: Handler) -> Handler:
        async def run(request: web.Request) -> web.StreamResponse:
            try:
                return await handler(request)
            except LocalCapabilityError as exc:
                return web.json_response({"error": {"code": exc.code.value, "message": exc.detail or exc.code.value}}, status=http_status(exc.code))
        return run

    @staticmethod
    def _no_query(request: web.Request) -> None:
        if request.query:
            raise LocalCapabilityError(C.INVALID, "unexpected query parameters")

    async def list(self, request: web.Request) -> web.StreamResponse:
        self._no_query(request)
        return web.json_response({"capabilities": await self._core.local_capabilities.list()})

    async def get(self, request: web.Request) -> web.StreamResponse:
        self._no_query(request)
        return web.json_response({"capability": await self._core.local_capabilities.get(request.match_info["capability_id"])})

    async def act(self, request: web.Request) -> web.StreamResponse:
        self._no_query(request)
        operation = request.match_info["operation"]
        if operation not in OPERATIONS:
            raise LocalCapabilityError(C.INVALID, f"unknown operation {operation[:40]!r}")
        raw = await request.read()
        if len(raw) > MAX_BODY_BYTES or raw.strip() not in (b"", b"{}"):
            raise LocalCapabilityError(C.INVALID, "the request body must be empty or {}")
        status, view = await self._core.local_capabilities.act(request.match_info["capability_id"], operation)
        return web.json_response({"capability": view}, status=status)
