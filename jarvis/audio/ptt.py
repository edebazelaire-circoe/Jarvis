from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from jarvis.domain.errors import AudioDeviceError


class PTTKeyListener:
    """Global push-to-talk listener. Keyboard callbacks only schedule async work."""

    def __init__(
        self,
        key_name: str,
        *,
        on_press: Callable[[], Awaitable[None]],
        on_release: Callable[[], Awaitable[None]],
    ) -> None:
        self.key_name = key_name.lower().strip()
        self.on_press = on_press
        self.on_release = on_release
        self._held = False
        self._listener = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        try:
            from pynput import keyboard  # type: ignore
        except ImportError as exc:
            raise AudioDeviceError("Le module pynput est requis pour le push-to-talk") from exc
        self._loop = asyncio.get_running_loop()
        target = self._resolve_key(keyboard)

        def press(key) -> None:  # noqa: ANN001
            if self._matches(key, target) and not self._held:
                self._held = True
                asyncio.run_coroutine_threadsafe(self.on_press(), self._loop)

        def release(key) -> None:  # noqa: ANN001
            if self._matches(key, target) and self._held:
                self._held = False
                asyncio.run_coroutine_threadsafe(self.on_release(), self._loop)

        self._listener = keyboard.Listener(on_press=press, on_release=release)
        self._listener.start()
        await self._stop.wait()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
        self._stop.set()

    def _resolve_key(self, keyboard):  # noqa: ANN001
        aliases = {"space": keyboard.Key.space, "ctrl": keyboard.Key.ctrl, "alt": keyboard.Key.alt, "shift": keyboard.Key.shift}
        if self.key_name in aliases:
            return aliases[self.key_name]
        if hasattr(keyboard.Key, self.key_name):
            return getattr(keyboard.Key, self.key_name)
        if len(self.key_name) == 1:
            return self.key_name
        raise AudioDeviceError(f"Touche PTT non supportee: {self.key_name}")

    @staticmethod
    def _matches(key, target) -> bool:  # noqa: ANN001
        if isinstance(target, str):
            return getattr(key, "char", None) == target
        return key == target
