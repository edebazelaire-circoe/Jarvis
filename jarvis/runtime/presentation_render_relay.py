"""Relais du Control Center vers Core pour l'export d'une présentation gelée (jarvis-remotion-presentation-integration, Slice 16).

Core possède le rendu (`docs/remotion-render.md`) ; le Control Center n'en garde rien. Ces routes relaient telles quelles vers Core (statut
et JSON, erreurs comprises) ; c'est le gestionnaire Sessions & Boards (`control_center_workspace.js`, vue Artefacts d'un Board) qui les appelle.

| Control Center | Core | Délai |
| --- | --- | --- |
| `GET /api/local-capabilities/remotion/render` | `GET /v1/local-capabilities/remotion/render` | 10 s |
| `GET /api/local-capabilities/remotion/render/jobs` | `GET .../render/jobs` | 10 s |
| `POST /api/local-capabilities/remotion/render/jobs` | `POST .../render/jobs` | 60 s (relecture et vérification du paquet) |
| `GET /api/local-capabilities/remotion/render/jobs/{job_id}` | `GET .../render/jobs/{job_id}` | 10 s |
| `POST /api/local-capabilities/remotion/render/jobs/{job_id}/cancel` | `POST .../jobs/{job_id}/cancel` | 40 s |

Seules ces cinq adresses existent. Toutes sont gardées (Host et origine de boucle locale, `READ_GUARDED_ROUTES`, préfixe `/api/local-capabilities`) :
elles lancent un processus. Mêmes refus codés, mêmes erreurs de Core injoignable ou trop lent que le relais du Studio. Journal :
`presentation_render.relayed` pour chaque écriture (jamais un corps).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiohttp import web

from jarvis.runtime.remotion_studio_relay import (
    CAPABILITY_ROUTE, CORE_CAPABILITY, MAX_BODY_BYTES, READ_TIMEOUT_S, SHORT_TIMEOUT_S, RemotionStudioRelayRoutes, _envelope,
)

RENDER_ROUTE = CAPABILITY_ROUTE + "/render"
CORE_RENDER = CORE_CAPABILITY + "/render"
CREATE_TIMEOUT_S = 60.0


class PresentationRenderRelayRoutes(RemotionStudioRelayRoutes):
    def routes(self) -> list[web.RouteDef]:
        jobs = RENDER_ROUTE + "/jobs"
        return [web.get(RENDER_ROUTE, self._read(CORE_RENDER)), web.get(jobs, self._read(CORE_RENDER + "/jobs")),
                web.get(jobs + "/{job_id}", self._read_job()), web.post(jobs, self._create()),
                web.post(jobs + "/{job_id}/cancel", self._cancel())]

    def _read_job(self) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            if request.query:
                return _envelope(400, "presentation_render_invalid", "unexpected query parameters")
            status, payload = await self._forward("GET", f"{CORE_RENDER}/jobs/{request.match_info['job_id']}", action="read",
                                                  timeout_s=READ_TIMEOUT_S)
            return self._answer(status, payload)
        return handler

    def _write(self, action: str, timeout_s: float, core_path_of: Callable[[web.Request], str] | None = None
               ) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            if request.query:
                return _envelope(400, "presentation_render_invalid", "unexpected query parameters")
            body = await request.read() if request.can_read_body else b""
            if len(body) > MAX_BODY_BYTES * 4:
                return _envelope(400, "presentation_render_invalid", "the request body is too large")
            status, payload = await self._forward("POST", core_path_of(request) if core_path_of else CORE_RENDER + "/jobs", action=action,
                                                  body=body or None, timeout_s=timeout_s)
            error = payload.get("error") if isinstance(payload, dict) else None
            job = payload.get("job") if isinstance(payload, dict) else None
            self._journal.emit("presentation_render.relayed", f"Export de présentation : {action} relayé à Core (HTTP {status})",
                               level="info" if status < 400 else "warning",
                               data={"action": action, "status": status, "code": error.get("code") if isinstance(error, dict) else None,
                                     "job_state": job.get("state") if isinstance(job, dict) else None,
                                     "job_id": job.get("job_id") if isinstance(job, dict) else None})
            return self._answer(status, payload)
        return handler

    def _create(self) -> Callable[[web.Request], Awaitable[web.Response]]:
        return self._write("create", CREATE_TIMEOUT_S)

    def _cancel(self) -> Callable[[web.Request], Awaitable[web.Response]]:
        return self._write("cancel", SHORT_TIMEOUT_S, lambda request: f"{CORE_RENDER}/jobs/{request.match_info['job_id']}/cancel")
