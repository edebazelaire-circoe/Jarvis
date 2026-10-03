"""Routes prefabs du Control Center : relais de Core (handoff jarvis-scene-window-prefab-foundation, Slice 03).

Core possède le catalogue (`PrefabService`, seule autorité de validation) ;
l'API est `jarvis/protocol/prefab_routes.py`. Le Control Center n'en garde
**rien** : `/api/prefabs<reste>` est relayé tel quel vers `/v1/prefabs<reste>`
(même mécanique que `capture_relay.py` : paramètres paire par paire, chaque
paramètre de route ré-encodé, statut et corps JSON de Core rendus tels quels,
erreurs comprises ; Core injoignable 503 `core_unreachable` /
`core_unconfigured`, délai 504 `core_timeout`). Contrat : `docs/prefabs.md` ›
*Control Center routes*.

| Control Center | Core | Slice |
| --- | --- | --- |
| `GET /api/prefabs/events` | `GET /v1/prefabs/events` | 04 |
| `POST /api/prefabs/events` | `POST /v1/prefabs/events`, **`actor` forcé à `user`** | 04 |
| `GET /api/prefabs` | `GET /v1/prefabs` | 03 |
| `GET /api/prefabs/{prefab_id}` | idem sous `/v1` | 03 |
| `GET /api/prefabs/{prefab_id}/{version}` | idem | 03 |
| `GET /api/prefabs/{prefab_id}/{version}/bundle` | idem (le runtime des cadres le lit) | 03 |

`POST /api/prefabs/events` est la seule écriture : la page y envoie les
événements de ses cadres (`control_center_prefab_host.js`). Le corps doit être
un objet JSON ; son `actor` est **remplacé** par `user`, quoi qu'il dise (même
règle que `/api/scene/commands`) : la page de l'utilisateur ne parle jamais au
nom du cerveau.

Le relais rend le JSON de Core, pas ses en-têtes : l'`ETag` du paquet reste
côté Core ; le runtime des cadres garde ses paquets en mémoire par `id@version`
(une version publiée ne change jamais).

**Garde.** `/api/prefabs` est dans `READ_GUARDED_ROUTES` du Control Center :
**toutes** les méthodes exigent un Host de bouclage, un Origin de bouclage
s'il existe et jamais `Sec-Fetch-Site: cross-site`. Un cadre de prefab
(origine opaque, `Origin: null`) ne peut donc rien lire ni écrire ici, même
si son CSP le laissait sortir.

`CorePrefabTransport` est l'accès typé à `/v1/prefabs*` sur un transport de
Core (`forward(method, path, *, params, body, timeout_s) -> (statut, JSON)`,
`CoreSessionTransport`) : le relais l'utilise, le serveur MCP `jarvis-display`
(Slice 07) le réutilisera. Il refuse tout chemin hors de `/v1/prefabs`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

import json

from aiohttp import web

from jarvis.protocol.strict_json import loads_strict_json
from jarvis.runtime.capture_relay import CaptureRelayRoutes, _code_of, _error
from jarvis.runtime.journal import RuntimeJournal

PREFABS_ROUTE = "/api/prefabs"
CORE_PREFIX = "/v1/prefabs"
#: Préfixes servis par ce module (gardés en lecture comme en écriture par le Control Center).
GUARDED_PREFIXES = (PREFABS_ROUTE,)

#: (méthode, action, chemin relatif sous `/api/prefabs` et `/v1/prefabs`).
_ROUTES = (
    # Segment fixe d'abord : jamais pris pour un `{prefab_id}`.
    ("GET", "prefab_events", "/events"),
    ("GET", "prefab_search", ""),
    ("GET", "prefab_detail", "/{prefab_id}"),
    ("GET", "prefab_version", "/{prefab_id}/{version}"),
    ("GET", "prefab_bundle", "/{prefab_id}/{version}/bundle"),
)


class CorePrefabTransport:
    """`/v1/prefabs*` sur un transport de Core ; statut et JSON de Core tels quels. Voir l'en-tête."""

    def __init__(self, transport: Any) -> None:
        self._transport = transport

    async def forward(self, method: str, path: str, *, params: Sequence[tuple[str, str]] | None = None,
                      body: bytes | None = None, timeout_s: float | None = None) -> tuple[int, Any]:
        if not (path == CORE_PREFIX or path.startswith(CORE_PREFIX + "/")):
            raise ValueError(f"CorePrefabTransport only reaches {CORE_PREFIX}*, not {path[:80]!r}")
        return await self._transport.forward(method, path, params=params, body=body, timeout_s=timeout_s)

    async def search(self, *, query: str | None = None, family: str | None = None, prefab_class: str | None = None,
                     limit: int | None = None) -> tuple[int, Any]:
        wanted = {"query": query, "family": family, "class": prefab_class,
                  "limit": None if limit is None else str(limit)}
        params = [(key, value) for key, value in wanted.items() if value is not None]
        return await self.forward("GET", CORE_PREFIX, params=params or None)

    async def detail(self, prefab_id: str) -> tuple[int, Any]:
        return await self.forward("GET", f"{CORE_PREFIX}/{quote(prefab_id, safe='')}")

    async def version(self, prefab_id: str, version: int, *, include_source: bool = False) -> tuple[int, Any]:
        return await self.forward("GET", f"{CORE_PREFIX}/{quote(prefab_id, safe='')}/{int(version)}",
                                  params=[("include_source", "1" if include_source else "0")])

    async def bundle(self, prefab_id: str, version: int) -> tuple[int, Any]:
        return await self.forward("GET", f"{CORE_PREFIX}/{quote(prefab_id, safe='')}/{int(version)}/bundle")


class PrefabRelayRoutes(CaptureRelayRoutes):
    """Relais `/api/prefabs*` -> `/v1/prefabs*` (même méthode), par `CorePrefabTransport`. Voir l'en-tête."""

    JOURNAL_PREFIX = "prefab.request"

    def __init__(self, *, transport: Callable[[], Any], journal: RuntimeJournal) -> None:
        # Transport relu à chaque requête (le Control Center peut le recevoir après coup), toujours borné à /v1/prefabs.
        def scoped() -> CorePrefabTransport | None:
            core = transport()
            return None if core is None else CorePrefabTransport(core)

        super().__init__(transport=scoped, journal=journal)

    def routes(self) -> list[web.RouteDef]:
        return [web.post(PREFABS_ROUTE + "/events", self.submit_event),
                *(web.route(method, PREFABS_ROUTE + path, self._relay(action, CORE_PREFIX + path))
                  for method, action, path in _ROUTES)]

    async def submit_event(self, request: web.Request) -> web.Response:
        """`POST /api/prefabs/events` : corps objet, `actor` forcé à `user`, relayé à Core."""

        if request.query:
            return _error(400, "invalid_request", "unexpected query parameters")
        try:
            raw = await self._read_body(request) or b""
            body = loads_strict_json(raw, invalid_message="body must be JSON")
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        if not isinstance(body, dict):
            return _error(400, "invalid_request", "body must be a JSON object")
        body["actor"] = "user"
        forced = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, payload = await self._forward("POST", CORE_PREFIX + "/events", action="prefab_event", params=None,
                                              body=forced, timeout_s=None)
        outcome = payload.get("outcome") if isinstance(payload, dict) else None
        self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"prefab_event relayé à Core (HTTP {status})",
                           level="info" if status < 400 else "warning",
                           data={"action": "prefab_event", "status": status, "outcome": outcome,
                                 "code": _code_of(payload)})
        if payload is None:
            return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)
