"""Routes HTTP de Core : le rail des presentations (masquer, archiver, renommer, etat de travail, demandes d'ecran, purge des archivees).

Meme garde, memes enveloppes et meme jeton porteur que `presentation_studio_routes.py` ; logique dans
`jarvis/core/presentation_studio_rail.py` (`core.presentation_studio_rail`). Contrat : `docs/presentation-studio.md` > *Rail des presentations*.

| Methode | Route | Corps -> reponse |
| --- | --- | --- |
| GET | `/v1/presentation-studio/rail` | `{presentations: [{...resume, hidden, archived, work: {state, label, age_s, code?, message?}, unreviewed: {since, label} or null, preview: {artifact_id, kind: presentation_still, width, height} or null, type: {engine}}], problems, work_revision, ui, playing}` ; masquees et archivees comprises (la page range), triees visibles puis masquees puis archivees ; `unreviewed` est `null` en `problem` ; `preview` se lit par `/v1/artifacts/{id}/payload` (jamais un chemin) |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/rail` | `{action: hide|show|archive|restore|rename|acknowledge|review, actor?: user|brain, confirmed?, title?}` -> `{presentation_id, action, changed, hidden, archived, restorable}` (`rename` : `{title, revision}` ; `review` : acteur `user` seulement, efface `unreviewed`, 400 pour le cerveau) ; `archive` par le cerveau sans `confirmed: true` : 400 `presentation_studio_confirmation_required` ; pendant sa lecture : 409 `presentation_studio_variant_in_playback` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/work` | `{event: begin|success|failure|ack, label?, code?, message?}` -> `{presentation_id, work}` (porte du cerveau, jamais relayee a la page ; `success` pose `unreviewed` dans `rail.json`) |
| POST | `/v1/presentation-studio/rail/display` | `{action: show_rail|hide_rail, presentation_id?}` -> `{seq, request, reported}` (demande d'ecran du cerveau, jamais relayee) |
| POST | `/v1/presentation-studio/rail/display-state` | `{rail_visible, variants_open, presentation_id, applied_seq?}` -> `{seq, request, reported}` (rapport de la page, relaye) |
| POST | `/v1/presentation-studio/rail/purge-plan` | `{presentation_ids?, actor?}` (corps facultatif) -> `{plan: {presentations: [{presentation_id, title, archived_at, revision, variants, archived_variants, scores, art_directions, compositions, snapshots, renders, prefabs}], count, totals, blocked, notes, irreversible: true, backup}, confirmation: "ppk_..." or null, expires_in_s}` ; **n'ecrit rien** ; une presentation du filtre non archivee : 409 `presentation_studio_not_archived` |
| POST | `/v1/presentation-studio/rail/purge` | `{confirmation, confirmed: true, presentation_ids?, actor?}` -> `{purged: [...], count, deleted: {presentations, variants, artifacts, prefabs, files}, backup: "backups/purge-presentations-<horodatage>", failed, orphan_folders, blocked, notes, forget_failed, complete}` ; sans `confirmed: true` ou sans jeton : 400 `presentation_studio_confirmation_required` ; ensemble change ou jeton expire : 409 `presentation_studio_confirmation_stale` ; sauvegarde impossible : 500 `presentation_studio_storage_io` (rien n'est efface). Logique : `jarvis/core/presentation_studio_purge.py` |
"""

from __future__ import annotations

from aiohttp import web

from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

RAIL_ROUTE = "/v1/presentation-studio/rail"
MAX_RAIL_BODY_BYTES = 4 * 1024
#: Purge : un filtre d'au plus 256 ids (`MAX_PURGE_IDS`) et un jeton.
MAX_PURGE_BODY_BYTES = 24 * 1024


class PresentationStudioRailRoutes(PresentationStudioProtocolRoutes):
    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(RAIL_ROUTE, g(self.overview)),
            web.post(RAIL_ROUTE + "/display", g(self.display)),
            web.post(RAIL_ROUTE + "/display-state", g(self.display_state)),
            web.post(RAIL_ROUTE + "/purge-plan", g(self.purge_plan)),
            web.post(RAIL_ROUTE + "/purge", g(self.purge)),
            web.post(PREFIX + "/{presentation_id}/rail", g(self.act)),
            web.post(PREFIX + "/{presentation_id}/work", g(self.work)),
        ]

    @property
    def _rail(self):
        return self._core.presentation_studio_rail

    @staticmethod
    async def _small(request: web.Request) -> object:
        _only(request, set())
        return loads_strict_json(await read_bounded(request.content, MAX_RAIL_BODY_BYTES), invalid_message="body must be JSON")

    @staticmethod
    async def _purge_body(request: web.Request, *, optional: bool) -> object:
        _only(request, set())
        if optional and (not request.can_read_body or request.content_length == 0):
            return {}
        return loads_strict_json(await read_bounded(request.content, MAX_PURGE_BODY_BYTES), invalid_message="body must be JSON")

    async def purge_plan(self, request: web.Request) -> web.Response:
        return web.json_response(await self._core.presentation_studio_purge.plan(await self._purge_body(request, optional=True)))

    async def purge(self, request: web.Request) -> web.Response:
        return web.json_response(await self._core.presentation_studio_purge.purge(await self._purge_body(request, optional=False)))

    async def overview(self, request: web.Request) -> web.Response:
        _only(request, set())
        return web.json_response(await self._rail.overview())

    async def act(self, request: web.Request) -> web.Response:
        return web.json_response(await self._rail.act(request.match_info["presentation_id"], await self._small(request)))

    async def work(self, request: web.Request) -> web.Response:
        return web.json_response(await self._rail.report_work(request.match_info["presentation_id"], await self._small(request)))

    async def display(self, request: web.Request) -> web.Response:
        return web.json_response(self._rail.request_ui(await self._small(request)))

    async def display_state(self, request: web.Request) -> web.Response:
        return web.json_response(self._rail.report_ui(await self._small(request)))
