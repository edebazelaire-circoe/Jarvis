"""OPT-IN: the only Test Lab tests that touch this workstation's real audio devices.

Skipped unless `JARVIS_TESTLAB_AUDIO=1`. Nothing in the default suite may enumerate or
open a device: the workstation Jarvis owns the laptop microphone and speakers
(READINESS B9), and a test that took them would interrupt a live conversation.

Two levels, both gated:

- `JARVIS_TESTLAB_AUDIO=1` enumerates devices (`sd.query_devices`, read-only) and runs
  the contention detector against the LIVE runtime root. It opens nothing.
- `JARVIS_TESTLAB_AUDIO_PLAYBACK=1` additionally records and plays two seconds through
  the real devices (`SoundDeviceAudioDiagnostics.test_record_and_playback`). It is a
  SECOND switch on purpose, and every test that uses it refuses to run unless the
  detector says the devices are free — a skip, never a steal.

A human runs these; Slice 08 ran the enumeration level only, with the contention
detector reporting the devices free.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.runtime.audio_devices import AudioDiagnosticError, SoundDeviceAudioDiagnostics, normalize_device_id
from jarvis.testlab.devices import ContentionState, default_contention_detector

REPO_ROOT = Path(__file__).resolve().parents[2]
#: The runtime root the workstation Jarvis publishes its voice signals in.
LIVE_RUNTIME_ROOT = Path(os.getenv("JARVIS_TESTLAB_LIVE_RUNTIME") or (REPO_ROOT / "runtime"))

audio_only = pytest.mark.skipif(
    os.getenv("JARVIS_TESTLAB_AUDIO") != "1",
    reason="requires JARVIS_TESTLAB_AUDIO=1 (touches this workstation's audio devices)")
playback_only = pytest.mark.skipif(
    os.getenv("JARVIS_TESTLAB_AUDIO") != "1" or os.getenv("JARVIS_TESTLAB_AUDIO_PLAYBACK") != "1",
    reason="requires JARVIS_TESTLAB_AUDIO=1 and JARVIS_TESTLAB_AUDIO_PLAYBACK=1 (opens the real devices)")


def devices_free() -> tuple[bool, str]:
    report = default_contention_detector(LIVE_RUNTIME_ROOT).detect()
    return report.available, report.reason()


def require_free_devices() -> None:
    """Refuse to touch the devices unless the detector positively says they are free."""
    free, reason = devices_free()
    if not free:
        pytest.skip(f"the audio devices are not free, so this test will not take them: {reason}")


@audio_only
def test_the_detector_answers_about_this_workstation():
    """The contention gate must produce a usable answer on the real runtime root."""
    report = default_contention_detector(LIVE_RUNTIME_ROOT).detect()
    assert report.state in tuple(ContentionState)
    assert report.evidence and report.evidence[0].source == "live_voice_runtime"
    assert report.reason()
    if report.state is ContentionState.BUSY:
        assert report.holder


@audio_only
def test_enumerating_devices_opens_nothing_and_names_a_default():
    """`list_devices` is a read-only PortAudio query; it is what a hardware profile reads."""
    listing = SoundDeviceAudioDiagnostics().list_devices()
    assert isinstance(listing.get("inputs"), list) and isinstance(listing.get("outputs"), list)
    for device in (*listing["inputs"], *listing["outputs"]):
        assert isinstance(device["id"], int) and device["name"]
        assert normalize_device_id(device["id"]) == device["id"]


@audio_only
def test_the_voice_sample_rate_is_supported_by_a_default_device_or_the_reason_is_named():
    """A format query, not an open: `check_*_settings` asks PortAudio, it takes nothing."""
    import sounddevice as sd

    try:
        sd.check_input_settings(device=None, channels=1, dtype="int16", samplerate=24_000)
        sd.check_output_settings(device=None, channels=1, dtype="int16", samplerate=24_000)
    except Exception as exc:  # pragma: no cover - depends on the workstation
        pytest.skip(f"the default devices do not accept the Voice format on this host: {type(exc).__name__}")


@playback_only
def test_a_real_record_and_playback_round_trip():
    """OPT-IN AND GATED. Opens the real microphone and speaker for two seconds.

    It refuses to run when the detector does not say the devices are free, which is the
    behaviour Slice 09's hardware profiles inherit: detect, then decline, never steal.
    """
    require_free_devices()
    try:
        result = SoundDeviceAudioDiagnostics().test_record_and_playback(
            input_device=None, output_device=None, duration_s=2.0)
    except AudioDiagnosticError as exc:
        if exc.code in ("audio_input_no_signal", "audio_input_unavailable", "audio_output_unavailable"):
            pytest.skip(f"the workstation could not complete the round trip ({exc.code}): {exc}")
        raise
    assert result["ok"] is True and result["sample_rate"] == 24_000
    assert result["peak_dbfs"] > -50.0
