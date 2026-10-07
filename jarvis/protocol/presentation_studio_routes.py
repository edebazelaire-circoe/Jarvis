"""Routes HTTP de Core : Presentations du Studio (handoff jarvis-interactive-presentation-studio, Slice 02).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ;
logique dans `jarvis/core/presentation_studio_service.py`
(`PresentationStudioService`, seule autorité). Pas de relais Control Center à
cette Slice (Slice 05+ : acteur forcé `user`). Contrat :
`docs/presentation-studio.md` › *Presentation contract*.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/presentation-studio/presentations[?limit]` | `{presentations: [{presentation_id, title, active_variant_id, variant_count, resource_count, revision, updated_at}], problems: [{presentation_id, code, message}]}` (`limit` ≤ 256) |
| POST | `/v1/presentation-studio/presentations` | corps `{title}` -> 201 `{presentation, variants}` (variante n° 1 active) |
| POST | `/v1/presentation-studio/presentations/validate` | corps `{presentation, variants}` (format disque) -> `{ok, errors: [{code, message}]}` ; rien n'est écrit |
| GET | `/v1/presentation-studio/presentations/{presentation_id}` | `{presentation, variants}` |
| PUT | `/v1/presentation-studio/presentations/{presentation_id}` | corps `{expected_revision, title, active_variant_id, resources}` -> le document `presentation` |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}` | le document `variant` |
| PUT | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}` | corps `{expected_revision, title, scenes, art_direction_id, score_id}` -> le document `variant` |

Refus : `{"error": {"code", "message"}}` avec les codes `presentation_studio_*`
du domaine et leur statut (400 entrée refusée ou état d'exécution, 404
inconnue, 409 révision périmée / document plus récent / document corrompu /
existe déjà / limite, 500 disque), `invalid_request` 400 pour une requête mal
formée (paramètre de requête, corps non JSON ou trop gros), `core_unavailable`
503 avant le démarrage, `internal_error` 500 pour un imprévu (journalisé en
`error`, jamais un 500 muet). Message sans chemin absolu (`redact_paths`).
La route à segment fixe `validate` s'enregistre avant `{presentation_id}`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.capture_api import redact_paths
from jarvis.domain.presentation_studio import MAX_DOCUMENT_BYTES, MAX_PRESENTATIONS, PresentationStudioError
from jarvis.protocol.capture_routes import _int, _only, error_response
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PREFIX = "/v1/presentation-studio/presentations"
#: Corps d'une validation : une Presentation et jusqu'à 64 variantes (échappement JSON compris).
MAX_VALIDATE_BODY_BYTES = 16 * MAX_DOCUMENT_BYTES


class PresentationStudioProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.presentation_studio`). Voir l'en-tête."""

    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(PREFIX, g(self.list_presentations)),
            web.post(PREFIX, g(self.create)),
            # Segment fixe d'abord : jamais pris pour un `{presentation_id}`.
            web.post(PREFIX + "/validate", g(self.validate)),
            web.get(PREFIX + "/{presentation_id}", g(self.get)),
            web.put(PREFIX + "/{presentation_id}", g(self.save_presentation)),
            web.get(PREFIX + "/{presentation_id}/variants/{variant_id}", g(self.get_variant)),
            web.put(PREFIX + "/{presentation_id}/variants/{variant_id}", g(self.save_variant)),
        ]

    @property
    def _service(self) -> Any:
        return self._core.presentation_studio

    def _guarded(self, handler: Handler) -> Handler:
        """Chaque refus devient l'enveloppe codée ; un imprévu est journalisé en `error`. Jamais un 500 muet."""

        async def run(request: web.Request) -> web.StreamResponse:
            try:
                if not self._core.health.ready:
                    return error_response(503, "core_unavailable", "core is not ready")
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except PresentationStudioError as exc:
                return error_response(exc.status, exc.code.value, exc.message)
            except ValueError as exc:
                return error_response(400, "invalid_request", redact_paths(str(exc)))
            except Exception as exc:  # noqa: BLE001 - boundary: recorded with its real cause, answered coded
                try:
                    self._service.report_unexpected(f"{request.method} {request.match_info.route.resource.canonical}", exc)
                except Exception:  # noqa: BLE001 - intentional: reporting must never mask the coded answer (the journal itself is what failed)
                    pass
                return error_response(500, "internal_error", f"unexpected {type(exc).__name__}; see the Error Logs")

        return run

    @staticmethod
    async def _body(request: web.Request, limit: int = MAX_DOCUMENT_BYTES) -> object:
        _only(request, set())
        raw = await read_bounded(request.content, limit)
        return loads_strict_json(raw, invalid_message="body must be JSON")

    async def list_presentations(self, request: web.Request) -> web.Response:
        _only(request, {"limit"})
        limit = _int(request, "limit", MAX_PRESENTATIONS, 1, MAX_PRESENTATIONS)
        return web.json_response((await self._service.list_presentations(limit)).to_dict())

    async def create(self, request: web.Request) -> web.Response:
        view = await self._service.create(await self._body(request))
        return web.json_response(view.to_dict(), status=201)

    async def validate(self, request: web.Request) -> web.Response:
        return web.json_response(self._service.validate(await self._body(request, MAX_VALIDATE_BODY_BYTES)))

    async def get(self, request: web.Request) -> web.Response:
        _only(request, set())
        view = await self._service.get(request.match_info["presentation_id"])
        return web.json_response(view.to_dict())

    async def save_presentation(self, request: web.Request) -> web.Response:
        saved = await self._service.save_presentation(request.match_info["presentation_id"], await self._body(request))
        return web.json_response(saved.to_document())

    async def get_variant(self, request: web.Request) -> web.Response:
        _only(request, set())
        variant = await self._service.get_variant(request.match_info["presentation_id"],
                                                  request.match_info["variant_id"])
        return web.json_response(variant.to_document())

    async def save_variant(self, request: web.Request) -> web.Response:
        saved = await self._service.save_variant(request.match_info["presentation_id"],
                                                 request.match_info["variant_id"], await self._body(request))
        return web.json_response(saved.to_document())
