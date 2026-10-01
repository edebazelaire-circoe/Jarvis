"""Dossier de travail d'un Context sur disque (handoff session-context-recording, Slice 02).

`<data_root>/sessions/<jarvis_session_id>/contexts/<context_id>/`, dérivé
uniquement de `context_workspace_path` (ids validés par le domaine) : aucun
chemin n'est reçu en entrée. Contrat : `docs/session-context.md` ›
*Workspace folder*.

Défenses :

- la racine de données doit être absolue et exister ; elle est résolue une
  fois, et le dossier final doit rester dessous (`relative_to`) ;
- chaque composant **sous** la racine (`sessions`, la Session, `contexts`,
  le Context) est inspecté par `lstat` : un lien symbolique, une jonction ou
  tout point d'analyse Windows (`FILE_ATTRIBUTE_REPARSE_POINT`) est refusé,
  de même qu'un fichier là où un dossier est attendu (`context_workspace_unsafe`) ;
- création composant par composant par `os.mkdir`, atomique au niveau du
  système de fichiers : un dossier existe entier ou n'existe pas. Le dossier
  est vide à la création, un nom temporaire puis un renommage n'apporteraient
  rien (et un renommage de dossier n'est pas un remplacement atomique sous
  Windows). Une création interrompue laisse un préfixe de la chaîne, que
  l'appel suivant complète ; une course (`FileExistsError`) est un succès
  après la même inspection ;
- idempotent, et ne supprime ni ne vide jamais rien : le contenu appartient
  à l'agent.

Pas de journal ici : l'appelant (service Core, Slice 03) journalise le
`ContextWorkspace` rendu ou l'erreur, qui porte un `code` stable.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from jarvis.domain.session_context import context_workspace_path

UNSAFE = "context_workspace_unsafe"
FAILED = "context_workspace_failed"


class ContextWorkspaceError(RuntimeError):
    """Dossier de Context refusé (`context_workspace_unsafe`) ou non créé (`context_workspace_failed`)."""

    def __init__(self, code: str, path: Path, reason: str) -> None:
        super().__init__(f"{code}: {path}: {reason}")
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class ContextWorkspace:
    #: Chemin absolu du dossier, sous la racine résolue.
    path: Path
    #: Vrai si cet appel a créé au moins un composant (dont le dossier final).
    created: bool


def _is_link(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _inspect(path: Path) -> None:
    info = os.lstat(path)
    if _is_link(info):
        raise ContextWorkspaceError(UNSAFE, path, "is a symbolic link, junction or reparse point")
    if not stat.S_ISDIR(info.st_mode):
        raise ContextWorkspaceError(UNSAFE, path, "exists and is not a directory")


def ensure_context_workspace(data_root: Path, jarvis_session_id: str, context_id: str) -> ContextWorkspace:
    """Crée (ou retrouve) le dossier du Context ; refuse tout chemin douteux.

    Lève `SessionContextError(invalid_context)` pour un id invalide (avant
    tout accès disque) et `ContextWorkspaceError` sinon.
    """

    relative = context_workspace_path(jarvis_session_id, context_id)
    root = Path(data_root)
    if not root.is_absolute():
        raise ContextWorkspaceError(UNSAFE, root, "data root must be an absolute path")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ContextWorkspaceError(FAILED, root, f"data root unavailable: {type(exc).__name__}: {exc}") from exc
    if not root.is_dir():
        raise ContextWorkspaceError(UNSAFE, root, "data root is not a directory")

    created = False
    current = root
    try:
        for part in relative.parts:
            current = current / part
            try:
                os.mkdir(current)
                created = True
            except FileExistsError:
                pass  # déjà là (ou créé par un concurrent) : inspecté juste après
            _inspect(current)
        resolved = current.resolve(strict=True)
    except ContextWorkspaceError:
        raise
    except OSError as exc:
        raise ContextWorkspaceError(FAILED, current, f"{type(exc).__name__}: {exc}") from exc
    # normcase: NTFS is case-insensitive, an existing `Sessions` is the same folder.
    if os.path.normcase(resolved) != os.path.normcase(current) or not resolved.is_relative_to(root):
        raise ContextWorkspaceError(UNSAFE, current, f"resolves outside its expected place: {resolved}")
    return ContextWorkspace(path=current, created=created)
