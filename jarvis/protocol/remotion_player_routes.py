"""Routes HTTP de Core : lecture d'une scène Remotion (handoff jarvis-remotion-presentation-integration, Slice 10).

Servies par `LocalProtocolServer` (jeton porteur) ; logique dans `jarvis/core/remotion_player.py`. Contrat :
`docs/presentation-engine.md` > *Runtime wiring status* et `docs/remotion-isolation.md` § 10.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/remotion/sandbox` | `{engine: {ready, reason, repair}, sandbox: {configured, origin, embedder_origin, listening}}` : l'état du moteur et l'origine à mettre dans `frame-src` |
| GET | `/v1/remotion/player/{prefab_id}/{version}` | descripteur de lecture (`kind: "remotion"`, adresse de la page du cadre, composition, valeurs par défaut) ; compile à la demande |

Refus (enveloppe `{"error": {code, message, diagnostics?}}`) : `presentation_studio_engine_unavailable` 409 (moteur non prêt : la
raison et la réparation de l'adaptateur), `compile_*` (4xx/5xx selon `COMPILE_HTTP_STATUS`, avec `diagnostics` fichier/ligne/
colonne), codes de prefab (404 inconnue, 409 altérée, 400 source refusée par les gardes). Jamais un résultat HTML.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.domain.prefab import MAX_VERSION
from jarvis.domain.presentation_studio_checks import PresentationStudioError
from jarvis.domain.remotion_compile import RemotionCompileError
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from jarvis.protocol.capture_routes import _only, error_response

PREFIX = "/v1/remotion"
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class RemotionPlayerProtocolRoutes:
    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [web.get(PREFIX + "/sandbox", g(self.sandbox)),
                web.get(PREFIX + "/player/{prefab_id}/{version}", g(self.player))]

    def _guarded(self, handler: Handler) -> Handler:
        async def run(request: web.Request) -> web.StreamResponse:
            try:
                if not self._core.health.ready:
                    return error_response(503, "core_unavailable", "core is not ready")
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except PresentationStudioError as exc:
                return error_response(exc.status, exc.code.value, exc.message)
            except RemotionCompileError as exc:
                return error_response(exc.status, exc.code.value, exc.message,
                                      diagnostics=[d.to_dict() for d in exc.diagnostics] or None)
            except PrefabStoreError as exc:
                return error_response(exc.status, exc.code.value, exc.message, errors=list(exc.errors) or None)
            except ValueError as exc:
                return error_response(400, "invalid_request", str(exc))

        return run

    @property
    def _player(self) -> Any:
        return self._core.remotion_player

    async def sandbox(self, request: web.Request) -> web.Response:
        _only(request, set())
        state = self._player.availability()
        return web.json_response({"engine": {"ready": state.ready, "reason": state.reason, "repair": state.repair},
                                  "sandbox": self._player.sandbox_info()})

    async def player(self, request: web.Request) -> web.Response:
        _only(request, set())
        raw = request.match_info["version"]
        if not (raw.isascii() and raw.isdigit() and len(raw) <= 4) or not 1 <= int(raw) <= MAX_VERSION:
            raise PrefabStoreError(PrefabStoreErrorCode.UNKNOWN_VERSION, f"version must be an integer 1..{MAX_VERSION}")
        body = await self._player.describe(request.match_info["prefab_id"], int(raw))
        return web.json_response(body, headers={"Cache-Control": "no-store"})
