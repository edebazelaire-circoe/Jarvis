"""Lexical recall leg: a thin wrapper over the store's FTS5 `search_ranked` (Slice 03).

`LexicalRetriever` is a `RecallLeg`: it ranks, the hybrid (`jarvis/core/memory_hybrid.py`)
fuses and packs. A hybrid with this leg alone is the lexical-only mode
(embedding provider `none`): fully functional, no embedding, no network. The
store call is synchronous disk I/O, so it runs in a thread.

Contract page: `docs/memory.md` (Hybrid retrieval).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Protocol

from jarvis.domain.memory import (
    CapabilityState,
    CapabilityStatus,
    DegradedReason,
    MemoryFilters,
    MemoryStoreError,
    RecallQuery,
    capability_ok,
)
from jarvis.domain.memory_leg import (
    LEG_LEXICAL,
    LEG_TOP,
    LegDegraded,
    LegHit,
    LegResult,
    is_valid_at,
    matched_terms,
    provenance_ref,
)

_LOG = logging.getLogger("jarvis")

#: Ask the store for more than the leg needs: notes outside their validity
#: window are dropped after the ranked search and must not eat the slots.
_OVERFETCH = 3


class RankedStore(Protocol):
    """The slice of `MarkdownMemoryBackend` this leg uses."""

    def search_ranked(self, query: str, limit: int = ..., filters: MemoryFilters | None = ...) -> list: ...


class LexicalRetriever:
    name = LEG_LEXICAL

    def __init__(self, store: RankedStore) -> None:
        self._store = store
        self._last_error = ""

    async def hits(self, query: RecallQuery, limit: int = LEG_TOP, timeout_s: float = 0.15) -> LegResult:
        """BM25-ranked hits in `query`'s scopes, retention, level and validity window.

        `timeout_s` is enforced by the caller (the thread cannot be cancelled,
        but the caller stops waiting for it).
        """

        if not query.scopes:
            return LegResult()
        try:
            found = await asyncio.to_thread(self._search, query, limit)
        except MemoryStoreError as exc:
            self._last_error = exc.message
            _LOG.warning("memory lexical leg failed: %s", exc)
            raise LegDegraded(DegradedReason.STORE_UNAVAILABLE, exc.message) from exc
        self._last_error = ""
        return LegResult(tuple(found))

    def _search(self, query: RecallQuery, limit: int) -> list[LegHit]:
        filters = MemoryFilters(
            scopes=query.scopes, retentions=query.retentions, levels=query.levels,
            include_superseded=query.include_history,
        )
        ranked = self._store.search_ranked(query.text, limit * _OVERFETCH, filters)
        at = query.at or datetime.now(timezone.utc)
        found: list[LegHit] = []
        for hit in ranked:
            if not query.include_history and not is_valid_at(hit.valid_from, hit.valid_to, at):
                continue
            terms = matched_terms(query.text, hit.title, hit.snippet)
            found.append(LegHit(
                memory_id=hit.memory_id, revision=hit.revision, updated_at=hit.updated_at, title=hit.title,
                snippet=hit.snippet, level=hit.level, retention=hit.retention,
                provenance_ref=provenance_ref(hit.retention, hit.memory_id),
                why=("terms " + ", ".join(terms)) if terms else "text match",
            ))
            if len(found) >= limit:
                break
        return found

    def status(self) -> CapabilityState:
        if self._last_error:
            return CapabilityState(
                CapabilityStatus.UNAVAILABLE, "lexical_unavailable", f"lexical index failed: {self._last_error}"[:300],
            )
        return capability_ok()
