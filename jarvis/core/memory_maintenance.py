from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import logging
from pathlib import Path
from typing import Protocol

from jarvis.domain.memory import (
    MAX_EVIDENCE_CHARS,
    Evidence,
    MemoryFilters,
    MemoryNote,
    Provenance,
    RetentionClass,
    SourceType,
)

_LOG = logging.getLogger("jarvis")

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


#: Newest short-term notes offered to the consolidation pipeline per run.
MAX_EVIDENCE_NOTES = 100


class EvidenceSource(Protocol):
    """What the pipeline half of the worker needs from the store: a listing."""

    def list(self, filters: MemoryFilters) -> Sequence[MemoryNote]: ...


class Consolidator(Protocol):
    """`ConsolidationPipeline.run` (`jarvis/core/memory_consolidation.py`), as the worker uses it."""

    async def run(self, evidence: Sequence[Evidence]): ...


def short_term_evidence(store: EvidenceSource, limit: int = MAX_EVIDENCE_NOTES) -> list[Evidence]:
    """L0 evidence of a run: the newest short-term notes, each cited by its own id."""

    evidence = []
    for note in store.list(MemoryFilters(retentions=(RetentionClass.SHORT_TERM,), limit=limit)):
        text = f"{note.title}\n{note.body}".strip()[:MAX_EVIDENCE_CHARS]
        if not text:
            continue
        evidence.append(Evidence(text, Provenance(SourceType.NOTE, note.id, note.updated_at), note.scope))
    return evidence


class MemoryMaintenanceWorker:
    """Daily memory maintenance: the retain rule, then (optionally) the consolidation pipeline.

    Two policy steps, in this order, both leaving provenance:

    1. **retain rule** (`jarvis:retain` marker): an explicit human marker promotes a
       short-term note to long-term. It is one policy rule, not the whole policy.
    2. **consolidation** (when a `consolidator` is wired): short-term notes become
       evidence, the pipeline proposes candidates and, in `auto` mode only, commits
       the ones its gate allows. A pipeline failure is logged and reported in the
       result; it never undoes or blocks step 1.

    Protected classes are never auto-deleted.

    Promotion (an explicit `jarvis:retain` marker) goes through the canonical
    store: the copy is a new note with provenance (`sources` ends with the
    source note) and reaches the derived index at once (handoff
    jarvis-memory-intelligence-knowledge, Slice 02, R3).
    """

    def __init__(
        self,
        root: Path,
        store: PromotingStore,
        consolidator: Consolidator | None = None,
        evidence: Callable[[], Sequence[Evidence]] | None = None,
    ) -> None:
        self.paths = ensure_memory_layout(root)
        self.store = store
        self.consolidator = consolidator
        self._evidence = evidence or (lambda: short_term_evidence(store))  # type: ignore[arg-type]

    async def execute(self, job) -> dict[str, object]:
        del job
        result = await asyncio.to_thread(self._promote_retained)
        if self.consolidator is not None:
            result["consolidation"] = await self._consolidate()
        return result

    async def _consolidate(self) -> dict[str, object]:
        try:
            evidence = await asyncio.to_thread(self._evidence)
            report = await self.consolidator.run(evidence)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - maintenance boundary: the pipeline's failure is reported, never raised
            _LOG.warning("memory consolidation failed: %s: %s", type(exc).__name__, exc)
            return {"error": type(exc).__name__}
        return report.to_payload()

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
