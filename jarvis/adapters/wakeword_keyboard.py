from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class KeyboardWakeWordBackend:
    """Global keyboard wake trigger used as a local/manual Voice fallback."""

    def __init__(self, *, key_name: str = "f9") -> None:
        self.key_name = key_name.lower().strip()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._listener = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._enabled = True
        self._held = False

    async def start(self) -> None:
        if self._listener is not None:
            return
        try:
            from pynput import keyboard  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Keyboard wake requires pynput") from exc

        self._loop = asyncio.get_running_loop()
        target = self._resolve_key(keyboard)

        def press(key) -> None:  # noqa: ANN001
            if self._closed or not self._enabled or self._held:
                return
            if self._matches(key, target):
                self._held = True
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._detected)

        def release(key) -> None:  # noqa: ANN001
            if self._matches(key, target):
                self._held = False

        self._listener = keyboard.Listener(on_press=press, on_release=release)
        self._listener.start()

    def _detected(self) -> None:
        if self._closed or not self._enabled or self._queue.full():
            return
        self._queue.put_nowait(self.key_name)

    async def suspend(self) -> None:
        self._enabled = False
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def suspend_for_active_session(self) -> None:
        """Keep the manual key active so a second press can submit the turn."""
        if not self._closed:
            self._enabled = True
            await self.start()

    async def resume(self) -> None:
        if not self._closed:
            self._enabled = True
            await self.start()

    async def detections(self) -> AsyncIterator[str]:
        await self.start()
        while not self._closed:
            yield await self._queue.get()

    async def close(self) -> None:
        self._closed = True
        self._enabled = False
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.stop()

    def _resolve_key(self, keyboard):  # noqa: ANN001
        if hasattr(keyboard.Key, self.key_name):
            return getattr(keyboard.Key, self.key_name)
        if len(self.key_name) == 1:
            return self.key_name
        raise RuntimeError(f"Unsupported keyboard wake key: {self.key_name}")

    @staticmethod
    def _matches(key, target) -> bool:  # noqa: ANN001
        if isinstance(target, str):
            return getattr(key, "char", None) == target
        return key == target
