"""Routes du workspace du Control Center : relais de Core (handoff board-memory-workspace-inspector, Slices 04-05).

Core possède Sessions, Boards, liaisons, Contexts, Artifacts et mémoire de
Board ; l'API est `jarvis/protocol/workspace_routes.py`. Le Control Center
n'en garde **rien** : `/api/workspace/<reste>` est relayé tel quel vers
`/v1/workspace/<reste>` (même mécanique que `capture_relay.py` : paramètres
paire par paire, chaque paramètre de route ré-encodé, statut et corps JSON de
Core rendus tels quels, erreurs comprises ; Core injoignable 503
`core_unreachable` / `core_unconfigured`, délai 504 `core_timeout` — pour une
mutation l'issue est alors **inconnue** : relire l'arbre ou l'activité).

Lectures (`GET`, Slice 04) et mutations (`POST` / `DELETE`, Slice 05 : mémoire
d'un Board et liens Board-artifact explicites). Corps relayé borné à
`MAX_MUTATION_BODY_BYTES` (la borne de Core), lu en entier.

**Garde.** `/api/workspace` est dans `READ_GUARDED_ROUTES` du Control Center :
**toutes** les méthodes, lecture comme écriture, exigent un Host de bouclage,
un Origin de bouclage s'il existe et jamais `Sec-Fetch-Site: cross-site` —
strictement plus que la garde d'écriture générique (Origin seul) de
`/api/boards`. La mémoire des Boards, les titres de Contexts et la provenance
des Artifacts sont aussi sensibles en lecture qu'en écriture.

**Journal.** Chaque mutation relayée : `workspace.request.relayed` (action,
statut, code), jamais un corps. Une panne de Core :
`workspace.request.core_unreachable`.
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from aiohttp import web

from jarvis.core.workspace_service import MAX_MUTATION_BODY_BYTES
from jarvis.runtime.capture_relay import PAYLOAD_TIMEOUT_S, CaptureRelayRoutes, _error

WORKSPACE_ROUTE = "/api/workspace"
GUARDED_PREFIXES = (WORKSPACE_ROUTE,)
#: Parcours de la mémoire sur disque (QA S02 : une recherche bornée a pris 2 à 9 s) : plus que les 10 s
#: par défaut du transport. Une suppression récursive (jusqu'à 10 000 entrées) aussi.
DISK_TIMEOUT_S = 30.0

#: (méthode, action, chemin relatif sous `/api/workspace` et `/v1/workspace`, délai).
_ROUTES = (
    ("GET", "workspace_sessions", "/sessions", None),
    ("GET", "workspace_session", "/sessions/{session_id}", None),
    ("GET", "workspace_activity", "/sessions/{session_id}/activity", None),
    ("GET", "workspace_board", "/boards/{board_id}", DISK_TIMEOUT_S),
    ("GET", "workspace_relations", "/relations", None),
    ("GET", "workspace_artifacts", "/artifacts", None),
    ("GET", "workspace_artifact_relations", "/artifacts/{artifact_id}/relations", None),
    ("GET", "workspace_presentation_sources", "/boards/{board_id}/presentation-sources", None),
    ("GET", "workspace_presentation_source", "/presentation-sources/{presentation_id}", None),
    ("GET", "workspace_memory_tree", "/boards/{board_id}/memory/tree", DISK_TIMEOUT_S),
    ("GET", "workspace_memory_stat", "/boards/{board_id}/memory/stat", None),
    ("GET", "workspace_memory_read", "/boards/{board_id}/memory/read", DISK_TIMEOUT_S),
    ("GET", "workspace_memory_search", "/boards/{board_id}/memory/search", DISK_TIMEOUT_S),
    ("POST", "workspace_memory_write", "/boards/{board_id}/memory/write", DISK_TIMEOUT_S),
    ("POST", "workspace_memory_mkdir", "/boards/{board_id}/memory/mkdir", DISK_TIMEOUT_S),
    ("POST", "workspace_memory_move", "/boards/{board_id}/memory/move", DISK_TIMEOUT_S),
    ("POST", "workspace_memory_delete", "/boards/{board_id}/memory/delete", DISK_TIMEOUT_S),
    ("POST", "workspace_artifact_link", "/boards/{board_id}/artifacts/{artifact_id}", None),
    ("DELETE", "workspace_artifact_unlink", "/boards/{board_id}/artifacts/{artifact_id}", None),
    # Dossier (wheel-dossier-refactor, Slice 05) : liste, entrée, source durable, Ranger, Afficher sur le Board.
    ("GET", "workspace_dossier", "/boards/{board_id}/dossier", DISK_TIMEOUT_S),
    ("GET", "workspace_dossier_entry", "/boards/{board_id}/dossier/entry", None),
    ("GET", "workspace_dossier_backing", "/boards/{board_id}/dossier/backing", None),
    ("POST", "workspace_dossier_ranger", "/boards/{board_id}/dossier/ranger", DISK_TIMEOUT_S),
    ("POST", "workspace_dossier_present", "/boards/{board_id}/dossier/present", None),
)


class WorkspaceRelayRoutes(CaptureRelayRoutes):
    """Relais `/api/workspace/*` -> `/v1/workspace/*` (même méthode). Voir l'en-tête."""

    JOURNAL_PREFIX = "workspace.request"
    MAX_BODY_BYTES = MAX_MUTATION_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [*(web.route(method, WORKSPACE_ROUTE + path, self._relay(action, "/v1/workspace" + path, timeout_s))
                  for method, action, path, timeout_s in _ROUTES),
                web.get(WORKSPACE_ROUTE + "/boards/{board_id}/memory/image", self.memory_image)]

    async def memory_image(self, request: web.Request) -> web.Response:
        """`GET /api/workspace/boards/{id}/memory/image?path=` : octets d'une image de la mémoire, pour la grille du Dossier
        (2026-10-29). Relais binaire borné (`forward_bytes`), même garde que le reste de `/api/workspace`."""

        if set(request.query) != {"path"} or len(request.query.getall("path")) != 1:
            return _error(400, "invalid_request", "exactly one path parameter is expected")
        transport = self._transport()
        if transport is None:
            return _error(503, "core_unconfigured", "the control center does not know Core")
        path = (f"/v1/workspace/boards/{quote(request.match_info['board_id'], safe='')}/memory/image"
                f"?path={quote(request.query['path'], safe='')}")
        try:
            status, headers, data = await transport.forward_bytes(path, timeout_s=PAYLOAD_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            self._unreachable("workspace_memory_image", "GET", path, "core_timeout", "TimeoutError")
            return _error(504, "core_timeout", "Core did not send the image in time")
        except ValueError as exc:
            return _error(400 if "only relays" in str(exc) else 502, "invalid_request" if "only relays" in str(exc)
                          else "payload_too_large_for_relay", str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 - surfaced: 503 with the real cause, and journaled
            self._unreachable("workspace_memory_image", "GET", path, "core_unreachable", type(exc).__name__)
            return _error(503, "core_unreachable", f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}")
        return web.Response(body=data, status=status, headers=headers)
