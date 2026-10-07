"""Pure fusion of ranked recall lists (memory handoff, Slice 03). No I/O, no clock.

`rrf_fuse` merges the lists of the legs (lexical, semantic, optional Tencent)
with reciprocal rank fusion: `score(id) = sum over legs of 1 / (k + rank)`,
equal weights, `k = 60`, the first `top = 20` hits of each leg. Then:

- dedup by `memory_id`, keeping the highest revision seen in any leg;
- superseded notes (judged on that highest revision) are dropped unless
  `include_history` (Memory Center); the legs filter temporal validity;
- ties break by `updated_at` descending, then `memory_id` ascending, so the
  order never depends on dict or thread timing.

`pack_items` then applies the count, per-item and total character budgets and
builds the `RecallItem`s (`why` and `rank_sources` on every item).

Contract page: `docs/memory.md` (Hybrid retrieval).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math

from jarvis.domain.memory import MAX_WHY_CHARS, RecallBudget, RecallItem
from jarvis.domain.memory_leg import LEG_TOP, RRF_K, LegHit, clip_text


@dataclass(frozen=True, slots=True)
class FusedHit:
    """A fused note: the representative hit (highest revision), its score and per-leg ranks."""

    hit: LegHit
    score: float
    rank_sources: Mapping[str, int]


def rrf_fuse(
    lists: Mapping[str, Sequence[LegHit]],
    k: int = RRF_K,
    *,
    top: int = LEG_TOP,
    include_history: bool = False,
) -> list[FusedHit]:
    """Fuse ranked lists, best first. `lists` maps a leg name to its hits (list order = rank).

    `include_history` keeps superseded notes (the legs already dropped the
    notes outside their validity window, which only they can see).
    """

    if k < 1 or top < 1:
        raise ValueError("k and top must be positive")
    legs = {name: tuple(hits[:top]) for name, hits in lists.items()}

    # Highest revision wins the representative slot; the first leg seen wins a tie.
    best: dict[str, LegHit] = {}
    for hits in legs.values():
        for hit in hits:
            current = best.get(hit.memory_id)
            if current is None or hit.revision > current.revision:
                best[hit.memory_id] = hit

    def kept(hit: LegHit) -> bool:
        if include_history:
            return True
        # The representative (highest revision) decides: a stale leg cannot resurrect a superseded note.
        return not best[hit.memory_id].superseded

    contributions: dict[str, list[float]] = {}
    ranks: dict[str, dict[str, int]] = {}
    for name, hits in legs.items():
        rank = 0
        seen: set[str] = set()
        for hit in hits:
            if hit.memory_id in seen or not kept(hit):
                continue
            seen.add(hit.memory_id)
            rank += 1
            contributions.setdefault(hit.memory_id, []).append(1.0 / (k + rank))
            ranks.setdefault(hit.memory_id, {})[name] = rank

    fused = [
        FusedHit(best[memory_id], math.fsum(parts), ranks[memory_id])
        for memory_id, parts in contributions.items()
    ]
    fused.sort(key=lambda item: (-item.score, -item.hit.updated_at.timestamp(), item.hit.memory_id))
    return fused


def _why(item: FusedHit, legs: Sequence[str]) -> str:
    parts = []
    for name in legs:
        rank = item.rank_sources.get(name)
        if rank is not None:
            parts.append(f"{name} #{rank}")
    text = ", ".join(parts)
    if item.hit.why:
        text = f"{text}: {item.hit.why}" if text else item.hit.why
    return clip_text(text, MAX_WHY_CHARS)


def pack_items(
    fused: Sequence[FusedHit], budget: RecallBudget, legs: Sequence[str] = (),
) -> tuple[RecallItem, ...]:
    """Apply the budgets in fused order and build the items.

    At most `max_items` items; each snippet is clipped to `max_item_chars`; the
    snippets together never exceed `max_total_chars` (the last one is clipped
    to what remains, then packing stops). `legs` fixes the order of the
    `why` text; it defaults to the legs found in `rank_sources`.
    """

    order = tuple(legs) or tuple(dict.fromkeys(name for item in fused for name in item.rank_sources))
    items: list[RecallItem] = []
    used = 0
    for item in fused:
        remaining = budget.max_total_chars - used
        if len(items) >= budget.max_items or remaining <= 0:
            break
        snippet = clip_text(item.hit.snippet, min(budget.max_item_chars, remaining))
        used += len(snippet)
        hit = item.hit
        items.append(RecallItem(
            memory_id=hit.memory_id, title=hit.title, snippet=snippet, score=item.score,
            rank_sources=item.rank_sources, level=hit.level, retention=hit.retention,
            provenance_ref=hit.provenance_ref, revision=hit.revision, why=_why(item, order),
        ))
    return tuple(items)

