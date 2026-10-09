"""Magasin de fichiers des capacités locales (`docs/local-capabilities.md` §Stockage).

`<data_root>/local_capabilities/<capability_id>/state.json` (état) et
`runtime/` (ce que le runner installe). Hors du dépôt comme toute donnée de
poste (`docs/local-data.md`) : aucun schéma SQLite, donc aucune migration. Un
`state.json` illisible est une erreur codée, jamais un état remplacé en silence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.local_capabilities import (
    CAPABILITY_ID_PATTERN, CapabilityState, LocalCapabilityError, LocalCapabilityErrorCode, state_from_payload,
)

ROOT_DIR = "local_capabilities"
STATE_FILE = "state.json"
RUNTIME_DIR = "runtime"
MAX_STATE_BYTES = 64 * 1024


def _store_failed(exc: BaseException, what: str) -> LocalCapabilityError:
    return LocalCapabilityError(LocalCapabilityErrorCode.STORE_FAILED, f"{what}: {type(exc).__name__}: {exc}")


class FileLocalCapabilityStore:
    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    def _check(self, capability_id: str) -> None:
        if not CAPABILITY_ID_PATTERN.fullmatch(capability_id or ""):
            raise LocalCapabilityError(LocalCapabilityErrorCode.INVALID, "capability_id is not a valid slug")

    def load(self, capability_id: str) -> CapabilityState | None:
        self._check(capability_id)
        try:
            base = safe_folders.check_existing_tree(self._data_root, [ROOT_DIR, capability_id])
            if base is None or not (base / STATE_FILE).is_file():
                return None
            path = base / STATE_FILE
            safe_folders.check_file_path(path)
            if path.stat().st_size > MAX_STATE_BYTES:
                raise LocalCapabilityError(LocalCapabilityErrorCode.STORE_FAILED, "state file is too large")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except LocalCapabilityError:
            raise
        except (safe_folders.SafeFolderError, OSError, ValueError) as exc:
            raise _store_failed(exc, capability_id) from None
        if not isinstance(payload, dict) or payload.get("capability_id") != capability_id:
            raise LocalCapabilityError(LocalCapabilityErrorCode.STORE_FAILED, f"{capability_id}: state file names another capability")
        return state_from_payload(payload)

    def save(self, state: CapabilityState) -> None:
        self._check(state.capability_id)
        try:
            base, _ = safe_folders.ensure_folder_tree(self._data_root, [ROOT_DIR, state.capability_id])
            path = base / STATE_FILE
            temporary = path.with_name(f"{STATE_FILE}.{secrets.token_hex(4)}.tmp")
            safe_folders.check_file_path(temporary)
            try:
                with open(temporary, "xb") as stream:
                    stream.write(json.dumps(state.to_payload(), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                replace_with_retry(temporary, path)
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass  # intentional: never created, or already consumed by the replace
                raise
        except (safe_folders.SafeFolderError, OSError) as exc:
            raise _store_failed(exc, state.capability_id) from None

    def list_ids(self) -> tuple[str, ...]:
        try:
            base = safe_folders.check_existing_tree(self._data_root, [ROOT_DIR])
            if base is None:
                return ()
            names = [e.name for e in os.scandir(base) if e.is_dir(follow_symlinks=False)]
        except (safe_folders.SafeFolderError, OSError) as exc:
            raise _store_failed(exc, "list") from None
        return tuple(sorted(n for n in names if CAPABILITY_ID_PATTERN.fullmatch(n)))

    def runtime_dir(self, capability_id: str) -> Path:
        self._check(capability_id)
        try:
            return safe_folders.ensure_folder_tree(self._data_root, [ROOT_DIR, capability_id, RUNTIME_DIR])[0]
        except safe_folders.SafeFolderError as exc:
            raise _store_failed(exc, capability_id) from None
