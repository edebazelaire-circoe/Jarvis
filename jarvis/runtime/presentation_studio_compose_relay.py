"""Relais Control Center de la comparaison et de la composition de variantes (handoff jarvis-interactive-presentation-studio, Slice 19).

Core possede la comparaison et la composition (`jarvis/protocol/presentation_studio_compose_routes.py`). Mecanique de
`presentation_studio_variants_relay.py` : statut et JSON de Core rendus tels quels, erreurs comprises (donc `error.conflicts` d'une
composition refusee) ; Core injoignable 503, delai 504. Le Control Center ne garde **aucun** etat.

| Control Center | Core |
| --- | --- |
| `GET /api/presentation-studio/presentations/{id}/compare` | idem |
| `POST .../compare/select`, `/pair`, `/mode`, `/navigate`, `/links`, `/links/remove`, `/clear` | idem |
| `POST .../compositions/plan` | idem, **`actor` force a `user`** ; n'ecrit rien |
| `POST .../compositions` | idem, **`actor` force a `user`** |
| `GET .../variants/{vid}/composition` | idem |

La comparaison n'a pas d'acteur (elle n'ecrit aucune variante). Le journal (`presentation_studio.request.relayed`) note l'action, le
statut et le code, jamais un titre ni une raison.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from aiohttp import web

from jarvis.runtime.capture_relay import _code_of, _error
from jarvis.protocol.strict_json import loads_strict_json, read_bounded
from jarvis.runtime.presentation_studio_relay import CORE_PREFIX, STUDIO_ROUTE, PresentationStudioRelayRoutes

COMPARE_PATH = "/{presentation_id}/compare"
COMPOSITION_READ_PATH = "/{presentation_id}/variants/{variant_id}/composition"
#: (chemin relatif, action journalisee, force l'acteur a `user`).
_WRITE_PATHS = (
    (COMPARE_PATH + "/select", "studio_compare_select", False),
    (COMPARE_PATH + "/pair", "studio_compare_pair", False),
    (COMPARE_PATH + "/mode", "studio_compare_mode", False),
    (COMPARE_PATH + "/navigate", "studio_compare_navigate", False),
    (COMPARE_PATH + "/links", "studio_compare_link", False),
    (COMPARE_PATH + "/links/remove", "studio_compare_unlink", False),
    (COMPARE_PATH + "/clear", "studio_compare_clear", False),
    ("/{presentation_id}/compositions/plan", "studio_composition_plan", True),
    ("/{presentation_id}/compositions", "studio_composition_create", True),
)
MAX_COMPOSE_BODY_BYTES = 64 * 1024


class PresentationStudioComposeRelayRoutes(PresentationStudioRelayRoutes):
    """Relais de la comparaison et de la composition -> Core. Voir l'en-tete."""

    MAX_BODY_BYTES = MAX_COMPOSE_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [web.get(STUDIO_ROUTE + COMPARE_PATH, self._relay("studio_compare", CORE_PREFIX + COMPARE_PATH)),
                web.get(STUDIO_ROUTE + COMPOSITION_READ_PATH, self._relay("studio_composition", CORE_PREFIX + COMPOSITION_READ_PATH)),
                *(web.post(STUDIO_ROUTE + path, self._write(path, action, force)) for path, action, force in _WRITE_PATHS)]

    def _write(self, path: str, action: str, force_user: bool):
        async def handler(request: web.Request) -> web.Response:
            return await self._forward_write(request, path, action, force_user)

        return handler

    async def _forward_write(self, request: web.Request, template: str, action: str, force_user: bool) -> web.Response:
        if request.query:
            return _error(400, "invalid_request", "unexpected query parameters")
        try:
            raw = (await read_bounded(request.content, self.MAX_BODY_BYTES) if request.can_read_body else b"") or b""
            body = loads_strict_json(raw, invalid_message="body must be JSON") if raw.strip() else {}
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        if not isinstance(body, dict):
            return _error(400, "invalid_request", "body must be a JSON object")
        if force_user:
            body["actor"] = "user"  # the page of the user never speaks as the brain
        path = CORE_PREFIX + template.format(**{k: quote(v, safe="") for k, v in request.match_info.items()})
        forced = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, payload = await self._forward("POST", path, action=action, params=None, body=forced, timeout_s=None)
        self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"{action} relayé à Core (HTTP {status})",
                           level="info" if status < 400 else "warning",
                           data={"action": action, "status": status, "code": _code_of(payload)})
        if payload is None:
            return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)
