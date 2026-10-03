"""Routes HTTP de Core : lecture du catalogue des prefabs (handoff jarvis-scene-window-prefab-foundation, Slice 03).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ;
logique dans `jarvis/core/prefab_service.py` (`PrefabService`, seule autorité).
Le Control Center les relaie sous `/api/prefabs...` (`jarvis/runtime/prefab_relay.py`).
Contrat : `docs/prefabs.md` › *Core routes*.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/prefabs/events[?after&object_id&limit]` | `{events: [{seq, at, object_id, prefab, event, class, payload, outcome, reason?}], last_seq}` (anneau de 256, `limit` ≤ 50 ; Slice 04) |
| POST | `/v1/prefabs/events` | corps `{actor: "user", object_id, prefab: {id, version}, event, payload, basis?}` -> `{outcome: applied\\|recorded\\|stale\\|refused, reason?, detail?, revision?}` ; 429 `rate_limited` (Slice 04) |
| POST | `/v1/prefabs/validate` | corps `{candidate}` -> `{ok, errors[≤ 20], fingerprint?}`, rien n'est écrit (Slice 07) |
| POST | `/v1/prefabs` | corps `{actor: brain ou user, candidate, derived_from?: {id, version}}` -> la publication (`publication.json`) ; 403 `base_protected` pour un id `jarvis.*`, 409 `version_exists` (Slice 07) |
| POST | `/v1/prefabs/{prefab_id}/base-edits` | corps `{actor: "brain", candidate, user_request, confirmed_by_user: true}` -> la publication ; 403 `base_edit_unconfirmed` (porte d'intention explicite, Slice 07) |
| GET | `/v1/prefabs[?query&family&class&limit]` | `{prefabs: [{id, latest_version, versions, title, family, class, description, input_names, event_names, base_edited}]}` (`limit` ≤ 50) |
| GET | `/v1/prefabs/{prefab_id}` | dernière version saine, sa publication, l'historique (chaîne de provenance) |
| GET | `/v1/prefabs/{prefab_id}/{version}[?include_source=0\\|1]` | une version (+ ses sources ≤ 128 Kio) |
| GET | `/v1/prefabs/{prefab_id}/{version}/bundle` | `{id, version, fingerprint, manifest, files, runtime: {version, shim, shell_css}}` ; `ETag` = empreinte de la version + version du runtime, `If-None-Match` -> 304 |

Les routes à segment fixe (`/v1/prefabs/events`, `/v1/prefabs/validate`, Slices
04 et 07) s'enregistrent **avant** `{prefab_id}` : un id porte toujours un
point, il ne peut pas valoir `events` ni `validate`. Les événements sont
traités par `PrefabEventService` (`jarvis/core/prefab_events.py`) : une issue
`stale` ou `refused` est une réponse 200 (le domaine a répondu), pas une erreur.

Refus : `{"error": {"code", "message"[, "errors"]}}` avec les codes de
`PrefabStoreError` et leur statut (`unknown_prefab` / `unknown_version` 404,
`tampered` 409, `storage_io` 500), `invalid_request` 400 pour une requête mal
formée, `rate_limited` 429 (événements), `scene_unavailable` 503, ou
`scene_persist_failed` 503 si la scène ne peut pas écrire (comme
`POST /v1/scene/commands`), `core_unavailable` 503 avant le démarrage. Message sans chemin absolu
(`redact_paths`). Les pannes sont journalisées par le service lui-même
(`core.prefab.tampered` avec `status: unreadable`, `core.prefab.runtime_unavailable`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.prefab_events import MAX_LIST_LIMIT, PrefabEventsRateLimited
from jarvis.core.prefab_service import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT
from jarvis.domain._checks import MAX_ID_CHARS
from jarvis.domain.prefab import (
    MAX_STATE_EVENT_PAYLOAD_BYTES, MAX_VERSION, PrefabClass, PrefabDefinitionError, PrefabRef,
)
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from jarvis.ports.scene import SceneStoreError, SceneUnavailableError
from jarvis.protocol.capture_routes import _int, _only, error_response
from jarvis.protocol.scene_wire import SCENE_PERSIST_FAILED
from jarvis.protocol.strict_json import loads_strict_json, read_bounded

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PREFIX = "/v1/prefabs"
#: Corps d'un événement : une charge d'état (16 Kio), sa basis (autant) et l'enveloppe.
MAX_EVENT_BODY_BYTES = 2 * MAX_STATE_EVENT_PAYLOAD_BYTES + 8 * 1024
#: Corps d'une définition (Slice 07) : sources ≤ 160 Kio, échappement JSON compris.
MAX_DEFINITION_BODY_BYTES = 512 * 1024


class PrefabProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.prefabs`). Voir l'en-tête."""

    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            # Segments fixes d'abord : jamais pris pour un `{prefab_id}`.
            web.get(PREFIX + "/events", g(self.events)),
            web.post(PREFIX + "/events", g(self.submit_event)),
            web.post(PREFIX + "/validate", g(self.validate)),
            web.get(PREFIX, g(self.search)),
            web.post(PREFIX, g(self.save)),
            web.get(PREFIX + "/{prefab_id}", g(self.detail)),
            web.get(PREFIX + "/{prefab_id}/{version}", g(self.version)),
            web.get(PREFIX + "/{prefab_id}/{version}/bundle", g(self.bundle)),
            web.post(PREFIX + "/{prefab_id}/base-edits", g(self.base_edit)),
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
            except PrefabEventsRateLimited as exc:
                return error_response(429, "rate_limited", str(exc))
            except SceneUnavailableError as exc:
                return error_response(503, "scene_unavailable", str(exc))
            except SceneStoreError as exc:
                # Écriture de la scène en échec, déjà journalisée par `SceneService` : 503 et le code de
                # `POST /v1/scene/commands` (`LocalProtocolServer._scene_failure`), jamais un 500.
                return error_response(503, SCENE_PERSIST_FAILED, str(exc))
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

    async def events(self, request: web.Request) -> web.Response:
        _only(request, {"after", "object_id", "limit"})
        after = _int(request, "after", None, 0, 2**53)
        limit = _int(request, "limit", MAX_LIST_LIMIT, 1, MAX_LIST_LIMIT)
        object_id = request.query.get("object_id")
        if object_id is not None and not 0 < len(object_id) <= MAX_ID_CHARS:
            raise ValueError(f"object_id must hold 1..{MAX_ID_CHARS} characters")
        service = self._core.prefab_events
        rows = service.entries(after=after, object_id=object_id, limit=limit)
        return web.json_response({"events": [row.to_dict() for row in rows], "last_seq": service.last_seq})

    async def submit_event(self, request: web.Request) -> web.Response:
        _only(request, set())
        raw = await read_bounded(request.content, MAX_EVENT_BODY_BYTES)
        body = loads_strict_json(raw, invalid_message="body must be JSON")
        result = await self._core.prefab_events.submit(body)
        return web.json_response(result.to_dict())

    async def search(self, request: web.Request) -> web.Response:
        _only(request, {"query", "family", "class", "limit"})
        wanted = request.query.get("class")
        if wanted is not None and wanted not in {item.value for item in PrefabClass}:
            raise ValueError("class must be base or custom")
        family = request.query.get("family")
        if family is not None and not (0 < len(family) <= 32):
            raise ValueError("family must be a token of at most 32 characters")
        limit = _int(request, "limit", DEFAULT_SEARCH_LIMIT, 1, MAX_SEARCH_LIMIT)
        rows = await self._prefabs.search(request.query.get("query"), family=family, class_filter=wanted,
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

    # ------------------------------------------------------------ définitions (Slice 07)

    @staticmethod
    async def _definition_body(request: web.Request, required: set[str], optional: set[str] = frozenset()) -> dict:
        _only(request, set())
        raw = await read_bounded(request.content, MAX_DEFINITION_BODY_BYTES)
        body = loads_strict_json(raw, invalid_message="body must be JSON")
        if not isinstance(body, dict) or not required <= set(body) <= required | set(optional):
            raise ValueError(f"body must be an object with {sorted(required)}"
                             + (f" and optionally {sorted(optional)}" if optional else ""))
        return body

    async def validate(self, request: web.Request) -> web.Response:
        """Validation sans écriture : toutes les erreurs vues (≤ 20), ou l'empreinte."""

        body = await self._definition_body(request, {"candidate"})
        return web.json_response(self._prefabs.validate_candidate(body["candidate"]).to_dict())

    async def save(self, request: web.Request) -> web.Response:
        body = await self._definition_body(request, {"actor", "candidate"}, {"derived_from"})
        derived = body.get("derived_from")
        if derived is not None:
            try:
                derived = PrefabRef.from_dict(derived)
            except PrefabDefinitionError as exc:
                raise ValueError(exc.errors[0]) from None
        publication = await self._prefabs.save(body["candidate"], actor=body["actor"], derived_from=derived)
        return web.json_response(publication.to_dict(), status=201)

    async def base_edit(self, request: web.Request) -> web.Response:
        body = await self._definition_body(request, {"actor", "candidate", "user_request", "confirmed_by_user"})
        publication = await self._prefabs.edit_base(request.match_info["prefab_id"], body["candidate"],
                                                    user_request=body["user_request"],
                                                    confirmed_by_user=body["confirmed_by_user"], actor=body["actor"])
        return web.json_response(publication.to_dict(), status=201)
