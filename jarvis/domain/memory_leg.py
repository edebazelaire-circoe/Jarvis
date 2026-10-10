"""One ranked list of the hybrid retriever (memory handoff, Slice 03). Pure.

A *leg* (lexical, semantic, later the Tencent sidecar) ranks canonical notes
and hands `LegHit` lists to the fusion in `jarvis/core/memory_fusion.py`. This
module sits in `domain` so adapters (which produce hits) and core (which fuses
them) share the types without core importing an adapter.

Contract page: `docs/memory.md` (Hybrid retrieval).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata

from jarvis.domain.memory import DegradedReason, MemoryLevel, RetentionClass

#: Reciprocal-rank-fusion constant (architecture 2.4).
RRF_K = 60
#: Items each leg contributes to the fusion.
LEG_TOP = 20

#: Leg names the hybrid knows, and the reasons each one reports.
LEG_LEXICAL = "lexical"
LEG_SEMANTIC = "semantic"
LEG_TENCENT = "tencent"


@dataclass(frozen=True, slots=True)
class LegHit:
    """A note as one leg ranks it. The list order IS the rank (best first).

    `snippet` is canonical text (a leg never supplies text of its own).
    `superseded` is the leg's view of the note; the fusion re-checks it on the
    highest revision it sees.
    """

    memory_id: str
    revision: int
    updated_at: datetime
    title: str
    snippet: str
    level: MemoryLevel
    retention: RetentionClass
    provenance_ref: str
    superseded: bool = False
    why: str = ""


@dataclass(frozen=True, slots=True)
class LegResult:
    """What a leg returns: its hits, plus a reason when it only partly answered."""

    hits: tuple[LegHit, ...] = ()
    degraded: DegradedReason | None = None


class LegDegraded(Exception):
    """A leg could not answer at all. Never reaches the caller of `recall`."""

    def __init__(self, reason: DegradedReason, message: str = "") -> None:
        super().__init__(message or reason.value)
        self.reason = reason


def provenance_ref(retention: RetentionClass, memory_id: str) -> str:
    """Stable, human-readable address of a recalled note (`<class>/<id>`)."""

    return f"{retention.value}/{memory_id}"


def is_valid_at(valid_from: datetime | None, valid_to: datetime | None, at: datetime) -> bool:
    """Temporal validity: `valid_from <= at < valid_to`; a missing bound is open."""

    if valid_from is not None and at < valid_from:
        return False
    return valid_to is None or at < valid_to


def fold(text: str) -> str:
    """Lower-case and strip diacritics, as the FTS5 `remove_diacritics` tokenizer does."""

    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def matched_terms(query: str, *texts: str, limit: int = 6) -> tuple[str, ...]:
    """Query words found in `texts` (folded, in query order, distinct): the "why" of a lexical hit."""

    haystack = set(_WORD.findall(fold(" ".join(texts))))
    found: dict[str, None] = {}
    for word in _WORD.findall(fold(query)):
        if word in haystack:
            found[word] = None
    return tuple(found)[:limit]


def clip_text(text: str, limit: int) -> str:
    """At most `limit` characters; a clipped text ends with an ellipsis inside the limit."""

    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"

