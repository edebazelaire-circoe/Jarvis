"""Routes de Core : Studio Remotion optionnel (handoff jarvis-remotion-presentation-integration, Slice 11 ; `docs/remotion-studio.md`).

Sous le préfixe frère `/v1/local-capabilities/remotion/studio` (le Studio est un processus supplémentaire de la capacité locale
Remotion, pas une capacité de plus) ; jeton porteur de Core obligatoire comme toutes les routes `/v1`.

| Méthode | Route | Corps | Réponse |
| --- | --- | --- | --- |
| GET | `/v1/local-capabilities/remotion/studio` | — | `{studio: vue}` (jamais un lancement) |
| POST | `.../studio/open` | `{"prefab_id", "version", "acknowledge_unsandboxed_scene": true}` | `{studio: vue}` ; `reused: true` si l'hôte vivant est réutilisé |
| POST | `.../studio/sync` | `{}` (scène courante relue) ou `{"prefab_id", "version", "acknowledge_unsandboxed_scene": true}` | `{studio: vue}` |
| POST | `.../studio/close` | `{}` | `{studio: vue}` |
| POST | `.../studio/restart` | `{"acknowledge_unsandboxed_scene": true}` | `{studio: vue}` |
| POST | `.../studio/publish` | `{"presentation_id", "variant_id", "scene_id", "base": {"prefab_id", "version"}, "digest", "confirm_publish": true}` (`digest` = `work_copy.digest` montré par la confirmation) | `{studio: vue, publish: {status, published, previous, variant_revision, mounted, files, message}}` |

Slice 12 (native-studio-playback-fix) : `open` et `sync` acceptent en plus `"discard_unpublished": true` (geste confirmé : les fichiers non
publiés de l'espace de travail sont copiés dans `studio-edits/` puis remplacés) ; sans lui, une modification non publiée n'est jamais
remplacée (409 `remotion_studio_unpublished_edits`). `publish` passe par la porte d'édition de source de la variante (nouvelle version) ;
ses refus portent `publish_code`, `diagnostics`, `base` / `current` dans l'enveloppe d'erreur.

Cible maître (master-project-studio-export Slice 05, `docs/remotion-master-project.md` § 9) : `open`, `sync` et `restart` acceptent aussi
`{"kind": "variant_master", "presentation_id", "variant_id", "project_key", "acknowledge_unsandboxed_project": true}` (au plus ~420 octets avec
`discard_unpublished`, admis aussi par `restart` maître ; le corps de scène de `restart` reste exactement l'accusé : sous le plafond de 1024) ; refus 409 `remotion_studio_master_incompatible` (`reason`, `detail`, `scene_ids`),
`remotion_studio_master_stale` (`project_key`, `variant_revision`, `scene_count` courants) ; `publish` d'une cible maître : 409
`remotion_studio_publish_master_unsupported`.

`open`, `restart` et `sync` d'une AUTRE scène exigent l'accusé explicite : sans lui, 400 `remotion_studio_ack_required` et rien n'est lancé
(la scène tourne sans le bac à sable du Player). Aucun chemin du cerveau, d'un outil MCP ni d'un agent n'appelle ces routes : `remotion_studio` (Slice 21) rend un pointeur vers la carte, l'accusé est à l'utilisateur.

Refus : `{"error": {"code": "remotion_studio_*", "message"}}` : 400 invalide, 404 source inconnue, 409 occupé / non ouvert /
environnement Remotion non prêt, 503 Core sans Studio. Un ÉCHEC de démarrage n'est pas une erreur HTTP : c'est la vue
(`status: failed`, `last_error_code`, `diagnostics`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Any

from aiohttp import web

from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C, parse_restart, parse_target
from jarvis.domain.remotion_studio_workspace import parse_publish, split_discard

PREFIX = "/v1/local-capabilities/remotion/studio"
MAX_BODY_BYTES = 1024
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class RemotionStudioProtocolRoutes:
    def __init__(self, core: Any) -> None:
        self._core = core
        self._current_core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [web.get(PREFIX, g(self.status)), web.post(PREFIX + "/open", g(self.open)), web.post(PREFIX + "/sync", g(self.sync)),
                web.post(PREFIX + "/close", g(self.close)), web.post(PREFIX + "/restart", g(self.restart)),
                web.post(PREFIX + "/publish", g(self.publish))]

    def _guarded(self, handler: Handler) -> Handler:
        async def run(request: web.Request) -> web.StreamResponse:
            try:
                if request.query:
                    raise StudioError(C.INVALID, "unexpected query parameters")
                return await handler(request)
            except StudioError as exc:
                return web.json_response({"error": {**exc.extra, "code": exc.code.value, "message": exc.detail or exc.code.value}},
                                         status=exc.http_status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - jamais un défaut muet : journalisé durablement (niveau error), 500 codé
                service = getattr(getattr(self, "_current_core", None), "remotion_studio", None)
                if service is not None:
                    service.report_unexpected(exc, request.method + " " + request.path)
                return web.json_response({"error": {"code": C.INTERNAL_ERROR.value, "message": f"unexpected {type(exc).__name__}"}}, status=500)
        return run

    def _service(self):
        service = getattr(self._core, "remotion_studio", None)
        if service is None:
            raise StudioError(C.UNAVAILABLE, "this Core has no Remotion Studio (no local capability store)")
        return service

    @staticmethod
    async def _body(request: web.Request) -> dict[str, Any]:
        raw = await request.read()
        if len(raw) > MAX_BODY_BYTES:
            raise StudioError(C.INVALID, "the request body is too large")
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except ValueError:
            raise StudioError(C.INVALID, "the request body is not JSON") from None
        if not isinstance(body, dict):
            raise StudioError(C.INVALID, "the request body must be a JSON object")
        return body

    async def status(self, request: web.Request) -> web.StreamResponse:
        return web.json_response({"studio": await self._service().status()})

    async def open(self, request: web.Request) -> web.StreamResponse:
        service = self._service()
        body, discard = split_discard(await self._body(request))
        return web.json_response({"studio": await service.open(parse_target(body), acknowledged=True, discard=discard)})

    async def sync(self, request: web.Request) -> web.StreamResponse:
        body, discard = split_discard(await self._body(request))
        service = self._service()
        if not body:
            return web.json_response({"studio": await service.sync(None, discard=discard)})
        return web.json_response({"studio": await service.sync(parse_target(body), acknowledged=True, discard=discard)})

    async def publish(self, request: web.Request) -> web.StreamResponse:
        service = self._service()
        return web.json_response(await service.publish(parse_publish(await self._body(request))))

    async def close(self, request: web.Request) -> web.StreamResponse:
        if await self._body(request):
            raise StudioError(C.INVALID, "close takes an empty body")
        return web.json_response({"studio": await self._service().close()})

    async def restart(self, request: web.Request) -> web.StreamResponse:
        service = self._service()
        master, discard = parse_restart(await self._body(request))
        return web.json_response({"studio": await service.restart(acknowledged=True, master=master, discard=discard)})
