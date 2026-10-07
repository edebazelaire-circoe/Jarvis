"""Scripted `CandidateExtractor` and `TextModel` for tests (memory handoff, Slice 04).

No model, no network. `FakeExtractor` answers whatever it was scripted with, so a
test controls exactly what the "LLM" proposes (including hostile output). It
never reads the evidence text to decide: a prompt injection inside the evidence
cannot change what it returns, which is what the policy tests rely on.

`script` is one of: a sequence of proposals (returned on every call), a callable
`(evidence) -> proposals`, or an exception instance (raised on every call).
`calls` records every evidence batch seen.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from jarvis.domain.memory import Evidence
from jarvis.ports.memory_consolidation import RelatedNote


class FakeExtractor:
    def __init__(self, script: Sequence[Any] | Callable[[Sequence[Evidence]], Any] | BaseException = (), *, delay: float = 0.0) -> None:
        self.script = script
        self.delay = delay
        self.calls: list[tuple[Evidence, ...]] = []
        self.related: list[tuple[RelatedNote, ...]] = []

    async def extract(self, evidence: Sequence[Evidence], related: Sequence[RelatedNote] = ()) -> Sequence[Mapping[str, Any]]:
        self.calls.append(tuple(evidence))
        self.related.append(tuple(related))
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.script, BaseException):
            raise self.script
        if callable(self.script):
            return self.script(evidence)
        return self.script


class FakeTextModel:
    """`TextModel` returning a fixed answer (or raising it); records the prompts it received."""

    def __init__(self, answer: str | BaseException) -> None:
        self.answer = answer
        self.prompts: list[tuple[str, str]] = []

    async def complete(self, system: str, prompt: str, *, timeout_s: float) -> str:
        self.prompts.append((system, prompt))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def proposal(title: str, body: str = "", **extra: Any) -> dict[str, Any]:
    """A valid proposal (kind fact, long_term_memory, confidence 0.9 unless overridden)."""

    return {"title": title, "body": body, "kind": "fact", "retention": "long_term_memory", "confidence": 0.9, **extra}
