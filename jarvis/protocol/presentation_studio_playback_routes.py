"""Routes HTTP de Core : lecture d'une Presentation du Studio (handoff jarvis-interactive-presentation-studio, Slice 12).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ; logique dans
`jarvis/core/presentation_studio_playback.py`. L'état de la lecture est **en mémoire** (R6) : ces routes ne lisent ni
n'écrivent une Presentation, sauf `edit`, qui passe par l'API d'édition de la Slice 05. Contrat :
`docs/presentation-studio.md` › *Playback runtime contract*.

| Méthode | Route | Corps -> réponse |
| --- | --- | --- |
| GET | `/v1/presentation-studio/playback` | `{state}` : « où en est-on » borné (ou `{phase: idle, running: false}`) |
| POST | `/v1/presentation-studio/playback/{verb}` | `verb` parmi `start stop pause resume next previous goto detour return reveal hide edit` ; corps à clés exactes, `actor` obligatoire -> `{status: applied, command, state, ...}` 200 ; `refused` 409 (`reason` = code stable de la machine) ; `stage_failed` 500 (la fenêtre n'a pas suivi : l'état dit pourquoi) |
| GET | `/v1/presentation-studio/playback/armed` | **suiveur de cues (Slice 13)** : `{run_id, generation, expires_in_s, cues: [{cue_id, phrases, semantics}], ambiguous}` ; une lecture renouvelle l'autorité du suiveur ; **non relayée** à la page |
| POST | `/v1/presentation-studio/cues/satisfied` | corps exact `{run_id, generation, cue_id}` (aucun texte) -> `{status: fired}` 200 ; `{status: refused, code}` 409 (`stale_run`, `stale_generation`, `armed_set_expired`, `cue_not_armed`) ou 429 (`rate_limited`) ; un doublon rend la même réponse + `duplicate: true` |

Refus : enveloppe `{"error": {"code", "message"}}` comme les routes des Presentations (`presentation_studio_*`, `invalid_request` 400
pour un corps mal formé ou un champ inattendu, `core_unavailable` 503, `internal_error` 500 journalisé).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.capture_api import redact_paths
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_edit import MAX_EDIT_BODY_BYTES
from jarvis.domain.presentation_studio_playback_requests import Verb
from jarvis.protocol.capture_routes import _only, error_response
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PLAYBACK = "/v1/presentation-studio/playback"
CUES = "/v1/presentation-studio/cues/satisfied"


class PresentationStudioPlaybackRoutes:
    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [web.get(PLAYBACK, g(self.state)), web.get(PLAYBACK + "/armed", g(self.armed)),
                web.post(PLAYBACK + "/{verb}", g(self.command)), web.post(CUES, g(self.cue_satisfied))]

    @property
    def _service(self) -> Any:
        return self._core.presentation_studio_playback

    def _guarded(self, handler: Handler) -> Handler:
        async def run(request: web.Request) -> web.StreamResponse:
            try:
                if not self._core.health.ready:
                    return error_response(503, "core_unavailable", "core is not ready")
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except PresentationStudioError as exc:
                return error_response(exc.status, exc.code.value, exc.message)
            except ValueError as exc:
                return error_response(400, "invalid_request", redact_paths(str(exc)))
            except Exception as exc:  # noqa: BLE001 - boundary: recorded with its real cause, answered coded
                try:
                    self._core.presentation_studio.report_unexpected(
                        f"{request.method} {request.match_info.route.resource.canonical}", exc)
                except Exception:  # noqa: BLE001 - intentional: reporting must never mask the coded answer
                    pass
                return error_response(500, "internal_error", f"unexpected {type(exc).__name__}; see the Error Logs")

        return run

    @staticmethod
    async def _body(request: web.Request) -> object:
        _only(request, set())
        raw = await read_bounded(request.content, MAX_EDIT_BODY_BYTES)
        return loads_strict_json(raw, invalid_message="body must be JSON")

    async def state(self, request: web.Request) -> web.Response:
        _only(request, set())
        return web.json_response({"state": self._service.where()})

    async def armed(self, request: web.Request) -> web.Response:
        _only(request, set())
        return web.json_response(self._service.armed_set())

    async def command(self, request: web.Request) -> web.Response:
        try:
            verb = Verb(request.match_info["verb"])
        except ValueError:
            return error_response(404, "invalid_request", "unknown playback command")
        method = {Verb.RETURN: "back_from_detour"}.get(verb, verb.value)
        result = await getattr(self._service, method)(await self._body(request))
        return web.json_response(result.to_dict(), status=result.http_status)

    async def cue_satisfied(self, request: web.Request) -> web.Response:
        answer = dict(await self._service.report_cue(await self._body(request)))
        return web.json_response(answer, status=answer.pop("http_status", 200))
