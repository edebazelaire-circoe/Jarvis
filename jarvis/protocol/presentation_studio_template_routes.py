"""Routes HTTP de Core : promotion et instanciation de modeles (handoff jarvis-interactive-presentation-studio, Slice 20).

Meme garde, memes enveloppes d'erreur et meme jeton porteur que `presentation_studio_routes.py` (dont cette classe herite la frontiere) ;
logique dans `jarvis/core/presentation_studio_template.py`. Contrat : `docs/presentation-studio.md` > *Template and prefab promotion
contract*.

| Methode | Route | Corps -> reponse |
| --- | --- | --- |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/templates/plan` | `{kind, title, slug, scenes?, art_direction?, ...}` -> 200 le plan (`ok`, `scenes`, `findings`, `would_publish`) ; **n'ecrit rien** |
| POST | `.../variants/{variant_id}/templates` | meme corps, selection obligatoire -> 201 `{template_id, template, prefabs, scenes, parameters, findings, derived_from}` |
| GET | `/v1/presentation-studio/templates[?kind=]` | `{templates: [resume], count, problems, limit}` |
| GET | `/v1/presentation-studio/templates/{template_id}` | `{template, summary, prefab_availability}` |
| POST | `/v1/presentation-studio/templates/{template_id}/instantiate` | `{actor?, title?, presentation_id?, variant_id?, expected_revision?}` -> 201 selon le genre |

`actor` : `user` (defaut) ou `brain` ; le relais du Control Center le **force** a `user`. Refus : l'enveloppe `{"error": {"code", "message"}}`.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

TEMPLATES_PREFIX = "/v1/presentation-studio/templates"
#: Un corps de promotion : jusqu'a 64 scenes avec deux listes d'ids de controle (32 chacune).
MAX_TEMPLATE_BODY_BYTES = 128 * 1024
VARIANT = PREFIX + "/{presentation_id}/variants/{variant_id}/templates"


class PresentationStudioTemplateRoutes(PresentationStudioProtocolRoutes):
    """Les routes ci-dessus. Voir l'en-tete."""

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.post(VARIANT + "/plan", g(self.plan)),
            web.post(VARIANT, g(self.promote)),
            web.get(TEMPLATES_PREFIX, g(self.list_templates)),
            web.get(TEMPLATES_PREFIX + "/{template_id}", g(self.get_template)),
            web.post(TEMPLATES_PREFIX + "/{template_id}/instantiate", g(self.instantiate)),
        ]

    @property
    def _templates(self):
        return self._core.presentation_studio_templates

    @staticmethod
    async def _json_body(request: web.Request, *, optional: bool = False) -> object:
        _only(request, set())
        if optional and (not request.can_read_body or request.content_length == 0):
            return {}
        return loads_strict_json(await read_bounded(request.content, MAX_TEMPLATE_BODY_BYTES), invalid_message="body must be JSON")

    async def plan(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._templates.plan(info["presentation_id"], info["variant_id"],
                                                            await self._json_body(request)))

    async def promote(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._templates.promote(info["presentation_id"], info["variant_id"],
                                                               await self._json_body(request)), status=201)

    async def list_templates(self, request: web.Request) -> web.Response:
        _only(request, {"kind"})
        return web.json_response(await self._templates.list_templates(request.query.get("kind")))

    async def get_template(self, request: web.Request) -> web.Response:
        _only(request, set())
        return web.json_response(await self._templates.get_template(request.match_info["template_id"]))

    async def instantiate(self, request: web.Request) -> web.Response:
        return web.json_response(await self._templates.instantiate(
            request.match_info["template_id"], await self._json_body(request, optional=True)), status=201)
