from __future__ import annotations

import json
from pathlib import Path
import time


class VisualSignalBus:
    VALID_STATES = {"idle", "listening", "thinking", "speaking"}

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def state(self, value: str) -> None:
        normalized = value.strip().lower()
        if normalized not in self.VALID_STATES:
            raise ValueError(f"invalid visual state: {value}")
        self._atomic_text(self.root / ".voice_state", normalized + "\n")

    def alert(self, message: str | None) -> None:
        path = self.root / ".voice_alert"
        if message:
            self._atomic_text(path, message.strip() + "\n")
        else:
            path.unlink(missing_ok=True)

    def waveform(self, samples: list[float]) -> None:
        payload = {"ts": time.time(), "samples": samples[:64]}
        self._atomic_text(self.root / ".voice_waveform", json.dumps(payload))

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
