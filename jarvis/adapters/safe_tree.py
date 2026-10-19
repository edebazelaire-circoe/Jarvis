"""Copie et effacement recursifs **surs** d'un dossier de donnees (purge definitive des presentations archivees).

Le seul usage : la purge (`jarvis/core/presentation_studio_purge.py`) sauvegarde puis efface un dossier de presentation, les dossiers
de version de ses sources de scene (`prefabs/`) et les dossiers de ses Artifacts. Regles, sans exception :

- **rien n'est suivi** : un lien symbolique, une jonction ou un point d'analyse (`safe_folders.is_link`) n'importe ou dans l'arbre,
  ou une entree qui n'est ni un dossier ni un fichier ordinaire, fait refuser TOUTE l'operation **avant** le premier octet copie ou
  efface (`UnsafeTree`) : on inventorie d'abord, on agit ensuite ;
- **jamais hors de la racine annoncee** : `remove_tree(folder, within=...)` refuse un dossier qui n'est pas strictement sous `within`
  (chemins resolus, apres avoir verifie que le dossier lui-meme n'est pas un lien) ;
- la copie ne remplace rien (la cible ne doit pas exister) et verifie, fichier par fichier, que la taille copiee est la taille lue.

Pas de regle metier ici : le magasin des presentations et la bibliotheque de prefabs appellent ces fonctions sous leurs propres
verrous et traduisent `UnsafeTree` / `OSError` en leurs refus codes.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import retry_on_permission

#: Profondeur maximale parcourue (un dossier de presentation a 2 niveaux, une version Remotion quelques-uns de plus).
MAX_DEPTH = 32


class UnsafeTree(Exception):
    """Arbre refuse (lien, jonction, entree inattendue, hors racine). `where` est relatif au dossier inspecte, jamais absolu."""

    def __init__(self, where: str, reason: str) -> None:
        self.where, self.reason = where, reason
        super().__init__(f"{where}: {reason}")


@dataclass(frozen=True, slots=True)
class TreeCount:
    files: int = 0
    bytes: int = 0
    folders: int = 0


def _walk(folder: Path) -> tuple[list[Path], list[tuple[Path, int]]]:
    """Dossiers (parents d'abord) et fichiers `(chemin, taille)` de `folder`, lui compris. Refuse tout ce qui n'est pas sur."""

    try:
        top = os.lstat(folder)
    except FileNotFoundError:
        raise
    if safe_folders.is_link(top) or not stat.S_ISDIR(top.st_mode):
        raise UnsafeTree(".", "not a plain folder (link, junction or file refused)")
    folders: list[Path] = []
    files: list[tuple[Path, int]] = []

    def visit(current: Path, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise UnsafeTree(current.relative_to(folder).as_posix(), f"deeper than {MAX_DEPTH} levels")
        folders.append(current)
        for entry in sorted(os.scandir(current), key=lambda item: item.name):
            path = Path(entry.path)
            info = os.lstat(path)
            label = path.relative_to(folder).as_posix()
            if safe_folders.is_link(info):
                raise UnsafeTree(label, "symbolic link, junction or reparse point refused")
            if stat.S_ISDIR(info.st_mode):
                visit(path, depth + 1)
            elif stat.S_ISREG(info.st_mode):
                files.append((path, info.st_size))
            else:
                raise UnsafeTree(label, "neither a folder nor a regular file")

    visit(folder, 0)
    return folders, files


def inventory(folder: Path) -> TreeCount:
    """Compte un arbre sur (fichiers, octets, dossiers). `UnsafeTree` s'il ne l'est pas, `FileNotFoundError` s'il manque."""

    folders, files = _walk(Path(folder))
    return TreeCount(len(files), sum(size for _, size in files), len(folders))


def copy_tree(source: Path, target: Path) -> TreeCount:
    """Copie `source` vers `target` (qui ne doit pas exister) ; inventaire d'abord, tailles verifiees apres chaque fichier."""

    source, target = Path(source), Path(target)
    folders, files = _walk(source)
    if os.path.lexists(target):
        raise FileExistsError(str(target.name))
    for folder in folders:
        destination = target / folder.relative_to(source)
        safe_folders.check_file_path(destination)
        destination.mkdir(parents=True, exist_ok=False)
    copied = 0
    for path, size in files:
        destination = target / path.relative_to(source)
        safe_folders.check_file_path(destination)
        retry_on_permission(lambda p=path, d=destination: shutil.copy2(p, d, follow_symlinks=False))
        written = os.lstat(destination).st_size
        if written != size:
            raise OSError(f"{path.relative_to(source).as_posix()}: copied {written} bytes, read {size}")
        copied += size
    return TreeCount(len(files), copied, len(folders))


def _inside(folder: Path, within: Path) -> bool:
    resolved, root = os.path.normcase(str(folder.resolve())), os.path.normcase(str(within.resolve()))
    return resolved != root and os.path.commonpath([resolved, root]) == root


def _unlink(path: Path) -> None:
    try:
        retry_on_permission(lambda: os.unlink(path))
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)  # a read-only file on Windows refuses unlink: clear the flag, once, then retry
        retry_on_permission(lambda: os.unlink(path))


def remove_tree(folder: Path, *, within: Path) -> TreeCount:
    """Efface `folder` (strictement sous `within`) : inventaire complet d'abord (rien n'est efface si un lien ou une entree inattendue
    s'y trouve), puis fichiers, puis dossiers des plus profonds aux moins profonds. Rend ce qui a ete efface."""

    folder, within = Path(folder), Path(within)
    try:
        info = os.lstat(folder)
    except FileNotFoundError:
        return TreeCount()
    if safe_folders.is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise UnsafeTree(".", "not a plain folder (link, junction or file refused)")
    if not _inside(folder, within):
        raise UnsafeTree(".", "outside the folder it may be removed from")
    folders, files = _walk(folder)
    removed = 0
    for path, size in files:
        _unlink(path)
        removed += size
    for current in reversed(folders):
        retry_on_permission(lambda c=current: os.rmdir(c))
    return TreeCount(len(files), removed, len(folders))
