from __future__ import annotations

import io
import threading
import wave

from jarvis.domain.errors import AudioDeviceError
from jarvis.domain.messages import AudioClip


class SoundDeviceRecorder:
    def __init__(self, *, sample_rate: int = 16000, channels: int = 1, input_device: str | None = None) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.input_device = input_device
        self._stream = None
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()

    def preflight(self) -> dict[str, object]:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise AudioDeviceError("Installez l'extra voice: pip install -e '.[voice]'") from exc
        try:
            device = self._resolve_device(sd)
            info = sd.query_devices(device, "input") if device is not None else sd.query_devices(kind="input")
            if int(info.get("max_input_channels", 0)) < self.channels:
                raise AudioDeviceError("Aucun canal micro compatible")
            return {"name": info.get("name"), "max_input_channels": info.get("max_input_channels")}
        except AudioDeviceError:
            raise
        except Exception as exc:
            raise AudioDeviceError(f"Microphone indisponible: {type(exc).__name__}") from exc

    def start(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise AudioDeviceError("Installez l'extra voice: pip install -e '.[voice]'") from exc
        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []
            device = self._resolve_device(sd)

            def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
                del frames, time_info, status
                with self._lock:
                    self._chunks.append(bytes(indata))

            try:
                self._stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="int16",
                    device=device,
                    callback=callback,
                )
                self._stream.start()
            except Exception as exc:
                self._stream = None
                raise AudioDeviceError(f"Impossible d'ouvrir le microphone: {type(exc).__name__}") from exc

    def stop(self) -> AudioClip:
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is None:
            raise AudioDeviceError("Aucun enregistrement en cours")
        try:
            stream.stop()
            stream.close()
        finally:
            with self._lock:
                pcm = b"".join(self._chunks)
                self._chunks = []
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)
        return AudioClip(out.getvalue(), self.sample_rate, self.channels, 2, "audio/wav")

    def abort(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._chunks = []
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass

    def _resolve_device(self, sd):  # noqa: ANN001
        if not self.input_device:
            return None
        devices = sd.query_devices()
        requested = self.input_device.casefold()
        exact = [i for i, d in enumerate(devices) if str(d.get("name", "")).casefold() == requested and d.get("max_input_channels", 0) > 0]
        if exact:
            return exact[0]
        partial = [i for i, d in enumerate(devices) if requested in str(d.get("name", "")).casefold() and d.get("max_input_channels", 0) > 0]
        if partial:
            return partial[0]
        raise AudioDeviceError(f"Microphone configure introuvable: {self.input_device}")
