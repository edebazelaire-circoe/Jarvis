"""Dossier d'un Board : projection et opérations sémantiques (handoff jarvis-board-ui-wheel-dossier-refactor, Slice 05).

Contrat : `docs/dossier.md`. Le service ne possède **rien** : il compose les
propriétaires canoniques sans les recopier.

- la mémoire du Board par `WorkspaceService` (`memory_tree`, `memory_stat`,
  `memory_write`, `artifact_link`) : bornes, chemins sûrs, verrou par Board,
  règle d'archivage et ledger `board.*` restent les siens ;
- les Artifacts liés par `BoardArtifactLinkStore` et `ArtifactService` ;
- la scène par `SceneService` (`snapshot`, `apply_if`) : autorité, bornes et
  révision restent celles du réducteur.

Cinq opérations, servies à l'identique à l'interface et au cerveau
(`jarvis/protocol/workspace_routes.py`, relais `/api/workspace/…`, MCP
`jarvis-workspace`) :

1. `list_entries` / `entry` : la liste composée (mémoire + Artifacts liés), bornée,
   vue humaine par défaut, détails techniques seulement avec `advanced` ;
2. `backing` : la source durable de chaque objet de scène désigné ;
3. `ranger` : durabilité confirmée ou créée **d'abord** (lien, ou contenu écrit une
   fois en Markdown dans `notes/`), retrait de la représentation **ensuite**, par
   **une** commande `archive_selection`. Un objet dont la durabilité échoue reste
   visible et son refus est nommé ;
4. `present` : « Afficher sur le Board » une entrée : une fenêtre qui pointe vers la
   même source (`source_path` pour un fichier de la mémoire, `registry_artifact_id`
   pour un Artifact), réutilisée si elle existe déjà ;
5. le canal agent -> interface pour ouvrir une entrée vit au Control Center
   (`jarvis/runtime/dossier_navigation.py`) ; Core en fournit la résolution (`entry`).

Ranger et Afficher sur le Board visent la scène affichée, donc le Board **actif**
(`dossier_board_not_active` sinon) ; un Board archivé ne peut pas l'être. Les
lectures acceptent tout Board, archivé compris, et n'écrivent rien.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import time
from typing import Any, Callable
import uuid

from jarvis.core.capture_api import artifact_summary, redact_paths
from jarvis.core.workspace_service import LEDGER_FAILED, MAX_READ_BYTES, WorkspaceError
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactKind
from jarvis.domain.board_artifact_links import BoardArtifactLink, BoardArtifactLinkOrigin
from jarvis.domain.board_memory import BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath
from jarvis.domain.dossier import (
    DEFAULT_LIST_LIMIT, MAX_LINKED_SCAN, MAX_LIST_LIMIT, MAX_RANGER_OBJECTS, MEMORY_SCAN_DEPTH, PRESENT_CATEGORY,
    RANGER_HEADING_BYTES,
    BackingKind, DossierCode, DossierEntryRef, EntryKind, EntrySource, artifact_entry_kind, artifact_entry_title,
    classify_scene_object, heading_title, is_ranger_note, memory_entry_kind, memory_entry_title, ranger_body,
    ranger_markdown, ranger_path,
    stored_body,
)
from jarvis.domain.research_freshness import (
    FRONT_MATTER_TOO_LONG, MAX_FRONT_MATTER_BYTES, MAX_RESEARCH_HEAD_BYTES, is_research_path, parse_front_matter,
)
from jarvis.domain.scene import (
    MAX_SOURCE_PATH_CHARS, MAX_TITLE_CHARS, Representation, SceneActor, SceneCommand, SceneCommandOutcome,
    SceneObject, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, SceneSnapshot, Visibility,
)
from jarvis.domain.scene_batch import SelectionChanges
from jarvis.domain.scene_selection import SceneSelection
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import Board, BoardError, BoardErrorCode, BoardStatus
from jarvis.ports.board_memory import BoardMemoryUnavailable
from jarvis.ports.scene import SceneStoreError
from jarvis.ports.v2 import DiagnosticSink

#: Entrées de la mémoire lues pour la liste (la borne de `memory_tree`).
_MEMORY_LIST_ENTRIES = 500
_TRACE_CHARS = 200
#: Phrase vouvoyée de chaque refus par objet (l'interface et le cerveau la lisent telle quelle).
SENTENCES: dict[DossierCode, str] = {
    DossierCode.OBJECT_NOT_FOUND: "Cet objet n'est plus sur le Board : rien n'a été rangé.",
    DossierCode.NOT_ELIGIBLE: "Cet objet ne se range pas dans le Dossier ; il reste sur le Board.",
    DossierCode.NOTHING_TO_KEEP: "Cet objet est vide : rien à ranger, il reste sur le Board.",
    DossierCode.SOURCE_OUTSIDE_BOARD: ("Ce fichier n'est pas dans la mémoire de ce Board : il n'est pas recopié, "
                                       "l'objet reste sur le Board."),
    DossierCode.SOURCE_MISSING: "Sa source a disparu : rien n'a été rangé, l'objet reste sur le Board.",
    DossierCode.CHANGED_MEANWHILE: ("Le contenu a changé pendant le rangement : la version rangée est gardée, "
                                    "l'objet reste sur le Board. Rangez-le de nouveau."),
    DossierCode.ARCHIVE_FAILED: ("Le contenu est bien dans le Dossier, mais l'objet n'a pas pu être retiré du Board ; "
                                 "il reste affiché."),
}
#: Aperçu (`backing`) d'un Board qui n'est pas celui affiché : Ranger refuserait (409) ; l'aperçu le dit.
BOARD_INACTIVE_SENTENCES: dict[str, str] = {
    DossierCode.BOARD_NOT_ACTIVE.value: ("Ce Board n'est pas le Board affiché : Ranger agit seulement sur le Board "
                                         "actif ; rien ne serait rangé."),
    BoardErrorCode.BOARD_ARCHIVED.value: "Ce Board est archivé : son Dossier se lit, rien ne s'y range.",
}


@dataclass(frozen=True, slots=True)
class _Resolved:
    """Source durable d'un objet de scène, vue par ce Board."""

    object_id: str
    backing: str  # memory | artifact | content | refused
    ref: DossierEntryRef | None = None
    code: str | None = None
    reason: str = ""
    item: SceneObject | None = None

    def view(self) -> dict[str, Any]:
        data: dict[str, Any] = {"object_id": self.object_id, "backing": self.backing,
                                "entry_id": None if self.ref is None else self.ref.entry_id,
                                "rangeable": self.backing != "refused"}
        if self.code is not None:
            data.update(code=self.code, message=_sentence(self.code), reason=self.reason)
        return data


def _sentence(code: str) -> str:
    try:
        return SENTENCES[DossierCode(code)]
    except ValueError:
        return "Refusé : l'objet reste sur le Board."


#: Sources d'un envoi (`upload_service.Provenance`) dites à l'humain : un dépôt sur le Board est un geste explicite.
_UPLOAD_PROVENANCES = {"board_drop": "déposé sur le Board", "chat_attachment": "joint dans la conversation"}


def _provenance(artifact: Artifact, link: BoardArtifactLink) -> str:
    """Comment l'entrée est arrivée dans ce Dossier, honnêtement (QA S05, polish 4).

    Un dépôt sur le Board crée le lien avec `origin=active_board` : le lien seul le dirait « automatique ». La
    provenance d'envoi de l'Artifact (`metadata.provenance`) départage ; sinon l'origine du lien.
    """

    if artifact.kind is ArtifactKind.UPLOAD:
        said = _UPLOAD_PROVENANCES.get(str(artifact.metadata.get("provenance") or ""))
        if said:
            return said
    if link.origin is BoardArtifactLinkOrigin.ACTIVE_BOARD:
        return "ajouté automatiquement (Board actif à sa création)"
    return "ajouté au Dossier"


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class DossierService:
    """Voir l'en-tête du module."""

    def __init__(self, *, workspace: Any, boards: Any, artifacts: Any, links: Any, memory: Any, scene: Any,
                 data_root: Path, diagnostics: DiagnosticSink | None = None,
                 clock: Callable[[], datetime] = utc_now, id_factory: Callable[[], str] | None = None) -> None:
        self._workspace = workspace
        self._boards = boards
        self._artifacts = artifacts
        self._links = links
        self._memory = memory
        #: `SceneService`, ou `None` dans un Core sans scène : Ranger et Afficher refusent alors `scene_unavailable`.
        self._scene = scene
        self._data_root = Path(data_root)
        self._diagnostics = diagnostics
        self._clock = clock
        self._new_id = id_factory or (lambda: uuid.uuid4().hex[:16])

    # ------------------------------------------------------------ Boards

    async def _board(self, board_id: object) -> Board:
        board = None
        if isinstance(board_id, str) and 0 < len(board_id) <= 128:
            board = await self._boards.get_board(board_id)
        if board is None:
            raise BoardError(BoardErrorCode.BOARD_NOT_FOUND, f"board {str(board_id)[:80]!r} does not exist")
        return board

    async def _displayed_board(self, board_id: object) -> Board:
        """Board actif et non archivé : la scène affichée est la sienne (V1 : une seule scène, celle du Board actif)."""

        board = await self._board(board_id)
        if board.status is BoardStatus.ARCHIVED:
            raise BoardError(BoardErrorCode.BOARD_ARCHIVED,
                             f"board {board.board_id} is archived: its Dossier is read-only")
        session = await self._boards.current_session()
        if session is None or session.active_board_id != board.board_id:
            raise WorkspaceError(DossierCode.BOARD_NOT_ACTIVE.value,
                                 f"board {board.board_id} is not the active board: Ranger and present act on the "
                                 "displayed scene, which belongs to the active board", status=409)
        return board

    def _memory_root(self, board_id: str) -> Path:
        return self._data_root.joinpath(*self._memory.memory_root_locator(board_id).split("/"))

    async def _snapshot(self) -> SceneSnapshot:
        if self._scene is None:
            raise WorkspaceError(DossierCode.SCENE_UNAVAILABLE.value, "the scene is not served by this Core", status=503)
        try:
            return await self._scene.snapshot()
        except SceneStoreError as exc:
            raise WorkspaceError(DossierCode.SCENE_UNAVAILABLE.value, f"the scene is unavailable: {exc}",
                                 status=503) from exc

    # ------------------------------------------------------------ 1. liste composée

    def _memory_view(self, board_id: str, entry: Mapping[str, Any], *, advanced: bool) -> dict[str, Any]:
        path = str(entry["path"])
        kind, open_mode = memory_entry_kind(path)
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        view: dict[str, Any] = {"entry_id": DossierEntryRef.memory(path).entry_id, "source": EntrySource.MEMORY.value,
                                "kind": kind.value, "title": memory_entry_title(path), "open": open_mode.value,
                                "folder": folder, "path": path, "size": entry.get("size"),
                                "modified_at": entry.get("modified_at")}
        if advanced:
            view["advanced"] = {"locator": f"{self._memory.memory_root_locator(board_id)}/{path}"}
        return view

    def _artifact_view(self, artifact: Artifact, link: BoardArtifactLink, *, advanced: bool) -> dict[str, Any]:
        kind, open_mode = artifact_entry_kind(artifact.kind, mime_type=artifact.mime_type,
                                              has_payload=artifact.payload_ref is not None,
                                              has_text=artifact.text is not None)
        summary = artifact_summary(artifact)
        view: dict[str, Any] = {
            "entry_id": DossierEntryRef.artifact(artifact.artifact_id).entry_id,
            "source": EntrySource.ARTIFACT.value, "kind": kind.value,
            "title": artifact_entry_title(artifact.kind, original_name=artifact.metadata.get("original_name"),
                                          text=artifact.text, created_at=artifact.created_at),
            "open": open_mode.value, "preview": summary.get("preview"), "state": artifact.state.value,
            "modified_at": _iso(max(artifact.updated_at, link.linked_at)), "added_at": _iso(link.linked_at),
            # Provenance humaine : comment l'élément est arrivé dans ce Dossier ; le reste est avancé.
            "provenance": _provenance(artifact, link),
        }
        if advanced:
            view["advanced"] = {"artifact_id": artifact.artifact_id, "artifact_kind": artifact.kind.value,
                                "source": artifact.source, "link_origin": link.origin.value,
                                "jarvis_session_id": artifact.jarvis_session_id, "context_id": artifact.context_id,
                                "mime_type": artifact.mime_type, "size_bytes": artifact.size_bytes}
        return view

    async def _memory_entries(self, board_id: str, *, advanced: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fichiers de la mémoire par `WorkspaceService.memory_tree` ; un refus du magasin est dit, pas levé."""

        try:
            tree = await self._workspace.memory_tree(board_id, depth=MEMORY_SCAN_DEPTH, max_entries=_MEMORY_LIST_ENTRIES)
        except (BoardMemoryError, BoardMemoryUnavailable, BoardError) as exc:
            # capture: la mémoire illisible ne cache pas les Artifacts ; dite avec son code, et journalisée.
            code = str(getattr(getattr(exc, "code", None), "value", getattr(exc, "code", "board_memory_failed")))
            self._trace("core.dossier.memory_unreadable", f"Mémoire du Board illisible pour le Dossier : {code}",
                        level="warning", data={"board_id": board_id, "code": code})
            return [], {"exists": None, "files": 0, "truncated": False, "error": code,
                        "message": redact_paths(str(exc))[:300]}
        files = [self._memory_view(board_id, entry, advanced=advanced) for entry in tree["entries"]
                 if entry.get("kind") == "file"]
        return files, {"exists": tree["exists"], "files": len(files), "truncated": tree["truncated"],
                       "skipped": tree["skipped"]}

    async def _artifact_entries(self, board_id: str, *, advanced: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        links = await self._links.links_of_board(board_id, limit=MAX_LINKED_SCAN + 1)
        shown, missing = [], 0
        for link in links[:MAX_LINKED_SCAN]:
            try:
                artifact = await self._artifacts.get(link.artifact_id)
            except ArtifactError as exc:
                if exc.code is not ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                    raise
                missing += 1  # intentional: a link to a vanished Artifact is counted (`missing`), never listed
                continue
            shown.append(self._artifact_view(artifact, link, advanced=advanced))
        if missing:
            self._trace("core.dossier.integrity_problem", "Liens du Board vers des Artifacts absents",
                        level="warning", data={"board_id": board_id, "missing": missing})
        return shown, {"linked": await self._links.count_links(board_id), "truncated": len(links) > MAX_LINKED_SCAN,
                       "missing": missing}

    @staticmethod
    def _board_view(board: Board) -> dict[str, Any]:
        return {"board_id": board.board_id, "title": board.title, "board_kind": board.board_kind.value,
                "status": board.status.value, "writable": board.status is not BoardStatus.ARCHIVED}

    async def list_entries(self, board_id: str, *, limit: int = DEFAULT_LIST_LIMIT, since: datetime | None = None,
                           advanced: bool = False) -> dict[str, Any]:
        """Entrées du Dossier (mémoire + Artifacts liés), `summary.md` d'abord puis les plus récentes ; bornée."""

        if type(limit) is not int or not 1 <= limit <= MAX_LIST_LIMIT:
            raise WorkspaceError("invalid_request", f"limit must be an integer in 1..{MAX_LIST_LIMIT}")
        if type(advanced) is not bool:
            raise WorkspaceError("invalid_request", "advanced must be true or false")
        started = time.monotonic()
        board = await self._board(board_id)
        memory, memory_source = await self._memory_entries(board.board_id, advanced=advanced)
        artifacts, artifact_source = await self._artifact_entries(board.board_id, advanced=advanced)
        entries = memory + artifacts
        if since is not None:
            entries = [entry for entry in entries
                       if entry["modified_at"] is not None and datetime.fromisoformat(entry["modified_at"]) > since]
        entries.sort(key=lambda e: (e["kind"] != EntryKind.MEMORY_SUMMARY.value,
                                    -datetime.fromisoformat(e["modified_at"]).timestamp() if e["modified_at"] else 0))
        page = entries[:limit]
        await self._ranger_titles(board.board_id, page)
        await self._research_details(board.board_id, page)
        self._read("dossier_list", started, board_id=board.board_id, count=len(page), total=len(entries))
        payload: dict[str, Any] = {
            "board": self._board_view(board), "entries": page, "total": len(entries),
            "truncated": len(entries) > limit or bool(memory_source.get("truncated"))
            or bool(artifact_source.get("truncated")),
            "sources": {"memory": memory_source, "artifacts": artifact_source},
        }
        if since is not None:
            payload["since"] = since.isoformat()
        return payload

    async def entry(self, board_id: str, entry_id: str, *, advanced: bool = False) -> dict[str, Any]:
        """Une entrée, résolue chez son propriétaire ; `dossier_entry_not_found` si elle n'est pas dans ce Dossier."""

        ref = DossierEntryRef.parse(entry_id)
        started = time.monotonic()
        board = await self._board(board_id)
        view = await self._resolve_entry(board, ref, advanced=advanced)
        await self._ranger_titles(board.board_id, [view])
        await self._research_details(board.board_id, [view])
        self._read("dossier_entry", started, board_id=board.board_id, source=ref.source.value)
        return {"board": self._board_view(board), "entry": view}

    async def _ranger_titles(self, board_id: str, views: list[dict[str, Any]]) -> None:
        """Une note rangée prend le titre `#` qu'elle porte (accents compris), lu en tête par le propriétaire.

        Seules les notes au nom de `ranger_path` sont lues (bornées par la page) ; une tête illisible garde le titre
        tiré du nom, sans suffixe d'empreinte (QA S05, polish 1).
        """

        for view in views:
            if view.get("source") != EntrySource.MEMORY.value or not is_ranger_note(str(view.get("path") or "")):
                continue
            try:
                head = await self._workspace.memory_read(board_id, path=view["path"], max_bytes=RANGER_HEADING_BYTES)
            except (BoardMemoryError, BoardMemoryUnavailable, BoardError, WorkspaceError) as exc:
                # capture: le titre du nom reste ; la cause est journalisée, la liste n'échoue pas pour un titre.
                self._trace("core.dossier.title_unread", "Titre d'une note rangée illisible", level="warning",
                            data={"board_id": board_id, "code": str(getattr(getattr(exc, "code", None), "value",
                                                                             getattr(exc, "code", "unknown")))})
                continue
            title = heading_title(str(head.get("text") or ""))
            if title:
                view["title"] = title

    async def _research_details(self, board_id: str, views: list[dict[str, Any]]) -> None:
        """Un document de recherche (`documents/research/*.md`, V1.2 Slice 04) prend son sujet pour titre et dit
        sa vérification (`research` : `checked_at`, `volatility`, sources, sources en échec, `problem`).

        Seul son front-matter est lu (2 Kio, relu jusqu'à 16 Kio s'il n'est pas fermé), pour la seule page rendue.
        Un document sans en-tête lisible garde son titre de nom et porte `research.problem` ; une lecture refusée
        est journalisée et la liste n'échoue pas.
        """

        for view in views:
            path = str(view.get("path") or "")
            if view.get("source") != EntrySource.MEMORY.value or not is_research_path(path):
                continue
            try:
                head = await self._workspace.memory_read(board_id, path=path, max_bytes=MAX_RESEARCH_HEAD_BYTES)
                meta, problem = parse_front_matter(str(head.get("text") or ""), complete=bool(head.get("eof")))
                if problem == FRONT_MATTER_TOO_LONG:
                    head = await self._workspace.memory_read(board_id, path=path, max_bytes=MAX_FRONT_MATTER_BYTES)
                    meta, problem = parse_front_matter(str(head.get("text") or ""), complete=bool(head.get("eof")))
            except (BoardMemoryError, BoardMemoryUnavailable, BoardError, WorkspaceError) as exc:
                # capture: le document reste listé sous son nom ; la cause est journalisée.
                self._trace("core.dossier.research_unread", "En-tête d'un document de recherche illisible",
                            level="warning", data={"board_id": board_id, "code": str(getattr(getattr(
                                exc, "code", None), "value", getattr(exc, "code", "unknown")))})
                view["research"] = {"problem": "unreadable"}
                continue
            details: dict[str, Any] = {"problem": problem} if problem else {}
            if meta is not None:
                if meta.topic:
                    view["title"] = meta.topic
                    details["topic"] = meta.topic
                details.update({"checked_at": meta.checked_at.isoformat() if meta.checked_at else None,
                                "volatility": meta.volatility.value if meta.volatility else None,
                                "sources": len(meta.sources),
                                "failed_sources": sum(1 for source in meta.sources if source.failed)})
            view["research"] = details

    async def _resolve_entry(self, board: Board, ref: DossierEntryRef, *, advanced: bool) -> dict[str, Any]:
        if ref.source is EntrySource.MEMORY:
            try:
                stat = await self._workspace.memory_stat(board.board_id, path=ref.key)
            except BoardMemoryError as exc:
                if exc.code is not BoardMemoryErrorCode.MEMORY_NOT_FOUND:
                    raise
                raise WorkspaceError(DossierCode.ENTRY_NOT_FOUND.value,
                                     f"{ref.entry_id} is not in the Dossier of board {board.board_id}",
                                     status=404) from None
            if stat["entry"]["kind"] != "file":
                raise WorkspaceError(DossierCode.ENTRY_NOT_FOUND.value,
                                     f"{ref.entry_id} is a folder, not a Dossier entry", status=404)
            return self._memory_view(board.board_id, stat["entry"], advanced=advanced)
        # Lecture directe du lien (Slice 08, polish S05 10) : un Artifact lié à plus de 500 Boards n'est plus lu
        # comme absent de ce Dossier.
        link = await self._links.link_of(board.board_id, ref.key)
        if link is None:
            raise WorkspaceError(DossierCode.ENTRY_NOT_FOUND.value,
                                 f"{ref.entry_id} is not linked to board {board.board_id}", status=404)
        try:
            artifact = await self._artifacts.get(ref.key)
        except ArtifactError as exc:
            if exc.code is not ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                raise
            raise WorkspaceError(DossierCode.ENTRY_NOT_FOUND.value, f"{ref.entry_id} no longer exists",
                                 status=404) from None
        return self._artifact_view(artifact, link, advanced=advanced)

    # ------------------------------------------------------------ 2. source durable d'un objet de scène

    @staticmethod
    def _object_ids(object_ids: object) -> tuple[str, ...]:
        if (not isinstance(object_ids, (list, tuple)) or not object_ids or len(object_ids) > MAX_RANGER_OBJECTS
                or not all(isinstance(item, str) and 0 < len(item) <= 128 for item in object_ids)):
            raise WorkspaceError("invalid_request",
                                 f"object_ids must be a list of 1..{MAX_RANGER_OBJECTS} scene object ids")
        return tuple(dict.fromkeys(object_ids))

    def _memory_path_of(self, board_id: str, source_path: str) -> BoardMemoryPath | None:
        """Le chemin relatif à la mémoire de **ce** Board, ou `None` s'il est ailleurs (autre Board, disque)."""

        root = os.path.normpath(str(self._memory_root(board_id)))
        target = os.path.normpath(source_path)
        if not os.path.normcase(target).startswith(os.path.normcase(root) + os.sep):
            return None
        relative = target[len(root) + 1:].replace(os.sep, "/")
        try:
            return BoardMemoryPath.parse(relative)
        except BoardMemoryError:
            return None  # intentional: a name the memory refuses is not one of its entries; said as outside

    async def _resolve_object(self, board: Board, snapshot: SceneSnapshot, object_id: str) -> _Resolved:
        item = snapshot.get_object(object_id)
        if item is None or not item.active:
            return _Resolved(object_id, "refused", code=DossierCode.OBJECT_NOT_FOUND.value,
                             reason="aucun objet actif de la scène ne porte cet identifiant")
        backing = classify_scene_object(item)
        if backing.kind is BackingKind.REFUSED:
            assert backing.code is not None
            return _Resolved(object_id, "refused", code=backing.code.value, reason=backing.reason, item=item)
        if backing.kind is BackingKind.CONTENT:
            return _Resolved(object_id, "content", ref=DossierEntryRef.memory(ranger_path(item).value), item=item)
        if backing.kind is BackingKind.ARTIFACT:
            try:
                await self._artifacts.get(backing.artifact_id)
            except ArtifactError as exc:
                if exc.code is not ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                    raise
                return _Resolved(object_id, "refused", code=DossierCode.SOURCE_MISSING.value,
                                 reason="l'Artifact du registre n'existe plus", item=item)
            return _Resolved(object_id, "artifact", ref=DossierEntryRef.artifact(backing.artifact_id), item=item)
        path = self._memory_path_of(board.board_id, backing.source_path)
        if path is None:
            return _Resolved(object_id, "refused", code=DossierCode.SOURCE_OUTSIDE_BOARD.value,
                             reason="le fichier lié est hors de la mémoire de ce Board", item=item)
        try:
            stat = await self._workspace.memory_stat(board.board_id, path=path.value)
        except BoardMemoryError as exc:
            if exc.code is not BoardMemoryErrorCode.MEMORY_NOT_FOUND:
                raise
            return _Resolved(object_id, "refused", code=DossierCode.SOURCE_MISSING.value,
                             reason="le fichier lié n'existe plus", item=item)
        return _Resolved(object_id, "memory", ref=DossierEntryRef.memory(stat["entry"]["path"]), item=item)

    async def backing(self, board_id: str, object_ids: object) -> dict[str, Any]:
        """Lecture : la source durable de chaque objet désigné (ce que Ranger ferait), sans rien écrire."""

        ids = self._object_ids(object_ids)
        started = time.monotonic()
        board = await self._board(board_id)
        snapshot = await self._snapshot()
        resolved = [await self._resolve_object(board, snapshot, object_id) for object_id in ids]
        # Ranger n'agit que sur le Board affiché (`_displayed_board`) : l'aperçu le dit au lieu de promettre
        # « rangeable » là où Ranger refuserait 409 (QA S05, polish 8 ; Slice 06).
        if board.status is BoardStatus.ARCHIVED:
            inactive: str | None = BoardErrorCode.BOARD_ARCHIVED.value
        else:
            session = await self._boards.current_session()
            active = session is not None and session.active_board_id == board.board_id
            inactive = None if active else DossierCode.BOARD_NOT_ACTIVE.value
        self._read("dossier_backing", started, board_id=board.board_id, count=len(resolved),
                   board_active=inactive is None)
        answer: dict[str, Any] = {"board_id": board.board_id, "board_active": inactive is None,
                                  "objects": [item.view() for item in resolved]}
        if inactive is not None:
            answer.update(board_code=inactive, board_message=BOARD_INACTIVE_SENTENCES[inactive])
        return answer

    # ------------------------------------------------------------ 3. Ranger

    @staticmethod
    def _actor(origin: str) -> SceneActor:
        return SceneActor.BRAIN if origin == "brain" else SceneActor.USER

    async def _make_durable(self, board: Board, resolved: _Resolved, origin: str) -> tuple[str, dict[str, Any]]:
        """Confirme ou crée la source durable ; rend (action, détails). Une exception = durabilité non acquise."""

        assert resolved.item is not None and resolved.ref is not None
        if resolved.backing == "artifact":
            linked = await self._workspace.artifact_link(board.board_id, resolved.ref.key, origin=origin)
            return ("linked" if linked["created"] else "confirmed"), {"artifact_id": resolved.ref.key}
        if resolved.backing == "memory":
            return "confirmed", {"path": resolved.ref.key}
        item = resolved.item
        text = ranger_markdown(item, stored_at=self._clock(), origin=origin)
        # Chemin de l'objet, puis, s'il porte un autre corps (contenu modifié depuis, même titre), celui de ce corps :
        # jamais d'écrasement, et seul un fichier au corps identique à l'affiché vaut « confirmé » (QA S05 B1).
        for path in (resolved.ref.key, ranger_path(item, content_variant=True).value):
            try:
                written = await self._workspace.memory_write(board.board_id, path=path, content=text, origin=origin)
            except BoardMemoryError as exc:
                if exc.code is not BoardMemoryErrorCode.MEMORY_EXISTS:
                    raise
                if await self._holds_body(board.board_id, path, ranger_body(item)):
                    return "confirmed", {"path": path}
                continue  # un autre corps (l'ancienne version) : il reste intact, on essaie le chemin de ce corps-ci
            except WorkspaceError as exc:
                if exc.code != LEDGER_FAILED:
                    raise
                # Le fichier EST écrit (`applied: true`) : la durabilité est acquise, la ligne d'activité manque.
                return "materialized", {"path": path, "ledger_failed": True}
            return "materialized", {"path": written["path"], "sha256": written["sha256"]}
        raise BoardMemoryError(BoardMemoryErrorCode.MEMORY_EXISTS,
                               f"{path}: already holds another content for this object; nothing overwritten")

    async def _holds_body(self, board_id: str, path: str, body: str) -> bool:
        """Le fichier rangé à `path` porte-t-il exactement ce corps (pied de provenance exclu) ?"""

        page = await self._workspace.memory_read(board_id, path=path, max_bytes=MAX_READ_BYTES)
        return bool(page["eof"]) and stored_body(page["text"]) == body

    async def ranger(self, board_id: str, object_ids: object, *, origin: str = "user") -> dict[str, Any]:
        """Ranger : source durable d'abord, retrait de la représentation ensuite ; résultat par objet."""

        origin = self._workspace._origin(origin)  # noqa: SLF001 - one rule for `origin`, the workspace's
        ids = self._object_ids(object_ids)
        started = time.monotonic()
        board = await self._displayed_board(board_id)
        snapshot = await self._snapshot()
        results: dict[str, dict[str, Any]] = {}
        durable: dict[str, _Resolved] = {}
        for object_id in ids:
            resolved = await self._resolve_object(board, snapshot, object_id)
            if resolved.backing == "refused":
                results[object_id] = self._refused(resolved.object_id, resolved.code or "", resolved.reason,
                                                   backing=None)
                continue
            try:
                action, detail = await self._make_durable(board, resolved, origin)
            except (BoardMemoryError, BoardError, ArtifactError, WorkspaceError, BoardMemoryUnavailable) as exc:
                # capture: durabilité non acquise -> l'objet reste affiché, refus nommé avec la cause du propriétaire.
                code = str(getattr(getattr(exc, "code", None), "value", getattr(exc, "code", "dossier_failed")))
                results[object_id] = self._refused(object_id, code, redact_paths(str(exc))[:300],
                                                   backing=resolved.backing, sentence=(
                                                       "Le Dossier n'a pas pu garder ce contenu : il reste sur le "
                                                       "Board."))
                continue
            assert resolved.ref is not None
            durable[object_id] = resolved
            entry_id = DossierEntryRef.memory(detail["path"]).entry_id if "path" in detail else resolved.ref.entry_id
            results[object_id] = {"object_id": object_id, "status": "stored", "backing": resolved.backing,
                                  "action": action, "entry_id": entry_id, "durable": True,
                                  "archived": False, **detail}
        revision = await self._archive_durable(board, durable, results, origin)
        stored = sum(1 for item in results.values() if item["status"] == "stored")
        self._mutated("dossier_ranger", started, board_id=board.board_id, stored=stored,
                      refused=len(results) - stored, archived=sum(1 for r in results.values() if r["archived"]),
                      origin=origin)
        return {"board_id": board.board_id, "stored": stored, "refused": len(results) - stored,
                "results": [results[object_id] for object_id in ids], "revision": revision}

    async def _archive_durable(self, board: Board, durable: Mapping[str, _Resolved],
                               results: dict[str, dict[str, Any]], origin: str) -> int | None:
        """**Une** `archive_selection` des objets dont la source durable est acquise ; un contenu changé reste."""

        if not durable:
            return None
        kept: list[str] = []

        def plan(snapshot: SceneSnapshot) -> SceneCommand | None:
            kept.clear()
            for object_id, resolved in durable.items():
                current = snapshot.get_object(object_id)
                if current is None or not current.active:
                    continue  # déjà retiré par un autre geste : rien à faire, la source durable est là
                if resolved.backing == "content" and resolved.item is not None \
                        and current.payload != resolved.item.payload:
                    continue  # le contenu rangé n'est plus celui affiché : ne pas retirer la version plus récente
                kept.append(object_id)
            if not kept:
                return None
            return SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=self._actor(origin),
                                selection=SceneSelection(ids=tuple(kept)))

        update = None
        try:
            update = await self._scene.apply_if(plan)
        except (SceneStoreError, ValueError, TypeError) as exc:
            self._archive_refused(board, results, kept, f"{type(exc).__name__}: {exc}")
        if update is not None and update.outcome not in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            reason = update.reason.value if update.reason is not None else update.outcome.value
            self._archive_refused(board, results, kept, f"{reason}: {update.detail}".rstrip(": "))
        if update is not None and update.outcome in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            snapshot = update.snapshot
        else:
            try:
                snapshot = await self._snapshot()
            except WorkspaceError as exc:
                # capture: la scène a disparu après la mise en Dossier ; chaque objet le dit, la source durable reste.
                self._archive_refused(board, results, list(durable), str(exc))
                return None
        for object_id, resolved in durable.items():
            current = snapshot.get_object(object_id)
            still_shown = current is not None and current.active
            results[object_id]["archived"] = not still_shown
            if still_shown and object_id not in kept and resolved.backing == "content":
                results[object_id].update(code=DossierCode.CHANGED_MEANWHILE.value,
                                          message=SENTENCES[DossierCode.CHANGED_MEANWHILE])
        applied = update is not None and update.outcome is SceneCommandOutcome.APPLIED
        return update.snapshot.revision if applied else None

    def _archive_refused(self, board: Board, results: dict[str, dict[str, Any]], ids: list[str], detail: str) -> None:
        for object_id in ids:
            results[object_id].update(code=DossierCode.ARCHIVE_FAILED.value, reason=detail[:300],
                                      message=SENTENCES[DossierCode.ARCHIVE_FAILED])
        self._trace("core.dossier.archive_failed", "Ranger : source durable acquise, retrait refusé par la scène",
                    level="warning", data={"board_id": board.board_id, "count": len(ids), "detail": detail[:_TRACE_CHARS]})

    def _refused(self, object_id: str, code: str, reason: str, *, backing: str | None,
                 sentence: str | None = None) -> dict[str, Any]:
        self._trace("core.dossier.ranger_refused", f"Ranger refusé pour un objet : {code}", level="warning",
                    data={"object_id": object_id, "code": code})
        return {"object_id": object_id, "status": "refused", "backing": backing, "action": None, "entry_id": None,
                "durable": False, "archived": False, "code": code, "message": sentence or _sentence(code),
                "reason": reason}

    # ------------------------------------------------------------ 4. Afficher sur le Board

    async def present(self, board_id: str, entry_id: str, *, representation: str = Representation.WINDOW.value,
                      origin: str = "user") -> dict[str, Any]:
        """Une représentation de l'entrée, pointant vers la même source ; réutilisée si elle existe déjà."""

        origin = self._workspace._origin(origin)  # noqa: SLF001 - one rule for `origin`, the workspace's
        ref = DossierEntryRef.parse(entry_id)
        try:
            shape = Representation(representation)
        except ValueError:
            raise WorkspaceError("invalid_request",
                                 f"representation must be one of {[r.value for r in Representation]}") from None
        started = time.monotonic()
        board = await self._displayed_board(board_id)
        view = await self._resolve_entry(board, ref, advanced=False)
        # Le nom tel que stocké (casse comprise) : la réponse et `source_path` désignent le fichier sur disque (QA S05, polish 5).
        ref = DossierEntryRef.parse(view["entry_id"])
        source_path, artifact_id = "", ""
        if ref.source is EntrySource.MEMORY:
            source_path = str(self._memory_root(board.board_id).joinpath(*ref.key.split("/")))
            if len(source_path) > MAX_SOURCE_PATH_CHARS:
                raise WorkspaceError(DossierCode.ENTRY_INVALID.value,
                                     f"the file path is longer than the scene bound ({MAX_SOURCE_PATH_CHARS})")
        else:
            artifact_id = ref.key
        payload = ScenePayload(title=view["title"][:MAX_TITLE_CHARS], source_path=source_path,
                               registry_artifact_id=artifact_id)
        actor = self._actor(origin)
        new_id = f"dossier-{ref.source.value}-{self._new_id()}"
        chosen: dict[str, Any] = {}

        def same_source(item: SceneObject) -> bool:
            if artifact_id:
                return item.payload.registry_artifact_id == artifact_id
            return bool(item.payload.source_path) and \
                os.path.normcase(os.path.normpath(item.payload.source_path)) == os.path.normcase(source_path)

        def plan(snapshot: SceneSnapshot) -> SceneCommand | None:
            found = next((item for item in snapshot.objects if item.active and same_source(item)), None)
            if found is None:
                chosen.update(object_id=new_id, created=True)
                fields = SceneObjectFields(kind=SceneObjectKind.WINDOW, category=PRESENT_CATEGORY, payload=payload,
                                           representation=shape)
                return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=actor, object_id=new_id, fields=fields)
            chosen.update(object_id=found.object_id, created=False)
            if found.visibility is Visibility.VISIBLE and found.representation is shape:
                return None
            return SceneCommand(op=SceneOp.PATCH_SELECTION, actor=actor,
                                selection=SceneSelection(ids=(found.object_id,)),
                                changes=SelectionChanges(visibility=Visibility.VISIBLE, representation=shape))

        if self._scene is None:
            raise WorkspaceError(DossierCode.SCENE_UNAVAILABLE.value, "the scene is not served by this Core", status=503)
        try:
            update = await self._scene.apply_if(plan)
        except SceneStoreError as exc:
            raise WorkspaceError(DossierCode.SCENE_UNAVAILABLE.value, f"the scene refused the write: {exc}",
                                 status=503) from exc
        if update is not None and update.outcome not in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            reason = update.reason.value if update.reason is not None else update.outcome.value
            raise WorkspaceError(reason, f"the scene refused the representation ({reason})"
                                 + (f": {update.detail}" if update.detail else ""), status=409)
        self._mutated("dossier_present", started, board_id=board.board_id, source=ref.source.value,
                      created=chosen["created"], origin=origin)
        return {"board_id": board.board_id, "entry_id": ref.entry_id, "object_id": chosen["object_id"],
                "created": chosen["created"], "reused": not chosen["created"], "representation": shape.value,
                "revision": None if update is None else update.snapshot.revision}

    # ------------------------------------------------------------ journal

    def _read(self, operation: str, started: float, **data: Any) -> None:
        self._trace("core.dossier.read", f"Dossier lu : {operation}",
                    data={"operation": operation, "duration_ms": int((time.monotonic() - started) * 1000), **data})

    def _mutated(self, operation: str, started: float, **data: Any) -> None:
        self._trace("core.dossier.mutated", f"Dossier : {operation}",
                    data={"operation": operation, "duration_ms": int((time.monotonic() - started) * 1000), **data})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not fail a Dossier operation
            pass


__all__ = ["DossierService", "SENTENCES"]
