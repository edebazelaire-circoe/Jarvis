"""Relais Control Center du graphe des variantes (handoff jarvis-interactive-presentation-studio, Slice 16).

Core possède le graphe (`jarvis/protocol/presentation_studio_variants_routes.py`, `PresentationStudioVariants`, seule autorité).
`/api/presentation-studio/presentations<reste>` est relayé vers `/v1/presentation-studio/presentations<reste>` (mécanique de
`presentation_studio_relay.py` : statut et JSON de Core rendus tels quels, erreurs comprises ; Core injoignable 503, délai 504).

| Control Center | Core |
| --- | --- |
| `GET /api/presentation-studio/presentations/{presentation_id}/graph` | idem (`?archived=1`, `?check=1` relayés) |
| `POST .../presentations/{presentation_id}/variants` | idem, **`actor` forcé à `user`** |
| `POST .../variants/{variant_id}/activate` et `.../rename` et `.../restore` | idem, **`actor` forcé à `user`** |
| `POST .../variants/{variant_id}/archive-plan` | idem, **`actor` forcé à `user`** ; n'écrit rien |
| `POST .../variants/{variant_id}/archive` | idem, **`actor` forcé à `user`** ; **sans `confirmation` le relais refuse lui-même** (`presentation_studio_confirmation_required`, 400, Core n'est pas appelé) |

L'interface n'a donc **aucune** porte pour archiver sans avoir demandé un plan et montré l'ensemble exact à l'utilisateur ; Core
refuse en plus tout jeton qui ne correspond plus à l'ensemble courant (`presentation_studio_confirmation_stale`). Le journal
(`presentation_studio.request.relayed`) note l'action, le statut et le code, jamais un titre ni une raison de création.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from aiohttp import web

from jarvis.runtime.capture_relay import _code_of, _error
from jarvis.protocol.strict_json import loads_strict_json, read_bounded
from jarvis.runtime.presentation_studio_relay import CORE_PREFIX, STUDIO_ROUTE, PresentationStudioRelayRoutes

GRAPH_PATH = "/{presentation_id}/graph"
#: (chemin relatif, action journalisée). Toutes à acteur forcé `user`.
_WRITE_PATHS = (
    ("/{presentation_id}/variants", "studio_variant_create"),
    ("/{presentation_id}/variants/{variant_id}/activate", "studio_variant_activate"),
    ("/{presentation_id}/variants/{variant_id}/rename", "studio_variant_rename"),
    ("/{presentation_id}/variants/{variant_id}/archive-plan", "studio_variant_archive_plan"),
    ("/{presentation_id}/variants/{variant_id}/archive", "studio_variant_archive"),
    ("/{presentation_id}/variants/{variant_id}/restore", "studio_variant_restore"),
)
ARCHIVE_ACTION = "studio_variant_archive"
MAX_VARIANTS_BODY_BYTES = 16 * 1024


class PresentationStudioVariantsRelayRoutes(PresentationStudioRelayRoutes):
    """Relais `/api/presentation-studio/presentations/{id}/graph` et opérations de variante -> Core. Voir l'en-tête."""

    MAX_BODY_BYTES = MAX_VARIANTS_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [web.get(STUDIO_ROUTE + GRAPH_PATH, self._relay("studio_graph", CORE_PREFIX + GRAPH_PATH)),
                *(web.post(STUDIO_ROUTE + path, self._variant_write(path, action)) for path, action in _WRITE_PATHS)]

    def _variant_write(self, path: str, action: str):
        async def handler(request: web.Request) -> web.Response:
            return await self._forward_variant(request, path, action)

        return handler

    async def _forward_variant(self, request: web.Request, template: str, action: str) -> web.Response:
        if request.query:
            return _error(400, "invalid_request", "unexpected query parameters")
        try:
            raw = (await read_bounded(request.content, self.MAX_BODY_BYTES) if request.can_read_body else b"") or b""
            body = loads_strict_json(raw, invalid_message="body must be JSON") if raw.strip() else {}
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        if not isinstance(body, dict):
            return _error(400, "invalid_request", "body must be a JSON object")
        body["actor"] = "user"  # the page of the user never speaks as the brain
        if action == ARCHIVE_ACTION and not (isinstance(body.get("confirmation"), str) and body["confirmation"]):
            # The relay refuses first: an archive without the confirmation of a plan never reaches Core.
            self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"{action} refuse par le relais (aucune confirmation)",
                               level="warning", data={"action": action, "status": 400,
                                                      "code": "presentation_studio_confirmation_required"})
            return _error(400, "presentation_studio_confirmation_required",
                          "archiving needs the confirmation token of a plan (plan first, then confirm)")
        path = CORE_PREFIX + template.format(**{k: quote(v, safe="") for k, v in request.match_info.items()})
        forced = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, payload = await self._forward("POST", path, action=action, params=None, body=forced, timeout_s=None)
        self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"{action} relayé à Core (HTTP {status})",
                           level="info" if status < 400 else "warning",
                           data={"action": action, "status": status, "code": _code_of(payload)})
        if payload is None:
            return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)
