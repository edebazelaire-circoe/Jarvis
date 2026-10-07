"""Hybrid retriever: parallel legs, per-leg and overall time budgets, fusion (Slice 03).

`HybridRetriever` is the `MemoryRetriever` Core talks to. It runs its legs
(lexical, optional semantic, optional Tencent slot) concurrently, each under
its own budget (`RecallBudget.lexical_timeout_ms` 150, `semantic_timeout_ms`
250 including the query embedding, `tencent_timeout_ms` 250) and under the
overall wall clock (`timeout_ms`, 400 hard). A leg that times out, fails or
only partly answers never breaks the recall: the legs that finished are fused
and `RecallResult.degraded` says why. With the lexical leg alone this is the
lexical-only mode (embedding provider `none`).

Scope is deny-by-default: with an `AgentMemoryPolicy` the requested scopes are
narrowed to what the agent may read; no scope, no recall.

`MemoryStoreError(memory_unavailable)` is raised only when no leg could answer
(every leg failed outright, none merely timed out).

Contract page: `docs/memory.md` (Hybrid retrieval).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
import logging
import time

from jarvis.core.memory_fusion import pack_items, rrf_fuse
from jarvis.domain.memory import (
    CapabilityState,
    CapabilityStatus,
    DegradedReason,
    MemoryErrorCode,
    MemoryStoreError,
    RecallBudget,
    RecallQuery,
    RecallResult,
    capability_ok,
)
from jarvis.domain.memory_leg import (
    LEG_LEXICAL,
    LEG_SEMANTIC,
    LEG_TENCENT,
    LEG_TOP,
    LegDegraded,
    LegResult,
)
from jarvis.domain.memory_policy import AgentMemoryPolicy
from jarvis.ports.memory_retrieval import RecallLeg

_LOG = logging.getLogger("jarvis")


@dataclass(frozen=True, slots=True)
class _LegRules:
    """Which budget a leg runs under and which reasons it reports."""

    timeout_field: str
    timeout_reason: DegradedReason
    failure_reason: DegradedReason


_RULES = {
    LEG_LEXICAL: _LegRules("lexical_timeout_ms", DegradedReason.LEXICAL_TIMEOUT, DegradedReason.STORE_UNAVAILABLE),
    LEG_SEMANTIC: _LegRules("semantic_timeout_ms", DegradedReason.SEMANTIC_TIMEOUT, DegradedReason.SEMANTIC_UNAVAILABLE),
    LEG_TENCENT: _LegRules("tencent_timeout_ms", DegradedReason.TENCENT_TIMEOUT, DegradedReason.TENCENT_UNAVAILABLE),
}

# Outcome of one leg.
_OK, _TIMEOUT, _DEGRADED, _ERROR = "ok", "timeout", "degraded", "error"


@dataclass(slots=True)
class _LegRun:
    result: LegResult
    outcome: str
    reason: DegradedReason | None
    elapsed_ms: float


class HybridRetriever:
    def __init__(self, legs: Sequence[RecallLeg], *, policy: AgentMemoryPolicy | None = None) -> None:
        legs = tuple(legs)
        names = [leg.name for leg in legs]
        if LEG_LEXICAL not in names:
            raise ValueError("a hybrid retriever needs the lexical leg: it is the deterministic fallback")
        unknown = sorted(set(names) - set(_RULES))
        if unknown or len(set(names)) != len(names):
            raise ValueError(f"legs must be distinct names among {sorted(_RULES)}, got {names}")
        # Lexical first: it wins representative ties and is the ground truth of `why`.
        self._legs = tuple(sorted(legs, key=lambda leg: list(_RULES).index(leg.name)))
        self._policy = policy

    # ------------------------------------------------------------------ recall
    async def recall(self, query: RecallQuery, budget: RecallBudget) -> RecallResult:
        started = time.perf_counter()
        scopes = self._policy.narrow(query.scopes) if self._policy is not None else query.scopes
        if not scopes:
            return RecallResult(timings_ms={"total": 0.0})
        query = replace(query, scopes=scopes)
        tasks = {
            leg.name: asyncio.create_task(self._run_leg(leg, query, budget), name=f"memory-leg-{leg.name}")
            for leg in self._legs
        }
        await asyncio.wait(tasks.values(), timeout=budget.timeout_ms / 1000)

        runs: dict[str, _LegRun] = {}
        degraded: list[DegradedReason] = []
        timings: dict[str, float] = {}
        for name, task in tasks.items():
            if task.done():
                run = task.result()
            else:
                task.cancel()  # past the overall wall clock: the leg's answer is no longer wanted
                run = _LegRun(LegResult(), _TIMEOUT, DegradedReason.RECALL_TIMEOUT, budget.timeout_ms)
            runs[name] = run
            timings[name] = round(run.elapsed_ms, 3)
            if run.reason is not None and run.reason not in degraded:
                degraded.append(run.reason)

        outcomes = {run.outcome for run in runs.values()}
        if outcomes <= {_ERROR, _DEGRADED} and _ERROR in outcomes:
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "no recall leg could answer")

        fusion_started = time.perf_counter()
        fused = rrf_fuse(
            {name: run.result.hits for name, run in runs.items()}, include_history=query.include_history,
        )
        items = pack_items(fused, budget, tuple(runs))
        now = time.perf_counter()
        timings["fusion"] = round((now - fusion_started) * 1000, 3)
        timings["total"] = round((now - started) * 1000, 3)
        return RecallResult(items=items, degraded=tuple(degraded), timings_ms=timings)

    async def _run_leg(self, leg: RecallLeg, query: RecallQuery, budget: RecallBudget) -> _LegRun:
        rules = _RULES[leg.name]
        timeout_s = getattr(budget, rules.timeout_field) / 1000
        started = time.perf_counter()

        def elapsed() -> float:
            return (time.perf_counter() - started) * 1000

        try:
            result = await asyncio.wait_for(leg.hits(query, LEG_TOP, timeout_s), timeout_s)
        except asyncio.TimeoutError:
            return _LegRun(LegResult(), _TIMEOUT, rules.timeout_reason, elapsed())
        except LegDegraded as exc:
            outcome = (
                _TIMEOUT if exc.reason is rules.timeout_reason
                else _ERROR if exc.reason is rules.failure_reason else _DEGRADED
            )
            return _LegRun(LegResult(), outcome, exc.reason, elapsed())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - leg boundary: a failing leg degrades the recall, never breaks it
            _LOG.warning("memory recall leg %s failed: %s: %s", leg.name, type(exc).__name__, exc)
            return _LegRun(LegResult(), _ERROR, rules.failure_reason, elapsed())
        return _LegRun(result, _OK, result.degraded, elapsed())

    # ------------------------------------------------------------------ status
    def status(self) -> CapabilityState:
        """Unavailable when the lexical leg is; degraded when another leg is not ok."""

        states = {leg.name: leg.status() for leg in self._legs}
        lexical = states[LEG_LEXICAL]
        if lexical.status is CapabilityStatus.UNAVAILABLE:
            return lexical
        for name, state in states.items():
            if not state.is_ok and state.status is not CapabilityStatus.DISABLED:
                return CapabilityState(CapabilityStatus.DEGRADED, state.reason_code, state.reason)
        return capability_ok()
