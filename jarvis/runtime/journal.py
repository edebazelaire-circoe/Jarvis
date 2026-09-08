from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RuntimeJournal:
    runtime_root: Path

    @property
    def trace_path(self) -> Path:
        return self.runtime_root / "trace.jsonl"

    @property
    def error_path(self) -> Path:
        return self.runtime_root / "errors.jsonl"

    @property
    def archive_path(self) -> Path:
        return self.runtime_root / "errors-archive.jsonl"

    def archive_errors(self) -> int:
        """Vider la liste active en conservant tout dans l'archive.

        Une erreur traitée doit disparaître du badge sans être perdue : les
        entrées sont déplacées telles quelles, horodatées de leur archivage.
        """
        try:
            raw = self.error_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return 0
        lines = [line for line in raw.splitlines() if line.strip()]
        if not lines:
            self.error_path.write_text("", encoding="utf-8")
            return 0
        archived_at = datetime.now(timezone.utc).isoformat()
        self.archive_path.parent.mkdir(parents=True, exist_ok=True)
        with self.archive_path.open("a", encoding="utf-8") as handle:
            for line in lines:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = {"ts": archived_at, "kind": "journal.unreadable", "level": "error", "message": line, "data": {}}
                if isinstance(payload, dict):
                    payload["archived_at"] = archived_at
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        # Tronqué seulement après l'écriture de l'archive : une coupure au
        # mauvais moment doit dupliquer des erreurs, jamais en perdre.
        self.error_path.write_text("", encoding="utf-8")
        return len(lines)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "level": level,
            "message": message,
            "data": data or {},
        }
        self._append(self.trace_path, payload)
        if level == "error":
            self._append(self.error_path, payload)

    @staticmethod
    def _append(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def read_jsonl_tail(path: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    if limit <= 0 or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for raw in lines[-limit:]:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out
