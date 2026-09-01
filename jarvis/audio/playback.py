from __future__ import annotations

import asyncio
import io
import time
import wave

from jarvis.domain.errors import AudioDeviceError
from jarvis.domain.messages import CancellationToken


class SoundDevicePlayback:
    """Chunked WAV playback with cooperative cancellation."""

    async def play_wav(self, wav_bytes: bytes, *, interrupt: CancellationToken) -> tuple[int, bool]:
        return await asyncio.to_thread(self._play_sync, wav_bytes, interrupt)

    @staticmethod
    def _play_sync(wav_bytes: bytes, interrupt: CancellationToken) -> tuple[int, bool]:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise AudioDeviceError("Le module sounddevice est requis pour la sortie audio") from exc
        started = time.perf_counter()
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
                if wav.getsampwidth() != 2:
                    raise AudioDeviceError("Le playback V1 attend un WAV PCM 16-bit")
                samplerate = wav.getframerate()
                channels = wav.getnchannels()
                with sd.RawOutputStream(samplerate=samplerate, channels=channels, dtype="int16") as stream:
                    while not interrupt.cancelled:
                        chunk = wav.readframes(1024)
                        if not chunk:
                            break
                        stream.write(chunk)
        except AudioDeviceError:
            raise
        except Exception as exc:
            raise AudioDeviceError(f"Echec de lecture audio: {type(exc).__name__}") from exc
        return int((time.perf_counter() - started) * 1000), interrupt.cancelled
