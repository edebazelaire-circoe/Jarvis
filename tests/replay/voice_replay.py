"""Compatibility layer over `jarvis.testlab.replay` plus the replay clock and driver.

Slice 04 moved the `jarvis.voice_replay` v1 decoding and action vocabulary into
`jarvis/testlab/` (production code cannot import from `tests/`), where the Test Lab
primitive registry now owns the action schema. This module re-exports that codec
unchanged — same names, same stable `fixture_*` error codes, same immutability — so
every fixture and every replay test keeps working.

What stays here is the *execution* half: `ReplayClock` and `ReplayDriver` advance a
fake clock and dispatch steps to named handlers without evaluating policy. The Test
Lab executor of scenarios is Slice 06; until it exists, these helpers stay test-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
import inspect
import math

from jarvis.testlab.replay import (
    MAX_FACT_LENGTH,
    MAX_FIXTURE_BYTES,
    MAX_IDENTIFIER_LENGTH,
    MAX_INT64,
    MAX_SOURCE_REF_LENGTH,
    MAX_STEPS,
    MAX_TIMELINE_MS,
    SCHEMA,
    SCHEMA_VERSION,
    ReplayEvidence,
    ReplayFixture,
    ReplayFixtureError,
    ReplayProvenance,
    ReplayStep,
    load_replay_fixture,
    loads_replay_fixture,
)

__all__ = [
    "MAX_FACT_LENGTH", "MAX_FIXTURE_BYTES", "MAX_IDENTIFIER_LENGTH", "MAX_INT64", "MAX_SOURCE_REF_LENGTH",
    "MAX_STEPS", "MAX_TIMELINE_MS", "SCHEMA", "SCHEMA_VERSION", "ReplayClock", "ReplayDriver", "ReplayEvidence",
    "ReplayFixture", "ReplayFixtureError", "ReplayHandler", "ReplayProvenance", "ReplayStep",
    "load_replay_fixture", "loads_replay_fixture",
]

ReplayHandler = Callable[[ReplayStep], object | Awaitable[object]]


class ReplayClock:
    """Wall and monotonic fake clocks sharing one integer-millisecond cursor."""

    def __init__(self, origin: datetime, *, monotonic_start: float = 0.0):
        if origin.tzinfo is None or origin.utcoffset() is None:
            raise ReplayFixtureError("clock_origin_invalid", "origin must include a UTC offset")
        if isinstance(monotonic_start, bool) or not isinstance(monotonic_start, (int, float)):
            raise ReplayFixtureError("clock_start_invalid", "monotonic_start must be a finite number")
        if not math.isfinite(monotonic_start) or monotonic_start < 0:
            raise ReplayFixtureError("clock_start_invalid", "monotonic_start must be finite and non-negative")
        self._origin = origin
        self._monotonic_start = float(monotonic_start)
        self._elapsed_ms = 0

    @property
    def elapsed_ms(self) -> int:
        return self._elapsed_ms

    def now(self) -> datetime:
        return self._origin + timedelta(milliseconds=self._elapsed_ms)

    def monotonic(self) -> float:
        return self._monotonic_start + self._elapsed_ms / 1000

    def monotonic_ns(self) -> int:
        return round(self.monotonic() * 1_000_000_000)

    def advance_to_ms(self, at_ms: int) -> None:
        if isinstance(at_ms, bool) or not isinstance(at_ms, int) or not 0 <= at_ms <= MAX_TIMELINE_MS:
            raise ReplayFixtureError("clock_target_invalid",
                                     f"at_ms must be a non-negative integer of at most {MAX_TIMELINE_MS}")
        if at_ms < self._elapsed_ms:
            raise ReplayFixtureError("clock_went_backwards", f"{at_ms} < {self._elapsed_ms}")
        self._elapsed_ms = at_ms


class ReplayDriver:
    """Advance time and dispatch fixture actions without evaluating policy."""

    def __init__(self, clock: ReplayClock):
        self.clock = clock

    async def run(self, fixture: ReplayFixture, handlers: Mapping[str, ReplayHandler]) -> None:
        for step in fixture.steps:
            self.clock.advance_to_ms(step.at_ms)
            handler = handlers.get(step.kind)
            if handler is None:
                raise ReplayFixtureError("replay_handler_missing", step.kind)
            result = handler(step)
            if inspect.isawaitable(result):
                await result
