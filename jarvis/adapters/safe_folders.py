"""Dossiers sûrs sous la racine de données (partagé par les Contexts et les Artifacts).

Une seule implémentation des défenses de chemin, utilisée par
`context_workspace` (dossiers des Contexts, Slice 02) et `artifact_payloads`
(dossiers des Artifacts, Slice 04) ; chacun traduit `SafeFolderError` en son
erreur codée.

- la racine doit être absolue et exister ; elle est résolue une fois et le
  dossier final doit rester dessous ;
- chaque composant **sous** la racine est inspecté par `lstat` : lien
  symbolique, jonction ou tout point d'analyse Windows
  (`FILE_ATTRIBUTE_REPARSE_POINT`) refusé, de même qu'un fichier là où un
  dossier est attendu ;
- création composant par composant par `os.mkdir` (atomique) ; une course
  (`FileExistsError`) est un succès après la même inspection ;
- chemin final au-delà de la limite Windows des dossiers refusé avant tout
  accès disque ;
- ne supprime jamais rien.
"""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import stat

#: Longueur maximale d'un chemin de **dossier** sous Windows sans chemins longs
#: (`MAX_PATH` 260 moins 12 pour un nom 8.3) : au-delà, `CreateDirectory`
#: échoue avec une erreur trompeuse (`FileNotFoundError`).
WINDOWS_MAX_DIR_PATH = 248

UNSAFE = "unsafe"
FAILED = "failed"


class SafeFolderError(Exception):
    """`kind` : `unsafe` (refus de sécurité) ou `failed` (le disque a refusé)."""

    def __init__(self, kind: str, path: Path, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind
        self.path = path
        self.reason = reason


def is_link(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def inspect_folder(path: Path) -> None:
    info = os.lstat(path)
    if is_link(info):
        raise SafeFolderError(UNSAFE, path, "is a symbolic link, junction or reparse point")
    if not stat.S_ISDIR(info.st_mode):
        raise SafeFolderError(UNSAFE, path, "exists and is not a directory")


def resolve_root(data_root: Path) -> Path:
    root = Path(data_root)
    if not root.is_absolute():
        raise SafeFolderError(UNSAFE, root, "data root must be an absolute path")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise SafeFolderError(FAILED, root, f"data root unavailable: {type(exc).__name__}: {exc}") from exc
    if not root.is_dir():
        raise SafeFolderError(UNSAFE, root, "data root is not a directory")
    return root


def ensure_folder_tree(data_root: Path, parts: Sequence[str]) -> tuple[Path, bool]:
    """Crée (ou retrouve) `data_root/parts...` ; rend `(chemin, créé)`. `parts` déjà validés par le domaine."""

    root = resolve_root(data_root)
    final = root.joinpath(*parts)
    if os.name == "nt" and len(str(final)) > WINDOWS_MAX_DIR_PATH:
        raise SafeFolderError(
            FAILED, final, f"path is {len(str(final))} characters, above the Windows folder limit of "
                           f"{WINDOWS_MAX_DIR_PATH}: shorten the data root or the ids")
    created = False
    current = root
    try:
        for part in parts:
            current = current / part
            try:
                os.mkdir(current)
                created = True
            except FileExistsError:
                pass  # déjà là (ou créé par un concurrent) : inspecté juste après
            inspect_folder(current)
        resolved = current.resolve(strict=True)
    except SafeFolderError:
        raise
    except OSError as exc:
        raise SafeFolderError(FAILED, current, f"{type(exc).__name__}: {exc}") from exc
    # normcase: NTFS is case-insensitive, an existing `Sessions` is the same folder.
    if os.path.normcase(resolved) != os.path.normcase(current) or not resolved.is_relative_to(root):
        raise SafeFolderError(UNSAFE, current, f"resolves outside its expected place: {resolved}")
    return current, created


def check_existing_tree(data_root: Path, parts: Sequence[str]) -> Path | None:
    """Inspecte `data_root/parts...` sans rien créer ; `None` si un composant manque."""

    root = resolve_root(data_root)
    current = root
    try:
        for part in parts:
            current = current / part
            try:
                inspect_folder(current)
            except FileNotFoundError:
                return None
    except SafeFolderError:
        raise
    except OSError as exc:
        raise SafeFolderError(FAILED, current, f"{type(exc).__name__}: {exc}") from exc
    return current
