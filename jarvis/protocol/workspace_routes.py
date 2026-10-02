"""Routes HTTP de Core : inspection du workspace (handoff board-memory-workspace-inspector, Slice 04, R4).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ;
logique dans `jarvis/core/workspace_service.py` (`WorkspaceService`). Le
Control Center les relaie sous `/api/workspace/...`
(`jarvis/runtime/workspace_relay.py`). **Lecture seule** : aucune route ne
bascule de Board, n'écrit une Session, une liaison, l'autorité de parole ni le
ledger, et aucune ne crée la mémoire d'un Board. Contrat : `docs/boards.md` ›
*Workspace inspection API*.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/workspace/sessions[?cursor&limit]` | Sessions ouvertes et closes, la plus récente d'abord |
| GET | `/v1/workspace/sessions/{session_id}` | Session, Boards (visités, actif, liaisons), Contexts, `problems` |
| GET | `/v1/workspace/sessions/{session_id}/activity[?cursor&limit&kind]` | ledger de cette Session (toute Session) |
| GET | `/v1/workspace/boards/{board_id}` | Board (archivé compris), liaisons, mémoire résumée, liens, refs héritées |
| GET | `/v1/workspace/relations?session_id=\\|board_id=` | relations d'une Session ou d'un Board |
| GET | `/v1/workspace/artifacts?board_id=\\|session_id=\\|context_id=[&kind&since&until&cursor&limit]` | Artifacts d'une portée |
| GET | `/v1/workspace/artifacts/{artifact_id}/relations` | provenance et Boards liés |
| GET | `/v1/workspace/boards/{board_id}/memory/tree[?path&depth&max_entries]` | arbre borné |
| GET | `/v1/workspace/boards/{board_id}/memory/stat?path=` | une entrée |
| GET | `/v1/workspace/boards/{board_id}/memory/read?path=[&offset&max_bytes]` | texte UTF-8 borné |
| GET | `/v1/workspace/boards/{board_id}/memory/search?q=[&path&limit]` | recherche littérale bornée |

Refus : `{"error": {"code", "message"}}`, code stable du domaine et son
statut (`board_not_found` 404, `session_not_found` 404, `artifact_not_found`
404, `context_not_found` 404, `memory_*`, `invalid_board` 400,
`invalid_request` 400, `core_unavailable` 503, `board_memory_unsafe` /
`board_memory_failed` / `board_store_*` 500, `workspace_failed` 500) ;
message sans chemin absolu (`redact_paths`). Chaque refus est journalisé
(`core.workspace.read_failed`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.capture_api import EvidenceApiError
from jarvis.core.workspace_service import (
    DEFAULT_ACTIVITY_LIMIT, DEFAULT_ARTIFACT_LIMIT, DEFAULT_READ_BYTES, DEFAULT_SEARCH_LIMIT, DEFAULT_SESSION_LIMIT,
    DEFAULT_TREE_DEPTH, DEFAULT_TREE_ENTRIES, MAX_PAGE_LIMIT, MAX_READ_BYTES, MAX_SEARCH_LIMIT, MAX_TREE_DEPTH,
    MAX_READ_OFFSET, MAX_TREE_ENTRIES, MIN_READ_BYTES, WorkspaceError,
)
from jarvis.domain.artifacts import ArtifactError, ArtifactKind, check_artifact_id
from jarvis.domain.board_memory import BoardMemoryError
from jarvis.domain.session_activity import ActivityError, ActivityKind
from jarvis.domain.session_context import SessionContextError
from jarvis.domain.workspace_board import BoardError
from jarvis.ports.board_memory import BoardMemoryUnavailable
from jarvis.ports.session_context import ContextStoreError
from jarvis.ports.workspace_board import BoardStoreError
from jarvis.protocol.capture_routes import _datetime, _enums, _int, _only, error_response

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PREFIX = "/v1/workspace"
#: Refus codés des domaines : leur `code` et leur `status` voyagent tels quels.
#: `BoardMemoryError` et `WorkspaceError` sont des `ValueError` : attrapés **avant** elle.
_CODED = (WorkspaceError, BoardMemoryError, BoardError, SessionContextError, ArtifactError, ActivityError)


def _code(exc: BaseException) -> str:
    return str(getattr(getattr(exc, "code", None), "value", getattr(exc, "code", "workspace_failed")))


class WorkspaceProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.workspace`). Voir l'en-tête."""

    def __init__(self, core: Any) -> None:
        self._core = core

    @property
    def _service(self) -> Any:
        return self._core.workspace

    def routes(self) -> list[web.RouteDef]:
        board = PREFIX + "/boards/{board_id}"
        session = PREFIX + "/sessions/{session_id}"
        g = self._guarded
        return [
            web.get(PREFIX + "/sessions", g("session_list", self.sessions)),
            web.get(session, g("session_get", self.session)),
            web.get(session + "/activity", g("activity", self.activity)),
            web.get(board, g("board_inspect", self.board)),
            web.get(PREFIX + "/relations", g("relations", self.relations)),
            web.get(PREFIX + "/artifacts", g("artifact_list", self.artifacts)),
            web.get(PREFIX + "/artifacts/{artifact_id}/relations", g("artifact_relations", self.artifact_relations)),
            web.get(board + "/memory/tree", g("memory_tree", self.memory_tree)),
            web.get(board + "/memory/stat", g("memory_stat", self.memory_stat)),
            web.get(board + "/memory/read", g("memory_read", self.memory_read)),
            web.get(board + "/memory/search", g("memory_search", self.memory_search)),
        ]

    def _guarded(self, operation: str, handler: Handler) -> Handler:
        """Chaque refus devient l'enveloppe codée, journalisée, sans chemin absolu ; jamais un 500 muet."""

        async def run(request: web.Request) -> web.StreamResponse:
            try:
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except EvidenceApiError as exc:
                return self._refused(operation, exc, exc.status, exc.code)
            except _CODED as exc:
                return self._refused(operation, exc, exc.status, _code(exc))
            except BoardMemoryUnavailable as exc:
                # Racine `boards/<id>/memory` piégée (lien, jonction) ou disque en défaut.
                return self._refused(operation, exc, 500, exc.code)
            except (BoardStoreError, ContextStoreError) as exc:
                # Ligne abîmée ou SQLite en défaut : dite, jamais réparée.
                return self._refused(operation, exc, 500, str(getattr(exc, "code", "store_failed")))
            except ValueError as exc:
                return self._refused(operation, exc, 400, "invalid_request")
            except Exception as exc:  # noqa: BLE001 - surfaced: 500 with its type, and journaled
                return self._refused(operation, exc, 500, "workspace_failed")

        return run

    def _refused(self, operation: str, exc: BaseException, status: int, code: str) -> web.Response:
        service = getattr(self._core, "workspace", None)
        if service is not None:
            service.trace_failure(operation, exc, status=status, code=code)
        message = str(exc) if status < 500 or code != "workspace_failed" else f"{type(exc).__name__}: {exc}"
        return error_response(status, code, message)

    def _ready(self) -> None:
        if not self._core.health.ready or not self._core.sessions.started:
            raise EvidenceApiError(503, "core_unavailable", "core is not ready")

    @staticmethod
    def _limit(request: web.Request, default: int, high: int = MAX_PAGE_LIMIT) -> int:
        return _int(request, "limit", default, 1, high) or default

    # ------------------------------------------------------------ Sessions

    async def sessions(self, request: web.Request) -> web.Response:
        _only(request, {"cursor", "limit"})
        self._ready()
        return web.json_response(await self._service.session_list(
            cursor=request.query.get("cursor"), limit=self._limit(request, DEFAULT_SESSION_LIMIT)))

    async def session(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        return web.json_response(await self._service.session_get(request.match_info["session_id"]))

    async def activity(self, request: web.Request) -> web.Response:
        _only(request, {"cursor", "limit", "kind"})
        self._ready()
        return web.json_response(await self._service.activity(
            request.match_info["session_id"], cursor=request.query.get("cursor"),
            limit=self._limit(request, DEFAULT_ACTIVITY_LIMIT), kinds=_enums(request, "kind", ActivityKind)))

    # ------------------------------------------------------------ Boards, relations

    async def board(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        return web.json_response(await self._service.board_inspect(request.match_info["board_id"]))

    async def relations(self, request: web.Request) -> web.Response:
        _only(request, {"session_id", "board_id"})
        self._ready()
        return web.json_response(await self._service.relations(
            jarvis_session_id=request.query.get("session_id"), board_id=request.query.get("board_id")))

    # ------------------------------------------------------------ Artifacts

    async def artifacts(self, request: web.Request) -> web.Response:
        _only(request, {"board_id", "session_id", "context_id", "kind", "since", "until", "cursor", "limit"})
        self._ready()
        return web.json_response(await self._service.artifact_list(
            board_id=request.query.get("board_id"), jarvis_session_id=request.query.get("session_id"),
            context_id=request.query.get("context_id"), kinds=_enums(request, "kind", ArtifactKind),
            since=_datetime(request, "since"), until=_datetime(request, "until"),
            cursor=request.query.get("cursor"), limit=self._limit(request, DEFAULT_ARTIFACT_LIMIT)))

    async def artifact_relations(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        artifact_id = request.match_info["artifact_id"]
        check_artifact_id(artifact_id)
        return web.json_response(await self._service.artifact_relations(artifact_id))

    # ------------------------------------------------------------ mémoire

    async def memory_tree(self, request: web.Request) -> web.Response:
        _only(request, {"path", "depth", "max_entries"})
        self._ready()
        return web.json_response(await self._service.memory_tree(
            request.match_info["board_id"], path=request.query.get("path"),
            depth=_int(request, "depth", DEFAULT_TREE_DEPTH, 1, MAX_TREE_DEPTH) or DEFAULT_TREE_DEPTH,
            max_entries=_int(request, "max_entries", DEFAULT_TREE_ENTRIES, 1, MAX_TREE_ENTRIES)
            or DEFAULT_TREE_ENTRIES))

    @staticmethod
    def _required(request: web.Request, name: str) -> str:
        value = request.query.get(name)
        if value is None:
            raise WorkspaceError("invalid_request", f"missing query parameter: {name}")
        return value

    async def memory_stat(self, request: web.Request) -> web.Response:
        _only(request, {"path"})
        self._ready()
        return web.json_response(await self._service.memory_stat(
            request.match_info["board_id"], path=self._required(request, "path")))

    async def memory_read(self, request: web.Request) -> web.Response:
        _only(request, {"path", "offset", "max_bytes"})
        self._ready()
        return web.json_response(await self._service.memory_read(
            request.match_info["board_id"], path=self._required(request, "path"),
            offset=_int(request, "offset", 0, 0, MAX_READ_OFFSET) or 0,
            max_bytes=_int(request, "max_bytes", DEFAULT_READ_BYTES, MIN_READ_BYTES, MAX_READ_BYTES)
            or DEFAULT_READ_BYTES))

    async def memory_search(self, request: web.Request) -> web.Response:
        _only(request, {"q", "path", "limit"})
        self._ready()
        return web.json_response(await self._service.memory_search(
            request.match_info["board_id"], query=self._required(request, "q"), path=request.query.get("path"),
            limit=self._limit(request, DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT)))
