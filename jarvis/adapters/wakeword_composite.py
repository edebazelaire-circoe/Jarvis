from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from jarvis.ports.v2 import WakeWordBackend


class CompositeWakeWordBackend:
    """Merge multiple local wake sources into one WakeWordBackend."""

    def __init__(self, backends: Sequence[WakeWordBackend]) -> None:
        if not backends:
            raise ValueError("at least one wake backend is required")
        self.backends = tuple(backends)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
        self._tasks: list[asyncio.Task[None]] = []
        self._closed = False

    async def _pump(self, backend: WakeWordBackend) -> None:
        async for detection in backend.detections():
            if self._closed:
                return
            if not self._queue.full():
                self._queue.put_nowait(detection)

    async def _ensure_started(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._pump(backend), name=f"jarvis-wake-{index}") for index, backend in enumerate(self.backends)]

    async def detections(self) -> AsyncIterator[str]:
        await self._ensure_started()
        while not self._closed:
            yield await self._queue.get()

    async def suspend(self) -> None:
        for backend in self.backends:
            suspend = getattr(backend, "suspend", None)
            if suspend is not None:
                await suspend()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def resume(self) -> None:
        for backend in self.backends:
            resume = getattr(backend, "resume", None)
            if resume is not None:
                await resume()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for backend in self.backends:
            await backend.close()
