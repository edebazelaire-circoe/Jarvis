from __future__ import annotations

import asyncio

import pytest

from jarvis.adapters.wakeword_composite import CompositeWakeWordBackend
from jarvis.adapters.wakeword_keyboard import KeyboardWakeWordBackend


class FakeWakeBackend:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.suspended = False
        self.active_session_suspended = False
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        self.suspended = True

    async def suspend_for_active_session(self) -> None:
        self.active_session_suspended = True

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
    await second.queue.put("f9")
    assert await asyncio.wait_for(pending, timeout=1) == "f9"

    await wake.suspend()
    assert first.suspended and second.suspended
    await wake.suspend_for_active_session()
    assert first.active_session_suspended and second.active_session_suspended
    await wake.resume()
    assert not first.suspended and not second.suspended
    await wake.close()
    assert first.closed and second.closed


def test_keyboard_wake_detection_is_debounced_by_bounded_queue():
    wake = KeyboardWakeWordBackend()
    wake._detected()
    wake._detected()
    assert wake._queue.qsize() == 1
    assert wake._queue.get_nowait() == "f9"


@pytest.mark.asyncio
async def test_keyboard_wake_stays_enabled_during_active_voice_session(monkeypatch):
    wake = KeyboardWakeWordBackend(key_name="f9")

    async def fake_start() -> None:
        return None

    monkeypatch.setattr(wake, "start", fake_start)
    await wake.suspend_for_active_session()
    wake._detected()

    assert wake._enabled is True
    assert wake._queue.get_nowait() == "f9"
