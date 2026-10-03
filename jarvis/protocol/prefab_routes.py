"""Routes HTTP de Core : lecture du catalogue des prefabs (handoff jarvis-scene-window-prefab-foundation, Slice 03).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ;
logique dans `jarvis/core/prefab_service.py` (`PrefabService`, seule autorité).
Le Control Center les relaie sous `/api/prefabs...` (`jarvis/runtime/prefab_relay.py`).
Contrat : `docs/prefabs.md` › *Core routes*.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/prefabs[?query&family&class&limit]` | `{prefabs: [{id, latest_version, versions, title, family, class, description, input_names, event_names, base_edited}]}` (`limit` ≤ 50) |
| GET | `/v1/prefabs/{prefab_id}` | dernière version saine, sa publication, l'historique (chaîne de provenance) |
| GET | `/v1/prefabs/{prefab_id}/{version}[?include_source=0\\|1]` | une version (+ ses sources ≤ 128 Kio) |
| GET | `/v1/prefabs/{prefab_id}/{version}/bundle` | `{id, version, fingerprint, manifest, files, runtime: {version, shim, shell_css}}` ; `ETag` = empreinte de la version + version du runtime, `If-None-Match` -> 304 |

Les routes à segment fixe (`/v1/prefabs/events`, `/v1/prefabs/validate`, Slices
04 et 07) s'enregistrent **avant** `{prefab_id}` : un id porte toujours un
point, il ne peut pas valoir `events` ni `validate`.

Refus : `{"error": {"code", "message"[, "errors"]}}` avec les codes de
`PrefabStoreError` et leur statut (`unknown_prefab` / `unknown_version` 404,
`tampered` 409, `storage_io` 500), `invalid_request` 400 pour une requête mal
formée, `core_unavailable` 503 avant le démarrage. Message sans chemin absolu
(`redact_paths`). Les pannes sont journalisées par le service lui-même
(`core.prefab.tampered` avec `status: unreadable`, `core.prefab.runtime_unavailable`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.prefab_service import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT
from jarvis.domain.prefab import MAX_VERSION, PrefabClass
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from jarvis.protocol.capture_routes import _int, _only, error_response

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PREFIX = "/v1/prefabs"


class PrefabProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.prefabs`). Voir l'en-tête."""

    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(PREFIX, g(self.search)),
            web.get(PREFIX + "/{prefab_id}", g(self.detail)),
            web.get(PREFIX + "/{prefab_id}/{version}", g(self.version)),
            web.get(PREFIX + "/{prefab_id}/{version}/bundle", g(self.bundle)),
        ]

    def _guarded(self, handler: Handler) -> Handler:
        """Chaque refus devient l'enveloppe codée ; une panne est aussi journalisée. Jamais un 500 muet."""

        async def run(request: web.Request) -> web.StreamResponse:
            try:
                if not self._core.health.ready:
                    return error_response(503, "core_unavailable", "core is not ready")
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except PrefabStoreError as exc:
                return error_response(exc.status, exc.code.value, exc.message, errors=list(exc.errors) or None)
            except ValueError as exc:
                return error_response(400, "invalid_request", str(exc))

        return run

    @property
    def _prefabs(self) -> Any:
        return self._core.prefabs

    @staticmethod
    def _version(request: web.Request) -> int:
        raw = request.match_info["version"]
        if not (raw.isascii() and raw.isdigit() and len(raw) <= 4) or not 1 <= int(raw) <= MAX_VERSION:
            raise PrefabStoreError(PrefabStoreErrorCode.UNKNOWN_VERSION, f"version must be an integer 1..{MAX_VERSION}")
        return int(raw)

    async def search(self, request: web.Request) -> web.Response:
        _only(request, {"query", "family", "class", "limit"})
        wanted = request.query.get("class")
        if wanted is not None and wanted not in {item.value for item in PrefabClass}:
            raise ValueError("class must be base or custom")
        family = request.query.get("family")
        if family is not None and not (0 < len(family) <= 32):
            raise ValueError("family must be a token of at most 32 characters")
        limit = _int(request, "limit", DEFAULT_SEARCH_LIMIT, 1, MAX_SEARCH_LIMIT)
        rows = await self._prefabs.search(request.query.get("query"), family=family, prefab_class=wanted,
                                          limit=limit)
        return web.json_response({"prefabs": [row.to_dict() for row in rows]})

    async def detail(self, request: web.Request) -> web.Response:
        _only(request, set())
        detail = await self._prefabs.get(request.match_info["prefab_id"])
        return web.json_response(detail.to_dict())

    async def version(self, request: web.Request) -> web.Response:
        _only(request, {"include_source"})
        include = request.query.get("include_source", "0")
        if include not in {"0", "1"}:
            raise ValueError("include_source must be 0 or 1")
        detail = await self._prefabs.get(request.match_info["prefab_id"], self._version(request))
        return web.json_response(detail.to_dict(include_source=include == "1"))

    async def bundle(self, request: web.Request) -> web.Response:
        _only(request, set())
        body = await self._prefabs.bundle(request.match_info["prefab_id"], self._version(request))
        etag = f'"{body["fingerprint"]}.{body["runtime"]["version"]}"'
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        return web.json_response(body, headers=headers)
