"""Controlled output/input device buffers of the `virtual` profile.

Moved from `tests/fakes/audio_device.py` (Slice 06): the virtual profile runs inside the
product, and production code may not import from `tests.`
(`tests/unit/test_v2_architecture.py::test_production_never_imports_test_frontends`).
`tests/fakes/audio_device.py` re-exports these two classes, so the ten test modules that
already use them keep working unchanged.

Advancing consumption is explicit input: nothing here plays audio or waits on a clock, so
a scenario decides when queued bytes become played bytes.

These doubles enforce the native-stream contract they stand for — one operation at a
time, no operation after close, no unchecked `stop`. Those checks were `assert`
statements while this was test-only code; as product code they raise
`DeviceContractError`, because `python -O` removes an `assert` and a double that stops
checking is a double that certifies whatever it is given.
"""

from __future__ import annotations

from contextlib import contextmanager
import threading


class DeviceContractError(RuntimeError):
    """The caller broke the native audio-stream contract this double stands for."""


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
            if self.native is not None:
                raise DeviceContractError(f"concurrent native operation: {self.native}/{name}")
            if self.closed:
                raise DeviceContractError(f"native operation {name} after close")
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
            if not self.active:
                raise DeviceContractError("write on a stopped stream")
            self.writes.append(bytes(pcm))
            self.queued_bytes += len(pcm)

    def consume(self):
        with self.condition:
            self.played_bytes += self.queued_bytes
            self.queued_bytes = 0
            self.condition.notify_all()

    def stop(self, *, ignore_errors=True):
        if ignore_errors is not False:
            raise DeviceContractError("unchecked stop is not device evidence")
        with self.operation("stop"):
            self.draining.set()
            with self.condition:
                if not self.condition.wait_for(lambda: self.queued_bytes == 0, timeout=5):
                    raise DeviceContractError("test device never consumed")
            self.active = False

    def abort(self, *, ignore_errors=True):
        if ignore_errors is not False:
            raise DeviceContractError("unchecked abort is not device evidence")
        with self.operation("abort"):
            self.queued_bytes = 0
            self.active = False

    def start(self):
        with self.operation("start"):
            self.active = True

    def close(self, *, ignore_errors=True):
        if ignore_errors is not False:
            raise DeviceContractError("unchecked close is not device evidence")
        with self.operation("close"):
            self.closed = True


class BufferedInputStream:
    def __init__(self):
        self.closed = False
        self.calls = []

    def stop(self, *, ignore_errors=True):
        if ignore_errors is not False:
            raise DeviceContractError("unchecked stop is not device evidence")
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")

    def close(self, *, ignore_errors=True):
        if ignore_errors is not False:
            raise DeviceContractError("unchecked close is not device evidence")
        self.calls.append("close")
        self.closed = True
