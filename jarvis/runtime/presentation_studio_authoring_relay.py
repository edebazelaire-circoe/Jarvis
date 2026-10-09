"""Relais Control Center du planificateur d'ecriture (handoff jarvis-interactive-presentation-studio, Slice 11).

Core possede le planificateur (`jarvis/protocol/presentation_studio_authoring_routes.py`, `PresentationStudioAuthoring`, seule
autorite). Le Control Center n'en garde **rien** : meme mecanique que `presentation_studio_relay.py` (statut et JSON de Core
rendus tels quels, un brouillon `refused` compris ; Core injoignable 503, delai 504), meme garde de lecture
(`/api/presentation-studio` est dans `READ_GUARDED_ROUTES` : un cadre de prefab, `Origin: null`, ne peut rien appeler ici).

| Control Center | Core |
| --- | --- |
| `POST /api/presentation-studio/authoring/check` | `POST /v1/presentation-studio/authoring/check`, **`actor` force a `user`** ; n'ecrit rien |
| `POST /api/presentation-studio/authoring/assemble` | `POST /v1/presentation-studio/authoring/assemble`, **`actor` force a `user`** |
| `POST /api/presentation-studio/authoring/finalize` | `POST /v1/presentation-studio/authoring/finalize`, **`actor` force a `user`** |

Le corps doit etre un objet JSON (plafond `MAX_AUTHORING_BODY_BYTES`, celui de Core : un brouillon porte des sources de prefab) ;
son `actor` est **remplace** par `user`, quoi qu'il dise : la page de l'utilisateur ne parle jamais au nom du cerveau, et Core
n'accepte `brain` que par la couche d'outils de la Slice 21. Le journal (`presentation_studio.request.relayed`) note l'action, le
statut HTTP, le `status` du resultat et son code, jamais un titre, une phrase ni une valeur du brouillon.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.domain.presentation_studio_authoring import MAX_AUTHORING_BODY_BYTES
from jarvis.protocol.client import AUTHORING_PREFIX
from jarvis.runtime.presentation_studio_relay import PresentationStudioRelayRoutes

AUTHORING_ROUTE = "/api/presentation-studio/authoring"
#: (chemin relatif, action journalisee). Toutes a acteur force `user`.
_PATHS = (("/check", "studio_authoring_check"), ("/assemble", "studio_authoring_assemble"),
          ("/finalize", "studio_authoring_finalize"))


class PresentationStudioAuthoringRelayRoutes(PresentationStudioRelayRoutes):
    """Relais `/api/presentation-studio/authoring/*` -> Core. Voir l'en-tete."""

    MAX_BODY_BYTES = MAX_AUTHORING_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [web.post(AUTHORING_ROUTE + path, self._forced(path, action, prefix=AUTHORING_PREFIX)) for path, action in _PATHS]
