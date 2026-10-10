"""Faux runner de rendu (Slice 16) : le port `RenderRunner` sans Node, sans navigateur, sans disque de travail.

Scénarios par `mode` : `ok` (rend un fichier minimal vrai), `fail` (échec typé), `block` (attend `release()` ou l'annulation, comme un
vrai rendu lent), `crash`. Les appels sont consignés dans `calls`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
from pathlib import Path
import threading
import time
from typing import Any

from jarvis.domain.presentation_render import RenderError, RenderErrorCode as C
from jarvis.ports.remotion_render import BrowserInfo, RunOutcome, VerifiedOutput

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1280).to_bytes(4, "big") + (720).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + b"0" * 20
MP4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64 + b"\n%%EOF\n"


class FakeInstalled:
    remotion_version = "4.0.534"
    react_version = "19.3.0"
    lock_sha256 = "c" * 64
    compiler_sha256 = "b" * 64

    def to_dict(self) -> dict[str, str]:
        return {"remotion_version": self.remotion_version, "react_version": self.react_version, "lock_sha256": self.lock_sha256,
                "compiler_sha256": self.compiler_sha256}


class FakeRenderRunner:
    def __init__(self, tmp_path: Path, *, mode: str = "ok") -> None:
        self.root = tmp_path / "fake-render"
        self.root.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.calls: list[tuple[str, Any]] = []
        self.files: dict[str, Mapping[str, bytes]] = {}
        self.browser: BrowserInfo | None = BrowserInfo("C:/chrome.exe", "chrome 154.0.0.0")
        self.runtime_problem: str | None = None
        self.installed: Any = FakeInstalled()
        self.running = threading.Event()
        self._release = threading.Event()
        self.fail_code = C.FAILED.value
        self.fail_detail = "boom"
        self.egress: dict[str, Any] = {"proxy_denied": 3, "blocked_connect": 0}
        self.alive_refs: set[str] = set()
        self.stopped: list[str] = []
        self.swept: list[str] = []
        self.records_on_disk: list[dict[str, Any]] = []
        self.written: dict[str, dict[str, Any]] = {}
        self.verify_error: RenderError | None = None
        self.out_of_spec = False  # verify() returns the wrong size

    def release(self) -> None:
        self._release.set()

    # ------------------------------------------------------------------ port
    def runtime_ready(self) -> str | None:
        return self.runtime_problem

    def installed_engine(self) -> Any | None:
        return self.installed

    def find_browser(self) -> BrowserInfo | None:
        return self.browser

    def prepare(self, job_id: str, files: Mapping[str, bytes]) -> None:
        self.calls.append(("prepare", job_id))
        self.files[job_id] = dict(files)
        if self.mode == "prepare_fails":
            raise RenderError(C.DISK_LOW, "10 MiB free")

    def run(self, job_id: str, spec: Mapping[str, Any], *, browser: BrowserInfo, cancel: threading.Event, timeout_s: float,
            on_start: Callable[[str], None], on_progress: Callable[[Mapping[str, Any]], None]) -> RunOutcome:
        self.calls.append(("run", dict(spec)))
        ref = f"4242:{job_id}"
        self.alive_refs.add(ref)
        on_start(ref)
        total = int(spec["frames_total"])
        on_progress({"phase": "rendering", "frames_done": min(2, total), "frames_total": total})
        self.running.set()
        try:
            if self.mode == "block":
                end = time.monotonic() + 30
                while time.monotonic() < end and not cancel.is_set() and not self._release.is_set():
                    time.sleep(0.01)
                if cancel.is_set():
                    return RunOutcome(False, C.CANCELLED.value, "cancelled by the user", egress=self.egress)
            if self.mode == "fail":
                return RunOutcome(False, self.fail_code, self.fail_detail, egress=self.egress, log_tail=["line one", "line two"])
            out = {"mp4": MP4, "still": PNG, "pdf": PDF}[spec["format"]]
            path = self.root / f"{job_id}.{spec['format']}"
            path.write_bytes(out)
            on_progress({"phase": "rendering", "frames_done": total, "frames_total": total})
            return RunOutcome(True, outputs=[path], egress=self.egress, elapsed_s=0.1)
        finally:
            self.alive_refs.discard(ref)

    def verify(self, job_id: str, fmt: str, *, width: int, height: int, frames: int | None, pages: int | None) -> VerifiedOutput:
        self.calls.append(("verify", fmt))
        if self.verify_error is not None:
            raise self.verify_error
        data = {"mp4": MP4, "still": PNG, "pdf": PDF}[fmt]
        path = self.root / f"{job_id}.{fmt}"
        if self.out_of_spec:
            width += 2
        return VerifiedOutput(path, len(data), hashlib.sha256(data).hexdigest(), width, height, 2000 if fmt == "mp4" else None,
                              frames, pages, {"mp4": "ffprobe", "still": "png", "pdf": "pdf"}[fmt])

    def copy_output(self, job_id: str, verified: VerifiedOutput, write: Callable[[bytes], Any]) -> None:
        data = verified.path.read_bytes()
        for start in range(0, len(data), 16):
            write(data[start:start + 16])

    def cleanup(self, job_id: str) -> None:
        self.calls.append(("cleanup", job_id))

    def prune(self, keep: int) -> int:
        self.calls.append(("prune", keep))
        return 0

    def sweep(self, job_id: str) -> int:
        self.swept.append(job_id)
        return 0

    def stop(self, process_ref: str) -> bool:
        self.stopped.append(process_ref)
        self.alive_refs.discard(process_ref)
        return True

    def alive(self, process_ref: str) -> bool:
        return process_ref in self.alive_refs

    def write_record(self, job_id: str, record: Mapping[str, Any]) -> None:
        self.written[job_id] = dict(record)

    def records(self) -> list[Mapping[str, Any]]:
        return list(self.records_on_disk)
