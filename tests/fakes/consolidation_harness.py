"""Wiring helpers for the consolidation tests (memory handoff, Slice 04).

A real `MarkdownMemoryBackend` and `FileCandidateStore` on a temp directory, a
`FakeExtractor`, a deterministic clock, and the diagnostics the pipeline emitted.
Nothing here touches the real data root or the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.memory_candidates import FileCandidateStore
from jarvis.adapters.memory_lexical import LexicalRetriever
from jarvis.core.memory_consolidation import ConsolidationPipeline
from jarvis.core.memory_hybrid import HybridRetriever
from jarvis.domain.memory import (
    Evidence,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    Provenance,
    RetentionClass,
    SourceType,
    new_memory_id,
)
from jarvis.domain.memory_settings import ConsolidationMode, ConsolidationSettings
from tests.fakes.fake_extractor import FakeExtractor

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
AUTO = ConsolidationSettings(mode=ConsolidationMode.AUTO)
MANUAL = ConsolidationSettings()


class Clock:
    """Strictly increasing clock: every call is one minute after the previous one."""

    def __init__(self, start: datetime = T0 + timedelta(days=30)) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def evidence(text: str, ref: str = "turn-1", *, scope: str = "private", at: datetime = T0, kind: SourceType = SourceType.TURN) -> Evidence:
    return Evidence(text, Provenance(kind, ref, at), scope)


def make_note(**over: Any) -> MemoryNote:
    base: dict[str, Any] = dict(
        id=new_memory_id(), title="Existing note", body="", level=MemoryLevel.L1, kind=MemoryKind.FACT,
        retention=RetentionClass.LONG_TERM, scope="private", created_at=T0, updated_at=T0,
    )
    return MemoryNote(**{**base, **over})


@dataclass
class Harness:
    root: Path
    store: MarkdownMemoryBackend
    cands: FileCandidateStore
    extractor: FakeExtractor
    pipeline: ConsolidationPipeline
    clock: Clock
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def event_names(self) -> list[str]:
        return [name for name, _ in self.events]

    def notes(self, **filters: Any) -> tuple[MemoryNote, ...]:
        from jarvis.domain.memory import MemoryFilters
        return self.store.list(MemoryFilters(limit=500, **filters))


#: Sentinel: wire the real lexical-only hybrid retriever (what `auto` needs). Pass `retriever=None` for none.
DEFAULT = object()


def build(root: Path, script: Any = (), settings: ConsolidationSettings = MANUAL, **kwargs: Any) -> Harness:
    store = MarkdownMemoryBackend(root)
    if kwargs.get("retriever", DEFAULT) is DEFAULT:
        kwargs["retriever"] = HybridRetriever([LexicalRetriever(store)])
    cands = FileCandidateStore(root)
    extractor = FakeExtractor(script)
    clock = Clock()
    events: list[tuple[str, dict[str, Any]]] = []
    pipeline = ConsolidationPipeline(
        store=store, candidates=cands, extractor=extractor, settings=settings, clock=clock,
        sink=lambda name, data: events.append((name, dict(data))), **kwargs,
    )
    return Harness(root, store, cands, extractor, pipeline, clock, events)
