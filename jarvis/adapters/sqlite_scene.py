"""Stockage SQLite de la scène constellation (handoff jarvis-constellation-scene-runtime, Slice 02).

Fichier dédié, `data/state/scene.sqlite3`, distinct de `jarvis.sqlite3` : la
scène évolue avec son propre `schema_version` sans toucher au schéma 1 de
l'état opérationnel, et un fichier de scène refusé ne rend jamais Core
indisponible.

Mêmes conventions que `sqlite_state.py` : table `schema_version`, colonnes
`data` en JSON, connexion unique sérialisée par un verrou asyncio, travail
natif dans un fil que l'annulation n'interrompt pas, WAL. Une base plus
récente, inconnue ou corrompue est **refusée** avec un code stable
(`SceneStoreErrorCode`), jamais réparée ni effacée.

Ce qui est stocké, c'est l'**état** qui résulte de chaque patch, pas une
suite de patchs à rejouer :

- `scene_meta` : ligne unique `scene_id`, `revision`, version du fil des
  colonnes `data` (`SCENE_SCHEMA_VERSION`) ;
- `scene_objects`, `scene_relations`, `scene_tombstones` : la scène active et
  ses pierres tombales, avec une `position` qui restitue exactement l'ordre
  des tuples de `SceneSnapshot` ;
- `scene_history` : la forme archivée de chaque objet, écrite par les
  opérations `archive_object`.

Chaque `commit` est une transaction `BEGIN IMMEDIATE … COMMIT` : un arrêt
brutal laisse la révision précédente ou la suivante, jamais une moitié. Le
chargement relit l'état par les décodeurs stricts du domaine
(`SceneObject.from_payload`, `SceneSnapshot`) : une ligne invalide est une
corruption, pas une valeur à deviner. Rien n'est rejoué, donc la garde des
champs immuables demandée par l'amendement PM de la Slice 02 pour un rejeu de
patchs stockés n'a pas lieu d'être ici.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, TypeVar

from jarvis.adapters.sqlite_state import run_sqlite_in_thread
from jarvis.domain.scene import (
    MAX_ARCHIVED_IDS,
    SCENE_SCHEMA_VERSION,
    PatchOpKind,
    SceneObject,
    ScenePatch,
    SceneRelation,
    SceneSnapshot,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.scene import ArchivedSceneObject, SceneStoreError, SceneStoreErrorCode

T = TypeVar("T")

#: Version de la disposition des tables de ce fichier. Toute autre valeur est
#: refusée : pas de migration implicite.
_SCHEMA_VERSION = 1
#: Lecture d'historique : bornée, jamais un fichier entier en mémoire.
MAX_HISTORY_READ = 1_000

_TABLES = ("schema_version", "scene_meta", "scene_objects", "scene_relations", "scene_tombstones", "scene_history")
_DDL = (
    "CREATE TABLE schema_version (version INTEGER NOT NULL)",
    """CREATE TABLE scene_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        scene_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 0),
        wire_schema_version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE scene_objects (
        object_id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, data TEXT NOT NULL)""",
    """CREATE TABLE scene_relations (
        relation_id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, data TEXT NOT NULL)""",
    """CREATE TABLE scene_tombstones (
        object_id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE)""",
    """CREATE TABLE scene_history (
        object_id TEXT NOT NULL, revision INTEGER NOT NULL, archived_at TEXT NOT NULL, data TEXT NOT NULL,
        PRIMARY KEY (object_id, revision))""",
    "CREATE INDEX idx_scene_history_revision ON scene_history(revision)",
)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _clip(value: object) -> str:
    """Valeur lue sur disque, bornée avant d'entrer dans un message."""

    text = str(value)
    return text if len(text) <= 80 else f"{text[:80]}…"


def _sqlite_code(exc: sqlite3.Error) -> SceneStoreErrorCode:
    """Classer une erreur SQLite sans la requalifier : fichier illisible ≠ disque indisponible."""

    name = getattr(exc, "sqlite_errorname", "")
    if name.startswith(("SQLITE_NOTADB", "SQLITE_CORRUPT")):
        return SceneStoreErrorCode.CORRUPTED
    if isinstance(exc, sqlite3.OperationalError):
        # Verrou, disque plein, droits : le fichier n'est pas en cause.
        return SceneStoreErrorCode.STORAGE_IO
    if isinstance(exc, sqlite3.DatabaseError):
        return SceneStoreErrorCode.CORRUPTED
    return SceneStoreErrorCode.STORAGE_IO


def _rollback(conn: sqlite3.Connection, exc: BaseException) -> None:
    if not conn.in_transaction:
        return
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error as rollback_exc:
        # L'erreur d'origine reste celle qui remonte ; l'échec du rollback
        # l'accompagne au lieu de la remplacer. SQLite annule de toute façon
        # une transaction non validée à la fermeture de la connexion.
        exc.add_note(f"rollback failed: {type(rollback_exc).__name__}: {rollback_exc}")


class SQLiteSceneRepository:
    """Implémente `SceneRepository` sur un fichier SQLite dédié."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------ ouverture

    async def initialize(self) -> None:
        async with self._lock:
            if self._conn is not None:
                return
            await run_sqlite_in_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        except (OSError, sqlite3.Error) as exc:
            raise SceneStoreError(
                SceneStoreErrorCode.STORAGE_IO, f"scene store {self.path} cannot be opened: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            self._prepare(conn)
        except sqlite3.Error as exc:
            conn.close()
            raise SceneStoreError(
                _sqlite_code(exc), f"scene store {self.path} unusable: {type(exc).__name__}: {exc}"
            ) from exc
        except BaseException:
            conn.close()
            raise
        self._conn = conn

    def _prepare(self, conn: sqlite3.Connection) -> None:
        # Lecture seule d'abord : un fichier refusé n'est modifié en rien, pas
        # même son en-tête de journal.
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if tables:
            self._check_existing(conn, tables)
        conn.execute("PRAGMA journal_mode=WAL")
        # FULL : une révision servie doit survivre à une coupure de courant,
        # puisque Core ne l'expose qu'après l'avoir persistée.
        conn.execute("PRAGMA synchronous=FULL")
        if not tables:
            self._create_schema(conn)

    def _check_existing(self, conn: sqlite3.Connection, tables: set[str]) -> None:
        if "schema_version" not in tables:
            raise SceneStoreError(
                SceneStoreErrorCode.SCHEMA_UNKNOWN,
                f"scene store {self.path} has tables but no schema_version: not a scene database",
            )
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        if len(rows) != 1 or type(rows[0][0]) is not int:
            raise SceneStoreError(
                SceneStoreErrorCode.SCHEMA_UNKNOWN,
                f"scene store {self.path} schema_version is unreadable ({len(rows)} rows)",
            )
        version = rows[0][0]
        if version > _SCHEMA_VERSION:
            raise SceneStoreError(
                SceneStoreErrorCode.SCHEMA_NEWER,
                f"scene store {self.path} schema {version} is newer than supported {_SCHEMA_VERSION}",
            )
        if version != _SCHEMA_VERSION:
            raise SceneStoreError(
                SceneStoreErrorCode.SCHEMA_UNKNOWN,
                f"scene store {self.path} schema {version} is unknown (supported {_SCHEMA_VERSION})",
            )
        missing = [name for name in _TABLES if name not in tables]
        if missing:
            raise SceneStoreError(
                SceneStoreErrorCode.CORRUPTED, f"scene store {self.path} schema {version} lacks tables {missing}"
            )
        quick = conn.execute("PRAGMA quick_check").fetchone()
        if not quick or quick[0] != "ok":
            raise SceneStoreError(
                SceneStoreErrorCode.CORRUPTED,
                f"scene store {self.path} quick_check failed: {_clip(quick[0]) if quick else 'no result'}",
            )

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _DDL:
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (_SCHEMA_VERSION,))
            conn.execute("COMMIT")
        except BaseException as exc:
            _rollback(conn, exc)
            raise

    # ------------------------------------------------------------ accès

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            conn = self._conn
            if conn is None:
                raise SceneStoreError(SceneStoreErrorCode.UNAVAILABLE, "scene store is not initialized or already closed")
            try:
                return await run_sqlite_in_thread(fn, conn)
            except sqlite3.Error as exc:
                raise SceneStoreError(_sqlite_code(exc), f"scene store {type(exc).__name__}: {exc}") from exc

    async def load(self) -> SceneSnapshot | None:
        return await self._run(self._load_sync)

    def _load_sync(self, conn: sqlite3.Connection) -> SceneSnapshot | None:
        meta = conn.execute("SELECT scene_id, revision, wire_schema_version FROM scene_meta WHERE singleton = 1").fetchone()
        if meta is None:
            for table in ("scene_objects", "scene_relations", "scene_tombstones", "scene_history"):
                if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
                    raise SceneStoreError(
                        SceneStoreErrorCode.CORRUPTED, f"scene store holds {table} rows but no scene_meta"
                    )
            return None
        scene_id, revision, wire_version = meta
        self._check_wire_version(wire_version)
        try:
            objects = tuple(
                self._decode_row(SceneObject, "scene_objects", key, data)
                for key, data in conn.execute("SELECT object_id, data FROM scene_objects ORDER BY position")
            )
            relations = tuple(
                self._decode_row(SceneRelation, "scene_relations", key, data)
                for key, data in conn.execute("SELECT relation_id, data FROM scene_relations ORDER BY position")
            )
            archived_ids = tuple(
                row[0] for row in conn.execute("SELECT object_id FROM scene_tombstones ORDER BY position")
            )
            return SceneSnapshot(
                scene_id=scene_id, revision=revision, objects=objects, relations=relations, archived_ids=archived_ids
            )
        except (TypeError, ValueError) as exc:
            raise SceneStoreError(
                SceneStoreErrorCode.CORRUPTED, f"stored scene is not a valid snapshot: {_clip(exc)}"
            ) from exc

    @staticmethod
    def _check_wire_version(version: object) -> None:
        # Les colonnes `data` suivent le fil du domaine : si sa version change,
        # ce fichier doit être refusé, pas décodé au petit bonheur.
        if type(version) is int and version > SCENE_SCHEMA_VERSION:
            raise SceneStoreError(
                SceneStoreErrorCode.SCHEMA_NEWER,
                f"stored scene payloads use schema {version}, newer than supported {SCENE_SCHEMA_VERSION}",
            )
        if type(version) is not int or version != SCENE_SCHEMA_VERSION:
            raise SceneStoreError(
                SceneStoreErrorCode.SCHEMA_UNKNOWN,
                f"stored scene payloads use unknown schema {_clip(version)} (supported {SCENE_SCHEMA_VERSION})",
            )

    @staticmethod
    def _decode_row(cls: Any, table: str, key: object, data: object) -> Any:
        if not isinstance(data, str):
            raise ValueError(f"{table} row {_clip(key)} has no JSON data")
        try:
            value = cls.from_payload(json.loads(data))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{table} row {_clip(key)}: {_clip(exc)}") from exc
        stored_key = value.relation_id if isinstance(value, SceneRelation) else value.object_id
        if stored_key != key:
            raise ValueError(f"{table} row {_clip(key)} holds {_clip(stored_key)}")
        return value

    async def create(self, scene_id: str) -> SceneSnapshot:
        snapshot = SceneSnapshot(scene_id=scene_id)

        def create(conn: sqlite3.Connection) -> None:
            now = utc_now().isoformat()
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM scene_meta WHERE singleton = 1").fetchone() is not None:
                    raise SceneStoreError(SceneStoreErrorCode.REVISION_CONFLICT, "a scene already exists in this store")
                conn.execute(
                    "INSERT INTO scene_meta(singleton, scene_id, revision, wire_schema_version, created_at, updated_at)"
                    " VALUES (1, ?, 0, ?, ?, ?)",
                    (snapshot.scene_id, SCENE_SCHEMA_VERSION, now, now),
                )
                conn.execute("COMMIT")
            except BaseException as exc:
                _rollback(conn, exc)
                raise

        await self._run(create)
        return snapshot

    async def commit(self, previous: SceneSnapshot, patch: ScenePatch, result: SceneSnapshot) -> None:
        if patch.revision != previous.revision + 1 or result.revision != patch.revision or result.scene_id != previous.scene_id:
            raise SceneStoreError(
                SceneStoreErrorCode.REVISION_CONFLICT,
                f"patch {patch.revision} does not lead from revision {previous.revision} to {result.revision}",
            )
        await self._run(lambda conn: self._commit_sync(conn, previous, patch, result))

    @staticmethod
    def _commit_sync(conn: sqlite3.Connection, previous: SceneSnapshot, patch: ScenePatch, result: SceneSnapshot) -> None:
        now = utc_now().isoformat()
        conn.execute("BEGIN IMMEDIATE")
        try:
            meta = conn.execute("SELECT scene_id, revision FROM scene_meta WHERE singleton = 1").fetchone()
            if meta is None or tuple(meta) != (previous.scene_id, previous.revision):
                stored = "no scene" if meta is None else f"revision {meta[1]}"
                raise SceneStoreError(
                    SceneStoreErrorCode.REVISION_CONFLICT,
                    f"stored scene holds {stored}, Core expected revision {previous.revision}",
                )
            for op in patch.ops:
                _write_op(conn, op.op, op, patch.revision, now)
            # Même éviction que `apply_scene_patch` : les plus anciennes
            # pierres tombales tombent au-delà de la borne.
            conn.execute(
                "DELETE FROM scene_tombstones WHERE position NOT IN "
                "(SELECT position FROM scene_tombstones ORDER BY position DESC LIMIT ?)",
                (MAX_ARCHIVED_IDS,),
            )
            counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("scene_objects", "scene_relations", "scene_tombstones")
            )
            expected = (len(result.objects), len(result.relations), len(result.archived_ids))
            if counts != expected:
                raise SceneStoreError(
                    SceneStoreErrorCode.REVISION_CONFLICT,
                    f"stored scene diverged from Core (rows {counts}, expected {expected})",
                )
            conn.execute(
                "UPDATE scene_meta SET revision = ?, updated_at = ? WHERE singleton = 1", (patch.revision, now)
            )
            conn.execute("COMMIT")
        except BaseException as exc:
            _rollback(conn, exc)
            raise

    async def archived_history(self, *, object_id: str | None = None, limit: int = 100) -> tuple[ArchivedSceneObject, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY_READ:
            raise ValueError(f"limit must be an integer between 1 and {MAX_HISTORY_READ}")

        def read(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
            if object_id is None:
                cursor = conn.execute(
                    "SELECT object_id, revision, archived_at, data FROM scene_history ORDER BY revision DESC LIMIT ?",
                    (limit,),
                )
            else:
                cursor = conn.execute(
                    "SELECT object_id, revision, archived_at, data FROM scene_history WHERE object_id = ?"
                    " ORDER BY revision DESC LIMIT ?",
                    (object_id, limit),
                )
            return cursor.fetchall()

        rows = await self._run(read)
        try:
            return tuple(
                ArchivedSceneObject(
                    object=self._decode_row(SceneObject, "scene_history", key, data), revision=revision, archived_at=archived_at
                )
                for key, revision, archived_at, data in rows
            )
        except (TypeError, ValueError) as exc:
            raise SceneStoreError(SceneStoreErrorCode.CORRUPTED, f"stored scene history is invalid: {_clip(exc)}") from exc

    async def close(self) -> None:
        async with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                await run_sqlite_in_thread(conn.close)


_UPSERT_OBJECT = (
    "INSERT INTO scene_objects(object_id, position, data)"
    " VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM scene_objects), ?)"
    " ON CONFLICT(object_id) DO UPDATE SET data = excluded.data"
)
_UPSERT_RELATION = (
    "INSERT INTO scene_relations(relation_id, position, data)"
    " VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM scene_relations), ?)"
    " ON CONFLICT(relation_id) DO UPDATE SET data = excluded.data"
)


def _write_op(conn: sqlite3.Connection, kind: PatchOpKind, op: Any, revision: int, now: str) -> None:
    """Écrire une opération de patch. Un remplacement garde sa `position` (ordre du tuple)."""

    if kind is PatchOpKind.PUT_OBJECT:
        conn.execute(_UPSERT_OBJECT, (op.object.object_id, _dump(op.object.to_payload())))
    elif kind is PatchOpKind.ARCHIVE_OBJECT:
        object_id = op.object.object_id
        if conn.execute("DELETE FROM scene_objects WHERE object_id = ?", (object_id,)).rowcount != 1:
            raise SceneStoreError(SceneStoreErrorCode.REVISION_CONFLICT, f"stored scene lacks archived object {_clip(object_id)}")
        conn.execute(
            "INSERT INTO scene_tombstones(object_id, position)"
            " VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM scene_tombstones))",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO scene_history(object_id, revision, archived_at, data) VALUES (?, ?, ?, ?)",
            (object_id, revision, now, _dump(op.object.to_payload())),
        )
    elif kind is PatchOpKind.PUT_RELATION:
        conn.execute(_UPSERT_RELATION, (op.relation.relation_id, _dump(op.relation.to_payload())))
    else:
        if conn.execute("DELETE FROM scene_relations WHERE relation_id = ?", (op.relation_id,)).rowcount != 1:
            raise SceneStoreError(
                SceneStoreErrorCode.REVISION_CONFLICT, f"stored scene lacks deleted relation {_clip(op.relation_id)}"
            )
