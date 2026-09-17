"""Captures PNG de la scène sur disque (handoff jarvis-constellation-scene-runtime, Slice 09, partie 2).

Dossier dédié (`runtime/scene-captures/`), fichiers `capture-<horodatage UTC>-<8 hex>.png` :
aucun texte de l'utilisateur ni identifiant de capture dans le nom. Écriture
atomique (temporaire puis `replace_with_retry`). Seuls les fichiers de ce motif
sont comptés et supprimés par la rétention, et seulement s'ils sont des fichiers ordinaires
(un dossier ou un lien au nom de capture est ignoré) : rien d'autre du dossier n'est touché.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.ports.scene import StoredSceneCapture

#: Sous-dossier du dossier runtime où Core range les captures.
SCENE_CAPTURE_DIR = "scene-captures"
CAPTURE_NAME = re.compile(r"\Acapture-\d{8}T\d{6}\d{3}Z-[0-9a-f]{8}\.png\Z")


class FileSceneCaptureStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).resolve()

    def save(self, png: bytes, *, now_epoch_s: float) -> StoredSceneCapture:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(now_epoch_s, tz=timezone.utc)
        name = f"capture-{stamp:%Y%m%dT%H%M%S}{stamp.microsecond // 1000:03d}Z-{secrets.token_hex(4)}.png"
        target = self.directory / name
        handle, raw_tmp = tempfile.mkstemp(prefix=".capture-", suffix=".tmp", dir=self.directory)
        tmp = Path(raw_tmp)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(png)
            replace_with_retry(tmp, target)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass  # intentional: the write failure is what the caller must see; a stray .tmp is removed by no one but harmless
            raise
        return StoredSceneCapture(name=name, path=str(target), size=len(png))

    def prune(self, *, now_epoch_s: float, keep: int, max_age_s: float) -> int:
        if not self.directory.is_dir():
            return 0
        captures = []
        for entry in self.directory.iterdir():
            if not CAPTURE_NAME.match(entry.name):
                continue
            try:
                info = entry.lstat()
            except FileNotFoundError:
                continue  # intentional: removed meanwhile (another prune, the user); nothing left to keep or delete
            if not stat.S_ISREG(info.st_mode):
                continue  # intentional: a directory or link named like a capture is not ours; it takes no slot
            captures.append((info.st_mtime, entry.name, entry))
        # Nom horodaté puis mtime : ordre stable même si deux fichiers ont la même mtime.
        captures.sort(key=lambda item: (item[0], item[1]), reverse=True)
        removed = 0
        for index, (mtime, _name, entry) in enumerate(captures):
            if index >= keep or now_epoch_s - mtime > max_age_s:
                try:
                    entry.unlink()
                    removed += 1
                except FileNotFoundError:
                    continue  # intentional: vanished between listing and deletion; the next file is still pruned
        return removed
