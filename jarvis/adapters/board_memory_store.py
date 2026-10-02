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
  (`memory_path_invalid`) ;
- actes (`write`, `mkdir`, `move`, `delete`) : l'identité (`st_dev`,
  `st_ino` de `lstat`) de chaque dossier de la chaîne `boards/<id>/memory/...`
  est relevée, puis revérifiée **avant** et **après** l'acte, ainsi que celle
  de l'entrée visée (temporaire, source, victime). Un dossier remplacé
  (jonction, lien, autre dossier) ou une entrée substituée ->
  `board_memory_unsafe`, trace `board.memory.chain_changed` (ERROR). Avant
  l'acte : rien n'est fait (notre temporaire est retiré s'il est encore à
  nous). Après : l'acte a pu atterrir ailleurs et n'est **pas** défait. Une
  suppression récursive revérifie le parent et l'entrée avant **chaque**
  retrait. Risque résiduel : un processus local hostile, avec droit
  d'écriture sur la racine, peut encore gagner la course dans l'instant entre
  la dernière vérification et l'appel système ; il est alors vu juste après.

Écritures : contenu UTF-8, au plus `MAX_MEMORY_IO_BYTES` par appel, toujours
dans un temporaire neuf du même dossier (`.~bm<hex>.tmp`, nom refusé aux
clients par `BoardMemoryPath`, un nom déjà pris n'est jamais touché),
`fsync`, puis `os.replace` (ou renommage sans écrasement pour `create`) : un
lecteur voit l'ancien fichier ou le neuf, jamais un morceau. Un temporaire
laissé par un arrêt brutal n'est jamais listé ni cherché.

Lectures : texte UTF-8 seulement (`memory_not_text` sur un octet NUL ou une
séquence invalide), bornées en octets ; `sha256` du fichier entier rendu
jusqu'à `MAX_READ_HASH_BYTES` (1 Mio), `None` au-delà ; arbre et recherche
bornés (entrées, fichiers, octets, correspondances).

Pas de ledger ici, et une seule trace (`board.memory.chain_changed`, course
vue) : le service (Slices 04-05) journalise et écrit `board.memory.*`. Une course entre deux écrivains (vérification puis
remplacement) n'est pas sérialisée ici : le service sérialise par Board.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import stat
from typing import BinaryIO
import uuid

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import replace_with_retry, retry_on_permission
from jarvis.diagnostics.logger import PrivacyLogger
from jarvis.domain.board_memory import (
    MAX_MEMORY_IO_BYTES, MEMORY_TEMP_PREFIX, MEMORY_TEMP_SUFFIX, BoardMemoryError, BoardMemoryErrorCode,
    BoardMemoryPath, board_memory_root, is_memory_temporary_name,
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
#: `read` rend le SHA-256 du fichier entier jusqu'à cette taille ; au-delà, `None`
#: (une page ne relit pas plusieurs Mio pour un condensé).
MAX_READ_HASH_BYTES = 4 * MAX_MEMORY_IO_BYTES
#: Forme des temporaires, partagée avec le domaine qui les refuse aux clients.
TEMP_PREFIX = MEMORY_TEMP_PREFIX
TEMP_SUFFIX = MEMORY_TEMP_SUFFIX
#: Noms de temporaire essayés avant de renoncer (un nom pris n'est jamais touché).
_TEMP_ATTEMPTS = 8
_C = BoardMemoryErrorCode
#: Identité d'une entrée sur disque : `(st_dev, st_ino)` de `lstat`.
_Identity = tuple[int, int]
#: Dossiers vérifiés avant d'agir, `(chemin, relatif à la racine de données, identité)`.
_Chain = list[tuple[Path, str, _Identity]]
_LOG = PrivacyLogger(logging.getLogger("jarvis"))


def _refuse(code: BoardMemoryErrorCode, message: str) -> BoardMemoryError:
    return BoardMemoryError(code, message)


def _is_temporary(name: str) -> bool:
    return is_memory_temporary_name(name)


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


def _identity(info: os.stat_result) -> _Identity:
    return info.st_dev, info.st_ino


def _same_file(opened: os.stat_result, seen: os.stat_result) -> bool:
    return _identity(opened) == _identity(seen)


def _unsafe_change(relative: str, reason: str, *, landed: bool) -> BoardMemoryUnavailable:
    """Un dossier de la chaîne ou l'entrée visée a changé pendant l'opération : refus, et trace bruyante.

    `landed` : l'acte a déjà eu lieu (en tout ou partie) ; il a pu atterrir
    hors de `memory/` et n'est **pas** défait : toucher un chemin qui ne mène
    plus là où on l'a vu serait suivre le lien.
    """

    _LOG.event("board.memory.chain_changed", level=logging.ERROR, path=relative, reason=reason, landed=landed)
    if landed:
        suffix = ("; the operation already happened (at least partly) and may have landed outside memory/; "
                  "it was not undone")
    else:
        suffix = "; stopped before acting"
    return BoardMemoryUnavailable(MEMORY_STORE_UNSAFE, relative, reason + suffix)


def _verify_chain(chain: _Chain, relative: str, *, landed: bool) -> None:
    """Chaque dossier de `chain` est encore un vrai dossier, et le même objet (`lstat`) ; sinon `board_memory_unsafe`."""

    for folder, label, seen in chain:
        try:
            info = os.lstat(folder)
        except OSError as exc:
            raise _unsafe_change(relative, f"folder {label} vanished during the operation ({exc})",
                                 landed=landed) from exc
        if safe_folders.is_link(info) or not stat.S_ISDIR(info.st_mode) or _identity(info) != seen:
            raise _unsafe_change(relative, f"folder {label} was replaced during the operation (link, junction or "
                                           "another folder)", landed=landed)


def _verify_entry(path: Path, seen: _Identity, relative: str, *, landed: bool) -> None:
    """L'entrée `path` est encore celle inspectée (`lstat`, jamais suivie) ; sinon `board_memory_unsafe`."""

    try:
        info = os.lstat(path)
    except OSError as exc:
        raise _unsafe_change(relative, f"entry {path.name} vanished during the operation ({exc})",
                             landed=landed) from exc
    if _identity(info) != seen:
        raise _unsafe_change(relative, f"entry {path.name} was replaced during the operation", landed=landed)


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

    def exists(self, board_id: str) -> bool:
        """Vrai si `boards/<id>/memory` existe ; **ne crée rien** (inspection, Slice 04).

        Chaque composant est inspecté par `lstat` : lien, jonction ou point
        d'analyse -> `board_memory_unsafe`, comme `_root`.
        """

        relative = board_memory_root(board_id)  # `invalid_board` avant tout accès disque
        try:
            return safe_folders.check_existing_tree(self._data_root, relative.parts) is not None
        except safe_folders.SafeFolderError as exc:
            code = MEMORY_STORE_UNSAFE if exc.kind == safe_folders.UNSAFE else MEMORY_STORE_FAILED
            raise BoardMemoryUnavailable(code, relative.as_posix(), exc.reason) from exc

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

    def _walk(self, root: Path, path: BoardMemoryPath) -> tuple[Path, os.stat_result | None, str]:
        """Chemin absolu de `path`, son `lstat` (`None` s'il manque, lui ou un parent) et son relatif sur disque.

        Chaque composant est cherché casse ignorée (`_lookup`) puis inspecté :
        lien/jonction -> `memory_path_escape`, fichier au milieu du chemin ->
        `memory_conflict`. Le relatif rendu porte les noms **tels que stockés**
        pour la partie existante, ceux de `path` pour la partie manquante.
        """

        current = root
        parts = path.parts
        real: list[str] = []
        info: os.stat_result | None = None
        for index, part in enumerate(parts):
            sub = "/".join(parts[:index + 1])
            name = _lookup(current, part, sub)
            info = None
            if name is not None:
                try:
                    info = os.lstat(current / name)
                except FileNotFoundError:
                    pass  # retiré entre la liste et l'inspection : manquant
                except OSError as exc:
                    raise _os_error(exc, sub) from exc
            if name is None or info is None:
                rest = [*real, *parts[index:]]
                return root.joinpath(*rest), None, "/".join(rest)
            real.append(name)
            current = current / name
            if safe_folders.is_link(info):
                raise _refuse(_C.MEMORY_PATH_ESCAPE,
                              f"{sub}: is a symbolic link, junction or reparse point; never followed")
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{sub}: is a file, a folder is expected")
        return current, info, "/".join(real)

    @staticmethod
    def _chain(root: Path, real_parts: tuple[str, ...], relative: str) -> _Chain:
        """Identité (`lstat`) de `boards`, `boards/<id>`, `memory` puis de chaque dossier `real_parts` sous `memory`.

        Référence que `_verify_chain` compare avant et après chaque acte : un
        dossier remplacé entre-temps (lien, jonction, autre dossier) est vu.
        """

        tail = root.parts[-3:]
        folders = [(root.parent.parent, tail[0]), (root.parent, "/".join(tail[:2])), (root, "/".join(tail))]
        current = root
        for index, part in enumerate(real_parts):
            current = current / part
            folders.append((current, "/".join((*tail, *real_parts[:index + 1]))))
        chain: _Chain = []
        for folder, label in folders:
            try:
                info = os.lstat(folder)
            except OSError as exc:
                raise _os_error(exc, relative) from exc
            if safe_folders.is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise _unsafe_change(relative, f"folder {label} is not a real folder", landed=False)
            chain.append((folder, label, _identity(info)))
        return chain

    def _existing(self, root: Path, path: BoardMemoryPath) -> tuple[Path, os.stat_result, str]:
        target, info, relative = self._walk(root, path)
        if info is None:
            raise _refuse(_C.MEMORY_NOT_FOUND, f"{path}: not found")
        return target, info, relative

    def _ensure_folders(self, root: Path, parts: tuple[str, ...], relative: str) -> tuple[Path, str, _Chain]:
        """Crée les dossiers manquants de `parts` sous la racine, chacun inspecté après coup.

        Un dossier déjà là sous une autre casse est réutilisé, jamais doublé.
        Après chaque création, la chaîne déjà vue est revérifiée : un parent
        remplacé par une jonction entre son inspection et `mkdir` est vu
        (`board_memory_unsafe` ; le dossier vide créé ailleurs n'est pas
        touché). Rend le dossier, son relatif sur disque et la chaîne vérifiée
        (référence des actes suivants).
        """

        chain = self._chain(root, (), relative)
        current = root
        real: list[str] = []
        for index, part in enumerate(parts):
            sub = "/".join(parts[:index + 1])
            name = _lookup(current, part, sub) or part
            current = current / name
            real.append(name)
            if os.name == "nt" and len(str(current)) > safe_folders.WINDOWS_MAX_DIR_PATH:
                raise _refuse(_C.MEMORY_PATH_INVALID, f"{sub}: folder path above the Windows limit of "
                                                      f"{safe_folders.WINDOWS_MAX_DIR_PATH} characters")
            try:
                os.mkdir(current)
            except FileExistsError:
                pass  # déjà là (ou créé par un concurrent) : inspecté juste après
            except OSError as exc:
                raise _os_error(exc, sub) from exc
            _verify_chain(chain, relative, landed=True)
            try:
                info = os.lstat(current)
            except OSError as exc:
                raise _os_error(exc, sub) from exc
            if safe_folders.is_link(info):
                raise _refuse(_C.MEMORY_PATH_ESCAPE, f"{sub}: is a symbolic link, junction or reparse point")
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{sub}: is a file, a folder is expected")
            chain.append((current, f"{chain[-1][1]}/{name}", _identity(info)))
        return current, "/".join(real), chain

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
            base, info, prefix = self._existing(root, path)
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a file, a folder is expected")
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
        _target, info, relative = self._existing(self._root(board_id), path)
        return _entry(relative, info)

    def read(self, board_id: str, path: BoardMemoryPath, *, offset: int = 0,
             max_bytes: int = MAX_MEMORY_IO_BYTES) -> MemoryText:
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if type(max_bytes) is not int or max_bytes < 4:
            raise ValueError("max_bytes must be an integer >= 4 (one UTF-8 character)")
        if max_bytes > MAX_MEMORY_IO_BYTES:
            raise _refuse(_C.MEMORY_TOO_LARGE, f"max_bytes {max_bytes} is above {MAX_MEMORY_IO_BYTES} per call")
        target, info, relative = self._existing(self._root(board_id), path)
        if not stat.S_ISREG(info.st_mode):
            raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a folder, a file is expected")
        sha256: str | None = None
        try:
            with open(target, "rb") as handle:
                opened = os.fstat(handle.fileno())
                if not _same_file(opened, info):
                    raise _refuse(_C.MEMORY_PATH_ESCAPE, f"{path}: changed between inspection and opening")
                head = handle.read(_SNIFF_BYTES)
                if b"\x00" in head:
                    raise _refuse(_C.MEMORY_NOT_TEXT, f"{path}: binary file (NUL byte), listed but never read")
                if opened.st_size <= MAX_READ_HASH_BYTES:
                    sha256 = _bounded_sha256(head, handle)
                size = handle.seek(0, os.SEEK_END)
                handle.seek(offset)
                data = handle.read(max_bytes)
        except OSError as exc:
            raise _os_error(exc, path.value) from exc
        if data and (data[0] & 0xC0) == 0x80:
            raise _refuse(_C.MEMORY_NOT_TEXT, f"{path}: offset {offset} is inside a UTF-8 character")
        final = offset + len(data) >= size
        text = _decode_text(data, path.value, final=final)
        # Le décodeur garde un caractère coupé en fin de tampon : la page suivante le reprend.
        return MemoryText(path=relative, text=text, offset=offset, next_offset=offset + len(text.encode("utf-8")),
                          size=size, sha256=sha256)

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
            base, info, prefix = self._existing(root, path)
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a file, a folder is expected")
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
        target, info, _relative = self._walk(root, path)
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
        parent, parent_rel, chain = self._ensure_folders(root, path.parts[:-1], path.value)
        # Fichier existant : remplacé sous son nom sur disque ; nouveau : le nom demandé.
        target = parent / target.name
        relative = f"{parent_rel}/{target.name}" if parent_rel else target.name
        self._check_length(parent / f"{TEMP_PREFIX}{'0' * 8}{TEMP_SUFFIX}", path.value)
        temporary, own = _open_temporary(parent, data, path.value)
        try:
            # Le dossier et le temporaire sont encore ceux vus : sinon rien n'est publié.
            _verify_chain(chain, path.value, landed=False)
            _verify_entry(temporary, own, path.value, landed=False)
            if mode is WriteMode.CREATE:
                self._publish_new(temporary, target)
            else:
                replace_with_retry(temporary, target)
        except OSError as exc:
            _discard(temporary, own)
            raise _os_error(exc, path.value) from exc
        except BaseException:
            _discard(temporary, own)
            raise
        # Un dossier remplacé pendant le remplacement lui-même est vu ici (pas défait).
        _verify_chain(chain, path.value, landed=True)
        try:
            written = os.lstat(target)
        except OSError as exc:
            raise _os_error(exc, path.value) from exc
        return MemoryWrite(entry=_entry(relative, written), sha256=hashlib.sha256(data).hexdigest(),
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
        _target, info, relative = self._walk(root, path)
        if info is not None:
            if not stat.S_ISDIR(info.st_mode):
                raise _refuse(_C.MEMORY_CONFLICT, f"{path}: is a file, a folder is expected")
            return _entry(relative, info), False
        folder, relative, _chain = self._ensure_folders(root, path.parts, path.value)
        try:
            created = os.lstat(folder)
        except OSError as exc:
            raise _os_error(exc, path.value) from exc
        return _entry(relative, created), True

    def move(self, board_id: str, source: BoardMemoryPath, target: BoardMemoryPath) -> MemoryEntry:
        """Déplace ou renomme un fichier ou un dossier ; jamais par-dessus une entrée existante."""

        root = self._root(board_id)
        source_abs, source_info, source_rel = self._existing(root, source)
        target_abs, target_info, target_rel = self._walk(root, target)
        # Même entrée sous une autre casse (`a.md` -> `A.md`) : renommage permis.
        same = target_info is not None and target_rel == source_rel
        if same and target.name == source_abs.name:
            return _entry(source_rel, source_info)
        if not same and _name_key(target_rel).startswith(_name_key(source_rel) + "/"):
            raise _refuse(_C.MEMORY_CONFLICT, f"{target}: is inside {source}, a folder cannot move into itself")
        if target_info is not None and not same:
            raise _refuse(_C.MEMORY_EXISTS, f"{target}: already exists")
        self._check_length(target_abs, target.value)
        parent, parent_rel, chain = self._ensure_folders(root, target.parts[:-1], target.value)
        chain += self._chain(root, tuple(source_rel.split("/")[:-1]), source.value)
        target_abs = parent / target.name
        target_rel = f"{parent_rel}/{target.name}" if parent_rel else target.name
        if os.name != "nt" and os.path.lexists(target_abs) and not same:
            raise _refuse(_C.MEMORY_EXISTS, f"{target}: already exists")  # POSIX `rename` écraserait
        _verify_chain(chain, target.value, landed=False)
        _verify_entry(source_abs, _identity(source_info), source.value, landed=False)
        try:
            retry_on_permission(lambda: os.rename(source_abs, target_abs))
        except OSError as exc:
            raise _os_error(exc, target.value) from exc
        _verify_chain(chain, target.value, landed=True)
        try:
            moved = os.lstat(target_abs)
        except OSError as exc:
            raise _os_error(exc, target.value) from exc
        return _entry(target_rel, moved)

    def delete(self, board_id: str, path: BoardMemoryPath, *, recursive: bool = False) -> int:
        """Retire une entrée ; récursif : chaque parent et chaque entrée revérifiés (`lstat`) juste avant retrait."""

        root = self._root(board_id)
        target, info, relative = self._existing(root, path)
        chain = self._chain(root, tuple(relative.split("/")[:-1]), path.value)
        is_folder = stat.S_ISDIR(info.st_mode)
        removed = 0
        try:
            if not is_folder or not recursive:
                if is_folder:
                    with os.scandir(target) as it:
                        if next(it, None) is not None:
                            raise _refuse(_C.MEMORY_CONFLICT, f"{path}: folder is not empty; delete it recursively")
                _verify_chain(chain, path.value, landed=False)
                _verify_entry(target, _identity(info), path.value, landed=False)
                remove = os.rmdir if is_folder else os.unlink
                retry_on_permission(lambda: remove(target))
                removed = 1
            else:
                doomed = _collect(target, _identity(info), chain[-1][2], path.value)
                _verify_chain(chain, path.value, landed=False)
                for victim in doomed:
                    # Parent puis entrée : encore les objets vus par `_collect`, sinon arrêt (jamais suivi).
                    _verify_entry(victim.parent, victim.parent_identity, path.value, landed=removed > 0)
                    _verify_entry(victim.path, victim.identity, path.value, landed=removed > 0)
                    remove = os.rmdir if victim.is_folder else os.unlink  # lien/jonction : le lien seul
                    retry_on_permission(lambda v=victim.path, r=remove: r(v))
                    removed += 1
        except OSError as exc:
            raise _os_error(exc, path.value) from exc
        _verify_chain(chain, path.value, landed=True)
        return removed

def _name_key(name: str) -> str:
    """Clé de comparaison de noms, casse ignorée comme NTFS : majuscule simple, caractère par caractère.

    Pas `casefold` : `ß` et `ss` sont deux fichiers pour NTFS. Même règle sous
    POSIX, pour que les mêmes noms entrent en collision partout.
    """

    return "".join(upper if len(upper := char.upper()) == 1 else char for char in name)


def _lookup(folder: Path, part: str, relative: str) -> str | None:
    """Nom sur disque de l'entrée `part` de `folder`, casse ignorée (nom exact d'abord) ; `None` si absente.

    Liste le dossier à chaque appel : la mémoire d'un Board est petite, et la
    casse stockée ne se lit pas autrement de façon portable.
    """

    try:
        with os.scandir(folder) as it:
            names = [entry.name for entry in it]
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _os_error(exc, relative) from exc
    if part in names:
        return part
    key = _name_key(part)
    return min((name for name in names if _name_key(name) == key), default=None)


def _addressable(relative: str) -> bool:
    """Vrai si un client peut désigner cette entrée par un `BoardMemoryPath`."""

    try:
        BoardMemoryPath(relative)
    except BoardMemoryError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class _Victim:
    """Entrée qu'une suppression récursive retirera, avec ce que `lstat` en a vu."""

    path: Path
    is_folder: bool
    identity: _Identity
    parent: Path
    parent_identity: _Identity


def _collect(folder: Path, identity: _Identity, parent_identity: _Identity, relative: str) -> list[_Victim]:
    """Entrées à retirer, enfants avant parents ; liens jamais suivis (`lstat` seul).

    Compté avant de rien retirer : au-delà de `MAX_DELETE_ENTRIES`, refus et rien n'est touché.
    """

    order: list[_Victim] = []

    def visit(current: Path, current_identity: _Identity, above: _Identity) -> None:
        with os.scandir(current) as it:
            children = [Path(child.path) for child in it]
        for child in children:
            # `lstat` et non l'entrée de `scandir` : sous Windows, celle-ci n'a ni `st_ino` ni `st_dev`.
            info = os.lstat(child)
            if stat.S_ISDIR(info.st_mode) and not safe_folders.is_link(info):
                visit(child, _identity(info), current_identity)
            else:
                order.append(_Victim(child, False, _identity(info), current, current_identity))
            if len(order) > MAX_DELETE_ENTRIES:
                raise _refuse(_C.MEMORY_TOO_LARGE, f"{relative}: more than {MAX_DELETE_ENTRIES} entries to "
                                                   "delete; delete it in parts")
        order.append(_Victim(current, True, current_identity, current.parent, above))

    visit(folder, identity, parent_identity)
    return order


def _bounded_sha256(head: bytes, handle: BinaryIO) -> str | None:
    """SHA-256 du fichier entier (`head` déjà lu) ; `None` s'il a grandi au-delà de `MAX_READ_HASH_BYTES`."""

    digest = hashlib.sha256(head)
    hashed = len(head)
    while chunk := handle.read(_CHUNK):
        hashed += len(chunk)
        if hashed > MAX_READ_HASH_BYTES:
            return None
        digest.update(chunk)
    return digest.hexdigest()


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


def _open_temporary(parent: Path, data: bytes, relative: str) -> tuple[Path, _Identity]:
    """Temporaire neuf (`xb`) dans `parent`, `data` écrit et `fsync` ; rend son chemin et son identité.

    Un nom déjà pris (temporaire d'un autre écrivain, ou laissé par un arrêt)
    n'est **jamais** touché : un autre nom est tiré.
    """

    for _attempt in range(_TEMP_ATTEMPTS):
        temporary = parent / f"{TEMP_PREFIX}{uuid.uuid4().hex[:8]}{TEMP_SUFFIX}"
        try:
            handle = open(temporary, "xb")
        except FileExistsError:
            continue  # nom pris : pas à nous, jamais retiré
        except OSError as exc:
            raise _os_error(exc, relative) from exc
        own: _Identity | None = None
        try:
            with handle:
                own = _identity(os.fstat(handle.fileno()))
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            _discard(temporary, own)
            raise _os_error(exc, relative) from exc
        except BaseException:
            _discard(temporary, own)
            raise
        return temporary, own
    raise BoardMemoryUnavailable(MEMORY_STORE_FAILED, relative,
                                 f"no free temporary name after {_TEMP_ATTEMPTS} attempts")


def _discard(temporary: Path, own: _Identity | None) -> None:
    """Retire **notre** temporaire : seulement si `lstat` y voit encore le fichier créé (`own`).

    `own` vaut `None` seulement si `fstat` a échoué juste après la création
    exclusive : le nom est à nous depuis un instant, retiré sans comparaison.
    """

    try:
        if own is not None and _identity(os.lstat(temporary)) != own:
            return  # argued: another entry now holds this name; it is not ours, never removed
        os.unlink(temporary)
    except OSError:
        pass  # argued: the temporary may already be gone; the real failure is raised by the caller
