"""Routes HTTP de Core : le graphe des variantes (handoff jarvis-interactive-presentation-studio, Slice 16).

Même garde, mêmes enveloppes d'erreur et même jeton porteur que `presentation_studio_routes.py` (dont cette classe hérite
la frontière) ; logique dans `jarvis/core/presentation_studio_variants.py` (`core.presentation_studio_variants`, seule
autorité). Contrat : `docs/presentation-studio.md` › *Variant graph and operations contract*.

| Méthode | Route | Corps -> réponse |
| --- | --- | --- |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/graph[?archived=1&check=1]` | `{presentation_id, revision, variant_counter, active_variant_id, nodes: [...], archived_count, reconciliation}` ; `archived=1` ajoute les noeuds archivés ; `check=1` ajoute `check` (rapport complet en lecture seule, lit tous les fichiers) |
| POST | `.../presentations/{presentation_id}/variants` | `{title, rationale?, source_variant_id?, activate?, actor?, expected_revision?}` -> 201 `{variant, node, presentation_revision, activated, source_variant_id, linked}` |
| POST | `.../variants/{variant_id}/activate` | `{actor?, expected_revision?}` -> `{changed, active_variant_id, variant_number, presentation_revision}` |
| POST | `.../variants/{variant_id}/rename` | `{title, actor?, expected_revision?}` -> `{changed, variant_id, variant_number, title, revision}` |
| POST | `.../variants/{variant_id}/archive-plan` | `{activate_variant_id?, actor?, expected_revision?}` -> `{plan: {affected: [{variant_id, variant_number, title}], count, includes_active, requires_new_active, suggested_active, blocked, ...}, confirmation, expires_in_s}` ; **n'écrit rien** |
| POST | `.../variants/{variant_id}/archive` | `{confirmation, activate_variant_id?, actor?, expected_revision?}` -> `{archived: [...], count, batch_id, active_variant_id, presentation_revision, restorable}` ; sans jeton valide du plan *courant* : `presentation_studio_confirmation_required` 400 / `presentation_studio_confirmation_stale` 409 |
| POST | `.../variants/{variant_id}/restore` | `{with_descendants?, actor?, expected_revision?}` -> `{restored: [...], count, variant_id, variant_number, presentation_revision}` |

Le corps est facultatif (objet vide) pour `activate`, `archive-plan` et `restore`. `actor` : `user` (défaut) ou `brain` ; le
relais du Control Center le **force** à `user`. Refus : l'enveloppe `{"error": {"code", "message"}}` des autres routes du
Studio, avec les codes `presentation_studio_*` du domaine.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

#: Le corps d'une opération du graphe est minuscule (un titre, une raison, un jeton).
MAX_VARIANTS_BODY_BYTES = 16 * 1024
TRUE = frozenset({"1", "true", "yes"})
FALSE = frozenset({"0", "false", "no", ""})


def _flag(request: web.Request, name: str) -> bool:
    raw = request.query.get(name, "0").lower()
    if raw in TRUE:
        return True
    if raw in FALSE:
        return False
    raise ValueError(f"{name} must be 1 or 0")


class PresentationStudioVariantsRoutes(PresentationStudioProtocolRoutes):
    """Les routes ci-dessus. Voir l'en-tête."""

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        base = PREFIX + "/{presentation_id}"
        return [
            web.get(base + "/graph", g(self.graph)),
            web.post(base + "/variants", g(self.create_branch)),
            web.post(base + "/variants/{variant_id}/activate", g(self.activate)),
            web.post(base + "/variants/{variant_id}/rename", g(self.rename)),
            web.post(base + "/variants/{variant_id}/archive-plan", g(self.archive_plan)),
            web.post(base + "/variants/{variant_id}/archive", g(self.archive)),
            web.post(base + "/variants/{variant_id}/restore", g(self.restore)),
        ]

    @property
    def _variants(self):
        return self._core.presentation_studio_variants

    @staticmethod
    async def _small_body(request: web.Request, *, optional: bool = False) -> object:
        _only(request, set())
        if optional and (not request.can_read_body or request.content_length == 0):
            return {}
        return loads_strict_json(await read_bounded(request.content, MAX_VARIANTS_BODY_BYTES), invalid_message="body must be JSON")

    async def graph(self, request: web.Request) -> web.Response:
        _only(request, {"archived", "check"})
        presentation_id = request.match_info["presentation_id"]
        answer = await self._variants.graph(presentation_id, include_archived=_flag(request, "archived"))
        if _flag(request, "check"):
            answer["check"] = await self._variants.check(presentation_id)
        return web.json_response(answer)

    async def create_branch(self, request: web.Request) -> web.Response:
        answer = await self._variants.create_branch(request.match_info["presentation_id"], await self._small_body(request))
        return web.json_response(answer, status=201)

    async def activate(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._variants.switch(
            info["presentation_id"], info["variant_id"], await self._small_body(request, optional=True)))

    async def rename(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._variants.rename(
            info["presentation_id"], info["variant_id"], await self._small_body(request)))

    async def archive_plan(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._variants.plan_archive(
            info["presentation_id"], info["variant_id"], await self._small_body(request, optional=True)))

    async def archive(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._variants.archive(
            info["presentation_id"], info["variant_id"], await self._small_body(request)))

    async def restore(self, request: web.Request) -> web.Response:
        info = request.match_info
        return web.json_response(await self._variants.restore(
            info["presentation_id"], info["variant_id"], await self._small_body(request, optional=True)))
