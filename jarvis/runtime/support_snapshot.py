"""Contenu « complet » du paquet de support (V1.2 Slice 07, `docs/support-report.md`).

Collecteurs appelés par `support_bundle.collect` quand l'utilisateur a demandé un rapport de problème (consentement
dans le Control Center, ou `support-bundle --full`). Chacun rend des fichiers DÉJÀ masqués et des lignes de manifeste
(`ManifestEntry`) : inclus, masqué, omis, refusé, avec la raison. Rien ici n'écrit hors du dossier de travail donné.

- `snapshot_database` : instantané COHÉRENT d'une base d'état par l'API de sauvegarde SQLite, la source ouverte en
  lecture seule (`open_readonly` : `mode=ro` si le `-shm` existe déjà, sinon `immutable=1`, qui ne crée rien et ne lit
  pas le `-wal` ; jamais un `-wal` rejoué dans une autre base). Puis, SUR LA COPIE seulement : déclencheurs retirés,
  coffre MCP (`mcp_credentials`) vidé, toute valeur BLOB vidée, toute valeur texte passée par le masqueur, et
  `VACUUM INTO` un fichier neuf (aucune page libérée ne garde un ancien octet). Au-delà de `MAX_DATABASE_BYTES`
  (base + `-wal`), la base est omise et le manifeste le dit.
- `board_memory` : les fichiers TEXTE de `<data>/boards/<board_id>/memory/`, masqués. Un lien symbolique, une jonction
  ou un point d'analyse n'est jamais suivi (refusé, dit au manifeste), un fichier binaire, trop gros ou au-delà du
  budget est omis, la racine doit rester sous la racine de données résolue.
- `sanitized_settings` : `control-center-settings.json` sans les clés (champs hérités `*_api_key`, liste
  `credentials`, scellée ou non : seulement leur nombre), puis masqué.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any

from jarvis.adapters import safe_folders

#: Une base plus grosse (fichier + `-wal`) n'est pas copiée : le masquage de chaque cellule et l'envoi deviendraient
#: impraticables. Le manifeste dit sa taille et la raison.
MAX_DATABASE_BYTES = 64 * 1024 * 1024
#: Mémoire du Board : un fichier au-delà est omis ; le total copié reste sous le budget.
MAX_MEMORY_FILE_BYTES = 1024 * 1024
MEMORY_BUDGET_BYTES = 16 * 1024 * 1024
MAX_MEMORY_FILES = 2000
MAX_MEMORY_DEPTH = 16
#: Tables vidées dans l'instantané, quelle que soit leur forme : le coffre des identifiants MCP.
SECRET_TABLES = ("mcp_credentials",)
#: Fichiers de clé ou de coffre jamais copiés de la mémoire, même texte (QA S07 M3) : dits `excluded` au manifeste.
KEY_FILE_SUFFIXES = frozenset({".ppk", ".pem", ".key", ".asc", ".gpg", ".pgp", ".p12", ".pfx", ".jks", ".keystore",
                               ".kdbx", ".der", ".p8"})
BOARD_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """Une ligne de `manifest.json`. `path` : dans le zip (inclus) ou logique (omis) ; jamais un chemin absolu."""

    path: str
    category: str
    status: str  # included | masked | omitted | refused | excluded
    bytes: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class SnapshotError(RuntimeError):
    """Instantané impossible : la base est omise, la cause est dite au manifeste (le paquet se fait quand même)."""


@contextmanager
def open_readonly(path: Path) -> Iterator[tuple[sqlite3.Connection, bool]]:
    """(connexion lecture seule, `wal_not_read`). Rien n'est jamais créé à côté de la base (QA S10 m9).

    `mode=ro` sur une base WAL crée un `-shm` s'il manque : on ne l'ouvre ainsi que si le `-shm` existe déjà (JARVIS
    ouvert, ou arrêté avec les deux) ; sinon `immutable=1`, qui ne lit pas le `-wal` (`wal_not_read`)."""

    wal = path.with_name(path.name + "-wal").exists()
    shm = path.with_name(path.name + "-shm").exists()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro{'' if shm else '&immutable=1'}", uri=True, timeout=2)
    try:
        yield conn, wal and not shm
    finally:
        conn.close()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def snapshot_database(source: Path, target: Path, mask: Callable[[str], str]) -> dict[str, Any]:
    """Instantané masqué de `source` dans `target` (qui ne doit pas exister) ; rend ce que le manifeste en dit.

    `SnapshotError` si la base est absente, trop grosse ou illisible : `target` n'existe alors pas."""

    try:
        info = os.lstat(source)
    except FileNotFoundError:
        raise SnapshotError("absent") from None
    if safe_folders.is_link(info) or not stat.S_ISREG(info.st_mode):
        raise SnapshotError("not_a_plain_file")
    wal = source.with_name(source.name + "-wal")
    size = info.st_size + (wal.stat().st_size if wal.exists() else 0)
    if size > MAX_DATABASE_BYTES:
        raise SnapshotError(f"too_large:{size}")
    work = target.with_name(target.name + ".work")
    report: dict[str, Any] = {"source_bytes": size}
    try:
        with open_readonly(source) as (src, wal_not_read):
            dst = sqlite3.connect(work)
            try:
                src.backup(dst)  # one step: a consistent read transaction, whatever Core writes meanwhile
            finally:
                dst.close()
        report["wal_not_read"] = wal_not_read
        conn = sqlite3.connect(work, isolation_level=None)
        try:
            report.update(_scrub(conn, mask))
            conn.execute("VACUUM INTO ?", (str(target),))
        finally:
            conn.close()
    except sqlite3.Error as exc:
        _discard(target)
        raise SnapshotError(f"sqlite_error:{type(exc).__name__}: {exc}") from exc
    except OSError as exc:
        _discard(target)
        raise SnapshotError(f"os_error:{type(exc).__name__}") from exc
    finally:
        for leftover in (work, work.with_name(work.name + "-journal"), work.with_name(work.name + "-wal"),
                         work.with_name(work.name + "-shm")):
            _discard(leftover)
    return report


def _scrub(conn: sqlite3.Connection, mask: Callable[[str], str]) -> dict[str, Any]:
    """Sur la COPIE : déclencheurs retirés, coffre vidé, BLOB vidés, texte masqué. Rend des comptes."""

    conn.create_function("jv_mask", 1, lambda value: mask(value) if isinstance(value, str) else value, deterministic=True)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA ignore_check_constraints=ON")
    conn.execute("PRAGMA secure_delete=ON")
    conn.execute("BEGIN")
    triggers = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
    for name in triggers:  # an update-refusing trigger (immutable rows) would stop the masking
        conn.execute(f"DROP TRIGGER {_quote(name)}")
    tables = {row[0]: "WITHOUT ROWID" in (row[1] or "").upper() for row in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL%'")}
    virtual = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE 'CREATE VIRTUAL%'")]
    for name in virtual:  # derived indexes (full text): dropped rather than half-masked
        conn.execute(f"DROP TABLE {_quote(name)}")
    vault_rows = 0
    for name in SECRET_TABLES:
        if name in tables:
            vault_rows += conn.execute(f"DELETE FROM {_quote(name)}").rowcount
    blobs = masked = 0
    for table, without_rowid in tables.items():
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_quote(table)})")]
        for column in columns:
            q_table, q_col = _quote(table), _quote(column)
            blobs += conn.execute(f"UPDATE {q_table} SET {q_col} = X'' WHERE typeof({q_col}) = 'blob' AND length({q_col}) > 0").rowcount
            changed = f"WHERE typeof({q_col}) = 'text' AND jv_mask({q_col}) <> {q_col}"
            if without_rowid:  # no rowid to keep colliding values apart: a collision fails the snapshot (said)
                masked += conn.execute(f"UPDATE {q_table} SET {q_col} = jv_mask({q_col}) {changed}").rowcount
                continue
            masked += conn.execute(f"UPDATE OR IGNORE {q_table} SET {q_col} = jv_mask({q_col}) {changed}").rowcount
            # A masked value that collides with another row of a UNIQUE column is kept distinct by its rowid; never
            # left unmasked.
            masked += conn.execute(f"UPDATE {q_table} SET {q_col} = jv_mask({q_col}) || ' <' || rowid || '>' "
                                   f"WHERE typeof({q_col}) = 'text' AND jv_mask({q_col}) <> {q_col}").rowcount
    conn.execute("COMMIT")
    return {"tables": len(tables), "triggers_removed": len(triggers), "virtual_tables_removed": len(virtual),
            "vault_rows_removed": vault_rows, "blob_values_emptied": blobs, "text_values_masked": masked}


def active_board_from_state(database: Path) -> dict[str, Any] | None:
    """Board actif d'après la base (session ouverte, sinon la plus récente) : `{board_id, title?}`, ou `None`."""

    if not database.is_file():
        return None
    try:
        with open_readonly(database) as (conn, _wal_not_read):
            row = conn.execute("SELECT active_board_id FROM jarvis_sessions ORDER BY status = 'open' DESC, "
                               "started_at DESC LIMIT 1").fetchone()
            if row is None or not isinstance(row[0], str):
                return None
            board: dict[str, Any] = {"board_id": row[0]}
            data = conn.execute("SELECT data FROM work_boards WHERE board_id = ?", (row[0],)).fetchone()
    except sqlite3.Error:
        return None  # intentional: an older schema or a damaged base gives no active board; the manifest says none
    if data is not None:
        try:
            payload = json.loads(data[0])
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            board.update({key: payload[key] for key in ("title", "board_kind") if isinstance(payload.get(key), str)})
    return board


def memory_root(data_root: Path, board_id: str) -> Path:
    """`<data>/boards/<id>/memory`, chaque composant inspecté (`lstat`) : jamais un lien, une jonction, ni hors racine.

    `SnapshotError` : `invalid_board_id`, `absent`, `link_refused`, `outside_data_root`."""

    if not BOARD_ID.fullmatch(board_id or ""):
        raise SnapshotError("invalid_board_id")
    try:
        root = safe_folders.resolve_root(data_root)
    except safe_folders.SafeFolderError as exc:
        raise SnapshotError(f"data_root_{exc.kind}") from exc
    current = root
    for part in ("boards", board_id, "memory"):
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise SnapshotError("absent") from None
        if safe_folders.is_link(info):
            raise SnapshotError("link_refused")
        if not stat.S_ISDIR(info.st_mode):
            raise SnapshotError("not_a_folder")
    if os.path.commonpath([os.path.realpath(current), str(root)]) != str(root):
        raise SnapshotError("outside_data_root")
    return current


def board_memory(data_root: Path, board_id: str, mask: Callable[[str], str],
                 prefix: str = "board/memory") -> tuple[dict[str, bytes], list[ManifestEntry]]:
    """Fichiers texte masqués de la mémoire du Board, et le manifeste de ce qui est inclus, omis ou refusé."""

    try:
        root = memory_root(data_root, board_id)
    except SnapshotError as exc:
        return {}, [ManifestEntry(prefix, "board_memory", "omitted" if str(exc) == "absent" else "refused",
                                  reason=str(exc))]
    files: dict[str, bytes] = {}
    entries: list[ManifestEntry] = []
    budget = MEMORY_BUDGET_BYTES

    def visit(folder: Path, relative: str, depth: int) -> None:
        nonlocal budget
        if depth > MAX_MEMORY_DEPTH:
            entries.append(ManifestEntry(f"{prefix}/{relative}", "board_memory", "omitted", reason="too_deep"))
            return
        try:
            children = sorted(os.scandir(folder), key=lambda item: item.name)
        except OSError as exc:
            entries.append(ManifestEntry(f"{prefix}/{relative}", "board_memory", "omitted", reason=f"unreadable:{type(exc).__name__}"))
            return
        for entry in children:
            shown = masked_name(entry.name, mask)  # a file name can carry a secret too (QA S07 M2)
            name = f"{relative}/{shown}" if relative else shown
            path = f"{prefix}/{name}"
            try:
                info = os.lstat(entry.path)
            except OSError as exc:
                entries.append(ManifestEntry(path, "board_memory", "omitted", reason=f"unreadable:{type(exc).__name__}"))
                continue
            if safe_folders.is_link(info):
                entries.append(ManifestEntry(path, "board_memory", "refused", reason="link_or_junction_not_followed"))
            elif stat.S_ISDIR(info.st_mode):
                visit(Path(entry.path), name, depth + 1)
            elif not stat.S_ISREG(info.st_mode):
                entries.append(ManifestEntry(path, "board_memory", "refused", reason="not_a_regular_file"))
            elif entry.name.startswith(".~bm") or entry.name.endswith(".tmp"):
                continue  # intentional: a temporary of an interrupted write is never listed by the memory store either
            elif info.st_nlink > 1:
                # A hard link may share its bytes with a file outside the data root (QA S07 m1): never read.
                entries.append(ManifestEntry(path, "board_memory", "refused", reason="hard_link_not_followed"))
            elif Path(entry.name).suffix.lower() in KEY_FILE_SUFFIXES:
                entries.append(ManifestEntry(path, "board_memory", "excluded", info.st_size, reason="key_file_never_included"))
            elif len(files) >= MAX_MEMORY_FILES:
                entries.append(ManifestEntry(path, "board_memory", "omitted", info.st_size, reason="file_count_limit"))
            elif info.st_size > MAX_MEMORY_FILE_BYTES:
                entries.append(ManifestEntry(path, "board_memory", "omitted", info.st_size, reason="too_large"))
            elif info.st_size > budget:
                entries.append(ManifestEntry(path, "board_memory", "omitted", info.st_size, reason="memory_budget_reached"))
            else:
                text = _read_text(Path(entry.path))
                if text is None:
                    entries.append(ManifestEntry(path, "board_memory", "omitted", info.st_size, reason="binary_or_not_utf8"))
                    continue
                body = mask(text).encode("utf-8")
                files[path] = body
                budget -= info.st_size
                entries.append(ManifestEntry(path, "board_memory", "masked", len(body)))

    visit(root, "", 0)
    if not files and not entries:
        entries.append(ManifestEntry(prefix, "board_memory", "omitted", reason="empty"))
    return files, entries


def masked_name(name: str, mask: Callable[[str], str]) -> str:
    """Le nom tel quel, ou `masque-<sha256 court><extension>` s'il porte un secret (stable d'un paquet à l'autre)."""

    if mask(name) == name:
        return name
    suffix = Path(name).suffix
    suffix = suffix if mask(suffix) == suffix and len(suffix) <= 12 else ""
    return f"masque-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:10]}{suffix}"


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def sanitized_settings(path: Path, structured: Callable[[Any], Any]) -> tuple[bytes | None, ManifestEntry]:
    """Réglages du Control Center sans aucune clé (seulement leur nombre), puis masqués."""

    from jarvis.runtime.credentials import LEGACY_KEYS

    target = "settings/control-center-settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, ManifestEntry(target, "settings", "omitted", reason="absent")
    except (OSError, ValueError) as exc:
        return None, ManifestEntry(target, "settings", "omitted", reason=f"unreadable:{type(exc).__name__}")
    if not isinstance(settings, dict):
        return None, ManifestEntry(target, "settings", "omitted", reason="not_an_object")
    removed = sum(1 for key in LEGACY_KEYS if settings.pop(key, None) is not None)
    credentials = settings.pop("credentials", None)
    removed += len(credentials) if isinstance(credentials, list) else 0
    settings["credentials_removed"] = removed
    body = (json.dumps(structured(settings), indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    return body, ManifestEntry(target, "settings", "masked", len(body), reason="keys removed, values masked")


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass  # intentional: nothing to remove
    except OSError:
        pass  # intentional: a leftover in the support work folder is swept by the retention pass
