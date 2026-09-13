"""Permanent controlled contract fixture; never a production analysis fallback."""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable

from jarvis.domain.front_brain_hints import (
    FrontBrainHintRequest, FrontBrainHintResult, FrontBrainHintValue, HintAnalysisStatus,
)


class FakeFrontBrainAnalyzer:
    """Each supplied result belongs to the request actually passed by the test.

    No automatic timer, scheduler, user commit, audio event or executor exists.
    The caller owns the asyncio task and optional gate. Cancellation propagates
    and leaves the fixture reusable; the retained call inventory is bounded.
    """
    def __init__(self, *, value: FrontBrainHintValue | None = None,
                 status: HintAnalysisStatus = HintAnalysisStatus.UNAVAILABLE,
                 gate: asyncio.Event | None = None, failure: Exception | None = None,
                 clock_ns: Callable[[], int] = lambda: 0) -> None:
        # Validate the configured envelope using the actual domain contract.
        FrontBrainHintResult("fixture-validation", status, value, 0)
        self.value = value
        self.status = status
        self.gate = gate
        self.failure = failure
        self.clock_ns = clock_ns
        self.started = asyncio.Event()
        self.requests: deque[FrontBrainHintRequest] = deque(maxlen=32)
        self.call_count = 0
        self.active_count = 0
        self.cancelled_count = 0

    async def analyze(self, request: FrontBrainHintRequest) -> FrontBrainHintResult:
        if not isinstance(request, FrontBrainHintRequest):
            raise ValueError("fake analysis request must be typed")
        self.requests.append(request)
        self.call_count += 1
        self.active_count += 1
        self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.failure is not None:
                raise self.failure
            return FrontBrainHintResult(request.request_id, self.status, self.value, self.clock_ns())
        except asyncio.CancelledError:
            self.cancelled_count += 1
            raise
        finally:
            self.active_count -= 1
