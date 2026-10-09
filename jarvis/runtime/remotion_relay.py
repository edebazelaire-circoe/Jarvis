"""Routes Remotion du Control Center (handoff jarvis-remotion-presentation-integration, Slice 10 ; `docs/remotion-isolation.md` § 10).

| Control Center | Rôle |
| --- | --- |
| `GET /remotion-stage?id=<prefab>&v=<version>` | la page de la scène : un document de confiance qui monte le bac à sable. Son en-tête est **`Content-Security-Policy: frame-src <origine du bac à sable>` et rien d'autre** (`embedder_frame_src`) ; `frame-src 'none'` quand Core ne configure aucun bac à sable. Jamais l'origine du visualiseur ni de Core. |
| `GET /api/remotion/sandbox` | relais de `GET /v1/remotion/sandbox` (état du moteur, origine du bac à sable) |
| `GET /api/remotion/player/{prefab_id}/{version}` | relais de `GET /v1/remotion/player/...` (compile à la demande : délai de 150 s) |
| `POST /api/remotion/report` | la page de la scène rend compte (`ready`, `failed`, `killed`, `violation`, `scene_error`) ; le Control Center journalise `remotion.sandbox.killed`, `remotion.stage.*` ; corps borné, champs d'une liste fermée |

Toutes les routes sont gardées comme `/api/prefabs` : Host de boucle locale, Origin de boucle locale s'il existe, jamais
`Sec-Fetch-Site: cross-site` (`READ_GUARDED_ROUTES`). Un cadre de bac à sable (origine opaque) ne peut donc rien lire ici.
"""

from __future__ import annotations

import json
import re
from typing import Any

from aiohttp import web

from jarvis.domain import remotion_sandbox as sb
from jarvis.runtime.capture_relay import CaptureRelayRoutes, _error
from jarvis.runtime.journal import RuntimeJournal

STAGE_ROUTE = "/remotion-stage"
API_ROUTE = "/api/remotion"
#: Préfixes gardés par le Control Center (toutes méthodes).
GUARDED_PREFIXES = (STAGE_ROUTE, API_ROUTE)
CORE_PREFIX = "/v1/remotion"
#: Compilation à la demande (jusqu'à 120 s côté Core) : le relais attend un peu plus.
PLAYER_TIMEOUT_S = 150.0
MAX_REPORT_BYTES = 2048
REPORT_EVENTS = frozenset({"ready", "failed", "killed", "violation", "scene_error"})
_PREFAB_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{0,60}\Z")


def stage_csp(sandbox_origin: str | None) -> str:
    """`frame-src` de la page de la scène : le bac à sable seul, ou `'none'`. Rien d'autre (docs/remotion-isolation.md § 4)."""

    return sb.embedder_frame_src(sandbox_origin) if sandbox_origin else "frame-src 'none'"


class RemotionRelayRoutes(CaptureRelayRoutes):
    JOURNAL_PREFIX = "remotion.request"

    def __init__(self, *, transport: Any, journal: RuntimeJournal, protocol_js: str, stage_js: str, page_template: str) -> None:
        super().__init__(transport=transport, journal=journal)
        close_tag, safe_tag = "</" + "script", "<\\/" + "script"
        self._page = (page_template.replace("/*__REMOTION_PROTOCOL_JS__*/", protocol_js.replace(close_tag, safe_tag))
                      .replace("/*__REMOTION_STAGE_JS__*/", stage_js.replace(close_tag, safe_tag)))

    def routes(self) -> list[web.RouteDef]:
        return [web.get(STAGE_ROUTE, self.stage),
                web.get(API_ROUTE + "/sandbox", self._relay("remotion_sandbox", CORE_PREFIX + "/sandbox")),
                web.get(API_ROUTE + "/player/{prefab_id}/{version}",
                        self._relay("remotion_player", CORE_PREFIX + "/player/{prefab_id}/{version}", PLAYER_TIMEOUT_S)),
                web.post(API_ROUTE + "/report", self.report)]

    async def stage(self, request: web.Request) -> web.Response:
        prefab_id, version = request.query.get("id", ""), request.query.get("v", "")
        if set(request.query) - {"id", "v"} or not _PREFAB_ID.fullmatch(prefab_id) or not (version.isascii() and version.isdigit() and 0 < len(version) <= 4):
            return _error(400, "invalid_request", "a Remotion stage names a prefab id and a version (?id=...&v=...)")
        # The sandbox origin is Core's to say (the CSP names exactly that origin); no Core or no sandbox -> 'none', and the page
        # tells the user why through the typed failure of the player route (engine_unavailable), never a blank frame.
        status, payload = await self._forward("GET", CORE_PREFIX + "/sandbox", action="remotion_sandbox", params=None, body=None, timeout_s=None)
        sandbox = payload.get("sandbox") if status == 200 and isinstance(payload, dict) else None
        origin = sandbox.get("origin") if isinstance(sandbox, dict) and sandbox.get("configured") else None
        config = {"prefabId": prefab_id, "version": int(version), "iframeAttributes": dict(sb.IFRAME_ATTRIBUTES)}
        body = self._page.replace("__REMOTION_STAGE_CONFIG__", json.dumps(config, separators=(",", ":")))
        return web.Response(text=body, content_type="text/html", headers={
            "Content-Security-Policy": stage_csp(origin), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer"})

    async def report(self, request: web.Request) -> web.Response:
        """La page de la scène rend compte : journalisé, jamais interprété. Champs d'une liste fermée, valeurs bornées."""

        raw = await request.content.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            return _error(413, "too_large", "a Remotion report is small")
        try:
            body = json.loads(raw)
        except ValueError:
            return _error(400, "invalid_request", "body must be JSON")
        event = body.get("event") if isinstance(body, dict) else None
        if event not in REPORT_EVENTS:
            return _error(400, "invalid_request", "unknown report event")
        data: dict[str, Any] = {"event": event}
        for key in ("prefab_id", "reason", "code", "directive", "detail"):
            value = body.get(key)
            if isinstance(value, str) and _TOKEN.fullmatch(value[:60]):
                data[key] = value[:60]
        for key in ("version", "diagnostics"):
            value = body.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**6:
                data[key] = value
        if isinstance(body.get("message"), str):
            data["message"] = re.sub(r"[\x00-\x1f]", " ", body["message"])[:200]
        kind = "remotion.sandbox.killed" if event == "killed" else f"remotion.stage.{event}"
        level = "warning" if event in ("failed", "killed", "violation", "scene_error") else "info"
        self._journal.emit(kind, f"Scene Remotion : {event}", level=level, data=data)
        return web.json_response({"ok": True})
