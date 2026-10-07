"""Candidate store port (memory handoff, Slice 04).

Candidates are proposals, never recalled, never auto-deleted. The adapter
(`jarvis.adapters.memory_candidates`) keeps them as human-readable Markdown
files under `<memory>/_candidates/`: no table, no migration. Synchronous on
purpose (blocking disk I/O, called from Core through a thread), like
`CanonicalMemoryStore`.

Besides the candidates the store keeps two kinds of bookkeeping the pipeline
needs to be idempotent and crash-safe:

- a **run marker** per evidence hash (this evidence was processed, here is what
  it produced), so a re-run neither re-extracts nor duplicates;
- a **decision intent** per candidate (actor and decision written before the
  canonical commit), so a crash between the commit and the candidate update is
  completed by `recover` with the original actor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from jarvis.domain.memory import Candidate, CandidateDecision, CandidateState


@dataclass(frozen=True, slots=True)
class DecisionIntent:
    """A decision announced before its canonical commit (crash recovery)."""

    candidate_id: str
    decision: CandidateDecision
    actor: str
    at: datetime


@runtime_checkable
class CandidateStore(Protocol):
    def save(self, candidate: Candidate) -> Candidate:
        """Create or atomically replace the file of `candidate`; returns it as stored."""
        ...

    def get(self, candidate_id: str) -> Candidate:
        """`memory_not_found` when the id is unknown (or its file is unreadable)."""
        ...

    def list(self, state: CandidateState | None = None, limit: int = 500) -> Sequence[Candidate]:
        """Candidates in `state` (all when `None`), oldest `created_at` first, ties by id.

        A file that cannot be read as a candidate is skipped, never raised.
        """
        ...

    def mark_run(self, evidence_hash: str, candidate_ids: Sequence[str]) -> None:
        """Record that this evidence was processed and produced these candidates."""
        ...

    def run_candidates(self, evidence_hash: str) -> tuple[str, ...] | None:
        """Candidate ids of a processed evidence hash; `None` when it was never processed."""
        ...

    def begin_decision(self, intent: DecisionIntent) -> None: ...

    def end_decision(self, candidate_id: str) -> None: ...

    def pending_decisions(self) -> Sequence[DecisionIntent]: ...
