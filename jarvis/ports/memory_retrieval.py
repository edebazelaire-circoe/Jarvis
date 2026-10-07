"""Retrieval ports (memory handoff, Slice 01): recall and embeddings.

A retriever ranks; it never owns a write and never invents text: every item
references a canonical `memory_id`, and the snippet is read from canonical.
Local lexical, local semantic, hybrid and the optional Tencent adapter all
implement the same `MemoryRetriever`.

Degraded semantics: a leg that times out or fails does NOT raise. `recall`
returns the items of the legs that finished and lists the reasons in
`RecallResult.degraded`. It raises `MemoryStoreError` only when nothing can
answer (`memory_unavailable`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jarvis.domain.memory import CapabilityState, RecallBudget, RecallQuery, RecallResult


@runtime_checkable
class MemoryRetriever(Protocol):
    async def recall(self, query: RecallQuery, budget: RecallBudget) -> RecallResult: ...

    def status(self) -> CapabilityState: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Text to vectors. Default provider is `none` (no instance); `FakeEmbedder` is for tests."""

    @property
    def model_id(self) -> str:
        """Identity of the model: a change invalidates stored vectors."""
        ...

    @property
    def dim(self) -> int: ...

    async def embed(self, texts: Sequence[str], timeout: float) -> list[list[float]]:
        """One vector of `dim` floats per text, within `timeout` seconds.

        Failure or timeout raises `MemoryStoreError(memory_unavailable)`; the caller
        turns it into a `degraded` reason, never into a failed recall.
        """
        ...
