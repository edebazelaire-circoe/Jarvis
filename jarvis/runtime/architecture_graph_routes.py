"""Routes HTTP du graphe d'architecture, montées par le Control Center (`_install_architecture_services`, Slice 07).

| Route | Effet |
| --- | --- |
| `GET /api/architecture` | snapshot faisant foi (le snapshot lui-même, sans enveloppe) |
| `POST /api/architecture/connections/{id}` `{"base_revision", "enabled"}` | bascule une liaison |
| `POST /api/architecture/connections` `{"base_revision", "source", "target", "channel"}` | création (refusée tant qu'aucune liaison créable n'existe) |
| `DELETE /api/architecture/connections/{id}?base_revision=` | suppression (idem) |
| `GET/PUT /api/architecture/layout` `{"base_revision", "positions"}` | disposition, interface seule |

Succès : `200 {"ok": true, "snapshot": {…}}` (et `"changed"`). Refus : `{"ok": false, "code", "reason",
"snapshot"}` avec le statut du code (`ERROR_STATUS`). Contrat : docs/architecture-graph.md.
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from jarvis.domain.architecture_graph import APPLY_FAILED, REQUEST_INVALID, ArchitectureGraphError
from jarvis.runtime.architecture_graph import ArchitectureGraphService
from jarvis.runtime.architecture_layout import ArchitectureLayoutStore

ARCHITECTURE_ROUTE = "/api/architecture"
CONNECTIONS_ROUTE = f"{ARCHITECTURE_ROUTE}/connections"
LAYOUT_ROUTE = f"{ARCHITECTURE_ROUTE}/layout"
SNAPSHOT_FAILED = "architecture_snapshot_failed"
MAX_BODY_BYTES = 64 * 1024


class ArchitectureGraphRoutes:
    def __init__(self, service: ArchitectureGraphService, layout: ArchitectureLayoutStore, *, journal: Any = None):
        self.service, self.layout, self.journal = service, layout, journal

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get(ARCHITECTURE_ROUTE, self.get_snapshot),
            web.post(CONNECTIONS_ROUTE, self.create_connection),
            web.post(CONNECTIONS_ROUTE + "/{connection_id}", self.toggle_connection),
            web.delete(CONNECTIONS_ROUTE + "/{connection_id}", self.delete_connection),
            web.get(LAYOUT_ROUTE, self.get_layout),
            web.put(LAYOUT_ROUTE, self.put_layout),
        ]

    async def get_snapshot(self, _request: web.Request) -> web.Response:
        try:
            return web.json_response(self.service.snapshot().to_dict())  # doc 11 : le snapshot, sans enveloppe
        except Exception as exc:  # noqa: BLE001 - capture: the route answers a coded failure, never a traceback
            self._emit("architecture.snapshot.failed", "Snapshot d'architecture impossible",
                       {"error_class": type(exc).__name__, "error": str(exc)[:300]}, level="error")
            return web.json_response({"ok": False, "code": SNAPSHOT_FAILED,
                                      "reason": f"Lecture de l'architecture impossible : {type(exc).__name__}: {exc}",
                                      "snapshot": None}, status=500)

    async def toggle_connection(self, request: web.Request) -> web.Response:
        conn_id = request.match_info["connection_id"]
        return await self._write(request, "toggle", conn_id, lambda body: self.service.set_connection_enabled(
            conn_id, base_revision=body.get("base_revision"), enabled=body.get("enabled")))

    async def create_connection(self, request: web.Request) -> web.Response:
        return await self._write(request, "create", None, lambda body: self.service.create_connection(
            base_revision=body.get("base_revision"), source=body.get("source"), target=body.get("target"),
            channel=body.get("channel")))

    async def delete_connection(self, request: web.Request) -> web.Response:
        conn_id = request.match_info["connection_id"]
        base = request.query.get("base_revision")
        return await self._write(request, "delete", conn_id, lambda _body: self.service.delete_connection(
            conn_id, base_revision=base), body_required=False)

    async def get_layout(self, _request: web.Request) -> web.Response:
        return web.json_response({"ok": True, **self.layout.read().to_dict()})

    async def put_layout(self, request: web.Request) -> web.Response:
        try:
            body = await self._body(request)
            document = self.layout.write(base_revision=body.get("base_revision"), positions=body.get("positions"))
        except ArchitectureGraphError as exc:
            self._emit("architecture.layout.refused", "Disposition refusée", {"code": exc.code}, level="warning")
            return web.json_response({"ok": False, "code": exc.code, "reason": exc.reason,
                                      **self.layout.read().to_dict()}, status=exc.status)
        return web.json_response({"ok": True, **document.to_dict()})

    async def _write(self, request: web.Request, action: str, conn_id: str | None, operation,
                     *, body_required: bool = True) -> web.Response:
        context = {"action": action, "connection_id": conn_id}
        try:
            body = await self._body(request) if body_required else {}
            result = operation(body)
        except ArchitectureGraphError as exc:
            self._emit("architecture.write.refused", "Écriture d'architecture refusée",
                       {**context, "code": exc.code, "status": exc.status},
                       level="error" if exc.status >= 500 else "warning")
            return web.json_response({"ok": False, "code": exc.code, "reason": exc.reason,
                                      "snapshot": self._snapshot_or_none()}, status=exc.status)
        except Exception as exc:  # noqa: BLE001 - capture: unexpected failure, coded and logged, nothing assumed
            self._emit("architecture.write.failed", "Écriture d'architecture en échec inattendu",
                       {**context, "error_class": type(exc).__name__, "error": str(exc)[:300]}, level="error")
            return web.json_response({"ok": False, "code": APPLY_FAILED,
                                      "reason": f"Échec inattendu : {type(exc).__name__}: {exc}",
                                      "snapshot": self._snapshot_or_none()}, status=500)
        return web.json_response({"ok": True, "changed": result.changed, "snapshot": result.snapshot.to_dict()})

    @staticmethod
    async def _body(request: web.Request) -> dict[str, Any]:
        if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
            raise ArchitectureGraphError(REQUEST_INVALID, "Corps de requête trop long.")
        try:
            body = json.loads(await request.text() or "null")
        except ValueError as exc:
            raise ArchitectureGraphError(REQUEST_INVALID, "Corps JSON illisible.") from exc
        if not isinstance(body, dict):
            raise ArchitectureGraphError(REQUEST_INVALID, "Le corps doit être un objet JSON.")
        return body

    def _snapshot_or_none(self) -> dict[str, object] | None:
        try:
            return self.service.snapshot().to_dict()
        except Exception as exc:  # noqa: BLE001 - capture: the refusal is still answered, without a snapshot
            self._emit("architecture.snapshot.failed", "Snapshot d'architecture impossible après un refus",
                       {"error_class": type(exc).__name__}, level="error")
            return None

    def _emit(self, kind: str, message: str, data: dict, *, level: str = "info") -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001
            pass  # argued: journal delivery is evidence, never authority over the HTTP answer
