"""Routes de Core : rendu et export d'une présentation gelée (handoff jarvis-remotion-presentation-integration, Slice 16 ; `docs/remotion-render.md`).

Sous le préfixe frère `/v1/local-capabilities/remotion/render` (un rendu est un travail de la capacité locale Remotion, comme le Studio) ; jeton
porteur de Core obligatoire. Le chemin `.../render/jobs` a au moins quatre segments : il ne rencontre jamais `/{capability_id}/{operation}`.

| Méthode | Route | Corps | Réponse |
| --- | --- | --- | --- |
| GET | `/v1/local-capabilities/remotion/render` | — | `{render: {ready, reason, browser, concurrency, max_queued}}` (lecture seule, ne lance rien) |
| GET | `.../render/jobs` | — | `{jobs: [vue]}` (les plus récents d'abord) |
| POST | `.../render/jobs` | voir ci-dessous | 202 `{job: vue}` : le travail est en file, l'Artifact dérivé existe `pending` |
| GET | `.../render/jobs/{job_id}` | — | `{job: vue}` : état, phase, images faites / total, secondes écoulées, délai, annulable |
| POST | `.../render/jobs/{job_id}/cancel` | `{}` | `{job: vue}` |

Corps d'une demande : `{"format": "mp4"|"still"|"pdf", "settings": {...}}` plus, au choix, `{"snapshot_id": "jart_ps_..."}` (rendre un snapshot déjà figé)
OU `{"presentation_id", "variant_id", "expected_presentation_revision", "expected_variant_revision", "authorised_boards": [...]}` (figer cette
variante, rejouable, puis la rendre ; `authorised_boards` absent = aucun Board lu). Aucun outil MCP, aucun chemin du cerveau : l'exportation est
une action explicite de l'utilisateur.

Refus : `{"error": {"code", "message"}}` ; codes `presentation_render_*` (400 invalide, 404 inconnu, 409 non prêt ou snapshot refusé, 429 file pleine,
503 Core sans rendu) et les codes des registres traversés (`stale_revision`, `live_ref_*`, `artifact_*`). Un ÉCHEC de rendu n'est pas une erreur
HTTP : c'est la vue du travail (`state: failed`, `error_code`, `error_detail`) et l'Artifact dérivé `failed`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Any

from aiohttp import web

from jarvis.domain.artifacts import ArtifactError
from jarvis.domain.presentation_live_refs import LiveRefError
from jarvis.domain.presentation_render import RenderError, RenderErrorCode as C
from jarvis.domain.presentation_studio import PresentationStudioError

PREFIX = "/v1/local-capabilities/remotion/render"
MAX_BODY_BYTES = 8192
SNAPSHOT_KEYS = frozenset({"format", "settings", "snapshot_id"})
EXPORT_KEYS = frozenset({"format", "settings", "presentation_id", "variant_id", "expected_presentation_revision",
                         "expected_variant_revision", "authorised_boards"})
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class PresentationRenderProtocolRoutes:
    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        jobs = PREFIX + "/jobs"
        return [web.get(PREFIX, g(self.availability)), web.get(jobs, g(self.list)), web.post(jobs, g(self.create)),
                web.get(jobs + "/{job_id}", g(self.get)), web.post(jobs + "/{job_id}/cancel", g(self.cancel))]

    def _guarded(self, handler: Handler) -> Handler:
        async def run(request: web.Request) -> web.StreamResponse:
            try:
                if request.query:
                    raise RenderError(C.INVALID, "unexpected query parameters")
                return await handler(request)
            except RenderError as exc:
                self._report(exc, request, level="warning" if exc.status < 500 else "error")
                return self._error(exc.code.value, exc.detail or exc.code.value, exc.status)
            except (ArtifactError, PresentationStudioError, LiveRefError) as exc:
                status = getattr(exc, "status", None) or getattr(exc, "http_status", None) or (409 if isinstance(exc, LiveRefError) else 400)
                code = getattr(getattr(exc, "code", None), "value", "presentation_render_failed")
                self._report(exc, request, level="warning")
                body = {"error": {"code": code, "message": str(exc)[:300]}}
                details = getattr(exc, "details", None)
                if details:
                    body["error"]["details"] = [dict(item) for item in details][:20]
                return web.json_response(body, status=int(status))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - jamais un défaut muet : journalisé durablement (niveau error), 500 codé
                self._report(exc, request, level="error")
                return self._error(C.INTERNAL.value, f"unexpected {type(exc).__name__}", 500)
        return run

    def _report(self, exc: BaseException, request: web.Request, *, level: str) -> None:
        diagnostics = getattr(self._core, "diagnostics", None) or getattr(self._core, "_diagnostics", None)
        if diagnostics is not None:
            try:
                diagnostics.emit("presentation_render.route_failed", f"{request.method} {request.path}: {type(exc).__name__}", level=level,
                                 data={"exception": type(exc).__name__, "code": str(getattr(getattr(exc, "code", None), "value", ""))})
            except Exception:  # noqa: BLE001 - intentional: an unavailable journal never changes the answer
                pass

    @staticmethod
    def _error(code: str, message: str, status: int) -> web.Response:
        return web.json_response({"error": {"code": code, "message": message}}, status=status)

    def _service(self):
        service = getattr(self._core, "presentation_render", None)
        if service is None:
            raise RenderError(C.UNAVAILABLE, "this Core has no presentation render service (no local capability store)")
        return service

    @staticmethod
    async def _body(request: web.Request) -> dict[str, Any]:
        raw = await request.read()
        if len(raw) > MAX_BODY_BYTES:
            raise RenderError(C.INVALID, "the request body is too large")
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except ValueError:
            raise RenderError(C.INVALID, "the request body is not JSON") from None
        if not isinstance(body, dict):
            raise RenderError(C.INVALID, "the request body must be a JSON object")
        return body

    async def availability(self, request: web.Request) -> web.StreamResponse:
        return web.json_response({"render": self._service().availability()})

    async def list(self, request: web.Request) -> web.StreamResponse:
        return web.json_response({"jobs": self._service().jobs()})

    async def get(self, request: web.Request) -> web.StreamResponse:
        return web.json_response({"job": self._service().get(request.match_info["job_id"])})

    async def cancel(self, request: web.Request) -> web.StreamResponse:
        if await self._body(request):
            raise RenderError(C.INVALID, "cancel takes an empty body")
        return web.json_response({"job": await self._service().cancel(request.match_info["job_id"])})

    async def create(self, request: web.Request) -> web.StreamResponse:
        service = self._service()
        body = await self._body(request)
        fmt = body.get("format")
        if not isinstance(fmt, str):
            raise RenderError(C.INVALID, "format is required: mp4, still or pdf")
        if "snapshot_id" in body:
            self._only(body, SNAPSHOT_KEYS)
            snapshot_id = body["snapshot_id"]
            if not isinstance(snapshot_id, str):
                raise RenderError(C.INVALID, "snapshot_id must be a string")
            job = await service.submit(snapshot_id, fmt, body.get("settings"))
        else:
            self._only(body, EXPORT_KEYS)
            missing = sorted(k for k in EXPORT_KEYS - {"settings", "authorised_boards"} - {"format"} if k not in body)
            if missing:
                raise RenderError(C.INVALID, f"pass snapshot_id, or all of {missing}")
            boards = body.get("authorised_boards", [])
            if not isinstance(boards, list) or any(not isinstance(item, str) for item in boards):
                raise RenderError(C.INVALID, "authorised_boards must be a list of Board ids")
            revisions = (body["expected_presentation_revision"], body["expected_variant_revision"])
            if any(type(v) is not int for v in revisions) or not all(isinstance(body[k], str) for k in ("presentation_id", "variant_id")):
                raise RenderError(C.INVALID, "presentation_id and variant_id are strings, the expected revisions are integers")
            job = await service.export(
                presentation_id=body["presentation_id"], variant_id=body["variant_id"], expected_presentation_revision=revisions[0],
                expected_variant_revision=revisions[1], authorised_boards=boards, render_format=fmt, settings=body.get("settings"))
        return web.json_response({"job": job}, status=202)

    @staticmethod
    def _only(body: dict[str, Any], allowed: frozenset[str]) -> None:
        extra = sorted(str(key)[:40] for key in body if key not in allowed)
        if extra:
            raise RenderError(C.INVALID, f"unknown fields {extra[:5]} for this request")
