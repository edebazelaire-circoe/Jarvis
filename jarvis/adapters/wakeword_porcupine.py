from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class PorcupineWakeWordBackend:
    """Local-only wake-word detector. Microphone frames are not persisted or streamed."""

    def __init__(self, *, access_key: str, keyword: str = "jarvis", device: str | None = None) -> None:
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
            if self._closed or engine is None:
                return
            import struct
            raw = bytes(indata)
            frame_bytes = engine.frame_length * 2
            for offset in range(0, len(raw) - frame_bytes + 1, frame_bytes):
                pcm = struct.unpack_from("h" * engine.frame_length, raw, offset)
                if engine.process(pcm) >= 0 and self._loop is not None:
                    self._loop.call_soon_threadsafe(self._detected)

        self._stream = sd.RawInputStream(samplerate=engine.sample_rate, channels=1, dtype="int16", device=self.device, blocksize=engine.frame_length, callback=callback)
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
                pass

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
