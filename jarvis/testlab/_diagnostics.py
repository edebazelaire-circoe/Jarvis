"""Private Test Lab helper: emit through an optional `DiagnosticSink` without ever failing the caller.

Binding contract: `docs/testlab.md` ("Corruption handling", "Capture service").
Shared by `FilesystemTestRunStore`, `FilesystemBundleStore` and the bundle
capture service (Slice 03 rework: one copy instead of three).
"""

from __future__ import annotations

import threading
from typing import Any

from jarvis.ports.v2 import DiagnosticSink


class SafeDiagnostics:
    """`emit` never raises: a broken sink cannot undo a committed write or fail a read or a capture.

    Refused emissions are counted in `failures` (under a lock, exact across threads)
    so the host can see that its diagnostics are incomplete.
    """

    def __init__(self, sink: DiagnosticSink | None) -> None:
        self._sink = sink
        self._lock = threading.Lock()
        self.failures = 0

    def emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        if self._sink is None:
            return
        try:
            self._sink.emit(kind, message, level=level, data=data)
        except Exception:
            # Capture as a count: the diagnostic is secondary to the operation that
            # already happened; `failures` keeps the loss visible.
            with self._lock:
                self.failures += 1
