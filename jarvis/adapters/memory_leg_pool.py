"""Dedicated bounded thread pool of one recall leg (memory handoff, Slice 03 polish).

`asyncio.to_thread` shares the loop's default executor: a store call that hangs
(disk stall, lock) holds a worker forever and, a recall after another, starves
every other `to_thread` user in Core. Each leg owns a small pool instead, and a
leg whose workers are all still busy is skipped with `leg_busy` rather than
queueing one more blocked call behind them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
import threading
from typing import TypeVar

from jarvis.domain.memory import DegradedReason
from jarvis.domain.memory_leg import LegDegraded

T = TypeVar("T")


class LegPool:
    def __init__(self, name: str, workers: int = 2) -> None:
        self._workers = workers
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"memory-{name}")
        self._lock = threading.Lock()
        self._inflight = 0

    @property
    def inflight(self) -> int:
        return self._inflight

    def _release(self, _future: Future) -> None:
        with self._lock:
            self._inflight -= 1

    async def run(self, function: Callable[..., T], *args, **kwargs) -> T:
        """Run `function` on this leg's threads; `LegDegraded(leg_busy)` when every worker is still occupied.

        The slot is released when the thread finishes, not when the caller
        stops waiting: a recall that timed out does not free a hung worker.
        """

        with self._lock:
            if self._inflight >= self._workers:
                raise LegDegraded(DegradedReason.LEG_BUSY, "the previous calls of this leg are still running")
            self._inflight += 1
        try:
            future = self._executor.submit(lambda: function(*args, **kwargs))
        except BaseException:
            with self._lock:
                self._inflight -= 1
            raise
        future.add_done_callback(self._release)
        return await asyncio.wrap_future(future)
