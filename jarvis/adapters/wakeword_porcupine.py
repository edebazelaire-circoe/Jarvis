from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from jarvis.audio.input_ownership import (
    OWNER_WAKEWORD_PORCUPINE,
    register_input_stream,
    release_input_stream,
)


class PorcupineWakeWordBackend:
    """Local-only wake-word detector. Microphone frames are not persisted or streamed.

    Owns a **second** input stream, separate from `SoundDeviceRealtimeAudio`'s.
    That is deliberate and retained for SIMPLE (decision D14, and
    `docs/03-implementation-strategy.md`: "Existing Porcupine standalone
    microphone path may remain for Simple if safer"). It works there only
    because the two are never open at once: this backend closes its device for
    the duration of an active session.

    PRESENTATION cannot use it — nothing suspends when JARVIS listens
    continuously — and uses `jarvis.adapters.wakeword_shared_pcm` instead. The
    stream opened here is registered in `jarvis.audio.input_ownership` so the
    difference is **counted** rather than asserted: two owners in SIMPLE, one in
    PRESENTATION.
    """

    def __init__(self, *, access_key: str, keyword: str = "jarvis", device: int | str | None = None) -> None:
        self.access_key = access_key
        self.keyword = keyword
        self.device = device
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
        self._stream = None
        self._engine = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    async def start(self) -> None:
        if self._stream is not None:
            return
        try:
            import pvporcupine  # type: ignore
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Wake word requires pvporcupine and sounddevice") from exc
        self._loop = asyncio.get_running_loop()
        if self._engine is None:
            self._engine = pvporcupine.create(access_key=self.access_key, keywords=[self.keyword])
        engine = self._engine

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            del frames, time_info, status
            loop = self._loop
            if self._closed or engine is None or loop is None:
                return
            import struct
            raw = bytes(indata)
            frame_bytes = engine.frame_length * 2
            for offset in range(0, len(raw) - frame_bytes + 1, frame_bytes):
                pcm = struct.unpack_from("h" * engine.frame_length, raw, offset)
                if engine.process(pcm) >= 0:
                    try:
                        loop.call_soon_threadsafe(self._detected)
                    except RuntimeError:
                        # La boucle se ferme : lever depuis un callback PortAudio
                        # ferait tomber le flux au lieu d'arrêter proprement.
                        return

        self._stream = sd.RawInputStream(samplerate=engine.sample_rate, channels=1, dtype="int16", device=self.device, blocksize=engine.frame_length, callback=callback)
        register_input_stream(OWNER_WAKEWORD_PORCUPINE, self._stream, label=str(self.device))
        self._stream.start()

    def _detected(self) -> None:
        if not self._queue.full():
            self._queue.put_nowait(self.keyword)

    async def suspend(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop(); stream.close()
            except Exception:
                # Audio-device teardown is best effort during lifecycle transitions.
                pass
            finally:
                # The device is released either way; the registry must say so,
                # or a failed teardown would leave a phantom owner in the count.
                release_input_stream(stream)

    async def suspend_for_active_session(self) -> None:
        await self.suspend()

    async def resume(self) -> None:
        if not self._closed:
            await self.start()

    async def detections(self) -> AsyncIterator[str]:
        await self.start()
        while not self._closed:
            yield await self._queue.get()

    async def close(self) -> None:
        self._closed = True
        await self.suspend()
        engine, self._engine = self._engine, None
        if engine is not None:
            engine.delete()
