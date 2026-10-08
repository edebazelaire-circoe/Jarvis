"""Relais Control Center des variantes locales d'une scène (handoff jarvis-interactive-presentation-studio, Slice 17).

Core possède l'ensemble (`jarvis/protocol/presentation_studio_scene_variants_routes.py`, `PresentationStudioSceneVariants`, seule
autorité). Mécanique de `presentation_studio_variants_relay.py` : statut et JSON de Core rendus tels quels, erreurs comprises.

| Control Center | Core |
| --- | --- |
| `GET /api/presentation-studio/presentations/{id}/variants/{vid}/scenes/{sid}/scene-variants` | idem |
| `POST .../scenes/{sid}/scene-variants/{xid}/preview` | idem, **`actor` forcé à `user`** ; n'écrit rien |
| `POST .../presentations/{id}/scene-variants/preview/cancel` | idem, **`actor` forcé à `user`** |
| `POST .../scenes/{sid}/scene-variants/{xid}/promote` | idem, **`actor` forcé à `user`** |

Créer, renommer, choisir et supprimer une variante locale passent par `POST .../variants/{vid}/edits` (déjà relayé, acteur forcé).
Le journal (`presentation_studio.request.relayed`) note l'action, le statut et le code, jamais un libellé ni un titre.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from aiohttp import web

from jarvis.runtime.capture_relay import _code_of, _error
from jarvis.protocol.strict_json import loads_strict_json, read_bounded
from jarvis.runtime.presentation_studio_relay import CORE_PREFIX, STUDIO_ROUTE, PresentationStudioRelayRoutes

SCENE_PATH = "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/scene-variants"
CANCEL_PATH = "/{presentation_id}/scene-variants/preview/cancel"
#: (chemin relatif, action journalisée). Toutes à acteur forcé `user`.
_WRITE_PATHS = (
    (SCENE_PATH + "/{scene_variant_id}/preview", "studio_scene_variant_preview"),
    (SCENE_PATH + "/{scene_variant_id}/promote", "studio_scene_variant_promote"),
    (CANCEL_PATH, "studio_scene_variant_cancel_preview"),
)
MAX_SCENE_VARIANT_BODY_BYTES = 16 * 1024


class PresentationStudioSceneVariantsRelayRoutes(PresentationStudioRelayRoutes):
    """Relais des variantes locales -> Core. Voir l'en-tête."""

    MAX_BODY_BYTES = MAX_SCENE_VARIANT_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [web.get(STUDIO_ROUTE + SCENE_PATH, self._relay("studio_scene_variants", CORE_PREFIX + SCENE_PATH)),
                *(web.post(STUDIO_ROUTE + path, self._write(path, action)) for path, action in _WRITE_PATHS)]

    def _write(self, path: str, action: str):
        async def handler(request: web.Request) -> web.Response:
            return await self._forward_write(request, path, action)

        return handler

    async def _forward_write(self, request: web.Request, template: str, action: str) -> web.Response:
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
        path = CORE_PREFIX + template.format(**{k: quote(v, safe="") for k, v in request.match_info.items()})
        forced = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, payload = await self._forward("POST", path, action=action, params=None, body=forced, timeout_s=None)
        self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"{action} relayé à Core (HTTP {status})",
                           level="info" if status < 400 else "warning",
                           data={"action": action, "status": status, "code": _code_of(payload)})
        if payload is None:
            return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)
