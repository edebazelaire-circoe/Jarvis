from __future__ import annotations

import json
import os
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

    def heartbeat(self) -> None:
        self._atomic_text(self.root / ".voice_heartbeat", f"{time.time()}\n")

    def reset(self) -> None:
        self.state("idle")
        self.alert(None)
        (self.root / ".voice_waveform").unlink(missing_ok=True)

    def offline(self) -> None:
        self.reset()
        (self.root / ".voice_heartbeat").unlink(missing_ok=True)

    def alert(self, message: str | None) -> None:
        path = self.root / ".voice_alert"
        if message:
            self._atomic_text(path, message.strip() + "\n")
        else:
            path.unlink(missing_ok=True)

    def waveform(self, samples: list[float]) -> None:
        payload = {"ts": time.time(), "samples": samples[:64]}
        self._atomic_text(self.root / ".voice_waveform", json.dumps(payload))

    # Windows opens files without FILE_SHARE_DELETE, so a reader polling the bus
    # at the same moment makes os.replace fail with PermissionError. Retrying and
    # then writing in place keeps the signal flowing instead of killing the writer.
    REPLACE_ATTEMPTS = 5
    REPLACE_BACKOFF_S = 0.02

    @classmethod
    def _atomic_text(cls, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        for attempt in range(cls.REPLACE_ATTEMPTS):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt + 1 < cls.REPLACE_ATTEMPTS:
                    time.sleep(cls.REPLACE_BACKOFF_S)
        try:
            path.write_text(content, encoding="utf-8")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
