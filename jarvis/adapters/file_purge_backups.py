"""Sauvegardes d'une purge definitive (presentations archivees) : `<data_root>/backups/purge-presentations-<horodatage UTC>/`.

Port : `jarvis.ports.presentation_studio.PurgeBackupStore` ; seul utilisateur : `jarvis/core/presentation_studio_purge.py`.

Disposition d'une sauvegarde (rien n'y est jamais relu par Core ; la restauration est un geste humain, `docs/OPERATIONS.md`) :

```
backups/purge-presentations-<AAAAMMJJTHHMMSSZ>/
  presentations/<pst_...>/...         # dossier entier de chaque presentation (FilePresentationStudioStore.copy_presentation)
  prefabs/<id>/..., prefabs/.archive/<id>/...   # sources de scene purgees (FilePrefabLibrary.copy_ids)
  artifacts/<jart_...>/...            # dossiers des Artifacts purges (snapshots et rendus)
  state/jarvis.sqlite3                # copie coherente de la base (API sqlite3 backup), seulement si des Artifacts partent
  purge.json                          # ce qui a ete sauvegarde puis efface, ecrit en dernier
```

Une sauvegarde se construit dans `backups/.partial-<nom>/` puis est publiee d'un seul renommage : un dossier sans `.partial-` est
une sauvegarde complete. Ce module ne supprime jamais une sauvegarde publiee ; `discard` ne retire que le `.partial-` d'une
sauvegarde qui a echoue (notre propre copie incomplete, jamais une donnee).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any

from jarvis.adapters import safe_folders
from jarvis.adapters.safe_tree import TreeCount, UnsafeTree, copy_tree, remove_tree
from jarvis.ports.presentation_studio import PurgeBackupDraft

BACKUPS_DIR = "backups"
BACKUP_PREFIX = "purge-presentations-"
PARTIAL_PREFIX = ".partial-"
MANIFEST_FILE = "purge.json"


class FilePurgeBackups:
    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    def _backups(self) -> Path:
        folder, _ = safe_folders.ensure_folder_tree(self._data_root, [BACKUPS_DIR])
        return folder

    def begin(self, moment: datetime) -> PurgeBackupDraft:
        backups = self._backups()
        base = BACKUP_PREFIX + moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        name, suffix = base, 1
        while os.path.lexists(backups / name) or os.path.lexists(backups / f"{PARTIAL_PREFIX}{name}"):
            suffix += 1
            name = f"{base}-{suffix}"
        folder = backups / f"{PARTIAL_PREFIX}{name}"
        safe_folders.check_file_path(folder / "presentations")
        folder.mkdir()
        return PurgeBackupDraft(name=name, folder=folder)

    def copy_artifact_folder(self, draft: PurgeBackupDraft, artifact_id: str) -> TreeCount | None:
        """Copie `artifacts/<id>/` sous `artifacts/<id>/` de la sauvegarde ; `None` si l'Artifact n'a pas de dossier."""

        source = safe_folders.check_existing_tree(self._data_root, ["artifacts", artifact_id])
        return None if source is None else copy_tree(source, draft.folder / "artifacts" / artifact_id)

    def database_path(self, draft: PurgeBackupDraft) -> Path:
        target = draft.folder / "state"
        target.mkdir(exist_ok=True)
        return target / "jarvis.sqlite3"

    def write_manifest(self, draft: PurgeBackupDraft, document: Mapping[str, Any]) -> None:
        with open(draft.folder / MANIFEST_FILE, "x", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(document), ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def publish(self, draft: PurgeBackupDraft) -> str:
        os.rename(draft.folder, draft.folder.with_name(draft.name))
        return f"{BACKUPS_DIR}/{draft.name}"

    def discard(self, draft: PurgeBackupDraft) -> None:
        try:
            remove_tree(draft.folder, within=self._backups())
        except (UnsafeTree, OSError, safe_folders.SafeFolderError):
            pass  # intentional: a `.partial-*` folder is never mistaken for a backup; the caller's refusal is what counts
