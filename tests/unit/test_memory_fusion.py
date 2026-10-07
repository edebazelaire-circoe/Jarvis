"""Pure fusion and hybrid orchestration (handoff jarvis-memory-intelligence-knowledge, Slice 03).

`rrf_fuse` / `pack_items` (deterministic, no I/O) and `HybridRetriever` with
stub legs (timeouts, failures, parallelism, scope policy, status).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import math
import time

import pytest

from jarvis.core.memory_fusion import FusedHit, pack_items, rrf_fuse
from jarvis.core.memory_hybrid import HybridRetriever
from jarvis.domain.memory import (
    CapabilityState,
    CapabilityStatus,
    DegradedReason,
    MemoryErrorCode,
    MemoryLevel,
    MemoryStoreError,
    RecallBudget,
    RecallQuery,
    RetentionClass,
    capability_ok,
)
from jarvis.domain.memory_leg import LegDegraded, LegHit, LegResult
from jarvis.domain.memory_policy import AgentMemoryPolicy

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
K = 60


def hit(memory_id: str, *, revision: int = 1, age: int = 0, snippet: str = "", superseded: bool = False,
        why: str = "") -> LegHit:
    return LegHit(
        memory_id=memory_id, revision=revision, updated_at=T0 - timedelta(minutes=age), title=f"title {memory_id}",
        snippet=snippet or f"snippet {memory_id}", level=MemoryLevel.L1, retention=RetentionClass.LONG_TERM,
        provenance_ref=f"long_term_memory/{memory_id}", superseded=superseded, why=why,
    )


def ids(fused: list[FusedHit]) -> list[str]:
    return [item.hit.memory_id for item in fused]


# ------------------------------------------------------------------------- rrf_fuse
def test_rrf_scores_are_exact_reciprocal_ranks():
    fused = rrf_fuse({"lexical": [hit("a"), hit("b"), hit("c")], "semantic": [hit("b"), hit("d"), hit("a")]})

    scores = {item.hit.memory_id: item.score for item in fused}
    assert scores["a"] == pytest.approx(1 / (K + 1) + 1 / (K + 3), abs=1e-15)
    assert scores["b"] == pytest.approx(1 / (K + 2) + 1 / (K + 1), abs=1e-15)
    assert scores["c"] == pytest.approx(1 / (K + 3), abs=1e-15)
    assert scores["d"] == pytest.approx(1 / (K + 2), abs=1e-15)
    assert ids(fused) == ["b", "a", "d", "c"]


def test_rrf_rank_sources_record_each_leg_rank():
    fused = rrf_fuse({"lexical": [hit("a"), hit("b")], "semantic": [hit("b")]})

    by_id = {item.hit.memory_id: dict(item.rank_sources) for item in fused}
    assert by_id == {"a": {"lexical": 1}, "b": {"lexical": 2, "semantic": 1}}


def test_rrf_uses_k_as_given():
    fused = rrf_fuse({"lexical": [hit("a")]}, k=10)

    assert fused[0].score == pytest.approx(1 / 11, abs=1e-15)
    with pytest.raises(ValueError):
        rrf_fuse({"lexical": [hit("a")]}, k=0)


def test_rrf_only_the_top_of_each_leg_counts():
    lexical = [hit(f"n{i:02d}") for i in range(30)]

    fused = rrf_fuse({"lexical": lexical}, top=20)

    assert ids(fused) == [f"n{i:02d}" for i in range(20)]


def test_rrf_ties_break_by_updated_at_descending_then_memory_id():
    # Rank 1 of each leg: identical scores, so only the tie-break orders them.
    fused = rrf_fuse({
        "lexical": [hit("zeta", age=5)],
        "semantic": [hit("alpha", age=5)],
        "tencent": [hit("mid", age=1)],
    })

    assert [item.score for item in fused] == [fused[0].score] * 3
    assert ids(fused) == ["mid", "alpha", "zeta"]  # newest first, then id ascending


def test_rrf_order_does_not_depend_on_the_leg_order():
    legs = {
        "lexical": [hit("a", age=3), hit("b", age=2), hit("c", age=1)],
        "semantic": [hit("c", age=1), hit("a", age=3), hit("d", age=9)],
        "tencent": [hit("d", age=9), hit("b", age=2)],
    }
    reference = [(item.hit.memory_id, item.score) for item in rrf_fuse(legs)]

    for names in ([*legs], [*reversed(legs)], ["semantic", "tencent", "lexical"]):
        reordered = {name: legs[name] for name in names}
        assert [(item.hit.memory_id, item.score) for item in rrf_fuse(reordered)] == reference


def test_rrf_sum_is_exact_whatever_the_summation_order():
    # Three terms: a naive left-to-right float sum differs by leg order; fsum does not.
    legs = {"a": [hit("x"), hit("y")], "b": [hit("y"), hit("x")], "c": [hit("x"), hit("y")]}
    fused = rrf_fuse(legs)

    assert fused[0].score == math.fsum([1 / 61, 1 / 62, 1 / 61])


def test_rrf_dedups_by_memory_id_keeping_the_highest_revision():
    fused = rrf_fuse({
        "lexical": [hit("a", revision=2, snippet="new text")],
        "semantic": [hit("a", revision=1, snippet="stale text"), hit("b")],
    })

    assert ids(fused) == ["a", "b"]
    assert fused[0].hit.revision == 2
    assert fused[0].hit.snippet == "new text"
    assert dict(fused[0].rank_sources) == {"lexical": 1, "semantic": 1}


def test_rrf_highest_revision_wins_whichever_leg_holds_it():
    fused = rrf_fuse({
        "lexical": [hit("a", revision=1, snippet="stale")],
        "semantic": [hit("a", revision=3, snippet="fresh")],
    })

    assert (fused[0].hit.revision, fused[0].hit.snippet) == (3, "fresh")


def test_rrf_a_duplicate_inside_one_leg_counts_its_first_rank_once():
    fused = rrf_fuse({"lexical": [hit("a"), hit("a", revision=2), hit("b")]})

    assert ids(fused) == ["a", "b"]
    assert fused[0].score == pytest.approx(1 / 61, abs=1e-15)
    assert fused[1].score == pytest.approx(1 / 62, abs=1e-15)


def test_rrf_excludes_superseded_by_default():
    fused = rrf_fuse({"lexical": [hit("old", superseded=True), hit("new")], "semantic": [hit("old", superseded=True)]})

    assert ids(fused) == ["new"]
    assert dict(fused[0].rank_sources) == {"lexical": 1}  # ranks are taken after the exclusion


def test_rrf_include_history_keeps_superseded():
    fused = rrf_fuse({"lexical": [hit("old", superseded=True), hit("new")]}, include_history=True)

    assert ids(fused) == ["old", "new"]


def test_rrf_a_stale_leg_cannot_resurrect_a_superseded_note():
    # Lexical knows the note is superseded at revision 2; the semantic row is still revision 1, live.
    fused = rrf_fuse({
        "lexical": [hit("a", revision=2, superseded=True)],
        "semantic": [hit("a", revision=1, superseded=False)],
    })

    assert fused == []


def test_rrf_empty_input():
    assert rrf_fuse({}) == []
    assert rrf_fuse({"lexical": []}) == []


# ----------------------------------------------------------------------- pack_items
def fused_of(*items: LegHit) -> list[FusedHit]:
    return rrf_fuse({"lexical": list(items)}, include_history=True)


def test_pack_stops_at_max_items():
    fused = fused_of(*(hit(f"n{i}") for i in range(10)))

    packed = pack_items(fused, RecallBudget(max_items=3), ("lexical",))

    assert [item.memory_id for item in packed] == ["n0", "n1", "n2"]


def test_pack_clips_each_snippet_to_max_item_chars():
    fused = fused_of(hit("a", snippet="x" * 100), hit("b", snippet="short"))

    packed = pack_items(fused, RecallBudget(max_item_chars=10), ("lexical",))

    assert packed[0].snippet == "x" * 9 + "…"
    assert len(packed[0].snippet) == 10
    assert packed[1].snippet == "short"


def test_pack_total_chars_clip_the_last_item_then_stop():
    fused = fused_of(hit("a", snippet="a" * 30), hit("b", snippet="b" * 30), hit("c", snippet="c" * 30))

    packed = pack_items(fused, RecallBudget(max_item_chars=30, max_total_chars=50), ("lexical",))

    assert [item.memory_id for item in packed] == ["a", "b"]
    assert len(packed[0].snippet) == 30
    assert len(packed[1].snippet) == 20  # what remained of 50
    assert sum(len(item.snippet) for item in packed) == 50


def test_pack_total_chars_exactly_spent_stops_without_an_empty_item():
    fused = fused_of(hit("a", snippet="a" * 10), hit("b", snippet="b" * 10))

    packed = pack_items(fused, RecallBudget(max_item_chars=10, max_total_chars=10), ("lexical",))

    assert [item.memory_id for item in packed] == ["a"]


def test_pack_default_budget_is_six_items_400_chars_3000_total():
    fused = fused_of(*(hit(f"n{i:02d}", snippet="z" * 900) for i in range(10)))

    packed = pack_items(fused, RecallBudget(), ("lexical",))

    assert len(packed) == 6
    assert all(len(item.snippet) == 400 for item in packed)
    assert sum(len(item.snippet) for item in packed) <= 3_000


def test_pack_items_carry_why_rank_sources_provenance_and_revision():
    fused = rrf_fuse({
        "lexical": [hit("a", revision=4, why="terms atlas")],
        "semantic": [hit("a", revision=4, why="cosine 0.81")],
    })

    item = pack_items(fused, RecallBudget(), ("lexical", "semantic"))[0]

    assert item.why == "lexical #1, semantic #1: terms atlas"
    assert dict(item.rank_sources) == {"lexical": 1, "semantic": 1}
    assert (item.revision, item.provenance_ref) == (4, "long_term_memory/a")
    assert item.score == pytest.approx(2 / 61, abs=1e-15)


def test_pack_why_is_bounded():
    fused = rrf_fuse({"lexical": [hit("a", why="w" * 500)]})

    assert len(pack_items(fused, RecallBudget(), ("lexical",))[0].why) <= 200


# ------------------------------------------------------------------- hybrid, stub legs
class StubLeg:
    def __init__(self, name: str, hits=(), *, delay: float = 0.0, error: BaseException | None = None,
                 degraded: DegradedReason | None = None, state: CapabilityState | None = None) -> None:
        self.name = name
        self._hits = tuple(hits)
        self._delay = delay
        self._error = error
        self._degraded = degraded
        self._state = state or capability_ok()
        self.queries: list[RecallQuery] = []
        self.limits: list[int] = []

    async def hits(self, query, limit, timeout_s):
        self.queries.append(query)
        self.limits.append(limit)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return LegResult(self._hits, self._degraded)

    def status(self):
        return self._state


def query(*scopes: str, **over) -> RecallQuery:
    return RecallQuery(text="atlas budget", scopes=scopes or ("private",), **over)


async def test_hybrid_fuses_the_legs_and_reports_timings():
    lexical = StubLeg("lexical", [hit("a", why="terms atlas"), hit("b")])
    semantic = StubLeg("semantic", [hit("b", why="cosine 0.9"), hit("c")])

    result = await HybridRetriever([lexical, semantic]).recall(query(), RecallBudget())

    assert [item.memory_id for item in result.items] == ["b", "a", "c"]
    assert result.degraded == ()
    assert {"lexical", "semantic", "fusion", "total"} <= set(result.timings_ms)
    assert lexical.limits == [20]


async def test_hybrid_needs_the_lexical_leg_and_known_distinct_legs():
    with pytest.raises(ValueError):
        HybridRetriever([StubLeg("semantic")])
    with pytest.raises(ValueError):
        HybridRetriever([StubLeg("lexical"), StubLeg("lexical")])
    with pytest.raises(ValueError):
        HybridRetriever([StubLeg("lexical"), StubLeg("other")])


async def test_hybrid_lexical_only_is_fully_functional():
    result = await HybridRetriever([StubLeg("lexical", [hit("a"), hit("b")])]).recall(query(), RecallBudget())

    assert [item.memory_id for item in result.items] == ["a", "b"]
    assert result.degraded == ()
    assert set(result.timings_ms) == {"lexical", "fusion", "total"}


async def test_hybrid_legs_run_in_parallel():
    legs = [StubLeg("lexical", [hit("a")], delay=0.1), StubLeg("semantic", [hit("b")], delay=0.1),
            StubLeg("tencent", [hit("c")], delay=0.1)]
    started = time.perf_counter()

    result = await HybridRetriever(legs).recall(query(), RecallBudget(timeout_ms=1_000, semantic_timeout_ms=500,
                                                                      tencent_timeout_ms=500, lexical_timeout_ms=500))

    assert time.perf_counter() - started < 0.25  # sequential would be 0.3 s
    assert {item.memory_id for item in result.items} == {"a", "b", "c"}


async def test_hybrid_slow_semantic_leg_times_out_and_lexical_survives():
    legs = [StubLeg("lexical", [hit("a")]), StubLeg("semantic", [hit("b")], delay=1.0)]
    started = time.perf_counter()

    result = await HybridRetriever(legs).recall(query(), RecallBudget(semantic_timeout_ms=50))

    assert time.perf_counter() - started < 0.4
    assert [item.memory_id for item in result.items] == ["a"]
    assert result.degraded == (DegradedReason.SEMANTIC_TIMEOUT,)


async def test_hybrid_slow_lexical_leg_times_out_and_semantic_survives():
    legs = [StubLeg("lexical", [hit("a")], delay=1.0), StubLeg("semantic", [hit("b")])]

    result = await HybridRetriever(legs).recall(query(), RecallBudget(lexical_timeout_ms=50))

    assert [item.memory_id for item in result.items] == ["b"]
    assert result.degraded == (DegradedReason.LEXICAL_TIMEOUT,)


async def test_hybrid_overall_budget_cuts_every_leg_still_running():
    legs = [StubLeg("lexical", [hit("a")]), StubLeg("semantic", [hit("b")], delay=2.0)]
    started = time.perf_counter()

    result = await HybridRetriever(legs).recall(
        query(), RecallBudget(timeout_ms=150, lexical_timeout_ms=1_000, semantic_timeout_ms=1_000),
    )

    assert time.perf_counter() - started < 0.5
    assert [item.memory_id for item in result.items] == ["a"]
    assert result.degraded == (DegradedReason.RECALL_TIMEOUT,)


async def test_hybrid_failing_leg_degrades_and_the_others_answer():
    legs = [StubLeg("lexical", [hit("a")]), StubLeg("semantic", error=RuntimeError("boom"))]

    result = await HybridRetriever(legs).recall(query(), RecallBudget())

    assert [item.memory_id for item in result.items] == ["a"]
    assert result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)


async def test_hybrid_leg_degraded_reason_is_passed_through():
    legs = [StubLeg("lexical", [hit("a")]),
            StubLeg("semantic", error=LegDegraded(DegradedReason.SEMANTIC_CAPACITY)),
            StubLeg("tencent", error=LegDegraded(DegradedReason.TENCENT_UNAVAILABLE))]

    result = await HybridRetriever(legs).recall(query(), RecallBudget())

    assert [item.memory_id for item in result.items] == ["a"]
    assert result.degraded == (DegradedReason.SEMANTIC_CAPACITY, DegradedReason.TENCENT_UNAVAILABLE)


async def test_hybrid_partial_leg_keeps_its_hits_and_reports_the_reason():
    legs = [StubLeg("lexical", [hit("a")]),
            StubLeg("semantic", [hit("b")], degraded=DegradedReason.SEMANTIC_UNAVAILABLE)]

    result = await HybridRetriever(legs).recall(query(), RecallBudget())

    assert {item.memory_id for item in result.items} == {"a", "b"}
    assert result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)


async def test_hybrid_raises_only_when_no_leg_could_answer():
    store_down = LegDegraded(DegradedReason.STORE_UNAVAILABLE)
    with pytest.raises(MemoryStoreError) as excinfo:
        await HybridRetriever([StubLeg("lexical", error=store_down)]).recall(query(), RecallBudget())
    assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE

    # A timeout is not "nothing can answer": the recall returns, empty and degraded.
    slow = StubLeg("lexical", delay=1.0)
    result = await HybridRetriever([slow]).recall(query(), RecallBudget(lexical_timeout_ms=30))
    assert result.items == () and result.degraded == (DegradedReason.LEXICAL_TIMEOUT,)

    # Lexical down but semantic answers: degraded, not raised.
    both = [StubLeg("lexical", error=store_down), StubLeg("semantic", [hit("s")])]
    result = await HybridRetriever(both).recall(query(), RecallBudget())
    assert [item.memory_id for item in result.items] == ["s"]
    assert result.degraded == (DegradedReason.STORE_UNAVAILABLE,)


async def test_hybrid_no_scope_means_no_recall_and_no_leg_call():
    lexical = StubLeg("lexical", [hit("a")])

    result = await HybridRetriever([lexical]).recall(RecallQuery(text="x", scopes=()), RecallBudget())

    assert result.items == () and lexical.queries == []


async def test_hybrid_policy_narrows_the_scopes_before_any_leg_sees_them():
    lexical = StubLeg("lexical", [hit("a")])
    policy = AgentMemoryPolicy("helper", read_scopes=("shared", "board:alpha"))

    await HybridRetriever([lexical], policy=policy).recall(
        RecallQuery(text="x", scopes=("private", "shared", "project:p1")), RecallBudget(),
    )

    assert lexical.queries[0].scopes == ("shared",)


async def test_hybrid_policy_without_a_readable_scope_recalls_nothing():
    lexical = StubLeg("lexical", [hit("a")])
    policy = AgentMemoryPolicy("helper", read_scopes=("shared",))

    result = await HybridRetriever([lexical], policy=policy).recall(RecallQuery(text="x", scopes=("private",)), RecallBudget())

    assert result.items == () and lexical.queries == []


async def test_hybrid_superseded_hits_are_excluded_unless_include_history():
    legs = [StubLeg("lexical", [hit("old", superseded=True), hit("new")])]

    default = await HybridRetriever(legs).recall(query(), RecallBudget())
    history = await HybridRetriever(legs).recall(query(include_history=True), RecallBudget())

    assert [item.memory_id for item in default.items] == ["new"]
    assert [item.memory_id for item in history.items] == ["old", "new"]


async def test_hybrid_applies_the_item_and_char_budgets():
    legs = [StubLeg("lexical", [hit(f"n{i}", snippet="s" * 500) for i in range(9)])]

    result = await HybridRetriever(legs).recall(query(), RecallBudget(max_items=4, max_item_chars=100, max_total_chars=250))

    assert [len(item.snippet) for item in result.items] == [100, 100, 50]


async def test_hybrid_status_reflects_the_legs():
    ok = StubLeg("lexical")
    assert HybridRetriever([ok]).status().is_ok

    degraded = CapabilityState(CapabilityStatus.DEGRADED, "semantic_capacity", "too many chunks")
    state = HybridRetriever([ok, StubLeg("semantic", state=degraded)]).status()
    assert (state.status, state.reason_code) == (CapabilityStatus.DEGRADED, "semantic_capacity")

    down = CapabilityState(CapabilityStatus.UNAVAILABLE, "lexical_unavailable", "index failed")
    assert HybridRetriever([StubLeg("lexical", state=down), StubLeg("semantic", state=degraded)]).status() == down

    disabled = CapabilityState(CapabilityStatus.DISABLED, "semantic_off", "off")
    assert HybridRetriever([ok, StubLeg("semantic", state=disabled)]).status().is_ok
