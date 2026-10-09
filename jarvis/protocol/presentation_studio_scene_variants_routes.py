"""Routes HTTP de Core : les variantes locales d'une scène (handoff jarvis-interactive-presentation-studio, Slice 17).

Même garde, mêmes enveloppes d'erreur et même jeton porteur que `presentation_studio_routes.py` (dont cette classe hérite la
frontière) ; logique dans `jarvis/core/presentation_studio_scene_variants.py`. Contrat : `docs/presentation-studio.md` ›
*Scene-local variant contract*.

**Les écritures d'ensemble n'ont pas de route propre** : créer, renommer, choisir, supprimer sont les opérations
`scene_variant.create|rename|select|delete` de `POST .../variants/{variant_id}/edits` (Slice 05), donc la même porte pour la voix
et l'interface, la même base de révision, la même annulation (Slice 08). Ne sont ici que ce que le vocabulaire ne dit pas :

| Méthode | Route | Corps -> réponse |
| --- | --- | --- |
| GET | `.../presentations/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/scene-variants` | `{selected, count, variants: [{variant_id, label, rationale, source, created_by, created_at, selected, prefab, controls, anchors}], limits, variant_revision}` ; sans contenu |
| POST | `.../scenes/{scene_id}/scene-variants/{scene_variant_id}/preview` | `{actor?, stage?, timeout_s?}` -> `{preview: {title, payload, budget}, written: false, staged, stage_reason, expires_in_s}` ; **n'écrit rien** ; `stage: true` la montre sur la fenêtre de scène si la lecture de la variante est en pause |
| POST | `.../presentations/{presentation_id}/scene-variants/preview/cancel` | `{actor?}` -> `{cancelled}` ; rend la fenêtre de scène à la scène canonique |
| POST | `.../scenes/{scene_id}/scene-variants/{scene_variant_id}/promote` | `{title, rationale?, activate?, actor?, expected_revision?, expected_variant_revision?}` -> 201 la réponse de branche de la Slice 16 (`variant, node, ...`) plus `scene_id`, `scene_variant_id` |

`actor` : `user` (défaut) ou `brain` ; le relais du Control Center le **force** à `user`. Refus : l'enveloppe
`{"error": {"code", "message"}}` des autres routes du Studio.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

#: Un corps d'aperçu ou de promotion est minuscule (un titre, une raison, trois drapeaux).
MAX_SCENE_VARIANT_BODY_BYTES = 16 * 1024
SCENE = PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/scene-variants"


class PresentationStudioSceneVariantsRoutes(PresentationStudioProtocolRoutes):
    """Les routes ci-dessus. Voir l'en-tête."""

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(SCENE, g(self.describe)),
            web.post(SCENE + "/{scene_variant_id}/preview", g(self.preview)),
            web.post(SCENE + "/{scene_variant_id}/promote", g(self.promote)),
            web.post(PREFIX + "/{presentation_id}/scene-variants/preview/cancel", g(self.cancel_preview)),
        ]

    @property
    def _scene_variants(self):
        return self._core.presentation_studio_scene_variants

    @staticmethod
    async def _small_body(request: web.Request, *, optional: bool = False) -> object:
        _only(request, set())
        if optional and (not request.can_read_body or request.content_length == 0):
            return {}
        return loads_strict_json(await read_bounded(request.content, MAX_SCENE_VARIANT_BODY_BYTES),
                                 invalid_message="body must be JSON")

    async def describe(self, request: web.Request) -> web.Response:
        _only(request, set())
        info = request.match_info
        return web.json_response(await self._scene_variants.describe(
            info["presentation_id"], info["variant_id"], info["scene_id"]))

    async def preview(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._scene_variants.preview(
            info["presentation_id"], info["variant_id"], info["scene_id"], info["scene_variant_id"],
            await self._small_body(request, optional=True)))

    async def cancel_preview(self, request: web.Request) -> web.Response:
        return web.json_response(await self._scene_variants.cancel_preview(
            request.match_info["presentation_id"], await self._small_body(request, optional=True)))

    async def promote(self, request: web.Request) -> web.Response:
        info = request.match_info
        answer = await self._scene_variants.promote(
            info["presentation_id"], info["variant_id"], info["scene_id"], info["scene_variant_id"],
            await self._small_body(request))
        return web.json_response(answer, status=201)
