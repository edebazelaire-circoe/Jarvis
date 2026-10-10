"""Relais Control Center de l'essai d'une version plus recente (handoff jarvis-remotion-presentation-integration, Slice 19).

Core possede l'avis et l'essai (`jarvis/protocol/presentation_studio_upgrades_routes.py`, `PresentationStudioUpgrades`, seule autorite).
Meme mecanique que `presentation_studio_template_relay.py` : statut et JSON de Core rendus tels quels, erreurs comprises ; le corps
d'une ecriture est un objet JSON et son `actor` est **remplace** par `user`.

| Control Center | Core |
| --- | --- |
| `GET /api/presentation-studio/presentations/{id}/variants/{vid}/upgrades` | idem ; n'ecrit rien |
| `POST .../variants/{vid}/upgrades/try` | idem, **`actor` force a `user`** (201) |

Le journal (`presentation_studio.request.relayed`) note l'action, le statut et le code, jamais un titre ni une valeur.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.runtime.presentation_studio_relay import CORE_PREFIX, STUDIO_ROUTE, PresentationStudioRelayRoutes

UPGRADES_PATH = "/{presentation_id}/variants/{variant_id}/upgrades"
MAX_UPGRADE_BODY_BYTES = 8 * 1024


class PresentationStudioUpgradesRelayRoutes(PresentationStudioRelayRoutes):
    """Relais de l'avis et de l'essai -> Core. Voir l'en-tete."""

    MAX_BODY_BYTES = MAX_UPGRADE_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get(STUDIO_ROUTE + UPGRADES_PATH, self._relay("studio_upgrades", CORE_PREFIX + UPGRADES_PATH)),
            web.post(STUDIO_ROUTE + UPGRADES_PATH + "/try", self._forced(UPGRADES_PATH + "/try", "studio_upgrade_try")),
        ]
