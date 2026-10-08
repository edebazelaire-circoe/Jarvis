"""Ledger file of the Studio's playback stage (handoff jarvis-interactive-presentation-studio, Slice 12).

`<data_root>/presentations/.playback-stage-ledger.json`: only the object ids the Studio's playback put on the scene, so
a Core killed mid-run can archive exactly those at the next start (`jarvis/core/presentation_studio_stage.py`). It is
**not** playback state (R6: position, detours and reveals are memory only): it holds no title, no content, nothing the
presentation says, and is erased as soon as the ids are taken back. The leading dot keeps it out of the store's listing
(`FilePresentationStudioStore.scan` ignores hidden names); a Presentation folder is never touched.

Written like every other file of the tree: a unique temporary in the same folder, `fsync`, `replace_with_retry`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
import secrets

from jarvis.adapters import safe_folders
from jarvis.adapters.file_presentation_studio_store import STORE_DIR
from jarvis.adapters.file_replace import replace_with_retry

LEDGER_FILE = ".playback-stage-ledger.json"
SCHEMA = "jarvis.presentation_studio.stage_ledger"


class FileStageLedger:
    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    def _path(self, *, create: bool) -> Path | None:
        if create:
            folder, _ = safe_folders.ensure_folder_tree(self._data_root, [STORE_DIR])
        else:
            folder = safe_folders.check_existing_tree(self._data_root, [STORE_DIR])
            if folder is None:
                return None
        path = folder / LEDGER_FILE
        safe_folders.check_file_path(path)
        return path

    def read(self) -> list[str] | None:
        """`None`: there is no ledger (the normal first run and clean shutdown). An unreadable or foreign file raises."""

        path = self._path(create=False)
        if path is None:
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None  # intentional: no ledger is the normal state (never written, or erased after a clean end)
        document = json.loads(text)
        if not isinstance(document, dict) or document.get("schema") != SCHEMA \
                or not isinstance(document.get("object_ids"), list):
            raise ValueError("not a stage ledger")
        return [item for item in document["object_ids"] if isinstance(item, str)]

    def write(self, ids: Sequence[str]) -> None:
        path = self._path(create=True)
        assert path is not None
        temporary = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
        text = json.dumps({"schema": SCHEMA, "object_ids": list(ids)}, separators=(",", ":"))
        with open(temporary, "xb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, path)

    def erase(self) -> None:
        path = self._path(create=False)
        if path is None:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass  # intentional: erasing what is already gone is the goal
