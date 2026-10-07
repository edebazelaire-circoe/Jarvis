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
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/controls` | introspection (Slice 04) : `{presentation_id, variant_id, variant_revision, scene_id, order, title, section, prefab, preview, controls, anchors, payload, problems, stage}` |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/score` | Slice 10 : `{score, problems}` (`problems` : références qui ne se résolvent plus dans la variante actuelle) |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/score` | Slice 10 : corps `{expected_variant_revision, start_item_id, items, cues, sequences, recovery_points}` -> 201 `{score, problems: []}` ; la variante reçoit `score_id` |
| PUT | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/score` | Slice 10 : corps `{expected_revision, ...contenu}` (remplacement) -> `{score, problems: []}` |
| GET | `.../variants/{variant_id}/scenes/{scene_id}/control-suggestions` | Slice 05 : `{basis, declared, proposals, truncated, apply}` ; propose, n'écrit rien |
| POST | `.../variants/{variant_id}/edits` | Slice 05 : corps `{actor, mode: preview or commit, basis: {variant_revision}, ops: [...]}` -> le résultat d'édition (`status` `applied` 200, `stale` 409, `refused` 400/404 avec son code ; toujours `{status, mode, committed, changed, tier, ops, undo, source_requests, revision}`, et `{error: {code, message}}` quand ce n'est pas `applied`) |
| GET | `.../variants/{variant_id}/history` | Slice 08 : l'historique d'annulation de la variante (mémoire seulement) : `{revision, in_sync, durable: false, tracked, reason, undo_count, redo_count, undo, redo, next_undo, next_redo, bytes, evicted, redo_cleared, stats}` ; ne modifie rien |
| POST | `.../variants/{variant_id}/undo` | Slice 08 : corps `{actor, expected_entry_id?}` -> le résultat d'historique (`status` `applied` 200, `history_unavailable` / `nothing_to_undo` / `stale` 409, `refused` 400/404/409, avec `error: {code, message}` sinon) |
| POST | `.../variants/{variant_id}/redo` | Slice 08 : idem pour rétablir (`nothing_to_redo`) |

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
from jarvis.domain.presentation_studio_edit import MAX_EDIT_BODY_BYTES
from jarvis.domain.presentation_studio_history import MAX_HISTORY_BODY_BYTES
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
            web.get(PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/controls",
                    g(self.scene_controls)),
            web.get(PREFIX + "/{presentation_id}/variants/{variant_id}/score", g(self.get_score)),
            web.post(PREFIX + "/{presentation_id}/variants/{variant_id}/score", g(self.create_score)),
            web.put(PREFIX + "/{presentation_id}/variants/{variant_id}/score", g(self.save_score)),
            web.get(PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/control-suggestions",
                    g(self.control_suggestions)),
            web.post(PREFIX + "/{presentation_id}/variants/{variant_id}/edits", g(self.edit)),
            web.get(PREFIX + "/{presentation_id}/variants/{variant_id}/history", g(self.history)),
            web.post(PREFIX + "/{presentation_id}/variants/{variant_id}/undo", g(self.undo)),
            web.post(PREFIX + "/{presentation_id}/variants/{variant_id}/redo", g(self.redo)),
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

    async def scene_controls(self, request: web.Request) -> web.Response:
        _only(request, set())
        info = request.match_info
        return web.json_response(await self._service.describe_scene(
            info["presentation_id"], info["variant_id"], info["scene_id"]))

    async def get_score(self, request: web.Request) -> web.Response:
        _only(request, set())
        info = request.match_info
        return web.json_response(await self._service.get_score(info["presentation_id"], info["variant_id"]))

    async def create_score(self, request: web.Request) -> web.Response:
        info = request.match_info
        answer = await self._service.create_score(info["presentation_id"], info["variant_id"], await self._body(request))
        return web.json_response(answer, status=201)

    async def save_score(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._service.save_score(
            info["presentation_id"], info["variant_id"], await self._body(request)))
    async def control_suggestions(self, request: web.Request) -> web.Response:
        _only(request, set())
        info = request.match_info
        return web.json_response(await self._core.presentation_studio_edit.suggest_controls(
            info["presentation_id"], info["variant_id"], info["scene_id"]))

    async def edit(self, request: web.Request) -> web.Response:
        """Un refus de l'édition (`refused`, `stale`) est un résultat complet avec son statut HTTP, pas une enveloppe nue."""

        result = await self._core.presentation_studio_edit.edit(
            request.match_info["presentation_id"], request.match_info["variant_id"],
            await self._body(request, MAX_EDIT_BODY_BYTES))
        return web.json_response(result.to_dict(), status=result.http_status)

    async def history(self, request: web.Request) -> web.Response:
        _only(request, set())
        info = request.match_info
        return web.json_response(await self._core.presentation_studio_history.status(
            info["presentation_id"], info["variant_id"]))

    async def undo(self, request: web.Request) -> web.Response:
        """Un refus (`history_unavailable`, `nothing_to_undo`, `stale`, `refused`) est un résultat complet, pas une enveloppe nue."""

        info = request.match_info
        result = await self._core.presentation_studio_history.undo(
            info["presentation_id"], info["variant_id"], await self._body(request, MAX_HISTORY_BODY_BYTES))
        return web.json_response(result.to_dict(), status=result.http_status)

    async def redo(self, request: web.Request) -> web.Response:
        info = request.match_info
        result = await self._core.presentation_studio_history.redo(
            info["presentation_id"], info["variant_id"], await self._body(request, MAX_HISTORY_BODY_BYTES))
        return web.json_response(result.to_dict(), status=result.http_status)

    async def save_variant(self, request: web.Request) -> web.Response:
        saved = await self._service.save_variant(request.match_info["presentation_id"],
                                                 request.match_info["variant_id"], await self._body(request))
        return web.json_response(saved.to_document())
