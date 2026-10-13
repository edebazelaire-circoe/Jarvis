"""Ledger file of the retired run stage (handoff jarvis-interactive-presentation-studio, Slice 12; retired by
native-studio-playback-fix Slice 09).

`<data_root>/state/presentation-studio-stage-ledger.json` held the Board object ids an older Core's playback put on THIS machine's
scene, so a Core killed mid-run could archive exactly those at its next start. Since Slice 09 a run no longer writes any Board object
(it plays inside Variants, on a memory surface): the file is only **read** once by the legacy reclaim
(`jarvis/core/presentation_studio_stage.py`), then **kept aside** as `<file>.retired-<UTC timestamp>` (never deleted, repo data
rules). No new ledger is ever written. It holds ids only (no title, no content) and lives outside `presentations/` on purpose.
"""

from __future__ import annotations

import json
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

    def _path(self) -> Path | None:
        folder = safe_folders.check_existing_tree(self._data_root, [STATE_DIR])
        if folder is None:
            return None
        path = folder / LEDGER_FILE
        safe_folders.check_file_path(path)
        return path

    def read(self) -> list[str] | None:
        """`None`: there is no ledger (the normal state since Slice 09). An unreadable or foreign file raises."""

        path = self._path()
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

    def quarantine(self) -> str | None:
        """Keep an unreadable ledger aside as `<file>.corrupt-<UTC timestamp>` (evidence for the human; the next write
        must never silently replace it). Returns the new name, `None` when there is no file."""

        path = self._path()
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

    def retire(self) -> str | None:
        """Keep a ledger whose ids were taken back aside as `<file>.retired-<UTC timestamp>` (never deleted: the human may want to
        see what an older Core left). Returns the new name, `None` when there is no file."""

        path = self._path()
        if path is None or not path.exists():
            return None
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        target = path.with_name(f"{path.name}.retired-{stamp}-{secrets.token_hex(2)}")
        replace_with_retry(path, target)
        return target.name
