"""Routes HTTP de Core : nouvelle version d'un prefab epingle et essai en variante (handoff jarvis-remotion-presentation-integration,
Slice 19). Meme garde, memes enveloppes d'erreur et meme jeton porteur que `presentation_studio_routes.py` ; logique dans
`jarvis/core/presentation_studio_upgrades.py`. Contrat : `docs/presentation-studio.md` > *Newer prefab versions and trial variants*.

| Methode | Route | Corps -> reponse |
| --- | --- | --- |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/upgrades` | `{notices: [{scene_id, prefab_id, pinned_version, latest_version, newer_versions, fits, problem, engine_ok, latest_catalog, trials}], count, unavailable, trials, auto_upgrade: false}` ; **n'ecrit rien** |
| POST | `.../variants/{variant_id}/upgrades/try` | `{scene_id, version?, title?, actor?, expected_variant_revision?}` -> 201 la reponse de branche de la Slice 16 plus `{trial: true, adopted: false, scene_id, from, to}` |

`actor` : `user` (defaut) ou `brain` ; le relais du Control Center le **force** a `user`. Refus : l'enveloppe `{"error": {"code", "message"}}`.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

#: Un corps d'essai est minuscule (une scene, une version, un titre).
MAX_UPGRADE_BODY_BYTES = 8 * 1024
UPGRADES = PREFIX + "/{presentation_id}/variants/{variant_id}/upgrades"


class PresentationStudioUpgradesRoutes(PresentationStudioProtocolRoutes):
    """Les routes ci-dessus. Voir l'en-tete."""

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [web.get(UPGRADES, g(self.notices)), web.post(UPGRADES + "/try", g(self.try_version))]

    @property
    def _upgrades(self):
        return self._core.presentation_studio_upgrades

    async def notices(self, request: web.Request) -> web.Response:
        _only(request, set())
        info = request.match_info
        return web.json_response(await self._upgrades.notices(info["presentation_id"], info["variant_id"]))

    async def try_version(self, request: web.Request) -> web.Response:
        _only(request, set())
        body = loads_strict_json(await read_bounded(request.content, MAX_UPGRADE_BODY_BYTES), invalid_message="body must be JSON")
        info = request.match_info
        return web.json_response(await self._upgrades.try_version(info["presentation_id"], info["variant_id"], body), status=201)
