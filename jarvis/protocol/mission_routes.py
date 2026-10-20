"""Routes HTTP de Core : déclarations de sous-agents et lecture de l'historique des missions (Slice 05).

Handoff jarvis-organic-agent-orchestration. Servies par `LocalProtocolServer`
(jeton porteur exigé par son middleware) ; logique dans
`jarvis/core/mission_history.py` (`MissionHistoryService`, `core.mission_history`).
Contrat : `docs/mission-history.md` › *Routes* et `docs/agent-orchestration.md`.

| Méthode | Route | Réponse |
| --- | --- | --- |
| POST | `/v1/missions/declarations` | `{"declarations": [1..32 × {fact, work_source, work_external_id, parent_work_external_id?}]}` → `{"store_id", "results": [DeclarationResult]}` dans l'ordre |
| GET | `/v1/missions/health` | `HistoryHealth` (état `ok`/`degraded`, écritures en attente, issues comptées) |
| GET | `/v1/missions/{mission_id}` | l'arbre de la mission : missions, instances (statut vivant lu dans Work State, ou `null`), relations, propriétaires |
| GET | `/v1/missions/work/{work_source}/{work_external_id}` | l'instance retenue pour ce travail, ou 404 |

Ingestion : le producteur est le Control Center (`declaration_relay.py`), qui
remet les faits du hook `PreToolUse` (`AgentDeclarationFact` v1) joints à leur
tâche. Enveloppe stricte (400 sinon) ; chaque élément est décodé seul : un champ
inconnu ou un fait hors contrat devient, à sa place, l'issue `refused` de code
`invalid_declaration` (index et règle, jamais la valeur), et les autres éléments
du lot sont enregistrés. Une déclaration valide mais
refusée par un contrat (rôle réécrit, mission inconnue) ou retenue en mode
dégradé n'est pas une erreur HTTP : son issue est dans `results`. Un Mission
Owner ouvre sa mission ici : objectif = libellé de la tâche, mission parente =
celle de son appelant (`MissionOpening(parent_from_caller=True)`) ; un membre
hérite de la mission de son appelant (`inherit_mission`).

`store_id` est celui de Work State : il change à chaque démarrage de Core, et
le relais renvoie alors les déclarations de ses tâches encore vivantes (les
éphémères en attente vivent en mémoire de Core).

Refus : `{"error": {"code", "message"}}` — `invalid_request` 400,
`mission_not_found` / `mission_instance_not_found` 404, `mission_history_unavailable`
503 (magasin indisponible : l'historique est dégradé, le travail vivant continue),
`mission_history_failed` 500. Chaque refus est journalisé
(`core.missions.route_failed`) avec son code, jamais le corps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.domain.mission_history import (
    AgentDeclarationFact, MissionHistoryError, MissionOpening,
)
from jarvis.domain.agent_orchestration import FALLBACK_OBJECTIVE
from jarvis.domain._checks import check_id
from jarvis.ports.mission_history import MissionHistoryStoreError, MissionHistoryUnavailable
from jarvis.protocol.capture_routes import error_response

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PREFIX = "/v1/missions"
#: Déclarations par lot : un tour du cerveau en lance rarement plus de quelques-unes.
MAX_DECLARATION_BATCH = 32
_ITEM_KEYS = frozenset({"fact", "work_source", "work_external_id", "parent_work_external_id"})
ROUTE_FAILED_KIND = "core.missions.route_failed"
DECLARATIONS_KIND = "core.missions.declarations"


def _id(name: str, value: object, *, required: bool) -> str | None:
    try:
        check_id(name, value, required=required)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: {exc}") from exc
    return value if isinstance(value, str) else None


Decoded = tuple[AgentDeclarationFact, str, str, str | None]


def decode_item(index: int, item: object) -> Decoded:
    """Un élément, strictement ; lève `ValueError` nommant l'index et la règle (jamais la valeur)."""

    try:
        if not isinstance(item, dict) or not set(item) <= _ITEM_KEYS or not {"fact", "work_source",
                                                                            "work_external_id"} <= set(item):
            raise ValueError(f"keys must be {sorted(_ITEM_KEYS)}")
        fact = AgentDeclarationFact.from_payload(item["fact"])
        source = _id("work_source", item["work_source"], required=True)
        external = _id("work_external_id", item["work_external_id"], required=True)
        parent = _id("parent_work_external_id", item.get("parent_work_external_id"), required=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"declarations[{index}]: {exc}") from exc
    return fact, source, external, parent


def decode_declarations(body: object) -> list[Decoded | ValueError]:
    """L'enveloppe, strictement (400 sinon) ; chaque élément décodé seul : un élément hors contrat devient son
    erreur, à sa place, et ne fait jamais perdre les déclarations valides du même lot (reprise QA)."""

    if not isinstance(body, dict) or set(body) != {"declarations"}:
        raise ValueError("body must be {\"declarations\": [...]}")
    items = body["declarations"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_DECLARATION_BATCH:
        raise ValueError(f"declarations must be a list of 1..{MAX_DECLARATION_BATCH} items")
    decoded: list[Decoded | ValueError] = []
    for index, item in enumerate(items):
        try:
            decoded.append(decode_item(index, item))
        except ValueError as exc:
            decoded.append(exc)
    return decoded


def opening_for(fact: AgentDeclarationFact) -> MissionOpening | None:
    """La mission qu'ouvre un fait de Mission Owner : objectif = libellé, parente = mission de l'appelant."""

    if not fact.mission_owner:
        return None
    return MissionOpening(objective=fact.label or FALLBACK_OBJECTIVE, parent_from_caller=True,
                          origin_kind=fact.profile or None)


class MissionProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.mission_history`). Voir l'en-tête."""

    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.post(PREFIX + "/declarations", g("declarations", self.declarations)),
            # Segments fixes avant `{mission_id}` : aiohttp résout dans l'ordre d'enregistrement.
            web.get(PREFIX + "/health", g("health", self.health)),
            web.get(PREFIX + "/work/{work_source}/{work_external_id}", g("work", self.for_work)),
            web.get(PREFIX + "/{mission_id}", g("mission", self.mission)),
        ]

    @property
    def _service(self) -> Any:
        return self._core.mission_history

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
                status, code, message = 503, "mission_history_unavailable", str(exc)
            except (MissionHistoryStoreError, MissionHistoryError) as exc:
                status, code, message = 500, getattr(exc, "code", None) or "mission_history_failed", str(exc)
            except LookupError as exc:
                status, code = 404, str(exc.args[0]) if exc.args else "not_found"
                message = str(exc.args[1]) if len(exc.args) > 1 else code
            except ValueError as exc:
                status, code, message = 400, "invalid_request", str(exc)
            except Exception as exc:  # noqa: BLE001 - the route boundary: logged with its type, answered 500
                status, code, message = 500, "mission_history_failed", f"{type(exc).__name__}: {exc}"
            self._emit(ROUTE_FAILED_KIND, f"route des missions refusée : {code}", level="warning" if status < 500
                       else "error", data={"operation": operation, "status": status, "code": code})
            return error_response(status, code, message)

        return run

    async def declarations(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError as exc:
            raise ValueError("body must be JSON") from exc
        batch = decode_declarations(body)
        results = []
        for decoded in batch:
            if isinstance(decoded, ValueError):
                # Refus par élément : la raison (index, règle) revient au relais, le reste du lot est enregistré.
                self._emit(ROUTE_FAILED_KIND, "déclaration de sous-agent hors contrat : élément refusé",
                           level="warning", data={"operation": "declarations", "status": 200,
                                                  "code": "invalid_declaration", "detail": str(decoded)[:200]})
                results.append({"outcome": "refused", "instance_id": None, "code": "invalid_declaration",
                                "message": str(decoded)[:500]})
                continue
            fact, source, external, parent = decoded
            result = await self._service.record_declaration(
                fact, work_source=source, work_external_id=external, parent_work_external_id=parent,
                mission=opening_for(fact), inherit_mission=True,
            )
            results.append(result.to_payload())
        outcomes: dict[str, int] = {}
        for result in results:
            outcomes[result["outcome"]] = outcomes.get(result["outcome"], 0) + 1
        self._emit(DECLARATIONS_KIND, "déclarations de sous-agents reçues", level="info",
                   data={"count": len(results), "outcomes": outcomes})
        return web.json_response({"store_id": self._core.work_state.store_id, "results": results})

    async def health(self, request: web.Request) -> web.Response:
        if request.query:
            raise ValueError("unexpected query parameters")
        # `store_id` de Work State : le relais y reconnaît un Core redémarré même sans rien à envoyer.
        return web.json_response({**self._service.health().to_payload(), "store_id": self._core.work_state.store_id})

    async def mission(self, request: web.Request) -> web.Response:
        mission_id = _id("mission_id", request.match_info["mission_id"], required=True)
        view = await self._service.mission_view(mission_id)
        if view is None:
            raise LookupError("mission_not_found", f"mission {mission_id} is unknown")
        tree, instances = view
        # `live_unknown` : dérivé, jamais persisté — ouverte, mais ni propriétaire ni membre connu de Work State
        # après le délai de grâce. À montrer « état inconnu », jamais « en cours » (Slice 08).
        unknown = self._service.live_unknown(tree)
        return web.json_response({
            "root_mission_id": tree.root_mission_id,
            "missions": [{**mission.to_payload(), "live_unknown": mission.mission_id in unknown}
                         for mission in tree.missions],
            "instances": [instance.to_payload() for instance in instances],
            "relations": [relation.to_payload() for relation in tree.relations],
            "ownership": [change.to_payload() for change in tree.ownership],
            "truncated": tree.truncated,
        })

    async def for_work(self, request: web.Request) -> web.Response:
        source = _id("work_source", request.match_info["work_source"], required=True)
        external = _id("work_external_id", request.match_info["work_external_id"], required=True)
        view = await self._service.instance_for_work(source, external)
        if view is None:
            raise LookupError("mission_instance_not_found", f"no agent instance is recorded for {source}/{external}")
        return web.json_response(view.to_payload())
