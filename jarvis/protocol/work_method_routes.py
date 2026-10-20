"""Routes HTTP de Core : catalogue des Work Methods, candidats appris et promotion explicite (Slice 12).

Handoff jarvis-organic-agent-orchestration. Servies par `LocalProtocolServer`
(jeton porteur exigé par son middleware) ; logique dans
`jarvis/core/work_method_learning.py` (`core.work_method_learning`). Contrat :
`docs/work-methods.md` › *Candidats* et *Promotion*.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/work-methods` | `{"methods": [WorkMethod], "latest": {method_id: key}}` (livrées + promues) |
| GET | `/v1/work-methods/candidates` | `{"candidates": [...], "scan": {...}, "thresholds": {...}}`, recalculés depuis l'historique |
| POST | `/v1/work-methods/promotions` | `{candidate_id, expected_version, promoted_by, method}` → `{"method"}` |

La promotion n'est appelée que par le Control Center, pour une personne
(`promoted_by="user"`) ; aucun outil d'agent ne l'atteint. Refus :
`{"error": {"code", "message"}}` — `invalid_request` 400, `work_method_candidate_unknown` 404,
`work_method_revision_conflict` / `work_method_version_conflict` 409, `work_method_promoter_not_human` 403,
autre refus de contrat (`work_method_*`) 422, magasin indisponible 503, défaut 500. Chaque refus est journalisé
(`core.work_methods.route_failed`) avec son code, jamais le corps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.domain._checks import check_id
from jarvis.domain.work_methods import MethodError
from jarvis.ports.mission_history import MissionHistoryStoreError, MissionHistoryUnavailable
from jarvis.protocol.capture_routes import error_response

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PREFIX = "/v1/work-methods"
ROUTE_FAILED_KIND = "core.work_methods.route_failed"
_PROMOTION_KEYS = frozenset({"candidate_id", "expected_version", "promoted_by", "method"})
_STATUS_OF = {
    "work_method_candidate_unknown": 404,
    "work_method_revision_conflict": 409,
    "work_method_version_conflict": 409,
    "work_method_promoter_not_human": 403,
}


class WorkMethodProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.work_method_learning`)."""

    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(PREFIX, g("catalogue", self.catalogue)),
            web.get(PREFIX + "/candidates", g("candidates", self.candidates)),
            web.post(PREFIX + "/promotions", g("promote", self.promote)),
        ]

    @property
    def _service(self) -> Any:
        return self._core.work_method_learning

    def _emit(self, kind: str, message: str, *, level: str, data: dict[str, Any]) -> None:
        diagnostics = getattr(self._core, "_diagnostics", None)
        if diagnostics is None:
            return
        try:
            diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            pass  # intentional: an unavailable journal never turns a route answer into a failure

    def _guarded(self, operation: str, handler: Handler) -> Handler:
        """Chaque refus devient l'enveloppe codée, journalisée avec son code ; jamais un 500 muet."""

        async def run(request: web.Request) -> web.StreamResponse:
            try:
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except MissionHistoryUnavailable as exc:
                status, code, message = 503, getattr(exc, "code", None) or "work_method_store_failed", str(exc)
            except MissionHistoryStoreError as exc:
                status, code, message = 500, getattr(exc, "code", None) or "work_method_store_unreadable", str(exc)
            except MethodError as exc:
                status, code, message = _STATUS_OF.get(exc.code, 422), exc.code, str(exc)
            except ValueError as exc:
                status, code, message = 400, "invalid_request", str(exc)
            except Exception as exc:  # noqa: BLE001 - the route boundary: logged with its type, answered 500
                status, code, message = 500, "work_methods_failed", f"{type(exc).__name__}: {exc}"
            self._emit(ROUTE_FAILED_KIND, f"route des Work Methods refusée : {code}",
                       level="warning" if status < 500 else "error",
                       data={"operation": operation, "status": status, "code": code})
            return error_response(status, code, message)

        return run

    @staticmethod
    def _no_query(request: web.Request) -> None:
        if request.query:
            raise ValueError("unexpected query parameters")

    async def catalogue(self, request: web.Request) -> web.Response:
        self._no_query(request)
        return web.json_response(await self._service.catalogue())

    async def candidates(self, request: web.Request) -> web.Response:
        self._no_query(request)
        return web.json_response((await self._service.candidates()).to_payload())

    async def promote(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError as exc:
            raise ValueError("body must be JSON") from exc
        if not isinstance(body, dict) or set(body) != _PROMOTION_KEYS:
            raise ValueError(f"body keys must be exactly {sorted(_PROMOTION_KEYS)}")
        try:
            check_id("candidate_id", body["candidate_id"], required=True)
            check_id("promoted_by", body["promoted_by"], required=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        expected = body["expected_version"]
        if type(expected) is not int or expected < 0:
            raise ValueError("expected_version must be a non-negative integer (0: no version yet)")
        if not isinstance(body["method"], dict):
            raise ValueError("method must be an object")
        method = await self._service.promote(body["candidate_id"], body["method"], expected_version=expected,
                                             promoted_by=body["promoted_by"])
        return web.json_response({"method": method.to_payload()})
