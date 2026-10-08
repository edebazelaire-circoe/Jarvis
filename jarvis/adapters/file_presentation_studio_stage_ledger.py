"""Ledger file of the Studio's playback stage (handoff jarvis-interactive-presentation-studio, Slice 12).

`<data_root>/state/presentation-studio-stage-ledger.json`, beside `scene.sqlite3`: only the object ids the Studio's playback
put on THIS machine's scene, so a Core killed mid-run can archive exactly those at the next start
(`jarvis/core/presentation_studio_stage.py`). It is **not** playback state (R6: position, detours and reveals are memory
only) and it is not part of a Presentation: it holds no title, no content, nothing the presentation says, it is erased as
soon as the ids are taken back, and it lives outside `presentations/` on purpose (a backup or a move of the Presentations
must never carry ids of another scene).

Written like every other file of the tree: a unique temporary in the same folder, `fsync`, `replace_with_retry`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
import secrets
import time

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import replace_with_retry

STATE_DIR = "state"
LEDGER_FILE = "presentation-studio-stage-ledger.json"
SCHEMA = "jarvis.presentation_studio.stage_ledger"
#: Unreadable ledgers kept aside (newest first); older ones are deleted so a recurring fault cannot fill the folder.
KEEP_QUARANTINED = 3


class FileStageLedger:
    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    def _path(self, *, create: bool) -> Path | None:
        if create:
            folder, _ = safe_folders.ensure_folder_tree(self._data_root, [STATE_DIR])
        else:
            folder = safe_folders.check_existing_tree(self._data_root, [STATE_DIR])
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

    def quarantine(self) -> str | None:
        """Keep an unreadable ledger aside as `<file>.corrupt-<UTC timestamp>` (evidence for the human; the next write
        must never silently replace it). Returns the new name, `None` when there is no file."""

        path = self._path(create=False)
        if path is None or not path.exists():
            return None
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        target = path.with_name(f"{path.name}.corrupt-{stamp}-{secrets.token_hex(2)}")
        replace_with_retry(path, target)
        for old in sorted(path.parent.glob(f"{path.name}.corrupt-*"), key=lambda item: item.stat().st_mtime,
                          reverse=True)[KEEP_QUARANTINED:]:
            try:
                old.unlink()
            except OSError:
                pass  # intentional: an old evidence file that cannot be removed is left; it costs a few bytes
        return target.name

    def erase(self) -> None:
        path = self._path(create=False)
        if path is None:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass  # intentional: erasing what is already gone is the goal
