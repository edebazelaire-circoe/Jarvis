"""Real workstation audio devices: selection, format pre-flight and the honest failure mapping.

Binding contract: `docs/testlab.md` ("Hardware profiles"). This module owns the
FIRST place in the Test Lab where a physical microphone and speaker are chosen and
proved usable. It opens nothing by itself: it resolves which device a run asked for,
asks PortAudio whether that device accepts the Voice format, and turns every way that
can go wrong into one exception family.

**Every device failure is `MeasurementUnavailable`, never a crash and never a verdict.**
A microphone another application holds, an output that refuses 24 kHz mono, a capture
that produced silence: none of them says anything about Jarvis, and none of them is a
defect of the lab. They say "we could not measure", which the worker records as
`measurement_unavailable` and `jarvis.testlab.outcomes` reads as `inconclusive`.

This is also the boundary the Slice 08 contention detector explicitly does NOT cover.
`jarvis.testlab.devices` answers "is the live Jarvis using the devices" by reading the
signals the live runtime publishes; it cannot see a third application holding the
microphone, and it is not an authority on whether a device can be opened at all. The
detector refuses BEFORE we take anything; this module reports honestly AFTER we tried.

Device selection, in order, the first that names something winning:

1. the diagnostic's declared `device.input` / `device.output` parameters;
2. the workstation's configured devices, read from the run's OWN settings copy
   (`<runtime_dir>/control-center-settings.json`), the same keys the Control Center
   writes (`audio_input_device`, `audio_output_device`);
3. `None`, which is PortAudio's own default device.

Ids are normalised exactly as the product normalises them
(`jarvis.runtime.audio_devices.normalize_device_id`), so "1", 1 and a device name all
mean here what they mean to Realtime Voice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from jarvis.runtime.audio_devices import (
    VOICE_SAMPLE_RATE,
    AudioDiagnosticError,
    SoundDeviceAudioDiagnostics,
    normalize_device_id,
)
from jarvis.testlab.devices import (
    MAX_EVIDENCE_DETAIL_CHARS,
    ContentionEvidence,
    ContentionState,
    DeviceContentionDetector,
    LiveVoiceRuntimeProbe,
)
from jarvis.testlab.runners import MeasurementUnavailable
from jarvis.testlab.validation import name_for_message

#: Declared diagnostic parameters a manifest uses to pin a device. Empty string means
#: "whatever this workstation is configured to use", which is the normal case.
DEVICE_INPUT_PARAMETER = "device.input"
DEVICE_OUTPUT_PARAMETER = "device.output"

#: The run's own settings copy, and the two keys the Control Center keeps devices under.
SETTINGS_FILE_NAME = "control-center-settings.json"
SETTINGS_INPUT_KEY = "audio_input_device"
SETTINGS_OUTPUT_KEY = "audio_output_device"
#: A settings copy is a small JSON document; anything larger is not one of ours.
MAX_SETTINGS_BYTES = 1024 * 1024

# Stable failure codes (docs/testlab.md, "Errors"). All of them are
# `MeasurementUnavailable`, so all of them read `inconclusive`.
DEVICE_ID_INVALID = "testlab_device_id_invalid"
DEVICE_BACKEND_UNAVAILABLE = "testlab_device_backend_unavailable"
DEVICE_INPUT_UNAVAILABLE = "testlab_device_input_unavailable"
DEVICE_OUTPUT_UNAVAILABLE = "testlab_device_output_unavailable"
DEVICE_INPUT_CAPTURE_FAILED = "testlab_device_input_capture_failed"
DEVICE_OUTPUT_PLAYBACK_FAILED = "testlab_device_output_playback_failed"
DEVICE_NO_SIGNAL = "testlab_device_input_no_signal"
DEVICE_NO_OUTPUT = "testlab_device_output_not_played"
DEVICE_OPEN_FAILED = "testlab_device_open_failed"
#: The one code every product audio error the table does not list lands on. A code is a
#: stable identifier callers branch on, so it is never synthesised from a message.
DEVICE_UNMAPPED = "testlab_device_unmapped"


class DeviceUnavailable(MeasurementUnavailable):
    """A real audio device could not be selected, opened, or made to carry a measurement.

    A `MeasurementUnavailable` on purpose, and this is the Slice 09 carry-over from
    Slice 08 spelled out: the contention detector answers "is the live Jarvis using the
    devices", never "can this device be opened". A third application holding the
    microphone, a USB headset unplugged between the gate and the open, a driver that
    refuses 24 kHz mono, a room so quiet nothing was captured — the Test Lab learnt
    nothing about Jarvis, and saying so is the honest outcome. Reading any of it as
    `crashed` would blame the lab; reading it as `failed` would blame the product.
    """


#: `AudioDiagnosticError.code` -> (our stable code, one English sentence a human can act on).
#: The product raises the left-hand codes; nothing here re-labels a cause, it only says
#: the same thing in the Test Lab's vocabulary and keeps the original as the `__cause__`.
DIAGNOSTIC_FAILURES: Mapping[str, tuple[str, str]] = {
    "audio_backend_unavailable": (
        DEVICE_BACKEND_UNAVAILABLE,
        "the sounddevice backend is not installed on this host, so no audio device can be opened"),
    "audio_device_enumeration_failed": (
        DEVICE_BACKEND_UNAVAILABLE,
        "PortAudio could not enumerate this host's audio devices"),
    "audio_input_unavailable": (
        DEVICE_INPUT_UNAVAILABLE,
        f"the selected microphone does not accept the Voice format ({VOICE_SAMPLE_RATE} Hz mono PCM16), "
        "or another application holds it"),
    "audio_output_unavailable": (
        DEVICE_OUTPUT_UNAVAILABLE,
        f"the selected output does not accept the Voice format ({VOICE_SAMPLE_RATE} Hz mono PCM16), "
        "or another application holds it"),
    "audio_input_capture_failed": (
        DEVICE_INPUT_CAPTURE_FAILED,
        "the microphone stream could not record"),
    "audio_input_no_signal": (
        DEVICE_NO_SIGNAL,
        "the microphone captured no signal above the Voice noise floor"),
    "audio_output_playback_failed": (
        DEVICE_OUTPUT_PLAYBACK_FAILED,
        "the audio could not be played back through the selected output"),
}


def device_failure(code: str, detail: str) -> DeviceUnavailable:
    """A `DeviceUnavailable` with one of this module's stable codes."""
    return DeviceUnavailable(code, detail)


def _one_line(code: object) -> str:
    """A product code, safe to put in a failure detail: bounded, printable, single line."""
    text = name_for_message(code)
    return " ".join(text.split()) or "no code"


def as_device_failure(exc: AudioDiagnosticError) -> DeviceUnavailable:
    """Translate a product audio-diagnostic error, keeping its real cause.

    An unmapped code is still `MeasurementUnavailable`: a device error we have not
    catalogued is still a device error, and guessing `crashed` for it would blame the
    lab for the workstation. It lands on ONE stable code, `testlab_device_unmapped`,
    with the product's own code in the detail — never on a code synthesised from it.
    A `RunFailure.code` is a stable identifier callers branch on and the Slice 01 name
    rules validate; `f"testlab_device_{exc.code}"` would happily produce
    `testlab_device_AUDIO WEIRD/code` from a product that grew a new message, which is
    neither stable nor a name.
    """
    known = DIAGNOSTIC_FAILURES.get(exc.code)
    if known is not None:
        return DeviceUnavailable(known[0], f"{known[1]} ({exc.code})")
    return DeviceUnavailable(
        DEVICE_UNMAPPED,
        "the workstation's audio device reported an error the Test Lab does not catalogue "
        f"({_one_line(exc.code)})")


# ---------------------------------------------------------------- selection

@dataclass(frozen=True, slots=True)
class DeviceSelection:
    """Which devices this run asked for, and where each choice came from.

    `None` is a real answer: it means "PortAudio's own default device", which is what
    Realtime Voice uses when nothing is configured. `source` is recorded in the run
    metadata so a reader knows whether a measurement was taken on a pinned device or on
    whatever the workstation happened to default to.
    """

    input_device: int | str | None = None
    output_device: int | str | None = None
    #: `parameter`, `settings` or `system_default`.
    input_source: str = "system_default"
    output_source: str = "system_default"

    def to_dict(self) -> dict[str, Any]:
        return {"input_device": self.input_device, "output_device": self.output_device,
                "input_source": self.input_source, "output_source": self.output_source}


def _normalize(value: object, name: str) -> int | str | None:
    """Product normalisation, with a bad id turned into a measurement failure.

    A caller who pins a device that cannot exist (a negative index, a boolean) has asked
    for an experiment that cannot be performed. That is a dead end of the situation, not
    a crash, so it joins the rest of the device family.
    """
    try:
        return normalize_device_id(value)
    except ValueError as exc:
        raise device_failure(DEVICE_ID_INVALID, f"{name} is not a usable audio device id: {exc}") from exc


def read_configured_devices(runtime_dir: Path | str) -> tuple[object, object]:
    """The workstation's configured devices, from the run's OWN settings copy.

    Never the live `runtime/`: the supervisor copies the settings into the run scratch
    and the worker refuses to start unless the roots it resolves are inside it. An
    unreadable or absent copy is the normal first-run state on a scratch that carries no
    settings, and it simply means "no configured device".
    """
    path = Path(runtime_dir) / SETTINGS_FILE_NAME
    try:
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            return None, None
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Intentional silence, argued: a run scratch without a settings copy is the
        # ordinary case (the supervisor only copies one when it has one), and the
        # fallback — PortAudio's own default device — is exactly what Realtime Voice
        # does with the same absent setting. The chosen device and its `source` are
        # recorded in the run metadata either way, so nothing is hidden.
        return None, None
    if not isinstance(document, dict):
        return None, None
    return document.get(SETTINGS_INPUT_KEY), document.get(SETTINGS_OUTPUT_KEY)


def resolve_device_selection(parameters: Mapping[str, Any] | None = None,
                             configured: tuple[object, object] = (None, None)) -> DeviceSelection:
    """Declared parameter, else configured default, else PortAudio's default.

    Pure: it reads the two declared parameters and the two configured values it is
    given, and normalises them the way the product does. It queries nothing and opens
    nothing, so it is safe to call before the contention gate has even been consulted.
    """
    values = parameters or {}

    def pick(parameter: str, setting: object) -> tuple[int | str | None, str]:
        declared = _normalize(values.get(parameter), parameter)
        if declared is not None:
            return declared, "parameter"
        fallback = _normalize(setting, f"settings.{parameter}")
        if fallback is not None:
            return fallback, "settings"
        return None, "system_default"

    input_device, input_source = pick(DEVICE_INPUT_PARAMETER, configured[0])
    output_device, output_source = pick(DEVICE_OUTPUT_PARAMETER, configured[1])
    return DeviceSelection(input_device, output_device, input_source, output_source)


# ---------------------------------------------------------------- pre-flight

def check_device_formats(selection: DeviceSelection, *,
                         diagnostics: SoundDeviceAudioDiagnostics | None = None) -> None:
    """Ask PortAudio whether the selected devices accept the Voice format. Opens nothing.

    This is the product's own check (`SoundDeviceAudioDiagnostics.check_input_format` /
    `check_output_format`, the same calls the Control Center audio test makes), used
    here as a pre-flight so a device that cannot work is reported with a precise code
    BEFORE a whole voice stack is mounted around it. A failure at open time is still
    caught, with `testlab_device_open_failed`, because a device can be taken between the
    two moments — this only makes the common case legible.
    """
    probe = diagnostics if diagnostics is not None else SoundDeviceAudioDiagnostics()
    try:
        probe.check_input_format(selection.input_device)
        probe.check_output_format(selection.output_device)
    except AudioDiagnosticError as exc:
        raise as_device_failure(exc) from exc


# ------------------------------------------------------- optional gate probe

class AudioBackendProbe:
    """"Can this host talk to PortAudio at all?", as one more fail-closed contention probe.

    It is NOT an authority on whether a device is in use: a WASAPI shared-mode open
    succeeds while Jarvis holds the microphone, so nothing short of taking the device
    could answer that, and taking it is exactly what the Test Lab may not do. This probe
    therefore answers `free` or `unknown` and never `busy`.

    **It never raises.** A probe that breaks must reach the detector as `unknown`
    evidence naming its cause, not as an exception: an exception that escapes the
    detector is turned into `supervisor_fault`, which reads `crashed` and means "our
    defect", and a missing sound driver is not our defect. `DeviceContentionDetector`
    has its own catch-all as a backstop; this one exists so the refusal says WHAT could
    not be reached instead of "the probe raised".
    """

    source = "audio_backend"

    def __init__(self, *, diagnostics: SoundDeviceAudioDiagnostics | None = None) -> None:
        self._diagnostics = diagnostics if diagnostics is not None else SoundDeviceAudioDiagnostics()

    def probe(self) -> ContentionEvidence:
        try:
            listing = self._diagnostics.list_devices()
            inputs = len(listing.get("inputs") or ())
            outputs = len(listing.get("outputs") or ())
        except AudioDiagnosticError as exc:
            return self._evidence(ContentionState.UNKNOWN,
                                  f"the audio backend could not be reached ({exc.code})")
        except Exception as exc:
            # Captured deliberately, and the reason is the whole point of this class:
            # PortAudio is native code on a machine we do not control, and a transient
            # failure inside it must make the gate MORE careful, never crash the run.
            return self._evidence(ContentionState.UNKNOWN,
                                  f"the audio backend raised while enumerating ({type(exc).__name__})")
        if not inputs or not outputs:
            return self._evidence(ContentionState.UNKNOWN,
                                  f"this host reports {inputs} input and {outputs} output device(s)")
        return self._evidence(ContentionState.FREE,
                              f"the audio backend answers with {inputs} input and {outputs} output device(s)")

    def _evidence(self, state: ContentionState, detail: str) -> ContentionEvidence:
        return ContentionEvidence(self.source, state, detail[:MAX_EVIDENCE_DETAIL_CHARS])


def hardware_contention_detector(runtime_root: Path | str, **options: Any) -> DeviceContentionDetector:
    """The live-voice probe plus the backend probe, combined fail-closed.

    Offered, not imposed: `RunSupervisor` still builds `default_contention_detector` by
    default, because adding a PortAudio query to every device reservation is a cost a
    caller should choose. Slice 10 composes this one for a workstation that runs
    hardware profiles, where "there is no sound backend" is worth knowing before a
    worker is spawned rather than after.
    """
    return DeviceContentionDetector((LiveVoiceRuntimeProbe(Path(runtime_root), **options), AudioBackendProbe()))
