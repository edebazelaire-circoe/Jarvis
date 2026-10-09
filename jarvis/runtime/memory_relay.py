"""Relais `/api/memory/brain/*` du Control Center vers Core (handoff jarvis-memory-intelligence-knowledge, Slice 05b).

Le serveur MCP `jarvis-memory` (`memory_mcp.py`) parle au Control Center, comme `jarvis-workspace` ; Core possède
tout (budget de 3 appels par tour, politique de portée du cerveau, candidats). Ce relais ne garde rien : même
mécanique que `workspace_relay.py` (`CaptureRelayRoutes._relay`, paramètres paire par paire, statut et corps de
Core rendus tels quels, Core injoignable 503, délai 504).

| Control Center | Core |
| --- | --- |
| `GET /api/memory/brain/search` | `GET /v1/memory/brain/search` |
| `GET /api/memory/brain/notes/{memory_id}` | `GET /v1/memory/brain/notes/{memory_id}` |
| `POST /api/memory/brain/candidates` | `POST /v1/memory/candidates` |
| `GET /api/memory/brain/knowledge/search` | `GET /v1/memory/brain/knowledge/search` |
| `GET /api/memory/brain/knowledge/{kind}/{asset_id}` | `GET /v1/memory/brain/knowledge/{kind}/{asset_id}` |

**Garde.** `/api/memory/brain` est dans `READ_GUARDED_ROUTES` : toutes les méthodes exigent un Host de bouclage et
jamais `Sec-Fetch-Site: cross-site` (la mémoire personnelle est aussi sensible en lecture qu'en écriture). Les
routes du Memory Center (`/api/memory*`, Slice 10b) sont à part.
"""

from __future__ import annotations

from aiohttp import web

from jarvis.runtime.capture_relay import CaptureRelayRoutes

MEMORY_BRAIN_ROUTE = "/api/memory/brain"
GUARDED_PREFIXES = (MEMORY_BRAIN_ROUTE,)
#: Un candidat proposé : titre, corps (4 000 caractères), quelques champs.
MAX_PROPOSAL_BODY_BYTES = 32 * 1024

_ROUTES = (
    ("GET", "memory_brain_search", "/search", "/v1/memory/brain/search"),
    ("GET", "memory_brain_read", "/notes/{memory_id}", "/v1/memory/brain/notes/{memory_id}"),
    ("POST", "memory_brain_propose", "/candidates", "/v1/memory/candidates"),
    ("GET", "memory_brain_knowledge_search", "/knowledge/search", "/v1/memory/brain/knowledge/search"),
    ("GET", "memory_brain_knowledge_read", "/knowledge/{kind}/{asset_id}",
     "/v1/memory/brain/knowledge/{kind}/{asset_id}"),
)


class MemoryBrainRelayRoutes(CaptureRelayRoutes):
    """Relais `/api/memory/brain/*` -> Core. Voir l'en-tête."""

    JOURNAL_PREFIX = "memory.request"
    MAX_BODY_BYTES = MAX_PROPOSAL_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [web.route(method, MEMORY_BRAIN_ROUTE + path, self._relay(action, core, None))
                for method, action, path, core in _ROUTES]
