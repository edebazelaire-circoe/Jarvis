"""Relais du Control Center vers Core pour l'export explicite d'un fichier final (presentation-edition-v1 Slice 03, `docs/export.md`).

| Control Center | Core | Délai |
| --- | --- | --- |
| `GET /api/exports/root` | `GET /v1/exports/root` | 10 s |
| `POST /api/exports` | `POST /v1/exports` | 120 s (copie d'un fichier jusqu'à 512 Mio) |

Seules ces deux adresses existent. Le corps est relayé tel quel, sauf `actor` : l'interface est l'utilisateur, un
`actor` autre que `user` est refusé ici (`export_invalid`). Gardées comme les Artifacts (`READ_GUARDED_ROUTES` : Host et
Origin de bouclage) : une écriture dans le dossier de l'utilisateur ne part jamais d'une autre page. Journal :
`export.request.relayed` pour chaque écriture (action, statut, code ; jamais un corps).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from aiohttp import web

from jarvis.runtime.capture_relay import CaptureRelayRoutes, _code_of, _error

EXPORTS_ROUTE = "/api/exports"
GUARDED_PREFIXES = (EXPORTS_ROUTE,)
EXPORT_TIMEOUT_S = 120.0


class ExportRelayRoutes(CaptureRelayRoutes):
    JOURNAL_PREFIX = "export.request"
    MAX_BODY_BYTES = 4096

    def routes(self) -> list[web.RouteDef]:
        return [web.get(EXPORTS_ROUTE + "/root", self._relay("export_root", "/v1/exports/root")),
                web.post(EXPORTS_ROUTE, self._create())]

    def _create(self) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            if request.query:
                return _error(400, "export_invalid", "unexpected query parameters")
            try:
                body = await self._read_body(request)
            except ValueError as exc:
                return _error(400, "export_invalid", str(exc))
            try:
                parsed = json.loads(body or b"{}")
            except ValueError:
                return _error(400, "export_invalid", "the body must be JSON")
            if isinstance(parsed, dict) and parsed.get("actor") not in (None, "user"):
                return _error(400, "export_invalid", "the Control Center exports for the user only")
            status, payload = await self._forward("POST", "/v1/exports", action="export", params=None, body=body,
                                                  timeout_s=EXPORT_TIMEOUT_S)
            self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"export relayé à Core (HTTP {status})",
                               level="info" if status < 400 else "warning",
                               data={"action": "export", "status": status, "code": _code_of(payload)})
            if payload is None:
                return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
            return web.json_response(payload, status=status)
        return handler
