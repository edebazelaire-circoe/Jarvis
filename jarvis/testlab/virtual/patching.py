"""Attribute patching without pytest.

The async conversation harness replaces three module attributes for the duration
of a stack (`realtime_audio.SoundDeviceRealtimeAudio`, `SpeechScheduler.RECONNECT_DELAY_S`,
`protocol_server.web.AppRunner`). Under pytest that was a `monkeypatch` fixture;
a Test Lab worker has no pytest, so `PatchStack` provides the same two operations
with the same signature (`setattr(target, name, value)` / restore in reverse order).

`voice_stack` therefore accepts either object: a pytest `monkeypatch` from a test,
a `PatchStack` from a runner. Nothing in the harness depends on anything else that
`monkeypatch` offers.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Protocol


class AttributePatcher(Protocol):
    """What `voice_stack` needs from its patcher: pytest's `monkeypatch` satisfies it."""

    def setattr(self, target: Any, name: str, value: Any, /) -> None: ...


class PatchStack:
    """Set attributes and restore them in reverse order, exactly once.

    Restoring is idempotent, and a stack already undone refuses a further patch:
    a runner that patched a module attribute after its own teardown would leave a
    double on a global for the next run of the same process.
    """

    __slots__ = ("_undo", "_closed")

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any, bool]] = []
        self._closed = False

    def setattr(self, target: Any, name: str, value: Any, /) -> None:
        if self._closed:
            raise RuntimeError("this PatchStack is closed; build a new one")
        existed = hasattr(target, name)
        previous = getattr(target, name, None)
        self._undo.append((target, name, previous, existed))
        setattr(target, name, value)

    def undo(self) -> None:
        """Restore every patched attribute, newest first. Safe to call twice."""
        self._closed = True
        while self._undo:
            target, name, previous, existed = self._undo.pop()
            if existed:
                setattr(target, name, previous)
            else:
                try:
                    delattr(target, name)
                except AttributeError:
                    # intentional: the attribute did not exist before the patch and no
                    # longer exists now, which is exactly the state we were restoring.
                    pass

    def __enter__(self) -> PatchStack:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.undo()
