"""Routes HTTP de Core : le planificateur d'ecriture (handoff jarvis-interactive-presentation-studio, Slice 11).

Meme garde, memes enveloppes d'erreur et meme jeton porteur que `presentation_studio_routes.py` (dont cette classe herite la
frontiere) ; logique dans `jarvis/core/presentation_studio_authoring.py` (`core.presentation_studio_authoring`, seule autorite).
Contrat : `docs/presentation-studio.md` > *Authoring contract (Slice 11)*.

| Methode | Route | Corps -> reponse |
| --- | --- | --- |
| POST | `/v1/presentation-studio/authoring/check` | `{actor?, brief, draft}` -> 200 `{status: "checked", ok, workflow, report}` ; **n'ecrit ni ne publie rien** (un rapport `ok: false` est un 200 : le brouillon est juge, pas la requete) |
| POST | `/v1/presentation-studio/authoring/assemble` | meme corps -> 201 `{status: "delivered", workflow, presentation_id, active_variant_id, variants, scenes, prefabs, report, provenance}` ; si la porte de qualite refuse : 400 `{status: "refused", workflow, report, error: {code: "presentation_studio_draft_refused", message}}` et **rien n'est ecrit** |
| GET | `/v1/presentation-studio/authoring/reconcile` | 200 `{pins_known, studio_prefab_versions, unreferenced_prefabs, unreferenced_count, truncated, unreadable_presentations}` ; lecture seule, **jamais relaye** a la page : ce qu'un assemblage interrompu peut laisser (versions de prefab que rien n'epingle, dossiers illisibles), rien n'est adopte ni supprime |

`actor` : `user` (defaut) ou `brain` ; le relais du Control Center le **force** a `user` (Core n'accepte `brain` que par la couche
d'outils de la Slice 21). Un corps mal forme (pas du JSON, plus de 4 Mio, cle inconnue de l'enveloppe) est un 400
`invalid_request` / `presentation_studio_invalid`. Les problemes du *contenu* du brouillon (schema, prefab, references) ne sont
jamais une erreur HTTP : ce sont des `failures` du rapport, tous listes.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.domain.presentation_studio_authoring import MAX_AUTHORING_BODY_BYTES
from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PresentationStudioProtocolRoutes

AUTHORING_PREFIX = "/v1/presentation-studio/authoring"


class PresentationStudioAuthoringRoutes(PresentationStudioProtocolRoutes):
    """Les routes ci-dessus. Voir l'en-tete."""

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [web.post(AUTHORING_PREFIX + "/check", g(self.authoring_check)),
                web.post(AUTHORING_PREFIX + "/assemble", g(self.authoring_assemble)),
                web.get(AUTHORING_PREFIX + "/reconcile", g(self.authoring_reconcile))]

    @property
    def _authoring(self):  # noqa: ANN202 - the Core service, resolved at call time (it is built with the application)
        return self._core.presentation_studio_authoring

    async def authoring_check(self, request: web.Request) -> web.Response:
        outcome = await self._authoring.check(await self._body(request, MAX_AUTHORING_BODY_BYTES))
        return web.json_response(outcome.to_dict(), status=outcome.http_status)

    async def authoring_reconcile(self, request: web.Request) -> web.Response:
        """Read-only report of what an interrupted assembly can leave (unreferenced prefab versions, unreadable folders). Not relayed."""

        _only(request, set())
        return web.json_response(await self._authoring.reconcile())

    async def authoring_assemble(self, request: web.Request) -> web.Response:
        """A refusal of the gate is a complete result with its status (400), not a bare envelope: the brain needs the report."""

        outcome = await self._authoring.assemble(await self._body(request, MAX_AUTHORING_BODY_BYTES))
        return web.json_response(outcome.to_dict(), status=outcome.http_status)
