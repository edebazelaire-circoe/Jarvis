"""Service Core des Boards de travail (handoff board-session, Slice 02 : partie stockage).

Core possède le magasin des Boards (06 section A). Ce service est la seule
porte d'écriture : les routes `/v1/boards*` (et, plus tard, le Control Center
et MCP par leur proxy) passent par lui, jamais par le dépôt. Les règles
(Board archivé non modifiable, Board actif non archivable, bornes) sont celles
des transitions pures de `jarvis.domain.workspace_board` ; rien n'est
redécidé ici.

Ce que fait cette Slice :

- lecture/création/édition/archivage, avec les gardes du domaine ;
- `ensure_default()` : migration idempotente de l'état mono-espace vers le
  Board `default` (06 section H), clé « table vide » ;
- **mode d'interaction par Board** (06 section F) : un abonné de
  `InteractionModeService` écrit chaque changement sur le Board actif, et le
  démarrage de Core réapplique le mode du Board actif (`source="board_restore"`).

**Board actif (V1).** Il n'y a pas de pointeur séparé : le Board actif est
`active_board_id` de la Session ouverte (`jarvis_sessions`, persistée), et
`default` quand aucune Session n'est ouverte (avant le démarrage). Depuis la
Slice 03, Core ouvre une Session à chaque démarrage sur le dernier Board actif
(`jarvis/core/session_manager.py`). Un second pointeur serait une deuxième
vérité ; celui-ci est celle que 03/04b écrivent.

**Reprise du réglage historique.** Le Control Center rejoue toujours sa
préférence globale quand Core est à la révision 0 (`control_center.py`,
sources `startup` / `core_restart`). Ce rejeu n'est plus qu'une entrée de
migration : sur un Board jamais réglé (`unset`) il est adopté une fois
(origine `migrated`) ; sur un Board déjà réglé il ne l'écrase pas, et Core
réapplique le mode du Board. `save_retry` n'est pas un rejeu : c'est le clic
de l'utilisateur livré en retard, traité comme un choix.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from jarvis.core.interaction_mode import InteractionModeService
from jarvis.domain.interaction_mode import InteractionMode, InteractionModeError
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, Board, BoardError, BoardErrorCode, InteractionModeOrigin, SceneRef,
    adopt_legacy_interaction_mode, archive_board, create_board, default_board, set_interaction_mode, update_board,
)
from jarvis.ports.v2 import DiagnosticSink
from jarvis.ports.workspace_board import BoardRepository, BoardStoreError

#: Sources de `InteractionModeService.request` émises par le rejeu global du
#: Control Center : entrée de migration, pas un choix (voir l'en-tête).
LEGACY_REPLAY_SOURCES = frozenset({"startup", "core_restart"})
#: Sources émises par ce service lui-même : le mode vient déjà du Board.
BOARD_RESTORE_SOURCE = "board_restore"
BOARD_SWITCH_SOURCE = "board_switch"
BOARD_SOURCES = frozenset({BOARD_RESTORE_SOURCE, BOARD_SWITCH_SOURCE})

#: Champs éditables d'un Board par `create` / `update` (routes, MCP, UI). Le
#: mode d'interaction n'y est pas : il change par `/v1/interaction-mode`, que
#: Core applique et que l'abonné enregistre sur le Board actif.
EDITABLE_FIELDS = frozenset({
    "title", "context_summary", "task_refs", "artifact_refs", "project_refs", "scene_ref", "runtime_metadata",
})

_TRACE_EXCEPTION_CHARS = 200


def _invalid(message: str) -> BoardError:
    return BoardError(BoardErrorCode.INVALID_BOARD, message)


def parse_board_edits(payload: object, *, require_title: bool) -> dict[str, Any]:
    """Corps JSON -> arguments de `update_board`. Strict : champ inconnu ou mal typé = `invalid_board`.

    Les valeurs elles-mêmes (longueurs, bornes) sont vérifiées par le domaine
    à la construction du Board ; ici seulement la forme du fil.
    """

    if not isinstance(payload, dict):
        raise _invalid("board request must be a JSON object")
    unknown = sorted(str(key)[:40] for key in payload if key not in EDITABLE_FIELDS)
    if unknown:
        raise _invalid(f"unknown board fields: {unknown[:5]}")
    if require_title and "title" not in payload:
        raise BoardError(BoardErrorCode.INVALID_TITLE, "title is required")
    if not payload:
        raise _invalid("board update names no field")
    edits: dict[str, Any] = {}
    for name, value in payload.items():
        if name in {"task_refs", "artifact_refs", "project_refs"}:
            # Une chaîne serait itérée caractère par caractère : liste exigée.
            if not isinstance(value, list):
                raise _invalid(f"{name} must be a list of strings")
            edits[name] = tuple(value)
        elif name == "scene_ref":
            edits[name] = None if value is None else SceneRef.from_payload(value)
        elif name == "runtime_metadata":
            if not isinstance(value, dict):
                raise _invalid("runtime_metadata must be an object")
            edits[name] = value
        elif name == "title":
            if not isinstance(value, str):
                raise BoardError(BoardErrorCode.INVALID_TITLE, "title must be a string")
            edits[name] = value
        else:  # context_summary
            if not isinstance(value, str):
                raise _invalid("context_summary must be a string")
            edits[name] = value
    return edits


class BoardService:
    """Porte unique des Boards dans Core. Voir l'en-tête du module."""

    def __init__(
        self,
        repository: BoardRepository,
        *,
        interaction_mode: InteractionModeService,
        diagnostics: DiagnosticSink | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repo = repository
        self._modes = interaction_mode
        self._diagnostics = diagnostics
        self._clock = clock
        # Lecture-modification-écriture d'un Board : deux éditions concurrentes
        # (route + abonné de mode) ne s'écrasent pas l'une l'autre.
        self._lock = asyncio.Lock()
        self._pending: set[asyncio.Task[None]] = set()
        self._listening = False

    # ------------------------------------------------------------ cycle de vie

    async def start(self, *, ensure_default: bool = True) -> None:
        """Au démarrage de Core, après `state.initialize()` et avant toute route.

        Lève seulement si la base refuse (Core ne démarre pas sur une base
        illisible) ; un mode de Board que Core refuse est journalisé, pas levé.
        Core appelle `ensure_default()` lui-même, avant d'ouvrir la Session
        (Slice 03 : le mode restauré est celui du Board de cette Session), puis
        `start(ensure_default=False)`.
        """

        if ensure_default:
            await self.ensure_default()
        await self.restore_interaction_mode()
        if not self._listening:
            # Après la restauration : l'application du mode du Board ne se
            # réécrit pas sur lui-même.
            self._modes.add_listener(self._on_mode_changed)
            self._listening = True

    async def stop(self) -> None:
        """Laisser finir les écritures de mode en vol, avant la fermeture de la base."""

        await self.drain()

    async def drain(self) -> None:
        while self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)

    # ------------------------------------------------------------ migration

    async def ensure_default(self) -> bool:
        """Créer le Board `default` si aucun Board n'existe (06 section H). Idempotent.

        Rend vrai si cet appel l'a créé. Clé « table vide », tenue dans une
        seule transaction : un second démarrage, ou deux démarrages concurrents
        sur le même fichier, n'insèrent jamais deux fois. Le Board naît
        `unset` : le mode global historique sera adopté par le rejeu du Control
        Center (`_on_mode_changed`), une seule fois. Des Boards existent sans
        `default` : rien n'est inventé, c'est dit ; `get_active()` le dira
        ensuite par `board_not_found` tant qu'aucune Session ne désigne un Board.
        """

        created = await self._repo.insert_board_if_empty(default_board(now=self._clock()))
        if created:
            self._trace("core.board.default_created", "Board par défaut créé (migration mono-espace)",
                        data={"board_id": DEFAULT_BOARD_ID})
        elif await self._repo.get_board(DEFAULT_BOARD_ID) is None:
            self._trace("core.board.default_absent", "Aucun Board par défaut : des Boards existent déjà",
                        level="warning", data={"board_id": DEFAULT_BOARD_ID})
        return created

    # ------------------------------------------------------------ lecture

    async def active_board_id(self) -> str:
        """Board de la Session ouverte, `default` sans Session (voir l'en-tête)."""

        session = await self._repo.current_session()
        return session.active_board_id if session is not None else DEFAULT_BOARD_ID

    async def list(self, *, include_archived: bool = False) -> tuple[Board, ...]:
        return tuple(await self._repo.list_boards(include_archived=include_archived))

    async def get(self, board_id: str) -> Board:
        board = await self._repo.get_board(board_id) if isinstance(board_id, str) else None
        if board is None:
            raise BoardError(BoardErrorCode.BOARD_NOT_FOUND, f"board {str(board_id)[:80]!r} does not exist")
        return board

    async def get_active(self) -> Board:
        return await self.get(await self.active_board_id())

    # ------------------------------------------------------------ écriture

    async def create(self, payload: object) -> Board:
        edits = parse_board_edits(payload, require_title=True)
        now = self._clock()
        title = edits.pop("title")
        board = create_board(title, now=now)
        if edits:
            board = update_board(board, now=now, **edits)
        async with self._lock:
            await self._repo.save_board(board)
        self._trace("core.board.created", "Board créé", data={"board_id": board.board_id})
        return board

    async def update(self, board_id: str, payload: object) -> Board:
        edits = parse_board_edits(payload, require_title=False)
        async with self._lock:
            board = update_board(await self.get(board_id), now=self._clock(), **edits)
            await self._repo.save_board(board)
        self._trace("core.board.updated", "Board modifié",
                    data={"board_id": board.board_id, "fields": sorted(edits)})
        return board

    async def archive(self, board_id: str) -> Board:
        async with self._lock:
            board = await self.get(board_id)
            archived = archive_board(board, active_board_id=await self.active_board_id(), now=self._clock())
            if archived is not board:
                await self._repo.save_board(archived)
        self._trace("core.board.archived", "Board archivé",
                    data={"board_id": board_id, "changed": archived is not board})
        return archived

    # ------------------------------------------------------------ mode d'interaction

    async def restore_interaction_mode(self) -> None:
        """Réappliquer le mode du Board actif au démarrage de Core. Ne lève pas pour un refus de mode.

        Board `unset` : rien n'est demandé, Core reste au défaut à la
        révision 0, et c'est précisément ce qui arme le rejeu du Control
        Center, donc la migration unique du réglage historique.
        """

        try:
            board = await self.get_active()
        except BoardError as exc:
            self._trace("core.board.interaction_mode.restore_failed",
                        f"Mode du Board actif non restauré : {exc}", level="error",
                        data={"code": exc.code.value})
            return
        if board.interaction_mode_origin is InteractionModeOrigin.UNSET:
            self._trace("core.board.interaction_mode.restore_skipped",
                        "Mode du Board jamais réglé : le réglage historique sera repris",
                        data={"board_id": board.board_id})
            return
        await self._apply_board_mode(board, source=BOARD_RESTORE_SOURCE)

    async def _apply_board_mode(self, board: Board, *, source: str) -> None:
        try:
            state, disposition = await self._modes.request(board.interaction_mode.value, source=source)
        except InteractionModeError as exc:
            self._trace("core.board.interaction_mode.apply_failed",
                        f"Mode du Board {board.board_id} refusé par Core : {exc}", level="error",
                        data={"board_id": board.board_id, "code": exc.code, "mode": board.interaction_mode.value,
                              "source": source})
            return
        self._trace("core.board.interaction_mode.applied", f"Mode du Board appliqué ({source})",
                    data={"board_id": board.board_id, "mode": state.mode.value, "revision": state.revision,
                          "disposition": disposition.value, "source": source})

    def _on_mode_changed(self, mode: InteractionMode) -> None:
        """Abonné synchrone de `InteractionModeService` : l'écriture part en tâche.

        La source est lue sur l'état du service, posé juste avant l'appel
        (`InteractionModeService._set` puis `_notify`). Les tâches s'exécutent
        dans l'ordre des changements (verrou FIFO) ; `drain()` les attend.
        """

        source = self._modes.state.source
        task = asyncio.get_running_loop().create_task(
            self._persist_mode(mode, source), name="jarvis-board-mode-persist")
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _persist_mode(self, mode: InteractionMode, source: str) -> None:
        if source in BOARD_SOURCES:
            return
        reassert: Board | None = None
        try:
            async with self._lock:
                board = await self.get_active()
                now = self._clock()
                if source in LEGACY_REPLAY_SOURCES:
                    if board.interaction_mode_origin is InteractionModeOrigin.UNSET:
                        await self._repo.save_board(adopt_legacy_interaction_mode(board, mode, now=now))
                        self._trace("core.board.interaction_mode.migrated",
                                    "Réglage de mode historique repris sur le Board",
                                    data={"board_id": board.board_id, "mode": mode.value, "source": source})
                    elif board.interaction_mode is not mode:
                        reassert = board
                elif not (board.interaction_mode is mode
                          and board.interaction_mode_origin is InteractionModeOrigin.USER):
                    await self._repo.save_board(set_interaction_mode(board, mode, now=now))
                    self._trace("core.board.interaction_mode.persisted", "Mode enregistré sur le Board actif",
                                data={"board_id": board.board_id, "mode": mode.value, "source": source})
        except (BoardError, BoardStoreError, RuntimeError, OSError) as exc:
            # Tâche de fond : personne à qui lever. Le mode effectif reste
            # appliqué ; seul son enregistrement sur le Board est perdu, et c'est
            # ce que dit cette ligne, avec la cause réelle.
            self._trace("core.board.interaction_mode.persist_failed",
                        f"Mode non enregistré sur le Board : {type(exc).__name__}: {str(exc)[:_TRACE_EXCEPTION_CHARS]}",
                        level="error",
                        data={"code": getattr(exc, "code", "board_store_failed"), "mode": mode.value,
                              "source": source})
            return
        if reassert is not None:
            # Hors du verrou : la demande notifie cet abonné, dont la tâche
            # (source board_restore) prend le verrou pour ne rien écrire.
            self._trace("core.board.interaction_mode.legacy_replay_overridden",
                        "Rejeu du réglage global ignoré : le Board a déjà son mode", level="warning",
                        data={"board_id": reassert.board_id, "board_mode": reassert.interaction_mode.value,
                              "replayed_mode": mode.value, "source": source})
            await self._apply_board_mode(reassert, source=BOARD_RESTORE_SOURCE)

    # ------------------------------------------------------------ journal

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not break a Board write
            pass
