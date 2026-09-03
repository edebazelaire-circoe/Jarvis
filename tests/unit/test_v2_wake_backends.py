from __future__ import annotations

import asyncio

import pytest

from jarvis.adapters.wakeword_composite import CompositeWakeWordBackend
from jarvis.adapters.wakeword_keyboard import KeyboardWakeWordBackend


class FakeWakeBackend:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.suspended = False
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        self.suspended = True

    async def resume(self) -> None:
        self.suspended = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_composite_wake_accepts_any_backend_and_propagates_lifecycle():
    first = FakeWakeBackend()
    second = FakeWakeBackend()
    wake = CompositeWakeWordBackend([first, second])
    detections = wake.detections()

    pending = asyncio.create_task(anext(detections))
    await asyncio.sleep(0)
    await second.queue.put("f1")
    assert await asyncio.wait_for(pending, timeout=1) == "f1"

    await wake.suspend()
    assert first.suspended and second.suspended
    await wake.resume()
    assert not first.suspended and not second.suspended
    await wake.close()
    assert first.closed and second.closed


def test_keyboard_wake_detection_is_debounced_by_bounded_queue():
    wake = KeyboardWakeWordBackend(key_name="f1")
    wake._detected()
    wake._detected()
    assert wake._queue.qsize() == 1
    assert wake._queue.get_nowait() == "f1"
