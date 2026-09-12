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
        self.authorization(None)
        self.capture(None)

    #: État réel de l'autorisation de conversation vu par Voice (Solo Owner,
    #: tâche 07) : lu par le Control Center tant que Voice bat.
    AUTHORIZATION_FILE = ".voice_authorization"

    def authorization(self, report: dict[str, object] | None) -> None:
        """Publier ce que Voice applique vraiment (`ready` / `refused`, code, message), ou l'effacer."""

        path = self.root / self.AUTHORIZATION_FILE
        if report is None:
            path.unlink(missing_ok=True)
            return
        self._atomic_text(path, json.dumps({**report, "ts": time.time()}, ensure_ascii=False))

    #: État réel de la capture duplex vu par Voice (tâche 08) : annulation
    #: d'écho effectivement active ou non, disponibilité du vérificateur et
    #: fenêtres perdues. Scalaires seulement, jamais d'audio ni d'empreinte.
    CAPTURE_FILE = ".voice_capture"

    def capture(self, report: dict[str, object] | None) -> None:
        """Publier l'état effectif de la capture duplex, ou l'effacer."""

        path = self.root / self.CAPTURE_FILE
        if report is None:
            path.unlink(missing_ok=True)
            return
        self._atomic_text(path, json.dumps({**report, "ts": time.time()}, ensure_ascii=False))

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
