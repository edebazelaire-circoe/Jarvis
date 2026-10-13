"""Routes HTTP de Core : le rail des presentations (masquer, archiver, renommer, etat de travail, demandes d'ecran).

Meme garde, memes enveloppes et meme jeton porteur que `presentation_studio_routes.py` ; logique dans
`jarvis/core/presentation_studio_rail.py` (`core.presentation_studio_rail`). Contrat : `docs/presentation-studio.md` > *Rail des presentations*.

| Methode | Route | Corps -> reponse |
| --- | --- | --- |
| GET | `/v1/presentation-studio/rail` | `{presentations: [{...resume, hidden, archived, work: {state, label, age_s, code?, message?}}], problems, work_revision, ui, playing}` ; masquees et archivees comprises (la page range), triees visibles puis masquees puis archivees |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/rail` | `{action: hide|show|archive|restore|rename|acknowledge, actor?: user|brain, confirmed?, title?}` -> `{presentation_id, action, changed, hidden, archived, restorable}` (`rename` : `{title, revision}`) ; `archive` par le cerveau sans `confirmed: true` : 400 `presentation_studio_confirmation_required` ; pendant sa lecture : 409 `presentation_studio_variant_in_playback` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/work` | `{event: begin|success|failure|ack, label?, code?, message?}` -> `{presentation_id, work}` (porte du cerveau, jamais relayee a la page) |
| POST | `/v1/presentation-studio/rail/display` | `{action: show_rail|hide_rail, presentation_id?}` -> `{seq, request, reported}` (demande d'ecran du cerveau, jamais relayee) |
| POST | `/v1/presentation-studio/rail/display-state` | `{rail_visible, variants_open, presentation_id, applied_seq?}` -> `{seq, request, reported}` (rapport de la page, relaye) |
"""

from __future__ import annotations

from aiohttp import web

from jarvis.protocol.capture_routes import _only
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

RAIL_ROUTE = "/v1/presentation-studio/rail"
MAX_RAIL_BODY_BYTES = 4 * 1024


class PresentationStudioRailRoutes(PresentationStudioProtocolRoutes):
    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(RAIL_ROUTE, g(self.overview)),
            web.post(RAIL_ROUTE + "/display", g(self.display)),
            web.post(RAIL_ROUTE + "/display-state", g(self.display_state)),
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
