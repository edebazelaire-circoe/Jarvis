from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from jarvis.domain.v2 import HistoryRecord, TurnKind, jsonable


class JsonlHistoryStore:
    """Append-only daily JSONL archive with record-id de-duplication."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._seen: set[str] = set()
        self._loaded = False

    async def append(self, record: HistoryRecord) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self._append_sync, record)

    def _load_seen(self) -> None:
        if self._loaded:
            return
        for path in sorted(self.root.glob("*.jsonl")):
            for payload in self._valid_payloads(path):
                if isinstance(payload.get("id"), str):
                    self._seen.add(payload["id"])
        self._loaded = True

    def _append_sync(self, record: HistoryRecord) -> bool:
        self._load_seen()
        if record.id in self._seen:
            return False
        path = self.root / f"{record.created_at.astimezone(timezone.utc):%Y-%m-%d}.jsonl"
        payload = json.dumps(jsonable(record), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._seen.add(record.id)
        return True

    async def read(self, *, conversation_id: str | None = None):
        async with self._lock:
            return await asyncio.to_thread(self._read_sync, conversation_id)

    def _read_sync(self, conversation_id: str | None):
        records = []
        for path in sorted(self.root.glob("*.jsonl")):
            for d in self._valid_payloads(path):
                if conversation_id is not None and d.get("conversation_id") != conversation_id:
                    continue
                records.append(HistoryRecord(id=d["id"],kind=TurnKind(d["kind"]),created_at=datetime.fromisoformat(d["created_at"]),correlation_id=d["correlation_id"],conversation_id=d.get("conversation_id"),content=d.get("content"),reference_id=d.get("reference_id"),metadata=d.get("metadata",{})))
        records.sort(key=lambda r: (r.created_at, r.id))
        return tuple(records)

    @staticmethod
    def _valid_payloads(path: Path):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if i == len(lines) - 1:
                    break
                raise RuntimeError(f"malformed history record in {path.name}:{i + 1}")

    async def cleanup(self, *, older_than: datetime) -> int:
        if older_than.tzinfo is None:
            raise ValueError("older_than must be timezone-aware")
        async with self._lock:
            return await asyncio.to_thread(self._cleanup_sync, older_than)

    def _cleanup_sync(self, older_than: datetime) -> int:
        removed = 0
        cutoff = older_than.astimezone(timezone.utc).date()
        for path in self.root.glob("*.jsonl"):
            try:
                partition = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if partition < cutoff:
                path.unlink()
                removed += 1
        if removed:
            self._loaded = False
            self._seen.clear()
        return removed
