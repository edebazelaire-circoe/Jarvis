from __future__ import annotations

from array import array
from types import SimpleNamespace

import pytest

from jarvis.runtime.audio_devices import AudioDiagnosticError, SoundDeviceAudioDiagnostics, normalize_device_id


class FakeRecording:
    def __init__(self, samples: list[int]) -> None:
        self.samples = samples

    def tobytes(self) -> bytes:
        return array("h", self.samples).tobytes()


class FakeSoundDevice:
    def __init__(self, samples: list[int] | None = None) -> None:
        self.default = SimpleNamespace(device=(1, 2))
        self.samples = samples or [0, 10_000, -10_000, 2_000]
        self.input_checks: list[dict[str, object]] = []
        self.output_checks: list[dict[str, object]] = []
        self.record_calls: list[dict[str, object]] = []
        self.play_calls: list[dict[str, object]] = []

    def query_devices(self):  # noqa: ANN201
        return [
            {"name": "Webcam Mic", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 48_000},
            {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48_000},
            {"name": "USB Speakers", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48_000},
        ]

    def query_hostapis(self):  # noqa: ANN201
        return [{"name": "Windows WASAPI"}]

    def check_input_settings(self, **kwargs) -> None:  # noqa: ANN003
        self.input_checks.append(kwargs)

    def check_output_settings(self, **kwargs) -> None:  # noqa: ANN003
        self.output_checks.append(kwargs)

    def rec(self, frames: int, **kwargs):  # noqa: ANN003, ANN201
        self.record_calls.append({"frames": frames, **kwargs})
        return FakeRecording(self.samples)

    def play(self, recording: FakeRecording, **kwargs) -> None:  # noqa: ANN003
        self.play_calls.append({"recording": recording, **kwargs})


def test_normalize_device_id_accepts_default_index_and_name():
    assert normalize_device_id(4) == 4
    assert normalize_device_id(" 4 ") == 4
    assert normalize_device_id("USB Mic") == "USB Mic"
    assert normalize_device_id("") is None
    with pytest.raises(ValueError):
        normalize_device_id(-1)


def test_audio_devices_are_split_by_capability(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake)

    result = SoundDeviceAudioDiagnostics().list_devices()

    assert [device["id"] for device in result["inputs"]] == [0, 1]
    assert [device["id"] for device in result["outputs"]] == [2]
    assert result["defaults"] == {"input": 1, "output": 2}
    assert result["inputs"][0]["hostapi"] == "Windows WASAPI"
    assert result["sample_rate"] == 24_000


def test_audio_test_records_signal_and_replays_same_buffer(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake)

    result = SoundDeviceAudioDiagnostics().test_record_and_playback(input_device=1, output_device=2)

    assert result["ok"] is True
    assert result["peak_dbfs"] > -20
    assert fake.input_checks[0]["device"] == 1
    assert fake.output_checks[0]["device"] == 2
    assert fake.record_calls[0]["samplerate"] == 24_000
    assert fake.record_calls[0]["blocking"] is True
    assert fake.play_calls[0]["device"] == 2
    assert fake.play_calls[0]["recording"].samples == fake.samples


def test_audio_test_rejects_silent_microphone(monkeypatch):
    fake = FakeSoundDevice(samples=[0] * 100)
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake)

    with pytest.raises(AudioDiagnosticError) as caught:
        SoundDeviceAudioDiagnostics().test_record_and_playback(input_device=1, output_device=2)

    assert caught.value.code == "audio_input_no_signal"
    assert fake.play_calls == []


def test_audio_test_rejects_incompatible_output_before_recording(monkeypatch):
    fake = FakeSoundDevice()

    def reject_output(**kwargs) -> None:  # noqa: ANN003
        del kwargs
        raise RuntimeError("unsupported format")

    fake.check_output_settings = reject_output  # type: ignore[method-assign]
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake)

    with pytest.raises(AudioDiagnosticError) as caught:
        SoundDeviceAudioDiagnostics().test_record_and_playback(input_device=1, output_device=2)

    assert caught.value.code == "audio_output_unavailable"
    assert fake.record_calls == []


def test_audio_device_enumeration_has_stable_failure_code(monkeypatch):
    fake = FakeSoundDevice()

    def fail_query():  # noqa: ANN202
        raise RuntimeError("portaudio unavailable")

    fake.query_devices = fail_query  # type: ignore[method-assign]
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake)

    with pytest.raises(AudioDiagnosticError) as caught:
        SoundDeviceAudioDiagnostics().list_devices()

    assert caught.value.code == "audio_device_enumeration_failed"
    assert caught.value.context["exception_type"] == "RuntimeError"
