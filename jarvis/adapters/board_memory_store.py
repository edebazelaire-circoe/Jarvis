"""Mémoire de Board sur disque (handoff board-memory-workspace-inspector, Slice 02).

`<data_root>/boards/<board_id>/memory/`, dérivé du seul `board_id`
(`board_memory_root`, Slice 01) ; les chemins reçus sont des
`BoardMemoryPath` (relatifs, sans `..`, sans nom réservé Windows), les
chemins rendus sont relatifs à `memory/`. Port :
`jarvis.ports.board_memory.BoardMemoryStore`. Contrat : `docs/boards.md` ›
*Board memory*.

Défenses, refaites à **chaque** opération :

- la racine `boards/<id>/memory` est (re)trouvée par
  `safe_folders.ensure_folder_tree` : racine de données absolue, chaque
  composant inspecté par `lstat`, lien, jonction ou point d'analyse refusé
  (`board_memory_unsafe`), limite Windows des dossiers. Créée à la première
  opération, lecture comprise, pour un Board actif comme archivé ;
- sous la racine, chaque composant du chemin est inspecté par `lstat` : un
  lien, une jonction ou un point d'analyse n'est **jamais suivi**
  (`memory_path_escape`) ; un fichier là où un dossier est attendu est
  `memory_conflict`. Un fichier ouvert est comparé (`fstat`) à ce que `lstat`
  a vu : une substitution entre les deux est refusée ;
- chemin de fichier au-delà de `MAX_PATH` refusé avant tout accès disque
  (`memory_path_invalid`).

Écritures : contenu UTF-8, au plus `MAX_MEMORY_IO_BYTES` par appel, toujours
dans un temporaire du même dossier (`.~bm<hex>.tmp`), `fsync`, puis
`os.replace` (ou renommage sans écrasement pour `create`) : un lecteur voit
l'ancien fichier ou le neuf, jamais un morceau. Un temporaire laissé par un
arrêt brutal n'est jamais listé ni cherché.

Lectures : texte UTF-8 seulement (`memory_not_text` sur un octet NUL ou une
séquence invalide), bornées en octets ; arbre et recherche bornés (entrées,
fichiers, octets, correspondances).

Pas de journal ni de ledger ici : le service (Slices 04-05) journalise et
écrit `board.memory.*`. Une course entre deux écrivains (vérification puis
remplacement) n'est pas sérialisée ici : le service sérialise par Board.
"""

from __future__ import annotations

import codecs
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat
import uuid

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import replace_with_retry, retry_on_permission
from jarvis.domain.board_memory import (
    MAX_MEMORY_IO_BYTES, BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath, board_memory_root,
)
from jarvis.ports.board_memory import (
    MEMORY_STORE_FAILED, MEMORY_STORE_UNSAFE, BoardMemoryUnavailable, MemoryEntry, MemoryEntryKind, MemoryMatch,
    MemorySearch, MemoryText, MemoryTree, MemoryWrite, WriteMode,
)

#: Profondeur et entrées au plus d'un arbre (le brief, Slice 03, demande 2 et 40).
MAX_TREE_DEPTH = 8
MAX_TREE_ENTRIES = 1000
#: Recherche littérale : requête, correspondances, fichiers lus, octets lus au total.
MAX_SEARCH_QUERY_CHARS = 200
MAX_SEARCH_MATCHES = 200
MAX_SEARCH_FILES = 500
MAX_SEARCH_BYTES = 16 * 1024 * 1024
#: Un fichier plus gros n'est pas cherché (compté dans `files_skipped`).
MAX_SEARCH_FILE_BYTES = MAX_MEMORY_IO_BYTES
#: `append` réécrit le fichier entier (atomicité) : taille finale bornée.
MAX_APPEND_FILE_BYTES = 4 * 1024 * 1024
#: Une suppression récursive retire au plus ce nombre d'entrées ; au-delà, refus, rien retiré.
MAX_DELETE_ENTRIES = 10_000
PREVIEW_CHARS = 200
#: Octets inspectés pour reconnaître un fichier binaire (octet NUL).
_SNIFF_BYTES = 8192
_CHUNK = 64 * 1024
TEMP_PREFIX = ".~bm"
TEMP_SUFFIX = ".tmp"
_C = BoardMemoryErrorCode


def _refuse(code: BoardMemoryErrorCode, message: str) -> BoardMemoryError:
    return BoardMemoryError(code, message)


def _is_temporary(name: str) -> bool:
    return name.startswith(TEMP_PREFIX) and name.endswith(TEMP_SUFFIX)


def _kind(info: os.stat_result) -> MemoryEntryKind:
    if safe_folders.is_link(info):
        return MemoryEntryKind.LINK
    if stat.S_ISDIR(info.st_mode):
        return MemoryEntryKind.DIRECTORY
    if stat.S_ISREG(info.st_mode):
        return MemoryEntryKind.FILE
    return MemoryEntryKind.LINK  # périphérique, tube... : pas un fichier ordinaire, jamais suivi


def _entry(relative: str, info: os.stat_result, depth: int = 0) -> MemoryEntry:
    kind = _kind(info)
    return MemoryEntry(path=relative, kind=kind, size=info.st_size if kind is MemoryEntryKind.FILE else None,
                       modified_at=datetime.fromtimestamp(info.st_mtime, tz=timezone.utc), depth=depth)


def _os_error(exc: OSError, relative: str) -> Exception:
    """Une `OSError` traduite : refus nommé quand le système dit pourquoi, panne sinon."""

    if isinstance(exc, FileNotFoundError):
        return _refuse(_C.MEMORY_NOT_FOUND, f"{relative}: not found")
    if isinstance(exc, FileExistsError):
        return _refuse(_C.MEMORY_EXISTS, f"{relative}: already exists")
    if isinstance(exc, (NotADirectoryError, IsADirectoryError)):
        return _refuse(_C.MEMORY_CONFLICT, f"{relative}: a file where a folder is expected, or the reverse")
    return BoardMemoryUnavailable(MEMORY_STORE_FAILED, relative, f"{type(exc).__name__}: {exc}")


def _same_file(opened: os.stat_result, seen: os.stat_result) -> bool:
    return (opened.st_dev, opened.st_ino) == (seen.st_dev, seen.st_ino)


def _decode_text(data: bytes, relative: str, *, final: bool) -> str:
    if b"\x00" in data:
        raise _refuse(_C.MEMORY_NOT_TEXT, f"{relative}: binary file (NUL byte), listed but never read")
    try:
        return codecs.getincrementaldecoder("utf-8")("strict").decode(data, final=final)
    except UnicodeDecodeError as exc:
        raise _refuse(_C.MEMORY_NOT_TEXT, f"{relative}: not UTF-8 text ({exc.reason} at byte {exc.start})") from exc


class FileBoardMemoryStore:
    """`BoardMemoryStore` sur une racine de données (composition root : Slice 04)."""

    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    def memory_root_locator(self, board_id: str) -> str:
        return board_memory_root(board_id).as_posix()

    # ------------------------------------------------------------ chemins

    def _root(self, board_id: str) -> Path:
        relative = board_memory_root(board_id)  # `invalid_board` avant tout accès disque
        try:
            path, _created = safe_folders.ensure_folder_tree(self._data_root, relative.parts)
        except safe_folders.SafeFolderError as exc:
            code = MEMORY_STORE_UNSAFE if exc.kind == safe_folders.UNSAFE else MEMORY_STORE_FAILED
            raise BoardMemoryUnavailable(code, relative.as_posix(), exc.reason) from exc
        return path

    @staticmethod
    def _check_length(path: Path, relative: str) -> None:
        try:
            safe_folders.check_file_path(path)
        except safe_folders.SafeFolderError as exc:
            raise _refuse(_C.MEMORY_PATH_INVALID, f"{relative}: {exc.reason}") from exc

    def _walk(self, root: Path, path: BoardMemoryPath) -> tuple[Path, os.stat_result | None]:
        """Chemin absolu de `path` et son `lstat` (`None` s'il manque, lui ou un parent).

        Chaque composant est inspecté : lien/jonction -> `memory_path_escape`,
        fichier au milieu du chemin -> `memory_conflict`.
        """

        current = root
        parts = path.parts
        for index, part in enumerate(parts):
            current = current / part
            sub = "/".join(parts[:index + 1])
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                return root.joinpath(*parts), None
            except OSError as exc:
                raise _os_error(exc, sub) from exc
            if safe_folders.is_link(info):
                raise _refuse(_C.MEMORY_PATH_ESCAPE,
                              f"{sub}: is a symbolic link, junction or reparse point; never followed")
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{sub}: is a file, a folder is expected")
        return current, info

    def _existing(self, root: Path, path: BoardMemoryPath) -> tuple[Path, os.stat_result]:
        target, info = self._walk(root, path)
        if info is None:
            raise _refuse(_C.MEMORY_NOT_FOUND, f"{path}: not found")
        return target, info

    def _ensure_folders(self, root: Path, parts: tuple[str, ...]) -> Path:
        """Crée les dossiers manquants de `parts` sous la racine, chacun inspecté après coup."""

        current = root
        for index, part in enumerate(parts):
            current = current / part
            sub = "/".join(parts[:index + 1])
            if os.name == "nt" and len(str(current)) > safe_folders.WINDOWS_MAX_DIR_PATH:
                raise _refuse(_C.MEMORY_PATH_INVALID, f"{sub}: folder path above the Windows limit of "
                                                      f"{safe_folders.WINDOWS_MAX_DIR_PATH} characters")
            try:
                os.mkdir(current)
            except FileExistsError:
                pass  # déjà là (ou créé par un concurrent) : inspecté juste après
            except OSError as exc:
                raise _os_error(exc, sub) from exc
            try:
                info = os.lstat(current)
            except OSError as exc:
                raise _os_error(exc, sub) from exc
            if safe_folders.is_link(info):
                raise _refuse(_C.MEMORY_PATH_ESCAPE, f"{sub}: is a symbolic link, junction or reparse point")
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{sub}: is a file, a folder is expected")
        return current

    @staticmethod
    def _read_checked(target: Path, seen: os.stat_result, relative: str, limit: int) -> bytes:
        """Les octets d'un fichier ordinaire déjà inspecté, au plus `limit` (sinon `memory_too_large`)."""

        if seen.st_size > limit:
            raise _refuse(_C.MEMORY_TOO_LARGE, f"{relative}: {seen.st_size} bytes, above {limit}")
        try:
            with open(target, "rb") as handle:
                if not _same_file(os.fstat(handle.fileno()), seen):
                    raise _refuse(_C.MEMORY_PATH_ESCAPE, f"{relative}: changed between inspection and opening")
                data = handle.read(limit + 1)
        except OSError as exc:
            raise _os_error(exc, relative) from exc
        if len(data) > limit:
            raise _refuse(_C.MEMORY_TOO_LARGE, f"{relative}: grew above {limit} bytes")
        return data

    # ------------------------------------------------------------ lecture

    def tree(self, board_id: str, path: BoardMemoryPath | None = None, *, depth: int = 2,
             max_entries: int = 200) -> MemoryTree:
        if type(depth) is not int or not 1 <= depth <= MAX_TREE_DEPTH:
            raise ValueError(f"depth must be in 1..{MAX_TREE_DEPTH}")
        if type(max_entries) is not int or not 1 <= max_entries <= MAX_TREE_ENTRIES:
            raise ValueError(f"max_entries must be in 1..{MAX_TREE_ENTRIES}")
        root = self._root(board_id)
        base, prefix = root, ""
        if path is not None:
            base, info = self._existing(root, path)
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a file, a folder is expected")
            prefix = path.value
        entries: list[MemoryEntry] = []
        state = {"truncated": False, "skipped": 0}

        def visit(folder: Path, folder_rel: str, level: int) -> None:
            try:
                with os.scandir(folder) as it:
                    items = sorted(it, key=lambda e: (e.name.casefold(), e.name))
            except OSError as exc:
                raise _os_error(exc, folder_rel or ".") from exc
            for item in items:
                relative = f"{folder_rel}/{item.name}" if folder_rel else item.name
                if _is_temporary(item.name) or not _addressable(relative):
                    state["skipped"] += 1
                    continue
                if len(entries) >= max_entries:
                    state["truncated"] = True
                    return
                try:
                    info = item.stat(follow_symlinks=False)
                except OSError as exc:
                    raise _os_error(exc, relative) from exc
                entry = _entry(relative, info, level)
                entries.append(entry)
                if entry.kind is MemoryEntryKind.DIRECTORY and level < depth:
                    visit(Path(item.path), relative, level + 1)
                    if state["truncated"]:
                        return

        visit(base, prefix, 1)
        return MemoryTree(path=prefix, entries=tuple(entries), truncated=state["truncated"],
                          skipped=state["skipped"])

    def stat(self, board_id: str, path: BoardMemoryPath) -> MemoryEntry:
        _target, info = self._existing(self._root(board_id), path)
        return _entry(path.value, info)

    def read(self, board_id: str, path: BoardMemoryPath, *, offset: int = 0,
             max_bytes: int = MAX_MEMORY_IO_BYTES) -> MemoryText:
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if type(max_bytes) is not int or max_bytes < 4:
            raise ValueError("max_bytes must be an integer >= 4 (one UTF-8 character)")
        if max_bytes > MAX_MEMORY_IO_BYTES:
            raise _refuse(_C.MEMORY_TOO_LARGE, f"max_bytes {max_bytes} is above {MAX_MEMORY_IO_BYTES} per call")
        target, info = self._existing(self._root(board_id), path)
        if not stat.S_ISREG(info.st_mode):
            raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a folder, a file is expected")
        digest = hashlib.sha256()
        try:
            with open(target, "rb") as handle:
                opened = os.fstat(handle.fileno())
                if not _same_file(opened, info):
                    raise _refuse(_C.MEMORY_PATH_ESCAPE, f"{path}: changed between inspection and opening")
                head = handle.read(_SNIFF_BYTES)
                if b"\x00" in head:
                    raise _refuse(_C.MEMORY_NOT_TEXT, f"{path}: binary file (NUL byte), listed but never read")
                digest.update(head)
                while chunk := handle.read(_CHUNK):
                    digest.update(chunk)
                size = handle.tell()
                handle.seek(offset)
                data = handle.read(max_bytes)
        except OSError as exc:
            raise _os_error(exc, path.value) from exc
        if data and (data[0] & 0xC0) == 0x80:
            raise _refuse(_C.MEMORY_NOT_TEXT, f"{path}: offset {offset} is inside a UTF-8 character")
        final = offset + len(data) >= size
        text = _decode_text(data, path.value, final=final)
        # Le décodeur garde un caractère coupé en fin de tampon : la page suivante le reprend.
        return MemoryText(path=path.value, text=text, offset=offset, next_offset=offset + len(text.encode("utf-8")),
                          size=size, sha256=digest.hexdigest())

    def search(self, board_id: str, query: str, *, path: BoardMemoryPath | None = None,
               limit: int = 50) -> MemorySearch:
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_SEARCH_QUERY_CHARS \
                or not query.isprintable():
            raise ValueError(f"query must be one printable line of 1..{MAX_SEARCH_QUERY_CHARS} characters")
        if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_MATCHES:
            raise ValueError(f"limit must be in 1..{MAX_SEARCH_MATCHES}")
        needle = query.casefold()
        root = self._root(board_id)
        base, prefix = root, ""
        if path is not None:
            base, info = self._existing(root, path)
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a file, a folder is expected")
            prefix = path.value
        matches: list[MemoryMatch] = []
        scanned = skipped = read_bytes = 0
        truncated = False
        stack: list[tuple[Path, str]] = [(base, prefix)]
        while stack and not truncated:
            folder, folder_rel = stack.pop()
            try:
                with os.scandir(folder) as it:
                    items = sorted(it, key=lambda e: (e.name.casefold(), e.name))
            except OSError as exc:
                raise _os_error(exc, folder_rel or ".") from exc
            subfolders: list[tuple[Path, str]] = []
            for item in items:
                relative = f"{folder_rel}/{item.name}" if folder_rel else item.name
                if _is_temporary(item.name) or not _addressable(relative):
                    continue
                try:
                    info = item.stat(follow_symlinks=False)
                except OSError as exc:
                    raise _os_error(exc, relative) from exc
                kind = _kind(info)
                if kind is MemoryEntryKind.DIRECTORY:
                    subfolders.append((Path(item.path), relative))
                    continue
                if kind is not MemoryEntryKind.FILE:
                    continue  # lien : jamais suivi
                if info.st_size > MAX_SEARCH_FILE_BYTES:
                    skipped += 1
                    continue
                if scanned >= MAX_SEARCH_FILES or read_bytes + info.st_size > MAX_SEARCH_BYTES:
                    truncated = True
                    break
                # `lstat` et non l'entrée de `scandir` : sous Windows, celle-ci n'a ni `st_ino` ni `st_dev`.
                try:
                    info = os.lstat(item.path)
                except FileNotFoundError:
                    continue  # retiré pendant la recherche
                except OSError as exc:
                    raise _os_error(exc, relative) from exc
                if _kind(info) is not MemoryEntryKind.FILE:
                    continue  # remplacé par un lien pendant la recherche : jamais suivi
                try:
                    text = _decode_text(self._read_checked(Path(item.path), info, relative, MAX_SEARCH_FILE_BYTES),
                                        relative, final=True)
                except BoardMemoryError as exc:
                    if exc.code in (_C.MEMORY_NOT_TEXT, _C.MEMORY_TOO_LARGE):
                        skipped += 1
                        continue
                    raise
                scanned += 1
                read_bytes += info.st_size
                for number, line in enumerate(text.splitlines(), start=1):
                    if needle in line.casefold():
                        matches.append(MemoryMatch(path=relative, line=number, preview=line[:PREVIEW_CHARS]))
                        if len(matches) >= limit:
                            truncated = True
                            break
                if truncated:
                    break
            # Pile : on dépile le dernier, donc on empile à l'envers pour garder l'ordre des noms.
            stack.extend(reversed(subfolders))
        return MemorySearch(matches=tuple(matches), files_scanned=scanned, files_skipped=skipped,
                            truncated=truncated)

    # ------------------------------------------------------------ écriture (primitives des Slices 05+)

    def write(self, board_id: str, path: BoardMemoryPath, content: str, *, mode: WriteMode,
              expected_sha256: str | None = None) -> MemoryWrite:
        mode = WriteMode(mode)
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
                                            or any(c not in "0123456789abcdef" for c in expected_sha256)):
            raise ValueError("expected_sha256 must be 64 lowercase hexadecimal characters")
        data = content.encode("utf-8")
        if len(data) > MAX_MEMORY_IO_BYTES:
            raise _refuse(_C.MEMORY_TOO_LARGE, f"{path}: {len(data)} bytes to write, above {MAX_MEMORY_IO_BYTES}")
        root = self._root(board_id)
        target, info = self._walk(root, path)
        self._check_length(target, path.value)
        if info is not None and not stat.S_ISREG(info.st_mode):
            raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a folder, a file is expected")
        if mode is WriteMode.CREATE and info is not None:
            raise _refuse(_C.MEMORY_EXISTS, f"{path}: already exists")
        if expected_sha256 is not None:
            if info is None:
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: expected an existing file (sha256 given), found none")
            if _sha256_of(target, info, path.value) != expected_sha256:
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: changed since it was read (sha256 mismatch)")
        if mode is WriteMode.APPEND and info is not None:
            if info.st_size + len(data) > MAX_APPEND_FILE_BYTES:
                raise _refuse(_C.MEMORY_TOO_LARGE, f"{path}: would grow above {MAX_APPEND_FILE_BYTES} bytes")
            current = self._read_checked(target, info, path.value, MAX_APPEND_FILE_BYTES - len(data))
            _decode_text(current, path.value, final=True)  # ajouter à un binaire : refus
            data = current + data
        parent = self._ensure_folders(root, path.parts[:-1])
        temporary = parent / f"{TEMP_PREFIX}{uuid.uuid4().hex[:8]}{TEMP_SUFFIX}"
        self._check_length(temporary, path.value)
        try:
            with open(temporary, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is WriteMode.CREATE:
                self._publish_new(temporary, target)
            else:
                replace_with_retry(temporary, target)
            written = os.lstat(target)
        except OSError as exc:
            _discard(temporary)
            raise _os_error(exc, path.value) from exc
        except BaseException:
            _discard(temporary)
            raise
        return MemoryWrite(entry=_entry(path.value, written), sha256=hashlib.sha256(data).hexdigest(),
                           created=info is None)

    @staticmethod
    def _publish_new(temporary: Path, target: Path) -> None:
        """Renommage **sans écrasement** : un fichier apparu entre-temps garde son contenu (`memory_exists`)."""

        if os.name == "nt":
            retry_on_permission(lambda: os.rename(temporary, target))  # Windows : FileExistsError si occupé
        else:
            os.link(temporary, target)  # POSIX : `rename` écraserait ; `link` refuse
            os.unlink(temporary)

    def mkdir(self, board_id: str, path: BoardMemoryPath) -> tuple[MemoryEntry, bool]:
        """Crée le dossier (et ses parents) ; `(entrée, créé)`. Un dossier déjà là n'est pas une erreur."""

        root = self._root(board_id)
        _target, info = self._walk(root, path)
        if info is not None:
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a file, a folder is expected")
            return _entry(path.value, info), False
        folder = self._ensure_folders(root, path.parts)
        return _entry(path.value, os.lstat(folder)), True

    def move(self, board_id: str, source: BoardMemoryPath, target: BoardMemoryPath) -> MemoryEntry:
        """Déplace ou renomme un fichier ou un dossier ; jamais par-dessus une entrée existante."""

        root = self._root(board_id)
        source_abs, source_info = self._existing(root, source)
        same = _fold(source.value) == _fold(target.value)
        if source.value == target.value:
            return _entry(source.value, source_info)
        if not same and _fold(target.value).startswith(_fold(source.value) + "/"):
            raise _refuse(_C.MEMORY_CONFLICT, f"{target}: is inside {source}, a folder cannot move into itself")
        target_abs, target_info = self._walk(root, target)
        if target_info is not None and not same:
            raise _refuse(_C.MEMORY_EXISTS, f"{target}: already exists")
        self._check_length(target_abs, target.value)
        self._ensure_folders(root, target.parts[:-1])
        if os.name != "nt" and os.path.lexists(target_abs) and not same:
            raise _refuse(_C.MEMORY_EXISTS, f"{target}: already exists")  # POSIX `rename` écraserait
        try:
            retry_on_permission(lambda: os.rename(source_abs, target_abs))
            moved = os.lstat(target_abs)
        except OSError as exc:
            raise _os_error(exc, target.value) from exc
        return _entry(target.value, moved)

    def delete(self, board_id: str, path: BoardMemoryPath, *, recursive: bool = False) -> int:
        root = self._root(board_id)
        target, info = self._existing(root, path)
        try:
            if not stat.S_ISDIR(info.st_mode):
                retry_on_permission(lambda: os.unlink(target))
                return 1
            if not recursive:
                with os.scandir(target) as it:
                    if next(it, None) is not None:
                        raise _refuse(_C.MEMORY_CONFLICT, f"{path}: folder is not empty; delete it recursively")
                retry_on_permission(lambda: os.rmdir(target))
                return 1
            doomed = _collect(target, path.value)
            for victim, is_folder in doomed:
                if is_folder:
                    retry_on_permission(lambda v=victim: os.rmdir(v))
                else:
                    retry_on_permission(lambda v=victim: os.unlink(v))  # lien/jonction : le lien seul
            return len(doomed)
        except OSError as exc:
            raise _os_error(exc, path.value) from exc


def _fold(relative: str) -> str:
    """Comparaison de chemins relatifs : NTFS ignore la casse, POSIX non (séparateur `/` gardé)."""

    return relative.casefold() if os.name == "nt" else relative


def _addressable(relative: str) -> bool:
    """Vrai si un client peut désigner cette entrée par un `BoardMemoryPath`."""

    try:
        BoardMemoryPath(relative)
    except BoardMemoryError:
        return False
    return True


def _collect(folder: Path, relative: str) -> list[tuple[Path, bool]]:
    """Entrées à retirer, enfants avant parents, `(chemin, est_un_dossier)` ; liens jamais suivis.

    Compté avant de rien retirer : au-delà de `MAX_DELETE_ENTRIES`, refus et rien n'est touché.
    """

    order: list[tuple[Path, bool]] = []

    def visit(current: Path) -> None:
        with os.scandir(current) as it:
            children = list(it)
        for child in children:
            info = child.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode) and not safe_folders.is_link(info):
                visit(Path(child.path))
            else:
                order.append((Path(child.path), False))
            if len(order) > MAX_DELETE_ENTRIES:
                raise _refuse(_C.MEMORY_TOO_LARGE, f"{relative}: more than {MAX_DELETE_ENTRIES} entries to "
                                                   "delete; delete it in parts")
        order.append((current, True))

    visit(folder)
    return order


def _sha256_of(target: Path, seen: os.stat_result, relative: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(target, "rb") as handle:
            if not _same_file(os.fstat(handle.fileno()), seen):
                raise _refuse(_C.MEMORY_PATH_ESCAPE, f"{relative}: changed between inspection and opening")
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
    except OSError as exc:
        raise _os_error(exc, relative) from exc
    return digest.hexdigest()


def _discard(temporary: Path) -> None:
    try:
        os.unlink(temporary)
    except OSError:
        pass  # argued: the temporary may not exist; the real failure is raised by the caller
