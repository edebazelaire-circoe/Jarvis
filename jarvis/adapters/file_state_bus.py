from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from collections.abc import Sequence

from jarvis.domain.events import JarvisState, StateEvent
from jarvis.ports.state import StatePublisher


_VISUAL_STATE = {
    JarvisState.IDLE: "idle",
    JarvisState.LISTENING: "listening",
    JarvisState.TRANSCRIBING: "listening",
    JarvisState.THINKING: "thinking",
    JarvisState.AWAITING_CONFIRMATION: "thinking",
    JarvisState.SPEAKING: "speaking",
    JarvisState.ERROR: "thinking",
}


class FileStatePublisher:
    def __init__(self, runtime_dir: Path) -> None:
        self.root = runtime_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def publish(self, event: StateEvent, *, waveform: Sequence[float] | None = None) -> None:
        await asyncio.to_thread(self._publish_sync, event, waveform)

    def _publish_sync(self, event: StateEvent, waveform: Sequence[float] | None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._atomic_text(self.root / ".voice_state", _VISUAL_STATE[event.state])
        alert = self.root / ".voice_alert"
        if event.state in {JarvisState.AWAITING_CONFIRMATION, JarvisState.ERROR}:
            self._atomic_text(alert, event.message or event.state.value)
        else:
            alert.unlink(missing_ok=True)
        if waveform is not None:
            samples = [float(x) for x in list(waveform)[:64]]
            if len(samples) < 64:
                samples.extend([0.0] * (64 - len(samples)))
            self._atomic_text(
                self.root / ".voice_waveform",
                json.dumps({"ts": time.time(), "samples": samples}, separators=(",", ":")),
            )
        elif event.state != JarvisState.SPEAKING:
            (self.root / ".voice_waveform").unlink(missing_ok=True)

    async def cleanup(self) -> None:
        await asyncio.to_thread(self._cleanup_sync)

    def _cleanup_sync(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._atomic_text(self.root / ".voice_state", "idle")
        for name in (".voice_waveform", ".voice_alert", ".voice_loading_pid"):
            (self.root / name).unlink(missing_ok=True)

    @staticmethod
    def _atomic_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


class BarehandsStatePublisher:
    """Optional mirror for the Barehands ring's native ./state contract."""

    def __init__(self, state_dir: Path) -> None:
        self.root = state_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def publish(self, event: StateEvent, *, waveform: Sequence[float] | None = None) -> None:
        await asyncio.to_thread(self._publish_sync, event, waveform)

    def _publish_sync(self, event: StateEvent, waveform: Sequence[float] | None) -> None:
        FileStatePublisher._atomic_text(self.root / "state", _VISUAL_STATE[event.state])
        mood = "red" if event.state == JarvisState.ERROR else "amber" if event.state == JarvisState.AWAITING_CONFIRMATION else "green"
        FileStatePublisher._atomic_text(self.root / "mood.json", json.dumps({"mood": mood, "ts": time.time()}))
        if waveform is not None:
            samples = [float(x) for x in list(waveform)[:64]]
            FileStatePublisher._atomic_text(self.root / "wave.json", json.dumps({"samples": samples, "ts": time.time()}))
        elif event.state != JarvisState.SPEAKING:
            (self.root / "wave.json").unlink(missing_ok=True)

    async def cleanup(self) -> None:
        FileStatePublisher._atomic_text(self.root / "state", "idle")
        for name in ("mood.json", "wave.json"):
            (self.root / name).unlink(missing_ok=True)


class CompositeStatePublisher:
    def __init__(self, *publishers: StatePublisher) -> None:
        self._publishers = publishers

    async def publish(self, event: StateEvent, *, waveform: Sequence[float] | None = None) -> None:
        results = await asyncio.gather(
            *(p.publish(event, waveform=waveform) for p in self._publishers),
            return_exceptions=True,
        )
        # UI degradation is intentional. If at least one publisher succeeds,
        # a failed optional UI sink must not break the voice loop.
        if results and all(isinstance(r, Exception) for r in results):
            raise RuntimeError("All state publishers failed")

    async def cleanup(self) -> None:
        await asyncio.gather(*(p.cleanup() for p in self._publishers), return_exceptions=True)
