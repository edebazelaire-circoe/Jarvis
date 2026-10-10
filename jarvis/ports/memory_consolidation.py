"""Consolidation ports (memory handoff, Slice 01).

Pipeline: L0 evidence -> candidate extraction -> dedup -> conflict detection ->
scoring -> policy gate. A candidate is a proposal in `_candidates/`; only
`accept` commits a canonical note (with provenance). Protected classes are
never rewritten by any path. Default mode is manual (a human decides).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from jarvis.domain.memory import Candidate, CandidateDecision, Evidence


@dataclass(frozen=True, slots=True)
class RelatedNote:
    """A durable note shown to the extractor as DATA, so it can cite its id in `supersedes`.

    Already scope-filtered by the pipeline (never a private note in a shared context),
    never protected, never superseded. `snippet` is one clipped line.
    """

    id: str
    title: str
    snippet: str = ""


@runtime_checkable
class MemoryConsolidator(Protocol):
    async def propose(self, evidence: Sequence[Evidence]) -> tuple[Candidate, ...]:
        """Candidates for this evidence. Idempotent per evidence hash."""
        ...

    async def decide(self, candidate_id: str, decision: CandidateDecision, actor: str) -> Candidate:
        """Move a `proposed` candidate to its decided state. `memory_not_found` if unknown."""
        ...


@runtime_checkable
class CandidateExtractor(Protocol):
    """LLM-backed in production, a fake in tests. Its output is untrusted."""

    async def extract(
        self, evidence: Sequence[Evidence], related: Sequence[RelatedNote] = (),
    ) -> Sequence[Mapping[str, Any]]:
        """Raw proposals. The consolidator schema-validates each and drops malformed ones.

        `related` are existing notes (data, not instructions) whose ids a proposal may
        cite in `supersedes`; the consolidator still validates every cited id.
        """
        ...
