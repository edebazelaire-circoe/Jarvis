"""Canonical memory store port (memory handoff, Slice 01).

The only owner of durable truth: Markdown notes under `<data_root>/memory`
(adapter: `jarvis.adapters.markdown_memory`, Slice 02). Derived indexes
(lexical, semantic, Tencent mirror) are rebuilt from it and never write to it.

Synchronous on purpose: it is blocking disk I/O, called from Core through a
thread (`asyncio.to_thread`), like the Board memory store.

Failures are `MemoryStoreError` with a stable `MemoryErrorCode`:
`memory_not_found` (unknown id), `memory_conflict_revision` (stale
`expected_revision`), `memory_scope_denied`, `memory_unavailable` (disk or
root in failure). It does not replace `jarvis.ports.memory.MemoryBackend`, the
legacy port, which stays as is.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.domain.memory import MemoryFilters, MemoryNote, MemoryPatch


@runtime_checkable
class CanonicalMemoryStore(Protocol):
    def get(self, memory_id: str) -> MemoryNote:
        """Latest revision. `memory_not_found` when the id is unknown."""
        ...

    def list(self, filters: MemoryFilters) -> tuple[MemoryNote, ...]:
        """Latest revisions matching `filters`, newest `updated_at` first, ties by id."""
        ...

    def create(self, note: MemoryNote) -> MemoryNote:
        """Persist a new note (caller-assigned id, revision 1) and return it as stored."""
        ...

    def revise(self, memory_id: str, patch: MemoryPatch, expected_revision: int) -> MemoryNote:
        """Write revision N+1 and keep revision N in history.

        `memory_conflict_revision` when `expected_revision` is not the current one;
        `memory_not_found` when the id is unknown. Never edits in place.

        Adapter extension (not part of this protocol): `MarkdownMemoryBackend.revise`
        also takes a keyword-only `human: bool = False`. Protected classes
        (`traumatic_memory`, `eternal_memory`) are never rewritten; only a human
        may change their links or validity. Callers that need it use the adapter.
        """
        ...

    def history(self, memory_id: str) -> tuple[MemoryNote, ...]:
        """Every revision, oldest first, the current one last."""
        ...

    def rebuild_indexes(self) -> int:
        """Rebuild every derived index from the canonical files; returns notes indexed."""
        ...
