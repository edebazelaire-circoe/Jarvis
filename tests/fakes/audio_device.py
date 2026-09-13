"""Controlled device buffer. Advancing consumption is explicit test input."""
from __future__ import annotations

from contextlib import contextmanager
import threading


class BufferedOutputStream:
    latency = 0.2

    def __init__(self):
        self.condition = threading.Condition()
        self.draining = threading.Event()
        self.queued_bytes = 0
        self.played_bytes = 0
        self.writes = []
        self.calls = []
        self.active = True
        self.closed = False
        self.native = None
        self.fail = set()

    @contextmanager
    def operation(self, name):
        with self.condition:
            assert self.native is None, f"concurrent native operation: {self.native}/{name}"
            assert not self.closed, "operation after native close"
            self.native = name
            self.calls.append(name)
        try:
            if name in self.fail:
                raise OSError(f"injected {name} failure")
            yield
        finally:
            with self.condition:
                self.native = None

    def write(self, pcm):
        with self.operation("write"):
            assert self.active
            self.writes.append(bytes(pcm))
            self.queued_bytes += len(pcm)

    def consume(self):
        with self.condition:
            self.played_bytes += self.queued_bytes
            self.queued_bytes = 0
            self.condition.notify_all()

    def stop(self, *, ignore_errors=True):
        assert ignore_errors is False, "unchecked stop is not device evidence"
        with self.operation("stop"):
            self.draining.set()
            with self.condition:
                assert self.condition.wait_for(lambda: self.queued_bytes == 0, timeout=5), "test device never consumed"
            self.active = False

    def abort(self, *, ignore_errors=True):
        assert ignore_errors is False
        with self.operation("abort"):
            self.queued_bytes = 0
            self.active = False

    def start(self):
        with self.operation("start"):
            self.active = True

    def close(self, *, ignore_errors=True):
        assert ignore_errors is False
        with self.operation("close"):
            self.closed = True


class BufferedInputStream:
    def __init__(self):
        self.closed = False
        self.calls = []

    def stop(self, *, ignore_errors=True):
        assert ignore_errors is False
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")

    def close(self, *, ignore_errors=True):
        assert ignore_errors is False
        self.calls.append("close")
        self.closed = True
