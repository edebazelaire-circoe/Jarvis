"""Inspection du workspace : Sessions, Boards, liaisons, Contexts, Artifacts, mémoire (handoff board-memory-workspace-inspector, Slice 04, R4).

Une seule vérité de lecture pour l'interface (Slices 07-08) et le serveur MCP
`jarvis-workspace` (Slice 06) : les relations Session / Board / liaison /
Context / Artifact / mémoire sont lues ici, jamais reconstruites par un client.
Le service ne possède rien : il compose les magasins canoniques
(`BoardRepository`, `ContextRepository`, `ArtifactService`,
`BoardArtifactLinkStore`, `BoardMemoryStore`) sans les dupliquer. Routes :
`jarvis/protocol/workspace_routes.py`. Contrat : `docs/boards.md` ›
*Workspace inspection API*.

Garanties tenues ici :

- **aucun effet de bord** : aucune méthode n'appelle la bascule, n'écrit une
  Session, une liaison ou un Board, ne touche l'autorité de parole (lue
  seulement), n'écrit le ledger ; la mémoire d'un Board n'est jamais créée par
  une lecture (`BoardMemoryStore.exists` avant tout appel qui la créerait) ;
- tout est borné (`limit` <= 100, curseurs opaques, arbres et lectures bornés) ;
- les appels synchrones du magasin de mémoire (disque, parfois plusieurs
  secondes) tournent dans un fil (`asyncio.to_thread`), jamais sur la boucle ;
- les bornes sont validées ici (`WorkspaceError`, `invalid_request`) avant le
  magasin : aucune `ValueError` nue du magasin ne devient un 500 ;
- une Session ouverte dont `active_board_id` (ou un Board visité, ou une
  liaison) nomme un Board absent est **dite** (`problems`), jamais un plantage.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from datetime import datetime
import json
import time
from typing import Any

from jarvis.core.capture_api import USER_AUTHORED_FIELDS, artifact_summary, redact_paths
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery
from jarvis.domain.board_memory import MAX_MEMORY_IO_BYTES, MEMORY_SUMMARY_NAME, BoardMemoryError, BoardMemoryErrorCode, \
    BoardMemoryPath
from jarvis.domain.session_activity import ActivityKind, ActivityQuery
from jarvis.domain.session_context import SessionContext, SessionContextError, SessionContextErrorCode
from jarvis.domain.workspace_board import (
    Board, BoardConversationBinding, BoardError, BoardErrorCode, JarvisSession, SessionStatus,
)
from jarvis.ports.artifacts import RelationDirection
from jarvis.ports.board_artifact_links import BoardArtifactLinkStore
from jarvis.ports.board_memory import BoardMemoryStore, MemoryEntry, MemoryEntryKind
from jarvis.ports.session_context import ContextRepository
from jarvis.ports.v2 import DiagnosticSink
from jarvis.ports.workspace_board import BoardRepository

#: Bornes de l'API (R4) : toute liste est paginée, au plus 100 éléments par page.
MAX_PAGE_LIMIT = 100
DEFAULT_SESSION_LIMIT = 20
DEFAULT_ARTIFACT_LIMIT = 20
DEFAULT_ACTIVITY_LIMIT = 50
#: Contexts d'une Session et liaisons d'un Board rendus au plus (les plus récents).
MAX_RELATED_ITEMS = 100
#: Liens Board d'un Artifact rendus par `artifact_relations`.
MAX_ARTIFACT_BOARDS = 100
#: Arbre de mémoire : profondeur et entrées par appel.
MAX_TREE_DEPTH = 8
DEFAULT_TREE_DEPTH = 2
MAX_TREE_ENTRIES = 500
DEFAULT_TREE_ENTRIES = 200
#: Lecture : octets par page (le magasin plafonne à 256 Kio).
DEFAULT_READ_BYTES = 64 * 1024
MIN_READ_BYTES = 4
#: Décalage de lecture maximal (12 chiffres, la borne des entiers de requête).
MAX_READ_OFFSET = 10**12 - 1
MAX_READ_BYTES = MAX_MEMORY_IO_BYTES
#: Recherche littérale : correspondances, longueur de la requête.
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 100
MAX_SEARCH_QUERY_CHARS = 200
#: Résumé de la mémoire dans `board_inspect` : un parcours borné, `truncated` au-delà.
SUMMARY_TREE_DEPTH = 8
SUMMARY_TREE_ENTRIES = 1000
MAX_ID_CHARS = 128

_TRACE_EXCEPTION_CHARS = 200


class WorkspaceError(ValueError):
    """Demande refusée par l'inspection elle-même (borne, curseur, portée) ; code stable et statut HTTP."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _invalid(message: str) -> WorkspaceError:
    return WorkspaceError("invalid_request", message)


def check_limit(name: str, value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise _invalid(f"{name} must be an integer in {low}..{high}")
    return value


def _check_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_CHARS or not value.isprintable():
        raise _invalid(f"{name} must be a short printable id")
    return value


# ------------------------------------------------------------------ curseurs opaques


def encode_cursor(kind: str, value: Any) -> str:
    raw = json.dumps({"k": kind, "v": value}, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(kind: str, cursor: object) -> Any:
    """La valeur d'un curseur rendu par une page `kind` ; `invalid_request` pour tout autre texte."""

    if not isinstance(cursor, str) or not cursor or len(cursor) > 512:
        raise _invalid(f"cursor is not a {kind} cursor")
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        raise _invalid(f"cursor is not a {kind} cursor") from None
    if not isinstance(data, dict) or data.get("k") != kind or "v" not in data:
        raise _invalid(f"cursor is not a {kind} cursor")
    return data["v"]


# ------------------------------------------------------------------ vues


def _board_brief(board: Board) -> dict[str, Any]:
    return {"board_id": board.board_id, "title": board.title, "board_kind": board.board_kind.value,
            "status": board.status.value, "last_opened_at": None if board.last_opened_at is None
            else board.last_opened_at.isoformat()}


def _entry(entry: MemoryEntry) -> dict[str, Any]:
    return {"path": entry.path, "kind": entry.kind.value, "size": entry.size,
            "modified_at": entry.modified_at.isoformat(), "depth": entry.depth}


class WorkspaceService:
    """Lectures du workspace, sans effet de bord. Voir l'en-tête du module."""

    def __init__(
        self,
        *,
        boards: BoardRepository,
        contexts: ContextRepository,
        artifacts: Any,
        links: BoardArtifactLinkStore,
        memory: BoardMemoryStore,
        authority: Any = None,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        self._boards = boards
        self._contexts = contexts
        #: `ArtifactService` : `get`, `query`, `relations`, `activity`, `latest_seq`.
        self._artifacts = artifacts
        self._links = links
        self._memory = memory
        #: `SpeechAuthority` : lue seulement (`binding`), jamais posée.
        self._authority = authority
        self._diagnostics = diagnostics

    # ------------------------------------------------------------ Sessions

    async def session_list(self, *, cursor: str | None = None, limit: int = DEFAULT_SESSION_LIMIT) -> dict[str, Any]:
        """Historique des Sessions, ouvertes et closes, la plus récente d'abord."""

        check_limit("limit", limit, 1, MAX_PAGE_LIMIT)
        before = None
        if cursor is not None:
            value = decode_cursor("sessions", cursor)
            if not isinstance(value, str):
                raise _invalid("cursor is not a sessions cursor")
            before = await self._boards.get_session(value)
            if before is None:
                raise _invalid("cursor names a session that no longer exists")
        sessions = await self._boards.list_sessions(limit=limit + 1, before=before)
        page = sessions[:limit]
        next_cursor = encode_cursor("sessions", page[-1].jarvis_session_id) if len(sessions) > limit else None
        return {"sessions": [{**session.to_payload(), "open": session.status is SessionStatus.OPEN}
                             for session in page], "next_cursor": next_cursor}

    async def _session(self, jarvis_session_id: object) -> JarvisSession:
        session = None
        if isinstance(jarvis_session_id, str) and 0 < len(jarvis_session_id) <= MAX_ID_CHARS:
            session = await self._boards.get_session(jarvis_session_id)
        if session is None:
            raise BoardError(BoardErrorCode.SESSION_NOT_FOUND,
                             f"session {str(jarvis_session_id)[:80]!r} does not exist")
        return session

    async def _board(self, board_id: object) -> Board:
        board = None
        if isinstance(board_id, str) and 0 < len(board_id) <= MAX_ID_CHARS:
            board = await self._boards.get_board(board_id)
        if board is None:
            raise BoardError(BoardErrorCode.BOARD_NOT_FOUND, f"board {str(board_id)[:80]!r} does not exist")
        return board

    async def _session_relations(
        self, session: JarvisSession,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[SessionContext]]:
        """Boards de la Session (visités, actif, liés) avec leur liaison, ses Contexts ; problèmes d'intégrité dits."""

        bindings = {binding.board_id: binding for binding in await self._boards.list_bindings(session.jarvis_session_id)}
        known = {board.board_id: board for board in await self._boards.list_boards(include_archived=True)}
        board_ids = list(dict.fromkeys((*session.visited_board_ids, session.active_board_id, *bindings)))
        problems: list[dict[str, Any]] = []
        boards: list[dict[str, Any]] = []
        for board_id in board_ids:
            board = known.get(board_id)
            binding = bindings.get(board_id)
            item: dict[str, Any] = {"board_id": board_id, "active": board_id == session.active_board_id,
                                    "visited": board_id in session.visited_board_ids,
                                    "binding": None if binding is None else binding.to_payload()}
            if board is None:
                item["missing"] = True
                field = "active_board_id" if item["active"] else "visited_board_ids" if item["visited"] \
                    else "binding"
                problems.append({"code": BoardErrorCode.BOARD_NOT_FOUND.value, "board_id": board_id, "field": field,
                                 "message": f"session {session.jarvis_session_id} names board {board_id} "
                                            f"({field}) which does not exist"})
            else:
                item.update(_board_brief(board))
            boards.append(item)
        if session.status is SessionStatus.OPEN and session.active_board_id not in bindings:
            problems.append({"code": BoardErrorCode.BINDING_NOT_FOUND.value, "board_id": session.active_board_id,
                             "field": "active_board_id",
                             "message": f"open session {session.jarvis_session_id} has no binding for its active "
                                        f"board {session.active_board_id}"})
        contexts = list(await self._contexts.list_contexts(session.jarvis_session_id))
        shown = contexts[-MAX_RELATED_ITEMS:]
        relations = {
            "session": {"jarvis_session_id": session.jarvis_session_id, "status": session.status.value,
                        "active_board_id": session.active_board_id},
            "boards": boards,
            "contexts": {"items": [{"context_id": c.context_id, "status": c.status.value, "title": c.title,
                                    "workspace_ref": c.workspace_path.as_posix()} for c in shown],
                         "total": len(contexts), "truncated": len(contexts) > len(shown)},
        }
        if problems:
            self._trace("core.workspace.integrity_problem", "Session incohérente vue par l'inspection",
                        level="warning", data={"jarvis_session_id": session.jarvis_session_id,
                                               "problems": len(problems), "code": problems[0]["code"]})
        return relations, problems, contexts

    async def session_get(self, jarvis_session_id: str) -> dict[str, Any]:
        """Une Session (ouverte ou close) : Boards visités, liaisons, Contexts, et l'autorité si elle est ouverte."""

        started = time.monotonic()
        session = await self._session(jarvis_session_id)
        relations, problems, contexts = await self._session_relations(session)
        shown = contexts[-MAX_RELATED_ITEMS:]
        payload: dict[str, Any] = {
            "session": session.to_payload(),
            "open": session.status is SessionStatus.OPEN,
            "boards": relations["boards"],
            "contexts": {"items": [{**redact_paths(c.to_payload(), keep=USER_AUTHORED_FIELDS),
                                    "workspace_ref": c.workspace_path.as_posix()} for c in shown],
                         "total": len(contexts), "truncated": len(contexts) > len(shown),
                         "active_context_id": next((c.context_id for c in contexts if c.status.value == "active"),
                                                   None)},
            "problems": problems,
        }
        if session.status is SessionStatus.OPEN:
            payload["speech_authority"] = self._authority_view()
        self._read("session_get", started, jarvis_session_id=session.jarvis_session_id)
        return payload

    def _authority_view(self) -> dict[str, Any] | None:
        binding: BoardConversationBinding | None = getattr(self._authority, "binding", None)
        if binding is None:
            return None
        return {"board_id": binding.board_id, "conversation_id": binding.conversation_id,
                "jarvis_session_id": binding.jarvis_session_id}

    # ------------------------------------------------------------ Boards

    async def _board_relations(self, board: Board) -> dict[str, Any]:
        bindings = await self._boards.list_bindings_of_board(board.board_id, limit=MAX_RELATED_ITEMS + 1)
        shown = bindings[:MAX_RELATED_ITEMS]
        sessions: list[dict[str, Any]] = []
        for binding in shown:
            session = await self._boards.get_session(binding.jarvis_session_id)
            sessions.append({
                **binding.to_payload(),
                "session_status": None if session is None else session.status.value,
                "active_in_session": session is not None and session.active_board_id == board.board_id,
            })
        current = await self._boards.current_session()
        return {"board": _board_brief(board),
                "active": current is not None and current.active_board_id == board.board_id,
                "sessions": {"items": sessions, "truncated": len(bindings) > len(shown)},
                "linked_artifacts": await self._links.count_links(board.board_id)}

    async def relations(self, *, jarvis_session_id: str | None = None, board_id: str | None = None) -> dict[str, Any]:
        """Relations d'une Session **ou** d'un Board (exactement un des deux)."""

        if (jarvis_session_id is None) == (board_id is None):
            raise _invalid("give exactly one of session_id and board_id")
        started = time.monotonic()
        if jarvis_session_id is not None:
            relations, problems, _contexts = await self._session_relations(await self._session(jarvis_session_id))
            payload = {**relations, "problems": problems}
        else:
            payload = await self._board_relations(await self._board(board_id))
        self._read("relations", started, jarvis_session_id=jarvis_session_id, board_id=board_id)
        return payload

    async def board_inspect(self, board_id: str) -> dict[str, Any]:
        """Un Board (archivé compris) : liaisons dans toutes les Sessions, mémoire résumée, liens, refs héritées."""

        started = time.monotonic()
        board = await self._board(board_id)
        relations = await self._board_relations(board)
        payload = {
            "board": board.to_payload(),
            "active": relations["active"],
            "sessions": relations["sessions"],
            "artifacts": {"linked": relations["linked_artifacts"]},
            "legacy_artifact_refs": {"items": list(board.artifact_refs), "legacy": True,
                                     "note": "opaque legacy references (Board.artifact_refs), not registry links"},
            "memory": await self._memory_summary(board.board_id),
        }
        self._read("board_inspect", started, board_id=board.board_id)
        return payload

    async def _memory_summary(self, board_id: str) -> dict[str, Any]:
        """Racine, entrées, octets, présence de `summary.md` ; un refus du magasin est dit (`error`), pas levé."""

        try:
            locator = self._memory.memory_root_locator(board_id)
        except BoardError as exc:
            # capture: un id que la mémoire refuse (plus strict que `Board`) ; l'inspection garde le Board.
            return {"locator": None, "exists": False, "error": exc.code.value, "message": str(exc)[:300]}
        summary: dict[str, Any] = {"locator": locator, "exists": False, "entries": 0, "files": 0, "directories": 0,
                                   "bytes": 0, "truncated": False, "summary": {"present": False}}
        try:
            if not await asyncio.to_thread(self._memory.exists, board_id):
                return summary
            tree = await asyncio.to_thread(self._memory.tree, board_id, None, depth=SUMMARY_TREE_DEPTH,
                                           max_entries=SUMMARY_TREE_ENTRIES)
            try:
                head = await asyncio.to_thread(self._memory.stat, board_id, BoardMemoryPath(MEMORY_SUMMARY_NAME))
            except BoardMemoryError as exc:
                if exc.code is not BoardMemoryErrorCode.MEMORY_NOT_FOUND:
                    raise
                head = None
        except BoardMemoryError as exc:
            # Avant tout `ValueError` : un refus nommé de la mémoire est dit avec son code.
            return {**summary, "exists": True, "error": exc.code.value, "message": redact_paths(str(exc))[:300]}
        except Exception as exc:  # noqa: BLE001 - capture: said in the answer with its code, and traced
            code = str(getattr(exc, "code", "board_memory_failed"))
            self._trace("core.workspace.memory_unreadable", f"Mémoire du Board illisible : {type(exc).__name__}: "
                        f"{str(exc)[:_TRACE_EXCEPTION_CHARS]}", level="error",
                        data={"board_id": board_id, "code": code, "exception_type": type(exc).__name__})
            return {**summary, "error": code, "message": redact_paths(str(exc))[:300]}
        files = [e for e in tree.entries if e.kind is MemoryEntryKind.FILE]
        summary.update(exists=True, entries=len(tree.entries), files=len(files),
                       directories=sum(e.kind is MemoryEntryKind.DIRECTORY for e in tree.entries),
                       bytes=sum(e.size or 0 for e in files), truncated=tree.truncated, skipped=tree.skipped,
                       summary={"present": head is not None and head.kind is MemoryEntryKind.FILE,
                                **({} if head is None else {"path": head.path, "size": head.size,
                                                            "modified_at": head.modified_at.isoformat()})})
        return summary

    # ------------------------------------------------------------ Artifacts

    async def artifact_list(
        self,
        *,
        board_id: str | None = None,
        jarvis_session_id: str | None = None,
        context_id: str | None = None,
        kinds: tuple[ArtifactKind, ...] = (),
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_ARTIFACT_LIMIT,
    ) -> dict[str, Any]:
        """Artifacts d'**un** Board (liens v8), d'une Session ou d'un Context ; filtres type et temps ; paginé."""

        scopes = [name for name, value in (("board_id", board_id), ("session_id", jarvis_session_id),
                                           ("context_id", context_id)) if value is not None]
        if len(scopes) != 1:
            raise _invalid("give exactly one of board_id, session_id and context_id")
        check_limit("limit", limit, 1, MAX_PAGE_LIMIT)
        registry_cursor = None
        if cursor is not None:
            registry_cursor = decode_cursor("artifacts", cursor)
            if not isinstance(registry_cursor, str):
                raise _invalid("cursor is not a artifacts cursor")
        started = time.monotonic()
        if board_id is not None:
            await self._board(board_id)
        elif jarvis_session_id is not None:
            await self._session(jarvis_session_id)
        else:
            _check_id("context_id", context_id)
            if await self._contexts.get_context(context_id) is None:
                raise SessionContextError(SessionContextErrorCode.CONTEXT_NOT_FOUND,
                                          f"context {context_id[:80]!r} does not exist")
        page = await self._artifacts.query(ArtifactQuery(
            board_id=board_id, jarvis_session_id=jarvis_session_id, context_id=context_id, kinds=kinds,
            since=since, until=until, cursor=registry_cursor, limit=limit))
        self._read("artifact_list", started, board_id=board_id, jarvis_session_id=jarvis_session_id,
                   context_id=context_id, count=len(page.items))
        return {"artifacts": [artifact_summary(item) for item in page.items],
                "next_cursor": None if page.next_cursor is None else encode_cursor("artifacts", page.next_cursor),
                "scope": {scopes[0]: board_id or jarvis_session_id or context_id}}

    async def artifact_relations(self, artifact_id: str) -> dict[str, Any]:
        """Provenance (origines, dépendants : `ArtifactService.relations`) et Boards liés (v8)."""

        started = time.monotonic()
        artifact = await self._artifacts.get(artifact_id)  # `artifact_not_found` plutôt qu'une liste vide
        payload: dict[str, Any] = {"artifact": artifact_summary(artifact)}
        for direction in (RelationDirection.ORIGINS, RelationDirection.DEPENDENTS):
            payload[direction.value] = [relation.to_payload()
                                        for relation in await self._artifacts.relations(artifact_id, direction)]
        links = await self._links.boards_of_artifact(artifact_id, limit=MAX_ARTIFACT_BOARDS + 1)
        payload["boards"] = {"items": [link.to_payload() for link in links[:MAX_ARTIFACT_BOARDS]],
                             "truncated": len(links) > MAX_ARTIFACT_BOARDS}
        self._read("artifact_relations", started, artifact_id=artifact.artifact_id)
        return payload

    # ------------------------------------------------------------ activité

    async def activity(self, jarvis_session_id: str, *, cursor: str | None = None,
                       limit: int = DEFAULT_ACTIVITY_LIMIT, kinds: tuple[ActivityKind, ...] = ()) -> dict[str, Any]:
        """Ledger d'**une** Session, ouverte ou close, par `seq` croissant ; ids et codes, jamais de texte."""

        check_limit("limit", limit, 1, MAX_PAGE_LIMIT)
        after = 0
        if cursor is not None:
            after = decode_cursor("activity", cursor)
            if type(after) is not int or after < 0:
                raise _invalid("cursor is not a activity cursor")
        session = await self._session(jarvis_session_id)
        events = await self._artifacts.activity(ActivityQuery(
            after_seq=after, limit=limit + 1, jarvis_session_id=session.jarvis_session_id, kinds=kinds))
        page = events[:limit]
        return {"jarvis_session_id": session.jarvis_session_id,
                "events": [redact_paths(event.to_payload()) for event in page],
                "next_cursor": encode_cursor("activity", page[-1].seq) if len(events) > limit else None}

    # ------------------------------------------------------------ mémoire

    async def _memory_board(self, board_id: object) -> tuple[str, bool]:
        """Board existant (actif ou archivé) et présence de sa racine, **sans** la créer."""

        board = await self._board(board_id)
        exists = await asyncio.to_thread(self._memory.exists, board.board_id)
        return board.board_id, exists

    @staticmethod
    def _path(raw: str | None) -> BoardMemoryPath | None:
        return None if raw is None else BoardMemoryPath.parse(raw)

    @staticmethod
    def _missing(path: BoardMemoryPath | str) -> BoardMemoryError:
        return BoardMemoryError(BoardMemoryErrorCode.MEMORY_NOT_FOUND, f"{path}: not found")

    async def memory_tree(self, board_id: str, *, path: str | None = None, depth: int = DEFAULT_TREE_DEPTH,
                          max_entries: int = DEFAULT_TREE_ENTRIES) -> dict[str, Any]:
        check_limit("depth", depth, 1, MAX_TREE_DEPTH)
        check_limit("max_entries", max_entries, 1, MAX_TREE_ENTRIES)
        target = self._path(path)
        started = time.monotonic()
        board_id, exists = await self._memory_board(board_id)
        locator = self._memory.memory_root_locator(board_id)
        if not exists:
            if target is not None:
                raise self._missing(target)
            return {"board_id": board_id, "locator": locator, "exists": False, "path": "", "entries": [],
                    "truncated": False, "skipped": 0}
        tree = await asyncio.to_thread(self._memory.tree, board_id, target, depth=depth, max_entries=max_entries)
        self._read("memory_tree", started, board_id=board_id, count=len(tree.entries))
        return {"board_id": board_id, "locator": locator, "exists": True, "path": tree.path,
                "entries": [_entry(entry) for entry in tree.entries], "truncated": tree.truncated,
                "skipped": tree.skipped}

    async def memory_stat(self, board_id: str, *, path: str) -> dict[str, Any]:
        target = BoardMemoryPath.parse(path)
        board_id, exists = await self._memory_board(board_id)
        if not exists:
            raise self._missing(target)
        entry = await asyncio.to_thread(self._memory.stat, board_id, target)
        return {"board_id": board_id, "entry": _entry(entry)}

    async def memory_read(self, board_id: str, *, path: str, offset: int = 0,
                          max_bytes: int = DEFAULT_READ_BYTES) -> dict[str, Any]:
        check_limit("offset", offset, 0, MAX_READ_OFFSET)
        check_limit("max_bytes", max_bytes, MIN_READ_BYTES, MAX_READ_BYTES)
        target = BoardMemoryPath.parse(path)
        started = time.monotonic()
        board_id, exists = await self._memory_board(board_id)
        if not exists:
            raise self._missing(target)
        text = await asyncio.to_thread(self._memory.read, board_id, target, offset=offset, max_bytes=max_bytes)
        self._read("memory_read", started, board_id=board_id, bytes=text.next_offset - text.offset)
        return {"board_id": board_id, "path": text.path, "text": text.text, "offset": text.offset,
                "next_offset": text.next_offset, "size": text.size, "eof": text.eof, "sha256": text.sha256}

    async def memory_search(self, board_id: str, *, query: str, path: str | None = None,
                            limit: int = DEFAULT_SEARCH_LIMIT) -> dict[str, Any]:
        check_limit("limit", limit, 1, MAX_SEARCH_LIMIT)
        if (not isinstance(query, str) or not query.strip() or len(query) > MAX_SEARCH_QUERY_CHARS
                or not query.isprintable()):
            raise _invalid(f"q must be one printable line of 1..{MAX_SEARCH_QUERY_CHARS} characters")
        target = self._path(path)
        started = time.monotonic()
        board_id, exists = await self._memory_board(board_id)
        if not exists:
            if target is not None:
                raise self._missing(target)
            return {"board_id": board_id, "query": query, "matches": [], "files_scanned": 0, "files_skipped": 0,
                    "truncated": False}
        found = await asyncio.to_thread(self._memory.search, board_id, query, path=target, limit=limit)
        self._read("memory_search", started, board_id=board_id, count=len(found.matches))
        return {"board_id": board_id, "query": query,
                "matches": [{"path": m.path, "line": m.line, "preview": m.preview} for m in found.matches],
                "files_scanned": found.files_scanned, "files_skipped": found.files_skipped,
                "truncated": found.truncated}

    # ------------------------------------------------------------ journal

    def _read(self, operation: str, started: float, **data: Any) -> None:
        """Chemin attendu dit aussi (info) : opération, ids, nombre, durée."""

        self._trace("core.workspace.read", f"Inspection du workspace : {operation}",
                    data={"operation": operation, "duration_ms": int((time.monotonic() - started) * 1000),
                          **{key: value for key, value in data.items() if value is not None}})

    def trace_failure(self, operation: str, exc: BaseException, *, status: int, code: str) -> None:
        """Échec d'une route d'inspection (appelée par `workspace_routes`), avec son code."""

        self._trace("core.workspace.read_failed", f"Inspection refusée ({operation}) : {type(exc).__name__}: "
                    f"{redact_paths(str(exc))[:_TRACE_EXCEPTION_CHARS]}",
                    level="error" if status >= 500 else "warning",
                    data={"operation": operation, "status": status, "code": code,
                          "exception_type": type(exc).__name__})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not fail a read
            pass
