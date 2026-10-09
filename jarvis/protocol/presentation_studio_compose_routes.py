"""Routes HTTP de Core : comparaison et composition de variantes (handoff jarvis-interactive-presentation-studio, Slice 19).

Meme garde, memes enveloppes d'erreur et meme jeton porteur que `presentation_studio_routes.py` (dont cette classe herite la
frontiere). Logique dans `jarvis/core/presentation_studio_compare.py` (etat d'interface en memoire, aucune ecriture de variante)
et `jarvis/core/presentation_studio_composition.py` (une variante enfant, sources immuables). Contrat :
`docs/presentation-studio.md` > *Comparison and semantic composition contract*.

| Methode | Route (sous `/v1/presentation-studio/presentations/{presentation_id}`) | Corps -> reponse |
| --- | --- | --- |
| GET | `/compare` | la vue de l'ensemble de comparaison |
| POST | `/compare/select` | `{variant_ids: [2 ou 4], pair?, mode?, expected_revision?}` -> la vue |
| POST | `/compare/pair` | `{pair: [a, b] ou null, expected_revision?}` -> la vue |
| POST | `/compare/mode` | `{mode: "sync"/"independent", expected_revision?}` -> la vue |
| POST | `/compare/navigate` | `{variant_id, scene_id ou step, expected_revision?}` -> la vue + `navigation` |
| POST | `/compare/links` et `/compare/links/remove` | `{a: {variant_id, scene_id}, b: {...}, expected_revision?}` -> la vue |
| POST | `/compare/clear` | `{expected_revision?}` -> `{presentation_id, cleared, active: false, revision}` |
| POST | `/compositions/plan` | corps d'une composition -> `{ok, dry_run, conflicts, composition}` ; n'ecrit rien |
| POST | `/compositions` | corps d'une composition -> 201 reponse d'une branche + `composition` ; conflits : 409 `presentation_studio_composition_refused` avec `error.conflicts` |
| GET | `/variants/{variant_id}/composition` | `{composition}` : la provenance ecrite (404 `presentation_studio_unknown_composition`) |
"""

from __future__ import annotations

from aiohttp import web

from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

#: Le corps d'une comparaison est minuscule ; celui d'une composition porte au plus quatre tranches de 64 ids de scene.
MAX_COMPARE_BODY_BYTES = 16 * 1024
MAX_COMPOSE_BODY_BYTES = 64 * 1024


class PresentationStudioComposeRoutes(PresentationStudioProtocolRoutes):
    """Les routes ci-dessus. Voir l'en-tete."""

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        base = PREFIX + "/{presentation_id}"
        return [
            web.get(base + "/compare", g(self.compare_view)),
            web.post(base + "/compare/select", g(self.compare_select)),
            web.post(base + "/compare/pair", g(self.compare_pair)),
            web.post(base + "/compare/mode", g(self.compare_mode)),
            web.post(base + "/compare/navigate", g(self.compare_navigate)),
            web.post(base + "/compare/links", g(self.compare_link)),
            web.post(base + "/compare/links/remove", g(self.compare_unlink)),
            web.post(base + "/compare/clear", g(self.compare_clear)),
            web.post(base + "/compositions/plan", g(self.composition_plan)),
            web.post(base + "/compositions", g(self.composition_create)),
            web.get(base + "/variants/{variant_id}/composition", g(self.composition_get)),
        ]

    @property
    def _compare(self):
        return self._core.presentation_studio_compare

    @property
    def _composition(self):
        return self._core.presentation_studio_composition

    @staticmethod
    async def _json_body(request: web.Request, limit: int = MAX_COMPARE_BODY_BYTES, *, optional: bool = False) -> object:
        _only(request, set())
        if optional and (not request.can_read_body or request.content_length == 0):
            return {}
        return loads_strict_json(await read_bounded(request.content, limit), invalid_message="body must be JSON")

    async def compare_view(self, request: web.Request) -> web.Response:
        _only(request, set())
        return web.json_response(await self._compare.view(request.match_info["presentation_id"]))

    async def compare_select(self, request: web.Request) -> web.Response:
        return web.json_response(await self._compare.select(request.match_info["presentation_id"], await self._json_body(request)))

    async def compare_pair(self, request: web.Request) -> web.Response:
        return web.json_response(await self._compare.set_pair(request.match_info["presentation_id"], await self._json_body(request)))

    async def compare_mode(self, request: web.Request) -> web.Response:
        return web.json_response(await self._compare.set_mode(request.match_info["presentation_id"], await self._json_body(request)))

    async def compare_navigate(self, request: web.Request) -> web.Response:
        return web.json_response(await self._compare.navigate(request.match_info["presentation_id"], await self._json_body(request)))

    async def compare_link(self, request: web.Request) -> web.Response:
        return web.json_response(await self._compare.link(request.match_info["presentation_id"], await self._json_body(request)))

    async def compare_unlink(self, request: web.Request) -> web.Response:
        return web.json_response(await self._compare.unlink(request.match_info["presentation_id"], await self._json_body(request)))

    async def compare_clear(self, request: web.Request) -> web.Response:
        return web.json_response(await self._compare.clear(
            request.match_info["presentation_id"], await self._json_body(request, optional=True)))

    async def composition_plan(self, request: web.Request) -> web.Response:
        return web.json_response(await self._composition.plan(
            request.match_info["presentation_id"], await self._json_body(request, MAX_COMPOSE_BODY_BYTES)))

    async def composition_create(self, request: web.Request) -> web.Response:
        answer = await self._composition.compose(
            request.match_info["presentation_id"], await self._json_body(request, MAX_COMPOSE_BODY_BYTES))
        return web.json_response(answer, status=201)

    async def composition_get(self, request: web.Request) -> web.Response:
        _only(request, set())
        info = request.match_info
        return web.json_response(await self._composition.provenance(info["presentation_id"], info["variant_id"]))
