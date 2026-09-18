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

Ouverture, dans cet ordre :

0. `sweep_leftovers` (appelé par le service avant l'ouverture) retire les
   temporaires de création interrompue **de ce dossier seulement**, plus
   vieux que 10 minutes, fichiers ordinaires uniquement (jamais un lien ni une
   jonction). Rien hors du dossier de la scène n'est jamais touché ;
1. fichier **absent** (et pas de `-wal` orphelin) : il est créé de façon
   atomique — schéma, `schema_version` et ligne `scene_meta` écrits dans un
   fichier temporaire du même dossier, puis renommé (`replace_with_retry`).
   Un arrêt brutal laisse au pire ce temporaire, jamais un `scene.sqlite3`
   vide ou partiel ;
2. fichier **présent** : `os.access` (fichier et dossier inscriptibles) avant
   toute ouverture, puis ouverture du vrai fichier en lecture-écriture sans
   jamais le créer (URI `mode=rw` : un fichier disparu entre-temps lève
   `storage_io`, au lieu de laisser un fichier vide ; le démarrage suivant crée
   la scène normalement). Un
   fichier vide ou sans table est refusé (`corrupted`) avant toute écriture,
   jamais recréé ;
3. validation complète **sous `BEGIN IMMEDIATE`** sur cette même connexion :
   `schema_version`, tables, `quick_check`, version du fil, décodage de toute
   la scène, puis une écriture sonde, et `ROLLBACK`. Tenir le verrou
   d'écriture empêche un écrivain concurrent de déchirer ce qui est lu, et
   rien ne change entre la validation et l'usage : la connexion acceptée est
   celle que le magasin garde.

Garantie de refus : le **contenu logique** d'un fichier refusé n'est jamais
modifié, réécrit, recréé ni effacé. Seuls des changements physiques peuvent
survenir (checkpoint WAL à la fermeture, en-tête de mode de journal passé en
WAL) ; l'identité octet pour octet du fichier, du `-wal` et du `-shm` n'est
pas promise. Ce que SQLite signale « pas une base » ou
« malformé » est `corrupted` ; verrou, droits et E/S sont `storage_io`.

Chaque `commit` est une transaction `BEGIN IMMEDIATE … COMMIT` : un arrêt
brutal laisse la révision précédente ou la suivante, jamais une moitié. Une
connexion restée dans une transaction après un échec (rollback impossible)
est signalée `fatal` : le service rend alors la scène indisponible. Un
`COMMIT` peut réussir sur disque et remonter pourtant une erreur : la commande
suivante échoue alors fermée (`revision_conflict`) et un redémarrage recharge
la révision réellement écrite. Rien n'est rejoué depuis le stockage, donc la
garde des champs immuables demandée par l'amendement PM de la Slice 02 pour un
rejeu de patchs n'a pas lieu d'être ici.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
from typing import Any, Callable, TypeVar

from jarvis.adapters.file_replace import replace_with_retry
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
from jarvis.domain.v2 import new_id, utc_now
from jarvis.ports.scene import ArchivedSceneObject, SceneStoreError, SceneStoreErrorCode, SceneSweepReport

T = TypeVar("T")

#: Version de la disposition des tables de ce fichier. Toute autre valeur est
#: refusée : pas de migration implicite.
_SCHEMA_VERSION = 1
#: Lecture d'historique : bornée, jamais un fichier entier en mémoire.
MAX_HISTORY_READ = 1_000
#: Âge minimal d'un temporaire de création pour être balayé : une création en
#: cours dans un autre Core (non pris en charge, mais possible) n'est jamais
#: coupée sous lui.
STALE_CREATION_S = 600.0
#: Attribut Windows d'un point d'analyse (lien symbolique, jonction) ; absent
#: ailleurs, où `S_ISREG` sur `lstat` suffit.
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_plain_file(info: os.stat_result) -> bool:
    """Fichier ordinaire lu par `lstat` : ni lien, ni jonction, ni dossier."""

    return stat.S_ISREG(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _sqlite_uri(path: Path, mode: str) -> str:
    """URI SQLite sûre pour un chemin Windows (espaces, `#`, `?` encodés par `as_uri`)."""

    return f"{path.as_uri()}?mode={mode}"

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
    if isinstance(exc, sqlite3.IntegrityError):
        # Contrainte violée pendant une écriture : le disque ne contient pas ce
        # que Core croit (ligne déjà là). Divergence, pas incident passager :
        # la scène doit échouer fermée.
        return SceneStoreErrorCode.REVISION_CONFLICT
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
        # l'accompagne au lieu de la remplacer. La connexion reste alors dans
        # la transaction : `_run` le voit et signale l'erreur `fatal`.
        exc.add_note(f"rollback failed: {type(rollback_exc).__name__}: {rollback_exc}")


class SQLiteSceneRepository:
    """Implémente `SceneRepository` sur un fichier SQLite dédié.

    `scene_id_factory` : identifiant donné à une scène créée (`new_id` ;
    injectable pour les tests).
    """

    def __init__(self, path: Path, *, scene_id_factory: Callable[[], str] = new_id) -> None:
        self.path = Path(path).resolve()
        self._scene_id_factory = scene_id_factory
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def _wal_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}-wal")

    # ------------------------------------------------------------ balayage

    async def sweep_leftovers(self) -> SceneSweepReport:
        return await run_sqlite_in_thread(self._sweep_sync)

    def _sweep_sync(self) -> SceneSweepReport:
        """Retirer les temporaires de création interrompue du dossier de la scène, et rien d'autre.

        Motif exact `scene.sqlite3.<aléa>.creating` (et son `-journal`), plus
        vieux que `STALE_CREATION_S`, fichier ordinaire seulement : un lien ou
        une jonction n'est jamais suivi ni supprimé (`os.lstat`). Rien hors de
        ce dossier n'est lu ni touché. Un lien physique ne perd que ce nom.
        """

        removed: list[str] = []
        failed: list[str] = []
        directory = self.path.parent
        pattern = re.compile(rf"^{re.escape(self.path.name)}\.[A-Za-z0-9_]+\.creating(-journal)?$")
        try:
            names = sorted(os.listdir(directory))
        except FileNotFoundError:
            # Premier démarrage : le dossier n'existe pas encore, rien à balayer.
            return SceneSweepReport()
        except OSError as exc:
            return SceneSweepReport(failed=(f"{directory}: {type(exc).__name__}: {exc}",))
        now = time.time()
        for name in names:
            if not pattern.match(name):
                continue
            target = directory / name
            try:
                info = os.lstat(target)
                if not _is_plain_file(info) or now - info.st_mtime < STALE_CREATION_S:
                    continue
                os.remove(target)
            except FileNotFoundError:
                # Retiré entre la liste et la suppression : il n'y a plus rien
                # à retirer, ce n'est pas un échec.
                continue
            except OSError as exc:
                failed.append(f"{target}: {type(exc).__name__}: {exc}")
                continue
            removed.append(str(target))
        return SceneSweepReport(removed=tuple(removed), failed=tuple(failed))

    # ------------------------------------------------------------ ouverture

    async def initialize(self) -> bool:
        async with self._lock:
            if self._conn is not None:
                return False
            return await run_sqlite_in_thread(self._initialize_sync)

    def _initialize_sync(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            exists = os.path.lexists(self.path)
            wal_exists = os.path.lexists(self._wal_path)
        except OSError as exc:
            raise SceneStoreError(
                SceneStoreErrorCode.STORAGE_IO, f"scene store {self.path} cannot be opened: {type(exc).__name__}: {exc}"
            ) from exc
        if not exists:
            if wal_exists:
                raise SceneStoreError(
                    SceneStoreErrorCode.CORRUPTED,
                    f"scene store {self.path} is missing but its -wal file exists: the database was moved without it",
                )
            self._create_file()
        elif not self.path.is_file():
            raise SceneStoreError(SceneStoreErrorCode.STORAGE_IO, f"scene store {self.path} is not a regular file")
        else:
            self._check_access()
        self._conn = self._open_validated()
        return not exists

    def _create_file(self) -> None:
        """Créer schéma et scène dans un temporaire du même dossier, puis le renommer."""

        temporary: Path | None = None
        try:
            handle, name = tempfile.mkstemp(dir=self.path.parent, prefix=f"{self.path.name}.", suffix=".creating")
            os.close(handle)
            temporary = Path(name)
            conn = sqlite3.connect(temporary, isolation_level=None)
            try:
                now = utc_now().isoformat()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for statement in _DDL:
                        conn.execute(statement)
                    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (_SCHEMA_VERSION,))
                    conn.execute(
                        "INSERT INTO scene_meta(singleton, scene_id, revision, wire_schema_version, created_at, updated_at)"
                        " VALUES (1, ?, 0, ?, ?, ?)",
                        (self._scene_id_factory(), SCENE_SCHEMA_VERSION, now, now),
                    )
                    conn.execute("COMMIT")
                except BaseException as exc:
                    _rollback(conn, exc)
                    raise
            finally:
                conn.close()
            replace_with_retry(temporary, self.path)
        except (OSError, sqlite3.Error) as exc:
            error = SceneStoreError(
                SceneStoreErrorCode.STORAGE_IO, f"scene store {self.path} cannot be created: {type(exc).__name__}: {exc}"
            )
            if temporary is not None:
                for leftover in (temporary, temporary.with_name(f"{temporary.name}-journal")):
                    try:
                        leftover.unlink(missing_ok=True)
                    except OSError as cleanup_exc:
                        # Balayé au prochain démarrage (`sweep_leftovers`) ;
                        # signalé ici avec l'erreur d'origine.
                        error.add_note(f"temporary {leftover.name} not removed: {cleanup_exc}")
            raise error from exc

    def _check_access(self) -> None:
        for target in (self.path, self.path.parent):
            if not os.access(target, os.W_OK):
                raise SceneStoreError(
                    SceneStoreErrorCode.STORAGE_IO,
                    f"scene store {target} is not writable: fix its permissions, then restart Core",
                )

    def _open_validated(self) -> sqlite3.Connection:
        """Ouvrir le vrai fichier et le valider entièrement sous son verrou d'écriture.

        La connexion validée est celle que le magasin garde : rien ne peut
        changer entre la validation et l'usage, et un écrivain concurrent ne
        peut pas déchirer ce qui est lu.
        """

        try:
            # `mode=rw` : ne jamais créer le fichier. S'il a disparu depuis
            # `_check_access`, l'ouverture échoue (`storage_io`) au lieu de
            # laisser un fichier vide que le démarrage suivant refuserait.
            conn = sqlite3.connect(
                _sqlite_uri(self.path, "rw"), uri=True, check_same_thread=False, isolation_level=None
            )
        except sqlite3.Error as exc:
            raise self._refusal(exc) from exc
        try:
            # Lecture d'abord, hors transaction : un fichier vide ou sans table
            # est refusé avant toute écriture (le passage en WAL écrirait son
            # en-tête), et un fichier qui n'est pas une base lève NOTADB ici.
            if not self._tables(conn):
                self._check_schema(conn, set())
            conn.execute("PRAGMA journal_mode=WAL")
            # FULL : une révision servie doit survivre à une coupure de courant,
            # puisque Core ne l'expose qu'après l'avoir persistée.
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._check_schema(conn, self._tables(conn))
                self._load_sync(conn)
                # Sonde d'écriture annulée : `os.access` ne voit ni les ACL ni
                # tout verrou ; `BEGIN IMMEDIATE` seul réussit même sur un
                # fichier en lecture seule, l'écriture non.
                conn.execute("UPDATE schema_version SET version = version")
            finally:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
        except sqlite3.Error as exc:
            conn.close()
            raise self._refusal(exc) from exc
        except BaseException:
            conn.close()
            raise
        return conn

    def _refusal(self, exc: sqlite3.Error) -> SceneStoreError:
        code = _sqlite_code(exc)
        if code is SceneStoreErrorCode.REVISION_CONFLICT:
            # Pas d'écriture réelle à l'ouverture : une contrainte n'y signale
            # pas une divergence de révision, mais un fichier incohérent.
            code = SceneStoreErrorCode.CORRUPTED
        return SceneStoreError(code, f"scene store {self.path} refused: {type(exc).__name__}: {exc}")

    @staticmethod
    def _tables(conn: sqlite3.Connection) -> set[str]:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}

    def _check_schema(self, conn: sqlite3.Connection, tables: set[str]) -> None:
        if not tables:
            raise SceneStoreError(
                SceneStoreErrorCode.CORRUPTED,
                f"scene store {self.path} exists but holds no table (empty or truncated file): refused, never recreated",
            )
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

    # ------------------------------------------------------------ accès

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            conn = self._conn
            if conn is None:
                raise SceneStoreError(SceneStoreErrorCode.UNAVAILABLE, "scene store is not initialized or already closed")
            try:
                return await run_sqlite_in_thread(fn, conn)
            except Exception as exc:
                if conn.in_transaction:
                    # Rollback impossible ou jamais atteint : la connexion reste
                    # coincée dans une transaction et toute écriture suivante
                    # échouerait. `fatal` : le service rend la scène indisponible.
                    raise SceneStoreError(
                        SceneStoreErrorCode.STORAGE_IO,
                        f"scene store connection left inside a transaction after {type(exc).__name__}: {exc}",
                        fatal=True,
                    ) from exc
                if isinstance(exc, sqlite3.Error):
                    raise SceneStoreError(_sqlite_code(exc), f"scene store {type(exc).__name__}: {exc}") from exc
                raise

    async def load(self) -> SceneSnapshot:
        return await self._run(self._load_sync)

    def _load_sync(self, conn: sqlite3.Connection) -> SceneSnapshot:
        meta = conn.execute("SELECT scene_id, revision, wire_schema_version FROM scene_meta WHERE singleton = 1").fetchone()
        if meta is None:
            # La création écrit cette ligne avec le schéma, dans le même
            # fichier renommé : son absence n'est jamais un premier démarrage.
            raise SceneStoreError(SceneStoreErrorCode.CORRUPTED, f"scene store {self.path} holds no scene_meta row")
        scene_id, revision, wire_version = meta
        self._check_wire_version(wire_version)
        # Lignes lues d'abord (`fetchall`) : une erreur de décodage ne doit pas
        # garder un curseur, donc le fichier, ouvert dans sa trace.
        object_rows = conn.execute("SELECT object_id, data FROM scene_objects ORDER BY position").fetchall()
        relation_rows = conn.execute("SELECT relation_id, data FROM scene_relations ORDER BY position").fetchall()
        tombstone_rows = conn.execute("SELECT object_id FROM scene_tombstones ORDER BY position").fetchall()
        try:
            objects = tuple(self._decode_row(SceneObject, "scene_objects", key, data) for key, data in object_rows)
            relations = tuple(self._decode_row(SceneRelation, "scene_relations", key, data) for key, data in relation_rows)
            archived_ids = tuple(row[0] for row in tombstone_rows)
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
        try:
            # Dans le `try` : si `BEGIN` a ouvert la transaction puis levé, elle
            # est quand même annulée.
            conn.execute("BEGIN IMMEDIATE")
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
