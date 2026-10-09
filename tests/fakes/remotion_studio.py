"""Faux `StudioRunner` en mémoire (Slice 11) : aucun processus, aucun fichier ; trace chaque appel et simule vivacité et activité."""

from __future__ import annotations

from collections.abc import Mapping
import itertools
from typing import Any

from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C
from jarvis.ports.remotion_studio import LaunchResult, SyncReport


class FakeStudioRunner:
    def __init__(self, *, port: int | None = None) -> None:
        self.calls: list[str] = []
        self.launches: list[int | None] = []
        self.work: dict[str, bytes] = {}
        self.alive: set[str] = set()
        self.stopped: list[str] = []
        self.port = port
        self.ready_reason: str | None = None
        self.launch_errors: list[StudioError] = []
        self.sync_error: StudioError | None = None
        self.modified: tuple[str, ...] = ()
        self.saved: tuple[str, ...] = ()
        self.edits_on_sync: tuple[str, ...] = ()
        self.activity_data: dict[str, Any] = {}
        self.healthy = True
        self.state: Mapping[str, Any] | None = None
        self.log: list[str] = ["Server ready"]
        self._pids = itertools.count(4100)
        self._ports = itertools.count(41000)
        self.launch_id = ""

    def configured_port(self):
        self.calls.append("configured_port")
        return self.port

    def runtime_ready(self):
        self.calls.append("runtime_ready")
        return self.ready_reason

    def sync_work(self, files):
        self.calls.append("sync_work")
        if self.sync_error:
            raise self.sync_error
        unchanged = sum(1 for path, data in files.items() if self.work.get(path) == data)
        removed = len(set(self.work) - set(files))
        self.work = dict(files)
        return SyncReport(len(files) - unchanged, removed, unchanged, self.edits_on_sync)

    def modified_work(self):
        return self.modified

    def save_modified(self):
        self.calls.append("save_modified")
        return self.saved

    def launch(self, *, port):
        self.calls.append("launch")
        self.launches.append(port)
        if self.launch_errors:
            raise self.launch_errors.pop(0)
        pid = next(self._pids)
        chosen = port if port is not None else next(self._ports)
        ref = f"{pid}:{pid * 7}"
        self.alive.add(ref)
        self.launch_id = f"launch{pid}"
        return LaunchResult(ref, chosen, self.launch_id)

    def probe(self, port, launch_id):
        self.calls.append("probe")
        if not self.healthy:
            raise StudioError(C.HEALTH_FAILED, "no answer")

    def is_alive(self, process_ref):
        return process_ref in self.alive

    def stop(self, process_ref):
        self.calls.append("stop")
        self.stopped.append(process_ref)
        self.alive.discard(process_ref)

    def activity(self, launch_id):
        return {"launch": launch_id, **self.activity_data}

    def log_tail(self, lines=8):
        return self.log[-lines:]

    def read_state(self):
        return self.state

    def write_state(self, payload):
        self.state = dict(payload)
