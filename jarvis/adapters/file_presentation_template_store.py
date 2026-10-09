"""Magasin de fichiers des modeles de presentation (handoff jarvis-interactive-presentation-studio, Slice 20).

`<data_root>/presentation_templates/<template_id>.json`, hors du depot comme tout le reste (`docs/local-data.md`). Ce n'est **pas** un
catalogue de prefabs : un fichier est une composition (versions de la bibliotheque partagee, valeurs neutres, direction artistique),
voir `jarvis/domain/presentation_studio_template.py`. Les ecritures et lectures reutilisent celles du magasin des Presentations
(`_write_file` : temporaire unique + `fsync` + remplacement atomique ; `_read_text` : fichier ordinaire borne, jamais un lien) et les
gardes de dossier de `safe_folders`. Un modele est cree une fois (`create` refuse un id pris) et n'est jamais reecrit ni supprime ici.
"""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.adapters import safe_folders
from jarvis.adapters.file_presentation_studio_store import _io, _read_text, _unsafe, _write_file
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_template import MAX_TEMPLATE_BYTES, is_template_id

TEMPLATES_DIR = "presentation_templates"
_SUFFIX = ".json"


class FilePresentationTemplateStore:
    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    def _check(self, template_id: str) -> None:
        if not is_template_id(template_id):
            raise PresentationStudioError(C.INVALID_PRESENTATION, "template_id is not a valid id")

    def list_ids(self) -> tuple[str, ...]:
        try:
            base = safe_folders.check_existing_tree(self._data_root, [TEMPLATES_DIR])
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, "templates") from None
        if base is None:
            return ()
        try:
            names = [e.name for e in os.scandir(base) if e.is_file(follow_symlinks=False)]
        except OSError as exc:
            raise _io(exc, "templates") from None
        return tuple(sorted(n[: -len(_SUFFIX)] for n in names if n.endswith(_SUFFIX) and is_template_id(n[: -len(_SUFFIX)])))

    def read(self, template_id: str) -> str:
        self._check(template_id)
        try:
            base = safe_folders.check_existing_tree(self._data_root, [TEMPLATES_DIR])
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, template_id) from None
        if base is None:
            raise PresentationStudioError(C.UNKNOWN_TEMPLATE, f"{template_id} is not in the template store")
        return _read_text(base / f"{template_id}{_SUFFIX}", template_id, missing=C.UNKNOWN_TEMPLATE)

    def create(self, template_id: str, text: str) -> None:
        """Ecrit un modele neuf, atomiquement. `already_exists` si l'id est pris (jamais un remplacement)."""

        self._check(template_id)
        if len(text.encode("utf-8")) > MAX_TEMPLATE_BYTES:
            raise PresentationStudioError(C.LIMIT_REACHED, f"a template document is at most {MAX_TEMPLATE_BYTES} bytes")
        try:
            folder, _ = safe_folders.ensure_folder_tree(self._data_root, [TEMPLATES_DIR])
            if (folder / f"{template_id}{_SUFFIX}").exists():
                raise PresentationStudioError(C.ALREADY_EXISTS, f"{template_id} already exists")
            _write_file(folder / f"{template_id}{_SUFFIX}", text)
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, template_id) from None
        except OSError as exc:
            raise _io(exc, template_id) from None
