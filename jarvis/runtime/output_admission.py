"""Atomic pre-write reservation shared by event loop and audio writer only."""
from __future__ import annotations

from enum import StrEnum
import threading
import time


class OutputAdmissionState(StrEnum):
    RESERVED = "reserved"
    INVALIDATED = "invalidated"
    WRITE_STARTED = "write_started"
    WRITTEN = "written"
    WRITE_FAILED = "write_failed"


class OutputAdmission:
    """No policy, asyncio or logging runs on the device worker.

    write_started reserves an in-flight native write; it is not heard evidence.
    A result arriving after that boundary cannot prove the output was unplayed.
    """
    def __init__(self, *, expires_at: float | None = None) -> None:
        self._state = OutputAdmissionState.RESERVED
        self._lock = threading.Lock()
        self._expires_at = expires_at

    @property
    def state(self) -> OutputAdmissionState:
        with self._lock:
            return self._state

    def invalidate(self) -> bool:
        with self._lock:
            if self._state is OutputAdmissionState.RESERVED:
                self._state = OutputAdmissionState.INVALIDATED
                return True
            return self._state is OutputAdmissionState.INVALIDATED

    def begin_write(self) -> bool:
        with self._lock:
            self._expire_locked()
            if self._state in (OutputAdmissionState.INVALIDATED, OutputAdmissionState.WRITE_FAILED):
                return False
            if self._state is OutputAdmissionState.RESERVED:
                self._state = OutputAdmissionState.WRITE_STARTED
            return True

    def can_write(self) -> bool:
        """Check eligibility without crossing the native-write boundary."""
        with self._lock:
            self._expire_locked()
            return self._state not in (OutputAdmissionState.INVALIDATED, OutputAdmissionState.WRITE_FAILED)

    def _expire_locked(self) -> None:
        if (self._state is OutputAdmissionState.RESERVED and self._expires_at is not None
                and time.monotonic() >= self._expires_at):
            self._state = OutputAdmissionState.INVALIDATED

    def finish_write(self, *, succeeded: bool) -> None:
        with self._lock:
            self._state = OutputAdmissionState.WRITTEN if succeeded else OutputAdmissionState.WRITE_FAILED
