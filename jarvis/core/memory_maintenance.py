from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from jarvis.domain.memory import MemoryNote, RetentionClass

#: One source of truth: the retention classes are the directory names.
MEMORY_CLASSES = tuple(item.value for item in RetentionClass)

RETAIN_MARKER = "<!-- jarvis:retain -->"


def ensure_memory_layout(root: Path) -> dict[str, Path]:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    paths = {name: root / name for name in MEMORY_CLASSES}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


class PromotingStore(Protocol):
    """What promotion needs from the canonical store (`MarkdownMemoryBackend.promote_file`)."""

    def promote_file(self, source_rel: str, target: RetentionClass) -> MemoryNote | None: ...


class MemoryMaintenanceWorker:
    """Markdown-only consolidation MVP; protected classes are never auto-deleted.

    Promotion (an explicit `jarvis:retain` marker) goes through the canonical
    store: the copy is a new note with provenance (`sources` ends with the
    source note) and reaches the derived index at once (handoff
    jarvis-memory-intelligence-knowledge, Slice 02, R3).
    """

    def __init__(self, root: Path, store: PromotingStore) -> None:
        self.paths = ensure_memory_layout(root)
        self.store = store

    async def execute(self, job) -> dict[str, object]:
        del job
        return await asyncio.to_thread(self._promote_retained)

    def _promote_retained(self) -> dict[str, object]:
        promoted = 0
        for source in sorted(self.paths["short_term_memory"].glob("*.md")):
            text = source.read_text(encoding="utf-8")
            if RETAIN_MARKER not in text:
                continue
            note = self.store.promote_file(f"{RetentionClass.SHORT_TERM.value}/{source.name}", RetentionClass.LONG_TERM)
            if note is not None:
                promoted += 1
        return {"promoted": promoted}

    async def cancel(self, job_id: str) -> None:
        del job_id
