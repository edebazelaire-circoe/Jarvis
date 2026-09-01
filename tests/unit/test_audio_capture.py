from __future__ import annotations

import sys
import types
import threading
import time

import pytest

from jarvis.audio.capture import SoundDeviceRecorder
from jarvis.domain.errors import AudioDeviceError


class FakeRawInputStream:
    def __init__(self, *, callback, **kwargs):
        self.callback = callback
        self.closed = False

    def start(self):
        threading.Timer(0.005, lambda: self.callback(b"\x01\x00" * 1600, 1600, None, None)).start()

    def stop(self):
        pass

    def close(self):
        self.closed = True

    def abort(self):
        pass


def fake_sounddevice(*, channels=1):
    module = types.SimpleNamespace()
    module.RawInputStream = FakeRawInputStream
    module.query_devices = lambda *args, **kwargs: {"name": "Fake Mic", "max_input_channels": channels}
    return module


def test_capture_creates_in_memory_wav_and_no_raw_file(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice())
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    recorder = SoundDeviceRecorder(sample_rate=16000, channels=1)
    assert recorder.preflight()["name"] == "Fake Mic"
    recorder.start()
    time.sleep(0.02)
    clip = recorder.stop()
    assert clip.data.startswith(b"RIFF")
    assert 95 <= clip.duration_ms <= 105
    assert set(tmp_path.iterdir()) == before


def test_microphone_preflight_fails_clearly_when_device_has_no_channel(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice(channels=0))
    recorder = SoundDeviceRecorder(sample_rate=16000, channels=1)
    with pytest.raises(AudioDeviceError, match="canal micro"):
        recorder.preflight()


def test_explicit_microphone_name_does_not_silently_fallback(monkeypatch):
    module = types.SimpleNamespace()
    module.RawInputStream = FakeRawInputStream
    module.query_devices = lambda *args, **kwargs: [
        {"name": "Built-in Mic", "max_input_channels": 1},
        {"name": "USB Mic", "max_input_channels": 1},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    recorder = SoundDeviceRecorder(input_device="Studio Mic")
    with pytest.raises(AudioDeviceError, match="configure introuvable"):
        recorder.preflight()
