"""Routes d'inspection du workspace du Control Center : relais de Core (handoff board-memory-workspace-inspector, Slice 04).

Core possède Sessions, Boards, liaisons, Contexts, Artifacts et mémoire de
Board ; l'API est `jarvis/protocol/workspace_routes.py`. Le Control Center
n'en garde **rien** : `/api/workspace/<reste>` est relayé tel quel vers
`/v1/workspace/<reste>` (même mécanique que `capture_relay.py` : paramètres
paire par paire, chaque paramètre de route ré-encodé, statut et corps JSON de
Core rendus tels quels, erreurs comprises ; Core injoignable 503
`core_unreachable` / `core_unconfigured`, délai 504 `core_timeout`). Lecture
seule : seules des routes `GET` existent.

**Garde.** `/api/workspace` est dans `READ_GUARDED_ROUTES` du Control Center :
la mémoire des Boards, les titres de Contexts et la provenance des Artifacts
sont aussi sensibles en lecture qu'en écriture.

**Journal.** Une panne de Core : `workspace.request.core_unreachable`.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.runtime.capture_relay import CaptureRelayRoutes

WORKSPACE_ROUTE = "/api/workspace"
GUARDED_PREFIXES = (WORKSPACE_ROUTE,)
#: Parcours de la mémoire sur disque (QA S02 : une recherche bornée a pris 2 à 9 s) : plus que les 10 s
#: par défaut du transport.
DISK_TIMEOUT_S = 30.0

#: (action, chemin relatif sous `/api/workspace` et `/v1/workspace`, délai) ; tout `GET`.
_ROUTES = (
    ("workspace_sessions", "/sessions", None),
    ("workspace_session", "/sessions/{session_id}", None),
    ("workspace_activity", "/sessions/{session_id}/activity", None),
    ("workspace_board", "/boards/{board_id}", DISK_TIMEOUT_S),
    ("workspace_relations", "/relations", None),
    ("workspace_artifacts", "/artifacts", None),
    ("workspace_artifact_relations", "/artifacts/{artifact_id}/relations", None),
    ("workspace_memory_tree", "/boards/{board_id}/memory/tree", DISK_TIMEOUT_S),
    ("workspace_memory_stat", "/boards/{board_id}/memory/stat", None),
    ("workspace_memory_read", "/boards/{board_id}/memory/read", DISK_TIMEOUT_S),
    ("workspace_memory_search", "/boards/{board_id}/memory/search", DISK_TIMEOUT_S),
)


class WorkspaceRelayRoutes(CaptureRelayRoutes):
    """Relais `GET /api/workspace/*` -> `GET /v1/workspace/*`. Voir l'en-tête."""

    JOURNAL_PREFIX = "workspace.request"

    def routes(self) -> list[web.RouteDef]:
        return [web.get(WORKSPACE_ROUTE + path, self._relay(action, "/v1/workspace" + path, timeout_s))
                for action, path, timeout_s in _ROUTES]
