"""An asyncio loop whose clock only moves when nothing else can run.

Test-only. Every `loop.time()` reader (`asyncio.sleep`, `wait_for`, `timeout`,
`call_later`) sees virtual seconds: when no callback is ready and no socket is
readable, the loop jumps straight to its next timer instead of blocking. A 30 s
`OUTPUT_TIMEOUT_S` therefore costs no wall-clock time, and "nothing happened for
5 s" is a deterministic statement rather than a real wait.

Worker threads (`asyncio.to_thread`, `run_in_executor` — the audio device writer
uses them) freeze the virtual clock until they report back: a device write never
appears to take the 2 s budget of a bounded wait merely because the loop was idle.

Threads started by other means (a library's private thread posting with
`call_soon_threadsafe`) are NOT tracked; keep such components out of a virtual run.
"""

from __future__ import annotations

import asyncio
import selectors
from collections.abc import Awaitable
from datetime import datetime, timedelta
from typing import TypeVar

T = TypeVar("T")

#: Real wait of one poll while a worker thread is in flight. Only ever spent when
#: a thread is actually running; the virtual clock does not move meanwhile.
_THREAD_POLL_S = 0.01


class _VirtualSelector(selectors.DefaultSelector):
    loop: "VirtualTimeLoop"

    def select(self, timeout=None):  # noqa: ANN001 - selectors signature
        loop = self.loop
        if loop.in_flight:
            return super().select(_THREAD_POLL_S if timeout is None else min(timeout, _THREAD_POLL_S))
        events = super().select(0)
        if events or timeout is None or timeout <= 0:
            return events
        loop.advance(timeout)
        return []


class VirtualTimeLoop(asyncio.SelectorEventLoop):
    """`SelectorEventLoop` with a virtual `time()` that jumps over idle periods."""

    def __init__(self) -> None:
        selector = _VirtualSelector()
        selector.loop = self
        self._virtual_now = 0.0
        self.in_flight = 0
        super().__init__(selector)

    def time(self) -> float:
        return self._virtual_now

    def advance(self, seconds: float) -> None:
        self._virtual_now += max(0.0, float(seconds))

    def run_in_executor(self, executor, func, *args):  # noqa: ANN001
        future = super().run_in_executor(executor, func, *args)
        self.in_flight += 1

        def done(_future) -> None:  # noqa: ANN001
            self.in_flight -= 1

        future.add_done_callback(done)
        return future


class VirtualWallClock:
    """`Clock` (datetime) and `monotonic` view of a `VirtualTimeLoop`.

    Lets the speech scheduler date requests and measure queue waits on the same
    virtual timeline the loop's timers run on.
    """

    def __init__(self, loop: VirtualTimeLoop, origin: datetime) -> None:
        self._loop = loop
        self._origin = origin

    def now(self) -> datetime:
        return self._origin + timedelta(seconds=self._loop.time())

    def monotonic(self) -> float:
        return self._loop.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def run_virtual(main: Awaitable[T], *, budget_s: float = 600.0) -> T:
    """Run `main` to completion on a fresh `VirtualTimeLoop`.

    `budget_s` is VIRTUAL: it bounds a scenario that would otherwise wait forever
    and costs nothing to set generously.
    """

    loop = VirtualTimeLoop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(asyncio.wait_for(main, timeout=budget_s))
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
