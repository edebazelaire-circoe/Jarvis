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
        self._queue: asyncio.Queue[tuple[str, dict[str, object] | None]] = asyncio.Queue(maxsize=4)
        #: Mesures (`provider`, `score`, `threshold`) de la détection qui vient d'être
        #: rendue par `detections()`, ou `None` : une touche ne mesure rien. Lue par
        #: Voice pour sa trace `voice.wake` ; jamais une entrée de comportement.
        self.last_detection: dict[str, object] | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._closed = False

    async def _pump(self, backend: WakeWordBackend) -> None:
        async for detection in backend.detections():
            if self._closed:
                return
            if not self._queue.full():
                # Le detecteur publie la mesure du mot qu'il vient de rendre (file de paires
                # `(mot, mesure)`), sans point d'attente entre le rendu et cette lecture. Une
                # touche n'a pas d'attribut : `None`, jamais la mesure d'une autre detection.
                facts = getattr(backend, "last_detection", None)
                self._queue.put_nowait((detection, dict(facts) if isinstance(facts, dict) else None))

    async def _ensure_started(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._pump(backend), name=f"jarvis-wake-{index}") for index, backend in enumerate(self.backends)]

    async def detections(self) -> AsyncIterator[str]:
        await self._ensure_started()
        while not self._closed:
            detection, self.last_detection = await self._queue.get()
            yield detection

    async def suspend(self) -> None:
        for backend in self.backends:
            await backend.suspend()
        self._clear_pending()

    async def suspend_for_active_session(self) -> None:
        for backend in self.backends:
            await backend.suspend_for_active_session()
        self._clear_pending()

    def _clear_pending(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def resume(self) -> None:
        for backend in self.backends:
            await backend.resume()

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
