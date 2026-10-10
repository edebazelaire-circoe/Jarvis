"""Relais Control Center des modeles de presentation (handoff jarvis-interactive-presentation-studio, Slice 20).

Core possede la promotion (`jarvis/protocol/presentation_studio_template_routes.py`, `PresentationStudioTemplates`, seule autorite). Meme
mecanique que `presentation_studio_relay.py` : statut et JSON de Core rendus tels quels, erreurs comprises ; le corps d'une ecriture est un
objet JSON et son `actor` est **remplace** par `user` (la page de l'utilisateur ne parle jamais au nom du cerveau).

| Control Center | Core |
| --- | --- |
| `POST /api/presentation-studio/presentations/{id}/variants/{vid}/templates/plan` | idem, **`actor` force a `user`** ; n'ecrit rien |
| `POST .../variants/{vid}/templates` | idem, **`actor` force a `user`** (201) |
| `GET /api/presentation-studio/templates[?kind=]` | `GET /v1/presentation-studio/templates` |
| `GET /api/presentation-studio/templates/{template_id}` | idem |
| `POST /api/presentation-studio/templates/{template_id}/instantiate` | idem, **`actor` force a `user`** (corps objet, `{}` si rien a dire) |

Le journal (`presentation_studio.request.relayed`) note l'action, le statut et le code, jamais un titre ni une valeur.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.runtime.presentation_studio_relay import CORE_PREFIX, STUDIO_ROUTE, PresentationStudioRelayRoutes

TEMPLATES_ROUTE = "/api/presentation-studio/templates"
CORE_TEMPLATES = "/v1/presentation-studio/templates"
PLAN_PATH = "/{presentation_id}/variants/{variant_id}/templates/plan"
PROMOTE_PATH = "/{presentation_id}/variants/{variant_id}/templates"
INSTANTIATE_PATH = "/{template_id}/instantiate"
MAX_TEMPLATE_BODY_BYTES = 128 * 1024


class PresentationStudioTemplateRelayRoutes(PresentationStudioRelayRoutes):
    """Relais des modeles -> Core. Voir l'en-tete."""

    MAX_BODY_BYTES = MAX_TEMPLATE_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [
            web.post(STUDIO_ROUTE + PLAN_PATH, self._forced(PLAN_PATH, "studio_template_plan")),
            web.post(STUDIO_ROUTE + PROMOTE_PATH, self._forced(PROMOTE_PATH, "studio_template_promote")),
            web.get(TEMPLATES_ROUTE, self._relay("studio_templates", CORE_TEMPLATES)),
            web.get(TEMPLATES_ROUTE + "/{template_id}", self._relay("studio_template", CORE_TEMPLATES + "/{template_id}")),
            web.post(TEMPLATES_ROUTE + INSTANTIATE_PATH,
                     self._forced(INSTANTIATE_PATH, "studio_template_instantiate", prefix=CORE_TEMPLATES)),
        ]
