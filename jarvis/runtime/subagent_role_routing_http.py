"""Handlers aiohttp de la politique par rôle — **non montés** : la Slice 07 les enregistre.

Routes prévues (contrat : `docs/subagent-roles.md` § 10) :

- `GET    /api/subagent-role-routing` : lecture (`subagent_role_routing.describe`) ;
- `PUT    /api/subagent-role-routing/{role_id}` : `{"base_revision", "candidates", "allow_general_fallback"}` ;
- `DELETE /api/subagent-role-routing/{role_id}?base_revision=…` : restauration à l'héritage.

Réponse d'une écriture : `200 {"ok": true, "snapshot": {…}}` (lecture complète faisant foi) ; refus :
`{"ok": false, "code", "reason", "snapshot"}` — `409` révision périmée, `404` rôle inconnu, `422`
liste invalide, `400` corps illisible, `500` fichier illisible ou écriture impossible (rien n'a changé).

Les dépendances sont injectées : `settings()` rend le dict de `control-center-settings.json` (pour la
politique par profil héritée et l'interrupteur Auto/Dupliqué) ; `candidates()` rend les candidats
mesurés et les raisons par agent, comme `/api/routing/candidates`.
"""

from __future__ import annotations

from json import JSONDecodeError
from typing import Any, Awaitable, Callable, Mapping, Sequence

from aiohttp import web

from jarvis.domain.routing import ModelCandidate, RoutingError
from jarvis.runtime import agent_routing, subagent_role_routing as store_module
from jarvis.runtime.subagent_role_routing import RoleRoutingStore

ROUTE = "/api/subagent-role-routing"
ROLE_ROUTE = ROUTE + "/{role_id}"

CandidatesProvider = Callable[[], Awaitable[tuple[Sequence[ModelCandidate], Mapping[str, str]]]]

_STATUS = {
    store_module.STALE_CODE: 409,
    store_module.UNKNOWN_ROLE_CODE: 404,
    store_module.BAD_PAYLOAD_CODE: 400,
    store_module.NOT_EXPLICIT_CODE: 409,
    store_module.UNREADABLE_CODE: 500,
    store_module.WRITE_FAILED_CODE: 500,
}
#: Refus de validation des candidats (codes partagés avec `agent_routing`) et liste vide.
_UNPROCESSABLE = 422


class SubagentRoleRoutingApi:
    def __init__(self, store: RoleRoutingStore, *, settings: Callable[[], Mapping[str, Any]],
                 candidates: CandidatesProvider, journal: Any) -> None:
        self.store = store
        self._settings = settings
        self._candidates = candidates
        self.journal = journal

    def routes(self) -> list[web.RouteDef]:
        return [web.get(ROUTE, self.get), web.put(ROLE_ROUTE, self.put), web.delete(ROLE_ROUTE, self.delete)]

    async def snapshot(self) -> dict[str, Any]:
        """La lecture complète. Ne lève pas : un catalogue en panne laisse les rôles lisibles."""
        loaded = self.store.load()
        profiles = agent_routing.load_policy(self._settings())
        catalog_error = ""
        measured: Sequence[ModelCandidate] = ()
        reasons: Mapping[str, str] = {}
        try:
            measured, reasons = await self._candidates()
        except Exception as exc:  # noqa: BLE001 - capture : la politique reste lisible sans catalogue
            catalog_error = f"Catalogue des candidats indisponible ({type(exc).__name__}) : disponibilité non mesurée."
            self._emit("subagent_role_routing.catalog_failed", catalog_error, level="error",
                       data={"code": "role_routing_catalog_failed", "exception_type": type(exc).__name__})
            reasons = {"*": catalog_error}
        enriched = store_module.enrich(measured, profiles, loaded.document,
                                       unavailable_reasons_by_agent=_ReasonsForAll(reasons))
        return store_module.describe(loaded.document, profiles, enriched,
                                     store_error=(loaded.error_code, loaded.error_reason),
                                     catalog_error=catalog_error)

    async def get(self, request: web.Request) -> web.Response:
        del request
        payload = await self.snapshot()
        self._emit("subagent_role_routing.read", "Politique des rôles lue.",
                   data={"code": "role_routing_read", "revision": payload["revision"],
                         "explicit_roles": [role["role_id"] for role in payload["roles"] if role["explicit"]]})
        return web.json_response(payload)

    async def put(self, request: web.Request) -> web.Response:
        role_id = request.match_info.get("role_id", "")
        try:
            body = await request.json()
        except (JSONDecodeError, UnicodeDecodeError, ValueError):
            return await self._refuse(RoutingError(store_module.BAD_PAYLOAD_CODE, "Corps JSON illisible."), role_id, "put")
        if not isinstance(body, Mapping):
            return await self._refuse(RoutingError(store_module.BAD_PAYLOAD_CODE, "Le corps doit être un objet."), role_id, "put")
        try:
            document = self.store.put(role_id, body, body.get("base_revision"))
        except RoutingError as exc:
            return await self._refuse(exc, role_id, "put")
        return await self._saved("subagent_role_routing.saved", role_id, document.revision, "put")

    async def delete(self, request: web.Request) -> web.Response:
        role_id = request.match_info.get("role_id", "")
        try:
            document = self.store.restore(role_id, request.query.get("base_revision"))
        except RoutingError as exc:
            return await self._refuse(exc, role_id, "restore")
        return await self._saved("subagent_role_routing.restored", role_id, document.revision, "restore")

    async def _saved(self, kind: str, role_id: str, revision: int, action: str) -> web.Response:
        self._emit(kind, f"Politique du rôle « {role_id} » : {action} accepté.",
                   data={"code": f"role_routing_{action}", "role_id": role_id,
                         "revision": store_module.format_revision(revision)})
        return web.json_response({"ok": True, "applies": store_module.APPLIES, "snapshot": await self.snapshot()})

    async def _refuse(self, exc: RoutingError, role_id: str, action: str) -> web.Response:
        status = _STATUS.get(exc.code, _UNPROCESSABLE)
        level = "error" if status >= 500 else "warning"
        self._emit("subagent_role_routing.rejected", f"Politique du rôle « {role_id} » refusée : {exc}", level=level,
                   data={"code": exc.code, "role_id": role_id[:24], "action": action, "status": status})
        return web.json_response(
            {"ok": False, "code": exc.code, "reason": str(exc), "snapshot": await self.snapshot()}, status=status,
        )

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any]) -> None:
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except OSError:
            # intentionnel : une trace impossible à écrire ne doit pas faire échouer la réponse servie.
            pass


class _ReasonsForAll(dict):
    """Raisons par agent ; la clé `*` vaut pour tous (catalogue entier indisponible)."""

    def get(self, key: object, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(key) or super().get("*") or default
