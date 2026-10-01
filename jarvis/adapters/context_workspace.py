"""Dossier de travail d'un Context sur disque (handoff session-context-recording, Slice 02).

`<data_root>/sessions/<jarvis_session_id>/contexts/<context_id>/`, dérivé
uniquement de `context_workspace_path` (ids validés par le domaine) : aucun
chemin n'est reçu en entrée. Contrat : `docs/session-context.md` ›
*Workspace folder*.

Défenses (implémentées par `safe_folders`, partagé avec les Artifacts) :

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

import codecs
import os
from pathlib import Path
import stat

from jarvis.adapters import safe_folders
from jarvis.domain.session_context import SESSIONS_DIR, context_workspace_path
from jarvis.ports.session_context import (
    WORKSPACE_FAILED, WORKSPACE_UNSAFE, ContextWorkspace, ContextWorkspaceError,
)

# Valeur et erreur appartiennent au port (Core les attrape sans importer l'adaptateur).
UNSAFE = WORKSPACE_UNSAFE
FAILED = WORKSPACE_FAILED
_CODES = {safe_folders.UNSAFE: UNSAFE, safe_folders.FAILED: FAILED}
#: Rappel (tests, messages) : la limite vit dans `safe_folders`.
WINDOWS_MAX_DIR_PATH = safe_folders.WINDOWS_MAX_DIR_PATH
_is_link = safe_folders.is_link


def ensure_context_workspace(data_root: Path, jarvis_session_id: str, context_id: str) -> ContextWorkspace:
    """Crée (ou retrouve) le dossier du Context ; refuse tout chemin douteux.

    Lève `SessionContextError(invalid_context)` pour un id invalide (avant
    tout accès disque) et `ContextWorkspaceError` sinon. Les défenses sont
    celles de `safe_folders.ensure_folder_tree` (partagées avec les Artifacts).
    """

    relative = context_workspace_path(jarvis_session_id, context_id)
    try:
        path, created = safe_folders.ensure_folder_tree(Path(data_root), relative.parts)
    except safe_folders.SafeFolderError as exc:
        raise ContextWorkspaceError(_CODES[exc.kind], exc.path, exc.reason) from exc
    return ContextWorkspace(path=path, created=created)


# ------------------------------------------------------------------ fichiers connus du Context (Slice 03)

#: Résumé court que l'agent tient lui-même ; relu (borné) à chaque tour.
SUMMARY_FILE = "summary.md"
#: Relais explicite écrit à la création d'un Context (D05) : jamais une copie du dossier précédent.
HANDOFF_FILE = "handoff.md"


def read_context_summary(workspace: Path, max_bytes: int) -> tuple[str, bool]:
    """`(texte, coupé)` de `summary.md` du dossier ; `("", False)` s'il n'existe pas.

    Le fichier doit être un fichier ordinaire **dans** le dossier : un lien
    symbolique, une jonction ou un point d'analyse est refusé
    (`context_workspace_unsafe`), sinon un résumé pourrait faire lire au
    cerveau n'importe quel fichier du disque. Au plus `max_bytes` octets sont
    lus ; la coupe tombe sur un caractère UTF-8 entier. Un octet invalide est
    remplacé (U+FFFD), jamais une erreur : le contenu appartient à l'agent.
    """

    path = Path(workspace) / SUMMARY_FILE
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "", False
    except OSError as exc:
        raise ContextWorkspaceError(FAILED, path, f"{type(exc).__name__}: {exc}") from exc
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        raise ContextWorkspaceError(UNSAFE, path, "is not a regular file inside the context folder")
    try:
        with open(path, "rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as exc:
        raise ContextWorkspaceError(FAILED, path, f"{type(exc).__name__}: {exc}") from exc
    clipped = len(data) > max_bytes
    # `final=False` : une séquence multi-octets coupée en fin de tampon est
    # laissée de côté au lieu de devenir U+FFFD (coupe sur un caractère entier).
    text = codecs.getincrementaldecoder("utf-8")("replace").decode(data[:max_bytes], final=not clipped)
    # Un octet invalide remplacé (U+FFFD, 3 octets) peut faire dépasser la borne : on retranche.
    while len(text.encode("utf-8")) > max_bytes:
        text, clipped = text[:-1], True
    return text, clipped


def write_context_handoff(workspace: Path, text: str) -> Path:
    """Écrit `handoff.md` dans le dossier (déjà créé et vérifié), atomiquement ; rend son chemin.

    Nom temporaire puis `os.replace` : un lecteur voit l'ancien fichier ou le
    neuf, jamais un morceau. Un `handoff.md` qui serait un lien est refusé
    (`context_workspace_unsafe`) plutôt que suivi.
    """

    folder = Path(workspace)
    target = folder / HANDOFF_FILE
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        info = None
    except OSError as exc:
        raise ContextWorkspaceError(FAILED, target, f"{type(exc).__name__}: {exc}") from exc
    if info is not None and (_is_link(info) or not stat.S_ISREG(info.st_mode)):
        raise ContextWorkspaceError(UNSAFE, target, "exists and is not a regular file")
    temporary = folder / f".{HANDOFF_FILE}.{os.getpid()}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, target)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass  # argued: the temporary may not exist; the real failure is raised below
        raise ContextWorkspaceError(FAILED, target, f"{type(exc).__name__}: {exc}") from exc
    return target


def sessions_root(data_root: Path) -> Path:
    """`<data_root résolue>/sessions` : le dossier que le Control Center accorde au CLI (`--add-dir`)."""

    return Path(data_root).resolve() / SESSIONS_DIR


class FileContextWorkspaces:
    """`ContextWorkspaceStore` sur une racine de données (composition root : `v2_app`)."""

    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    def sessions_root(self) -> Path:
        return sessions_root(self._root)

    def expected_path(self, jarvis_session_id: str, context_id: str) -> Path:
        return self._root.resolve().joinpath(*context_workspace_path(jarvis_session_id, context_id).parts)

    def ensure(self, jarvis_session_id: str, context_id: str) -> ContextWorkspace:
        return ensure_context_workspace(self._root, jarvis_session_id, context_id)

    def read_summary(self, workspace: Path, max_bytes: int) -> tuple[str, bool]:
        return read_context_summary(workspace, max_bytes)

    def write_handoff(self, workspace: Path, text: str) -> Path:
        return write_context_handoff(workspace, text)
