from __future__ import annotations

from array import array
import math
from typing import Any

from jarvis.audio.input_ownership import (
    OWNER_DEVICE_PROBE,
    register_input_stream,
    release_input_stream,
)


VOICE_SAMPLE_RATE = 24_000
TEST_DURATION_S = 2.0
MIN_SIGNAL_DBFS = -50.0


class AudioDiagnosticError(RuntimeError):
    def __init__(self, code: str, message: str, *, context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.context = context or {}


def normalize_device_id(value: object) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("audio device id must not be a boolean")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("audio device id must be positive")
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        index = int(text)
    except ValueError:
        return text
    if index < 0:
        raise ValueError("audio device id must be positive")
    return index


class SoundDeviceAudioDiagnostics:
    """Enumerates and exercises the same sounddevice path used by Realtime Voice."""

    @staticmethod
    def _sounddevice():  # noqa: ANN205
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise AudioDiagnosticError(
                "audio_backend_unavailable",
                "Le module sounddevice n'est pas installé.",
            ) from exc
        return sd

    def list_devices(self) -> dict[str, object]:
        sd = self._sounddevice()
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            defaults = tuple(sd.default.device)
        except Exception as exc:
            raise AudioDiagnosticError(
                "audio_device_enumeration_failed",
                "Impossible de récupérer les périphériques audio.",
                context={"exception_type": type(exc).__name__},
            ) from exc

        inputs: list[dict[str, object]] = []
        outputs: list[dict[str, object]] = []
        for index, raw in enumerate(devices):
            device = dict(raw)
            hostapi_index = int(device.get("hostapi", -1))
            hostapi_name = ""
            if 0 <= hostapi_index < len(hostapis):
                hostapi_name = str(hostapis[hostapi_index].get("name") or "")
            common = {
                "id": index,
                "name": str(device.get("name") or f"Périphérique {index}"),
                "hostapi": hostapi_name,
                "default_samplerate": int(float(device.get("default_samplerate") or 0)),
            }
            input_channels = int(device.get("max_input_channels") or 0)
            output_channels = int(device.get("max_output_channels") or 0)
            if input_channels > 0:
                inputs.append({**common, "channels": input_channels})
            if output_channels > 0:
                outputs.append({**common, "channels": output_channels})

        return {
            "inputs": inputs,
            "outputs": outputs,
            "defaults": {
                "input": self._default_index(defaults, 0),
                "output": self._default_index(defaults, 1),
            },
            "sample_rate": VOICE_SAMPLE_RATE,
        }

    def test_record_and_playback(
        self,
        *,
        input_device: int | str | None,
        output_device: int | str | None,
        duration_s: float = TEST_DURATION_S,
    ) -> dict[str, object]:
        sd = self._sounddevice()
        self._check_input(sd, input_device)
        self._check_output(sd, output_device)
        frames = int(VOICE_SAMPLE_RATE * duration_s)
        # `sd.rec` ouvre un vrai flux d'entree pour la duree de l'appel. Il est
        # inscrit au registre des proprietaires comme les autres, avec un jeton
        # qui vit exactement le temps de l'enregistrement : sans cela le compte
        # mentirait pendant le test de peripherique, et PRESENTATION pourrait
        # s'activer par-dessus.
        probe = object()
        register_input_stream(OWNER_DEVICE_PROBE, probe, label=str(input_device))
        try:
            recording = sd.rec(
                frames,
                samplerate=VOICE_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=input_device,
                blocking=True,
            )
        except Exception as exc:
            raise AudioDiagnosticError(
                "audio_input_capture_failed",
                "Le microphone n'a pas pu enregistrer.",
                context={"exception_type": type(exc).__name__},
            ) from exc
        finally:
            release_input_stream(probe)

        peak_dbfs, rms_dbfs = self._levels(recording.tobytes())
        if peak_dbfs < MIN_SIGNAL_DBFS:
            raise AudioDiagnosticError(
                "audio_input_no_signal",
                "Aucun signal vocal détecté. Vérifiez le micro sélectionné et recommencez en parlant.",
                context={"peak_dbfs": round(peak_dbfs, 1)},
            )

        try:
            sd.play(
                recording,
                samplerate=VOICE_SAMPLE_RATE,
                device=output_device,
                blocking=True,
            )
        except Exception as exc:
            raise AudioDiagnosticError(
                "audio_output_playback_failed",
                "L'enregistrement a fonctionné, mais sa lecture a échoué.",
                context={"exception_type": type(exc).__name__, "peak_dbfs": round(peak_dbfs, 1)},
            ) from exc

        return {
            "ok": True,
            "duration_s": duration_s,
            "sample_rate": VOICE_SAMPLE_RATE,
            "peak_dbfs": round(peak_dbfs, 1),
            "rms_dbfs": round(rms_dbfs, 1),
        }

    def check_input_format(self, device: int | str | None) -> None:
        """Does this input accept the Voice capture format? Asks PortAudio; opens nothing.

        Public because the Test Lab hardware profiles need the format question on its
        own, without recording the user's microphone as `test_record_and_playback` does.
        Same call, same `AudioDiagnosticError` codes.
        """
        self._check_input(self._sounddevice(), device)

    def check_output_format(self, device: int | str | None) -> None:
        """Does this output accept the Voice playback format? Asks PortAudio; opens nothing."""
        self._check_output(self._sounddevice(), device)

    @staticmethod
    def _default_index(defaults: tuple[Any, ...], offset: int) -> int | None:
        try:
            value = int(defaults[offset])
        except (IndexError, TypeError, ValueError):
            return None
        return value if value >= 0 else None

    @staticmethod
    def _check_input(sd, device: int | str | None) -> None:  # noqa: ANN001
        try:
            sd.check_input_settings(device=device, channels=1, dtype="int16", samplerate=VOICE_SAMPLE_RATE)
        except Exception as exc:
            raise AudioDiagnosticError(
                "audio_input_unavailable",
                "Le microphone sélectionné n'accepte pas le format Voice 24 kHz mono.",
                context={"exception_type": type(exc).__name__},
            ) from exc

    @staticmethod
    def _check_output(sd, device: int | str | None) -> None:  # noqa: ANN001
        try:
            sd.check_output_settings(device=device, channels=1, dtype="int16", samplerate=VOICE_SAMPLE_RATE)
        except Exception as exc:
            raise AudioDiagnosticError(
                "audio_output_unavailable",
                "La sortie sélectionnée n'accepte pas le format Voice 24 kHz mono.",
                context={"exception_type": type(exc).__name__},
            ) from exc

    @staticmethod
    def _levels(pcm: bytes) -> tuple[float, float]:
        samples = array("h")
        samples.frombytes(pcm)
        if not samples:
            return -96.0, -96.0
        peak = max(abs(sample) for sample in samples) / 32768.0
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
        peak_dbfs = 20.0 * math.log10(max(peak, 1.0 / 32768.0))
        rms_dbfs = 20.0 * math.log10(max(rms, 1.0 / 32768.0))
        return peak_dbfs, rms_dbfs
